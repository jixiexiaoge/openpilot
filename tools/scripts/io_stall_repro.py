#!/usr/bin/env python3
"""
io_stall_repro.py — bench reproduction + fix-validation rig for the VW PQ EPS
HCA fault (control loop stalling on a /data read under eMMC write saturation).

The real fault chain (proven from rlog b29ee8c5a0a735d1/000000e4--8a8ba97b54):
  loggerd buffered writes saturate eMMC -> ext4 jbd2 journal commits ->
  controlsd's inline Params.get (util::read_file on /data) blocks ~300-630ms ->
  controlsd stops publishing carControl -> card's all_alive guard withholds
  HCA_1 -> EPS LH2_Sta_HCA 7->2.

This reproduces the *proximate* cause WITHOUT driving, WITHOUT the EPS, and
WITHOUT touching the real control stack. Two roles:

  --writer : emulate loggerd. Buffered (no-fsync) writes to /data at a target
             MB/s, with an optional periodic big flush to mimic 60s segment
             rotation. This is what saturates the eMMC.

  --probe  : emulate controlsd's I/O exposure. A 100Hz loop that every
             --param-period seconds reads a real param (util::read_file on
             /data). It records per-iteration loop gaps and param-read
             durations. A 300ms gap here == the stall that drops HCA.
             --threaded moves the param read to a background thread (the
             proposed fix, mirroring card.py's params_thread) so you can A/B it.

USAGE (run parked, ignition on, on the device):
  # 1) baseline: probe alone -> gaps should be tiny
  python3 io_stall_repro.py --probe --secs 120

  # 2) reproduce: writer in one shell, probe in another
  python3 io_stall_repro.py --writer --mbps 25 --rotate 60
  python3 io_stall_repro.py --probe --secs 180          # expect big gaps

  # 3) validate fix A (params off control thread):
  python3 io_stall_repro.py --probe --secs 180 --threaded   # gaps should vanish

  # 4) validate fix B (smoother writeback) — set before step 2, as root:
  #   echo 5  > /proc/sys/vm/dirty_background_ratio
  #   echo 10 > /proc/sys/vm/dirty_ratio
  #   then re-run step 2 inline probe and compare gap distribution.

Cleanup: writer deletes its scratch files on exit. Read-only wrt openpilot.
"""
import argparse, os, sys, time, threading, statistics, signal

SCRATCH_DEFAULT = "/data/media/0/io_repro_scratch"

# ----------------------------------------------------------------------------- writer
def run_writer(args):
  os.makedirs(args.scratch, exist_ok=True)
  chunk = os.urandom(1 << 20)  # 1 MiB
  bytes_per_s = int(args.mbps * (1 << 20))
  print(f"[writer] buffered no-fsync writes to {args.scratch} at ~{args.mbps} MB/s, "
        f"rotate every {args.rotate}s (big flush). Ctrl-C to stop.", file=sys.stderr)

  stop = {"v": False}
  signal.signal(signal.SIGINT, lambda *_: stop.update(v=True))
  signal.signal(signal.SIGTERM, lambda *_: stop.update(v=True))

  files = []
  seg = 0
  try:
    while not stop["v"]:
      seg_start = time.monotonic()
      path = os.path.join(args.scratch, f"seg_{seg}.bin")
      f = open(path, "wb", buffering=1 << 20)
      files.append(path)
      written = 0
      # write at target rate using buffered fwrite, NO fsync (exactly loggerd)
      while not stop["v"] and (time.monotonic() - seg_start) < args.rotate:
        t0 = time.monotonic()
        f.write(chunk)
        written += len(chunk)
        # pace to target MB/s
        target_t = written / bytes_per_s
        elapsed = time.monotonic() - seg_start
        if target_t > elapsed:
          time.sleep(min(0.1, target_t - elapsed))
      # "segment rotation": flush+close a big buffered file at once -> writeback burst
      f.flush()
      f.close()
      seg += 1
      # keep only a few recent files so we don't fill the disk
      while len(files) > 3:
        old = files.pop(0)
        try: os.remove(old)
        except OSError: pass
  finally:
    for p in files:
      try: os.remove(p)
      except OSError: pass
    print("[writer] stopped, scratch cleaned.", file=sys.stderr)

# ----------------------------------------------------------------------------- probe
def _get_param(key):
  # real /data read, same syscall path as controlsd's get_params_iq
  try:
    from openpilot.common.params import Params
    return Params().get_bool(key)
  except Exception:
    # fallback: plain file read of a param file if openpilot import unavailable
    p = os.path.join(os.getenv("PARAMS_ROOT", "/data/params"), "d", key)
    try:
      with open(p, "rb") as fh:
        return fh.read()
    except OSError:
      return None

class ThreadedParam:
  """Mirror card.py params_thread: refresh the param on a bg thread, control
  loop reads the cached value (non-blocking)."""
  def __init__(self, key, period):
    self.key = key; self.period = period; self.val = None
    self.stop = False
    self.t = threading.Thread(target=self._loop, daemon=True); self.t.start()
  def _loop(self):
    while not self.stop:
      self.val = _get_param(self.key)
      time.sleep(self.period)
  def read(self):  # O(1), no I/O on the control thread
    return self.val

def run_probe(args):
  # pin like controlsd (core 4) so we share the same iowait domain if possible
  try:
    os.sched_setaffinity(0, {args.core})
  except (OSError, AttributeError):
    pass

  interval = 0.01  # 100Hz, like the control loop
  gaps = []          # ms, per-iteration loop overrun beyond 10ms
  read_ms = []       # ms, time spent in the param read on the control thread
  worst = 0.0
  threaded = ThreadedParam(args.param_key, args.param_period) if args.threaded else None

  print(f"[probe] 100Hz loop for {args.secs}s, param '{args.param_key}' every "
        f"{args.param_period}s, threaded={args.threaded}, core={args.core}", file=sys.stderr)
  t_end = time.monotonic() + args.secs
  next_t = time.monotonic()
  last_param = 0.0
  while time.monotonic() < t_end:
    loop_start = time.monotonic()

    # the I/O exposure: read param on the control thread (inline) every period
    if loop_start - last_param >= args.param_period:
      r0 = time.monotonic()
      if threaded is not None:
        _ = threaded.read()            # cached, no I/O on this thread (the FIX)
      else:
        _ = _get_param(args.param_key)  # inline /data read (current behavior)
      dr = (time.monotonic() - r0) * 1000
      read_ms.append(dr)
      last_param = loop_start

    # measure scheduling/lag: how late did this iteration actually fire?
    next_t += interval
    lag = (time.monotonic() - next_t) * 1000  # ms behind schedule
    if lag > 5:
      gaps.append(lag)
      worst = max(worst, lag)
    sleep = next_t - time.monotonic()
    if sleep > 0:
      time.sleep(sleep)
    else:
      next_t = time.monotonic()  # don't spiral after a big stall

  if threaded:
    threaded.stop = True

  def pct(xs, p):
    return sorted(xs)[int(p/100*(len(xs)-1))] if xs else 0.0
  print("\n================ PROBE RESULT ================")
  print(f"loop-lag events >5ms : {len(gaps)}")
  print(f"loop-lag p50/p99/max : {pct(gaps,50):.0f} / {pct(gaps,99):.0f} / {worst:.0f} ms")
  print(f"param-read p50/p99/max: {pct(read_ms,50):.1f} / {pct(read_ms,99):.1f} / {max(read_ms+[0]):.1f} ms  (n={len(read_ms)})")
  hca_class = max(gaps + [0])
  verdict = ("FAULT-CLASS STALL REPRODUCED (>250ms -> would drop HCA)" if hca_class > 250
             else "marginal (100-250ms)" if hca_class > 100
             else "clean (<100ms)")
  print(f"VERDICT: {verdict}")
  print("=============================================")

# ----------------------------------------------------------------------------- main
def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--writer", action="store_true", help="emulate loggerd eMMC saturation")
  ap.add_argument("--probe", action="store_true", help="emulate controlsd I/O exposure")
  ap.add_argument("--mbps", type=float, default=25.0, help="writer target MB/s (loggerd ~10-30)")
  ap.add_argument("--rotate", type=float, default=60.0, help="writer segment/flush period s")
  ap.add_argument("--scratch", default=SCRATCH_DEFAULT)
  ap.add_argument("--secs", type=float, default=180.0, help="probe duration s")
  ap.add_argument("--param-key", default="IsMetric", help="a real param key to read")
  ap.add_argument("--param-period", type=float, default=3.0, help="controlsd reads every 3s")
  ap.add_argument("--threaded", action="store_true", help="probe: read param off control thread (the FIX)")
  ap.add_argument("--core", type=int, default=4, help="probe cpu affinity (control core)")
  args = ap.parse_args()
  if args.writer == args.probe:
    ap.error("pick exactly one of --writer / --probe (run them in separate shells)")
  run_writer(args) if args.writer else run_probe(args)

if __name__ == "__main__":
  main()

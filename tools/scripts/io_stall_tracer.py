#!/usr/bin/env python3
"""
io_stall_tracer.py — continuous low-overhead per-process disk-I/O tracer.

WHY: the VW PQ EPS HCA faults are caused by a control process (controlsd/card)
blocking ~300-630ms in disk I/O (iowait) on /data, which stops HCA_1 TX. The
stall is far too short to catch with a manual `iostat`/`iotop` run. This sampler
runs for the whole drive at 100ms cadence and records, per process:

  - write_bytes      (/proc/<pid>/io)   -> identifies the WRITER saturating eMMC
  - delayacct_blkio  (/proc/<pid>/stat) -> per-process cumulative block-I/O wait
  - state            (/proc/<pid>/stat) -> catches 'D' (uninterruptible disk wait)

plus whole-device /proc/diskstats. After a fault, find the wall-clock time of the
LH2_Sta_HCA->2 event (from the rlog) and look at the rows around it: the process
whose write_bytes delta spikes is the bully; the control process whose blkio
delta jumps / state == 'D' is the victim.

Deploy: copy to the device, run alongside openpilot during a drive:
    python3 io_stall_tracer.py --out /data/media/0/io_trace.csv
Overhead: reading /proc for ~40 procs every 100ms is well under 1% of one core,
and it pins itself to CPU 0 (away from the control cores 4/5) at low priority.

Read-only. Writes a single CSV. No openpilot deps.
"""
import argparse, os, time, glob, sys

CLK_TCK = os.sysconf("SC_CLK_TCK")  # usually 100 -> blkio ticks are 10ms each

def read_proc_io(pid):
  # wchar/rchar = bytes moved via read()/write() syscalls (catches BUFFERED writers
  # like loggerd, which never appear in write_bytes because the kernel flushes their
  # page-cache dirty pages asynchronously via kworker). write_bytes = bytes actually
  # sent to the block device. Track both.
  try:
    with open(f"/proc/{pid}/io") as f:
      d = {}
      for line in f:
        k, _, v = line.partition(":")
        d[k] = int(v)
      return (d.get("wchar", 0), d.get("rchar", 0),
              d.get("write_bytes", 0), d.get("read_bytes", 0))
  except (OSError, ValueError):
    return None

def read_proc_stat(pid):
  # state is field 3; delayacct_blkio_ticks is field 42 (1-indexed). comm may
  # contain spaces/parens, so split on the last ')'.
  try:
    with open(f"/proc/{pid}/stat") as f:
      data = f.read()
    rparen = data.rfind(")")
    comm = data[data.find("(") + 1:rparen]
    rest = data[rparen + 2:].split()
    state = rest[0]                       # field 3
    blkio_ticks = int(rest[39]) if len(rest) > 39 else 0  # field 42
    return comm, state, blkio_ticks
  except (OSError, ValueError, IndexError):
    return None

def read_diskstats():
  # returns {dev: (sectors_written, ms_doing_io)} for whole-disk devices
  out = {}
  try:
    with open("/proc/diskstats") as f:
      for line in f:
        p = line.split()
        if len(p) < 14:
          continue
        dev = p[2]
        # field 10 (idx 9) = sectors written; field 13 (idx 12) = ms doing I/O
        out[dev] = (int(p[9]), int(p[12]))
  except (OSError, AttributeError):
    pass
  return out

# These counters tell us WHICH kernel mechanism caused a stall, which decides
# the fix: compact_stall jumping -> memory compaction (texture-pool fix);
# allocstall/pgsteal jumping -> direct reclaim; high nr_dirty/nr_writeback ->
# loggerd writeback bomb (loggerd sync_file_range fix). meminfo Dirty/Writeback
# are absolute kB; vmstat ones are cumulative event counts (we delta them).
VMSTAT_KEYS = ("compact_stall", "compact_fail", "allocstall_normal", "allocstall_movable",
               "pgsteal_direct", "pgscan_direct", "pgmajfault", "nr_dirty", "nr_writeback")
MEMINFO_KEYS = ("MemFree", "MemAvailable", "Dirty", "Writeback")

def read_vmstat():
  out = {}
  try:
    with open("/proc/vmstat") as f:
      for line in f:
        k, _, v = line.partition(" ")
        if k in VMSTAT_KEYS:
          out[k] = int(v)
  except OSError:
    pass
  return out

def read_meminfo():
  out = {}
  try:
    with open("/proc/meminfo") as f:
      for line in f:
        k, _, v = line.partition(":")
        if k in MEMINFO_KEYS:
          out[k] = int(v.split()[0])  # kB
  except (OSError, IndexError):
    pass
  return out

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--out", default="/data/media/0/io_trace.csv")
  ap.add_argument("--hz", type=float, default=10.0, help="sample rate (default 10Hz/100ms)")
  ap.add_argument("--disk", default="sda", help="comma-separated disk devices to track (default sda)")
  ap.add_argument("--names", default="controlsd,car.c,selfd,ui,loggerd,encoderd,modeld,camerad,locationd,paramsd,navd,mapd",
                  help="substring match of process comm to record (others summed as 'other')")
  args = ap.parse_args()

  # be a good citizen: low priority, off the control cores
  try:
    os.nice(10)
    os.sched_setaffinity(0, {0})
  except OSError:
    pass

  watch = [n.strip() for n in args.names.split(",") if n.strip()]
  disks = [d.strip() for d in args.disk.split(",") if d.strip()]
  interval = 1.0 / args.hz

  prev_io = {}      # pid -> (wchar, rchar, write_bytes, read_bytes)
  prev_blkio = {}   # pid -> blkio_ticks
  prev_disk = read_diskstats()
  prev_vm = read_vmstat()

  f = open(args.out, "w", buffering=1)
  # per-proc rows fill the first block; one SYS row per tick fills the trailing
  # mechanism columns (deltas for the vmstat counts, absolute kB for meminfo).
  f.write("wall,mono,proc,pid,state,d_wchar_kB,d_wbytes_kB,d_blkio_ms,disk_d_write_kB,disk_d_busy_ms,"
          "compact_stall,allocstall,pgmajfault,dirty_kB,writeback_kB,memfree_kB,memavail_kB\n")
  print(f"[io_stall_tracer] writing {args.out} at {args.hz}Hz, tracking {watch}", file=sys.stderr)

  while True:
    t_wall = time.time()
    t_mono = time.monotonic()

    # whole-disk delta (write kB + busy ms) for the named disks
    disk = read_diskstats()
    disk_dw = disk_db = 0
    for dev in disks:
      if dev in disk and dev in prev_disk:
        disk_dw += (disk[dev][0] - prev_disk[dev][0]) * 512 / 1024.0  # sectors->kB
        disk_db += (disk[dev][1] - prev_disk[dev][1])
    prev_disk = disk

    seen = set()
    rows = []
    for path in glob.glob("/proc/[0-9]*"):
      pid = path.rsplit("/", 1)[1]
      st = read_proc_stat(pid)
      if st is None:
        continue
      comm, state, blkio = st
      label = next((w for w in watch if w in comm), None)
      if label is None:
        # still track D-state of anything to catch surprise writers/blockers
        if state != "D":
          continue
        label = comm
      io = read_proc_io(pid)
      if io is None:
        continue
      wchar, rchar, wbytes, rbytes = io
      pw = prev_io.get(pid, io)
      pblk = prev_blkio.get(pid, blkio)
      d_wchar = (wchar - pw[0]) / 1024.0     # syscall write volume (catches loggerd)
      d_wbytes = (wbytes - pw[2]) / 1024.0   # bytes hitting the block device
      d_blk = (blkio - pblk) * (1000.0 / CLK_TCK)  # ticks -> ms blocked on block I/O
      prev_io[pid] = io
      prev_blkio[pid] = blkio
      seen.add(pid)
      # only emit rows that carry signal (writing, blocked, or in D) to keep file small
      if d_wchar > 4 or d_wbytes > 4 or d_blk > 5 or state == "D":
        rows.append((label, pid, state, d_wchar, d_wbytes, d_blk))

    # drop dead pids from prev maps occasionally
    if len(prev_io) > 4000:
      prev_io = {p: v for p, v in prev_io.items() if p in seen}
      prev_blkio = {p: v for p, v in prev_blkio.items() if p in seen}

    for label, pid, state, d_wchar, d_wbytes, d_blk in rows:
      f.write(f"{t_wall:.3f},{t_mono:.3f},{label},{pid},{state},{d_wchar:.0f},{d_wbytes:.0f},{d_blk:.0f},{disk_dw:.0f},{disk_db:.0f},,,,,,,\n")

    # one SYS row per tick: the kernel-mechanism counters (compaction vs reclaim
    # vs writeback). Compare these against the stall's wall-clock to see which
    # one spiked.
    vm = read_vmstat(); mi = read_meminfo()
    d_compact = vm.get("compact_stall", 0) - prev_vm.get("compact_stall", 0)
    d_alloc = ((vm.get("allocstall_normal", 0) + vm.get("allocstall_movable", 0))
               - (prev_vm.get("allocstall_normal", 0) + prev_vm.get("allocstall_movable", 0)))
    d_majflt = vm.get("pgmajfault", 0) - prev_vm.get("pgmajfault", 0)
    prev_vm = vm
    f.write(f"{t_wall:.3f},{t_mono:.3f},SYS,0,-,,,,,,"
            f"{d_compact},{d_alloc},{d_majflt},{mi.get('Dirty',0)},{mi.get('Writeback',0)},"
            f"{mi.get('MemFree',0)},{mi.get('MemAvailable',0)}\n")

    time.sleep(max(0.0, interval - (time.monotonic() - t_mono)))

if __name__ == "__main__":
  main()

#!/usr/bin/env python3
"""
sendcan_gap_audit.py — measure the openpilot->car actuator TX cadence from an rlog.

WHY: VW PQ random long/lat disengages are caused by control-loop STALLS that
freeze the `sendcan` publish for >100ms. The car's ECU runs a counter/checksum
watchdog on the actuator messages (ACC_System ADR, HCA_1) and FAULTS when frames
arrive late/missing — it does NOT care about the payload value. So the single
metric that predicts the fault is the inter-frame GAP in sendcan, not anything
about accel/torque. (Reference: route 20e3cd4f0d5f39d1|00000038--0f69286335 had a
103ms gap at ~373s -> engine MO2_Sta_GRA->0 -> main switch off -> disengage. A
separate 60ms gap did NOT disengage: the ECU timeout sits ~60-100ms.)

This is the pass/fail metric for the mlockall / loggerd-writeback fix (5324c46)
and, later, the decoupled in-card heartbeat TX. Run it on a BASELINE route to see
the offending gaps, then on POST-FIX drives to confirm they're gone.

  python3 tools/scripts/sendcan_gap_audit.py <route_or_segment> [--warn-ms 30] [--fault-ms 100]

Exit code 0 if no gap >= --fault-ms, else 1 (so it can gate CI / a smoke test).
Read-only; pulls rlogs via the normal LogReader (konn3kt for IQ.Pilot routes).
"""
import argparse
import sys

from openpilot.tools.lib.logreader import LogReader


def audit(route: str, warn_ms: float, fault_ms: float) -> int:
  lr = LogReader(route, sort_by_time=True)

  last = None
  gaps = []          # (t_end, dt_ms) for every gap >= warn_ms
  n = 0
  worst = 0.0
  for m in lr:
    if m.which() != "sendcan":
      continue
    t = m.logMonoTime / 1e9
    n += 1
    if last is not None:
      dt = (t - last) * 1000.0
      worst = max(worst, dt)
      if dt >= warn_ms:
        gaps.append((t, dt))
    last = t

  faults = [(t, dt) for t, dt in gaps if dt >= fault_ms]

  print(f"route            : {route}")
  print(f"sendcan frames   : {n}")
  print(f"worst gap        : {worst:.1f} ms")
  print(f"gaps >= {warn_ms:.0f}ms     : {len(gaps)}")
  print(f"gaps >= {fault_ms:.0f}ms (FAULT-RISK): {len(faults)}")
  if gaps:
    print("\n  t(s)        gap(ms)   risk")
    for t, dt in gaps:
      print(f"  {t:10.3f}  {dt:7.1f}   {'<-- FAULT RISK' if dt >= fault_ms else ''}")

  if faults:
    print(f"\nFAIL: {len(faults)} gap(s) >= {fault_ms:.0f}ms can trip the car's "
          f"actuator counter watchdog (late/missing frames).")
    return 1
  print(f"\nPASS: no sendcan gap >= {fault_ms:.0f}ms.")
  return 0


def main() -> int:
  p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  p.add_argument("route", help="route name, segment, or URL (e.g. dongle|time--hash or .../5:8)")
  p.add_argument("--warn-ms", type=float, default=30.0, help="list gaps >= this (default 30)")
  p.add_argument("--fault-ms", type=float, default=100.0, help="fail on gaps >= this (default 100)")
  args = p.parse_args()
  return audit(args.route, args.warn_ms, args.fault_ms)


if __name__ == "__main__":
  sys.exit(main())

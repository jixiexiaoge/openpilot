#!/usr/bin/env python3
"""Run maneuversd against a synthetic longitudinal plant and write an rlog.

    ./tools/longitudinal_maneuvers/sim_maneuvers.py --out /tmp/long_rlog.zst
    ./tools/longitudinal_maneuvers/generate_report.py /tmp/long_rlog.zst
"""
import argparse
from pathlib import Path

from openpilot.tools.longitudinal_maneuvers.sim_harness import ManeuverSim, Plant

WN = 6.0    # powertrain natural frequency (rad/s)
ZETA = 0.6  # underdamped, so actual accel overshoots the target like a real car


class LongitudinalPlant(Plant):
  def __init__(self):
    super().__init__()
    self.jerk = 0.0

  def step(self, dt, plan):
    a_target = float(plan.aTarget) if plan is not None else 0.0
    if plan is not None and plan.shouldStop:
      a_target = min(a_target, -0.5)

    self.jerk += dt * (WN ** 2 * (a_target - self.a_ego) - 2 * ZETA * WN * self.jerk)
    self.a_ego += dt * self.jerk

    self.v_ego = max(self.v_ego + self.a_ego * dt, 0.0)
    if self.v_ego <= 0.0:
      self.a_ego = min(self.a_ego, 0.0)
      self.jerk = min(self.jerk, 0.0)
    self.lat_accel = 0.0


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--out", type=Path, default=Path("/tmp/longitudinal_maneuvers_sim/rlog.zst"))
  parser.add_argument("--max-maneuvers", type=int, default=0, help="stop after N maneuvers (0 = all)")
  parser.add_argument("--timeout", type=float, default=900.0)
  args = parser.parse_args()

  sim = ManeuverSim("openpilot.tools.longitudinal_maneuvers.maneuversd", LongitudinalPlant(),
                    max_maneuvers=args.max_maneuvers, timeout=args.timeout)
  out = sim.run(args.out)
  print(f"\nmaneuvers seen: {sim.seen_maneuvers}")
  print(f"rlog: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
  main()

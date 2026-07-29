#!/usr/bin/env python3
import argparse
import statistics
import time

import cereal.messaging as messaging


SERVICES = [
  "carState",
  "selfdriveState",
  "controlsState",
  "modelV2",
  "uiDebug",
  "liveCalibration",
]


def summarize(values: list[float]) -> str:
  if not values:
    return "n=0"
  return f"n={len(values)} avg_ms={statistics.fmean(values):.2f} max_ms={max(values):.2f}"


def main() -> None:
  parser = argparse.ArgumentParser(description="On-device runtime lag probe")
  parser.add_argument("--seconds", type=float, default=15.0, help="Sampling window")
  args = parser.parse_args()

  sm = messaging.SubMaster(SERVICES)
  last_seen: dict[str, float] = {}
  gaps: dict[str, list[float]] = {service: [] for service in SERVICES}
  ui_draw_times: list[float] = []
  car_cum_lag: list[float] = []
  model_frame_drop: list[float] = []

  deadline = time.monotonic() + args.seconds
  while time.monotonic() < deadline:
    sm.update(100)
    now = time.monotonic()
    for service in SERVICES:
      if not sm.updated[service]:
        continue
      previous = last_seen.get(service)
      if previous is not None:
        gaps[service].append((now - previous) * 1000.0)
      last_seen[service] = now

    if sm.updated["uiDebug"]:
      ui_draw_times.append(float(sm["uiDebug"].drawTimeMillis))
    if sm.updated["carState"]:
      car_cum_lag.append(float(sm["carState"].cumLagMs))
    if sm.updated["modelV2"]:
      model_frame_drop.append(float(sm["modelV2"].frameDropPerc))

  print("Lag probe summary")
  for service in SERVICES:
    print(f"{service}: {summarize(gaps[service])}")

  print(f"uiDebug.drawTimeMillis: {summarize(ui_draw_times)}")
  print(f"carState.cumLagMs: {summarize(car_cum_lag)}")
  print(f"modelV2.frameDropPerc: {summarize(model_frame_drop)}")

  if sm.seen["liveCalibration"]:
    live_calib = sm["liveCalibration"]
    print(
      "liveCalibration:"
      f" status={int(live_calib.calStatus)}"
      f" calPerc={int(live_calib.calPerc)}"
      f" rpy={list(live_calib.rpyCalib)}"
      f" spread={list(live_calib.rpyCalibSpread)}"
    )


if __name__ == "__main__":
  main()

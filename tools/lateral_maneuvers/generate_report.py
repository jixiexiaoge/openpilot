#!/usr/bin/env python3
"""Lateral maneuver compliance report — analog of tools/longitudinal_maneuvers/generate_report.py.

Produces the "sine 0.5 Hz 30 mph" / "50% peak crossed in X.XXXs" style HTML report comma posts
on social media for steering-rack compliance comparisons. Reads any iqpilot/openpilot rlog
route, slices it into lateral maneuver windows (either by `alertDebug` markers from a scripted
maneuversd run, or by auto-detection of contiguous lat-active sweeps), and emits a 4-panel
plot per run:

    1. Lateral accel (desired + actual, m/s²) on left axis and steering-wheel angle (deg) on
       right axis. Black circle marks the time the actual lat-accel first crosses 50 % of the
       desired peak in the same direction.
    2. Vehicle speed (mph)
    3. Lateral jerk (m/s³), numerically differentiated from actual lat-accel
    4. Roll (deg) from liveParameters

Usage:
    python tools/lateral_maneuvers/generate_report.py <route> [description]

Examples:
    python tools/lateral_maneuvers/generate_report.py 1ce1b50dd82993a1\\|0000003b--a389fbdf35
    python tools/lateral_maneuvers/generate_report.py /path/to/local/rlog.zst "sine 0.5Hz 30mph"
"""
import argparse
import base64
import io
import math
import os
import pprint
import webbrowser
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from tabulate import tabulate

from openpilot.tools.lib.logreader import LogReader
from openpilot.system.hardware.hw import Paths


MPS_TO_MPH = 2.23693629
AUTO_DESIRED_LAT_ACCEL_THRESHOLD = 0.5
AUTO_MIN_V_EGO = 5.0
AUTO_MIN_DURATION_S = 1.5
AUTO_GAP_S = 0.5


def format_car_params(CP):
  return pprint.pformat({k: v for k, v in CP.to_dict().items() if not k.endswith("DEPRECATED")}, indent=2)


def _series(msgs, which):
  rows = [(m.logMonoTime, getattr(m, which)) for m in msgs if m.which() == which]
  if not rows:
    return [], []
  t, v = zip(*rows, strict=True)
  return list(t), list(v)


def _to_relative_seconds(t_ns, t0):
  return [(t - t0) / 1e9 for t in t_ns]


def _resample(t_src, v_src, t_dst):
  if not t_src or not t_dst:
    return np.zeros(len(t_dst))
  return np.interp(t_dst, t_src, v_src)


def _peak_crossing_time(t, desired, actual, fraction=0.5):
  if len(desired) == 0:
    return None, 0.0
  desired = np.asarray(desired)
  actual = np.asarray(actual)
  peak_idx = int(np.argmax(np.abs(desired)))
  peak = desired[peak_idx]
  if abs(peak) < 1e-3:
    return None, peak
  target = fraction * peak
  prev = False
  for i in range(peak_idx + 1):
    crossed = (target > 0 and actual[i] >= target) or (target < 0 and actual[i] <= target)
    if crossed and prev:
      return t[i], peak
    prev = crossed
  return None, peak


def _slice_by_alert_debug(msgs):
  out = []
  active_prev = False
  description_prev = None
  for msg in msgs:
    if msg.which() == "alertDebug":
      # Match both the longitudinal daemon ("Maneuver Active: …") and the lateral daemon
      # ("Active sine …", "Active +0.5m/s² …", "Complete").
      text1 = msg.alertDebug.alertText1
      active = "Maneuver Active" in text1 or text1.startswith("Active") or text1 == "Complete"
      if active and not active_prev:
        if msg.alertDebug.alertText2 == description_prev:
          out[-1][1].append([])
        else:
          out.append((msg.alertDebug.alertText2, [[]]))
        description_prev = out[-1][0]
      active_prev = active
    if active_prev:
      out[-1][1][-1].append(msg)
  return out


def _slice_auto(msgs):
  t_cc, cc_vals = _series(msgs, "carControl")
  t_cs, cs_vals = _series(msgs, "carState")
  if not t_cc or not t_cs:
    return []

  v_ego = np.asarray([m.vEgo for m in cs_vals])
  curvature = np.asarray([m.actuators.curvature for m in cc_vals])
  lat_active = np.asarray([1.0 if m.latActive else 0.0 for m in cc_vals])

  t_cc_s = np.asarray([(t - t_cc[0]) / 1e9 for t in t_cc])
  t_cs_s = np.asarray([(t - t_cc[0]) / 1e9 for t in t_cs])
  v_at_cc = np.interp(t_cc_s, t_cs_s, v_ego)
  desired_lat_accel = curvature * v_at_cc ** 2
  signal = np.abs(desired_lat_accel) * lat_active * (v_at_cc > AUTO_MIN_V_EGO).astype(float)

  cycle_dt = float(np.median(np.diff(t_cc_s))) if len(t_cc_s) > 1 else 0.01
  min_frames = max(1, int(AUTO_MIN_DURATION_S / cycle_dt))

  windows = []
  start = None
  for i, s in enumerate(signal):
    if s > AUTO_DESIRED_LAT_ACCEL_THRESHOLD and start is None:
      start = i
    elif s <= AUTO_DESIRED_LAT_ACCEL_THRESHOLD and start is not None:
      if i - start > min_frames:
        windows.append((t_cc[start], t_cc[i]))
      start = None
  if start is not None and len(signal) - start > min_frames:
    windows.append((t_cc[start], t_cc[-1]))

  merged = []
  for a, b in windows:
    if merged and (a - merged[-1][1]) / 1e9 < AUTO_GAP_S:
      merged[-1] = (merged[-1][0], b)
    else:
      merged.append((a, b))

  runs = []
  for a, b in merged:
    runs.append([m for m in msgs if a <= m.logMonoTime <= b])
  if not runs:
    return []
  return [("auto-detected lateral sweep", runs)]


def _plot_run(description, run_idx, msgs, builder, target_cross_times):
  t_cc, carControl = _series(msgs, "carControl")
  t_cs, carState   = _series(msgs, "carState")
  t_lp, livePose   = _series(msgs, "livePose")

  if not (t_cc and t_cs and t_lp):
    builder.append(f"<p style='color:red'>Run #{run_idx + 1}: missing required data, skipping.</p>\n")
    return

  t0 = min(t_cc[0], t_cs[0], t_lp[0])
  t_cc_s = _to_relative_seconds(t_cc, t0)
  t_cs_s = _to_relative_seconds(t_cs, t0)
  t_lp_s = _to_relative_seconds(t_lp, t0)

  v_ego = np.asarray([m.vEgo for m in carState])
  steer = np.asarray([m.steeringAngleDeg for m in carState])

  curvature = np.asarray([m.actuators.curvature for m in carControl])
  v_at_cc = _resample(t_cs_s, v_ego, t_cc_s)
  desired_lat_accel = curvature * v_at_cc ** 2

  actual_lat_accel = np.asarray([m.accelerationDevice.y for m in livePose])
  jerk = np.gradient(actual_lat_accel, t_lp_s)

  t_lpar, liveParameters = _series(msgs, "liveParameters")
  if liveParameters:
    t_lpar_s = _to_relative_seconds(t_lpar, t0)
    roll_deg = np.asarray([math.degrees(m.roll) for m in liveParameters])
  else:
    t_lpar_s = []
    roll_deg = np.asarray([])

  desired_lat_accel_on_lp = _resample(t_cc_s, desired_lat_accel, t_lp_s)
  cross_time, peak = _peak_crossing_time(t_lp_s, desired_lat_accel_on_lp, actual_lat_accel, fraction=0.5)

  title = f"Run #{run_idx + 1}"
  builder.append(f"<details open><summary><h3 style='display:inline-block;'>{title}</h3></summary>\n")
  if cross_time is not None:
    builder.append(f"<h3 style='font-weight:normal'>50% peak, <strong>crossed in {cross_time:.3f}s</strong></h3>\n")
    target_cross_times[description].append(cross_time)
  else:
    builder.append("<h3 style='font-weight:normal'>50% peak, <strong>not crossed</strong></h3>\n")
  builder.append(f"<h3 style='font-weight:normal'>Peak desired lat accel: <strong>{peak:+.2f} m/s²</strong>, "
                 f"avg speed: <strong>{np.mean(v_ego) * MPS_TO_MPH:.1f} mph</strong></h3>\n")

  plt.rcParams["font.size"] = 32
  fig = plt.figure(figsize=(28, 22))
  ax = fig.subplots(4, 1, sharex=True, gridspec_kw={"height_ratios": [5, 2, 2, 2]})

  ax_la = ax[0]
  ax_la.grid(linewidth=2)
  ax_la.plot(t_cc_s, desired_lat_accel, label="desired lat accel", linewidth=4)
  ax_la.plot(t_lp_s, actual_lat_accel,  label="actual lat accel",  linewidth=4)
  ax_la.set_ylabel("Lateral Accel (m/s²)")

  ax_st = ax_la.twinx()
  ax_st.plot(t_cs_s, steer, color="tab:green", label="steer angle", linewidth=4)
  ax_st.set_ylabel("Steering Angle (deg)")

  lines_l, labels_l = ax_la.get_legend_handles_labels()
  lines_r, labels_r = ax_st.get_legend_handles_labels()
  ax_la.legend(lines_l + lines_r, labels_l + labels_r, loc="upper right", prop={"size": 22})

  if cross_time is not None:
    cross_val = float(np.interp(cross_time, t_lp_s, actual_lat_accel))
    ax_la.plot(cross_time, cross_val, marker="o", markersize=30, markeredgewidth=4,
               markeredgecolor="black", markerfacecolor="None")

  ax[1].grid(linewidth=2)
  ax[1].plot(t_cs_s, v_ego * MPS_TO_MPH, color="tab:blue", label="vEgo", linewidth=4)
  ax[1].set_ylabel("Velocity (mph)")
  ax[1].legend(loc="upper right", prop={"size": 22})

  ax[2].grid(linewidth=2)
  ax[2].plot(t_lp_s, jerk, color="tab:blue", label="actual jerk", linewidth=4)
  ax[2].set_ylabel("Jerk (m/s³)")
  ax[2].legend(loc="upper left", prop={"size": 22})

  ax[3].grid(linewidth=2)
  if len(roll_deg):
    ax[3].plot(t_lpar_s, roll_deg, color="tab:blue", label="roll", linewidth=4)
  ax[3].set_ylabel("Roll (deg)")
  ax[3].legend(loc="upper right", prop={"size": 22})

  ax[-1].set_xlabel("Time (s)")
  fig.tight_layout()

  buffer = io.BytesIO()
  fig.savefig(buffer, format="webp")
  plt.close(fig)
  buffer.seek(0)
  builder.append(f"<img src='data:image/webp;base64,{base64.b64encode(buffer.getvalue()).decode()}' "
                 "style='width:100%; max-width:900px;'>\n")
  builder.append("</details>\n")


def report(platform, route, description, CP, ID, maneuvers):
  output_path = Path(__file__).resolve().parent / "lateral_reports"
  output_path.mkdir(exist_ok=True)
  safe_route = route.replace("/", "_").replace("|", "_")
  output_fn = output_path / f"{platform}_{safe_route}.html"

  target_cross_times = defaultdict(list)

  builder = [
    "<style>summary { cursor: pointer; } td, th { padding: 8px; } body { font-family: Arial, sans-serif; }</style>\n",
    "<h1>Lateral maneuver report</h1>\n",
    f"<h3>{platform}</h3>\n",
    f"<h3>{route}</h3>\n",
    f"<h3>{ID.gitCommit}, {ID.gitBranch}, {ID.gitRemote}</h3>\n",
  ]
  if description is not None:
    builder.append(f"<h3>Description: {description}</h3>\n")
  builder.append(f"<details><summary><h3 style='display:inline-block;'>CarParams</h3></summary><pre>{format_car_params(CP)}</pre></details>\n")
  builder.append("{ summary }")

  for maneuver_description, runs in maneuvers:
    print(f"plotting maneuver: {maneuver_description}, runs: {len(runs)}")
    builder.append("<div style='border-top:1px solid #000; margin:20px 0;'></div>\n")
    builder.append(f"<h2>{maneuver_description}</h2>\n")
    for run_idx, msgs in enumerate(runs):
      _plot_run(maneuver_description, run_idx, msgs, builder, target_cross_times)

  summary = ["<h2>Summary</h2>\n"]
  cols = ["maneuver", "crossed", "runs", "mean (s)", "min (s)", "max (s)"]
  table = []
  for maneuver_description, runs in maneuvers:
    times = target_cross_times[maneuver_description]
    row = [maneuver_description, len(times), len(runs)]
    if times:
      row.extend([round(np.mean(times), 3), round(np.min(times), 3), round(np.max(times), 3)])
    table.append(row)
  summary.append(tabulate(table, headers=cols, tablefmt="html", numalign="left") + "\n")

  sum_idx = builder.index("{ summary }")
  builder[sum_idx:sum_idx + 1] = summary

  with open(output_fn, "w") as f:
    f.write("".join(builder))
  print(f"\nOpening report: {output_fn}\n")
  webbrowser.open_new_tab(str(output_fn))


def _rank_runs(runs, top_n, min_vego_mph, min_peak):
  scored = []
  for r in runs:
    t_cc, cc = _series(r, "carControl")
    t_cs, cs = _series(r, "carState")
    if not (t_cc and t_cs):
      continue
    v_ego = np.mean([m.vEgo for m in cs]) * MPS_TO_MPH
    curv = np.asarray([m.actuators.curvature for m in cc])
    v_at_cc = np.interp([(t - t_cc[0]) / 1e9 for t in t_cc],
                        [(t - t_cc[0]) / 1e9 for t in t_cs],
                        [m.vEgo for m in cs])
    peak = float(np.max(np.abs(curv * v_at_cc ** 2)))
    if v_ego < min_vego_mph or peak < min_peak:
      continue
    scored.append((peak, r))
  scored.sort(key=lambda x: -x[0])
  return [r for _, r in scored[:top_n]] if top_n > 0 else [r for _, r in scored]


def main():
  parser = argparse.ArgumentParser(description="Generate lateral maneuver compliance report from a route")
  parser.add_argument("route", type=str, help="Route name, segment range, local rlog path, or directory of rlogs")
  parser.add_argument("description", type=str, nargs="?")
  parser.add_argument("--auto", action="store_true",
                      help="Auto-detect lateral sweeps instead of relying on alertDebug 'Maneuver Active' markers")
  parser.add_argument("--top-n", type=int, default=10,
                      help="Plot only the N largest-peak sweeps (0 = all). Default 10.")
  parser.add_argument("--min-vego-mph", type=float, default=15.0,
                      help="Drop sweeps below this average speed. Default 15 mph.")
  parser.add_argument("--min-peak", type=float, default=0.5,
                      help="Drop sweeps with peak desired lat accel below this (m/s²). Default 0.5.")
  args = parser.parse_args()

  if os.path.isdir(args.route):
    rlogs = sorted(p for p in Path(args.route).glob("*rlog.zst"))
    if not rlogs:
      raise SystemExit(f"no *rlog.zst files in {args.route}")
    print(f"loading {len(rlogs)} rlogs from {args.route}")
    lr = LogReader([str(p) for p in rlogs])
  elif os.path.exists(args.route):
    lr = LogReader(args.route)
  elif "/" in args.route or "|" in args.route:
    lr = LogReader(args.route)
  else:
    segs = [seg for seg in os.listdir(Paths.log_root()) if args.route in seg]
    lr = LogReader([os.path.join(Paths.log_root(), seg, "rlog.zst") for seg in segs])

  msgs = list(lr)
  CP = next(m.carParams for m in msgs if m.which() == "carParams")
  ID = next(m.initData for m in msgs if m.which() == "initData")
  platform = CP.carFingerprint
  print("processing report for", platform)

  maneuvers = [] if args.auto else _slice_by_alert_debug(msgs)
  if not maneuvers:
    print("no alertDebug 'Maneuver Active' windows found; auto-detecting lateral sweeps")
    maneuvers = _slice_auto(msgs)

  if not maneuvers:
    print("no lateral maneuvers detected — treating the whole route as one run")
    maneuvers = [("full route", [msgs])]
  else:
    filtered = []
    for description, runs in maneuvers:
      kept = _rank_runs(runs, args.top_n, args.min_vego_mph, args.min_peak)
      print(f"  {description}: {len(runs)} candidate sweeps → {len(kept)} after rank/filter")
      if kept:
        filtered.append((description, kept))
    maneuvers = filtered or [("filtered out", [])]

  report(platform, args.route, args.description, CP, ID, maneuvers)


if __name__ == "__main__":
  main()

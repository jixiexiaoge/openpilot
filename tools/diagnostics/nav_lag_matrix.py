#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEO_AUDIT = REPO_ROOT / "tools" / "diagnostics" / "video_lag_audit.py"

NAV_ALL_FALSE = {
  "allow_mapd": False,
  "allow_offline_fallback": False,
  "allow_offline_routing": False,
  "allow_route_updates": False,
  "allow_live_data": False,
  "allow_nav_state": False,
  "allow_render": False,
  "allow_nav_influence": False,
  "allow_on_screen_navigation": False,
  "allow_lane_position": False,
}

SCENARIOS: dict[str, dict | None] = {
  "default": None,
  "all_false": NAV_ALL_FALSE,
  "no_nav_state": {"allow_nav_state": False},
  "no_render": {"allow_render": False},
  "no_live_data": {"allow_live_data": False},
  "no_route_updates": {"allow_route_updates": False},
  "no_mapd_offline_fallback": {"allow_mapd": False, "allow_offline_fallback": False},
  "no_offline_routing": {"allow_offline_routing": False},
  "no_influence_lane": {"allow_nav_influence": False, "allow_lane_position": False},
  "no_onscreen": {"allow_on_screen_navigation": False},
}

LAG_PATTERNS = {
  "navd": re.compile(r"navd step slow total_ms=(?P<total>[0-9.]+)"),
  "card": re.compile(r"card step slow total_ms=(?P<total>[0-9.]+)"),
  "controlsd": re.compile(r"controlsd step slow total_ms=(?P<total>[0-9.]+)"),
  "selfdrived": re.compile(r"selfdrived step slow total_ms=(?P<total>[0-9.]+)"),
  "selfdrived_sample": re.compile(r"selfdrived sample slow total_ms=(?P<total>[0-9.]+)"),
}


def run(cmd: list[str], *, check: bool = True, capture: bool = True, cwd: Path | None = None) -> str:
  result = subprocess.run(
    cmd,
    cwd=cwd,
    check=check,
    capture_output=capture,
    text=True,
  )
  return result.stdout if capture else ""


def ssh(host: str, command: str, *, check: bool = True) -> str:
  return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, command], check=check)


def scp_from(host: str, remote_path: str, local_path: Path) -> None:
  local_path.parent.mkdir(parents=True, exist_ok=True)
  subprocess.run(
    ["scp", "-q", f"{host}:{remote_path}", str(local_path)],
    check=True,
    capture_output=True,
    text=True,
  )


def remote_write_json(host: str, remote_path: str, payload: dict) -> None:
  encoded = json.dumps(payload, sort_keys=True)
  ssh(host, f"cat > {shlex.quote(remote_path)} <<'EOF'\n{encoded}\nEOF")


def remote_remove(host: str, remote_path: str) -> None:
  ssh(host, f"rm -f {shlex.quote(remote_path)}")


def set_nav_flags(host: str, flags: dict | None) -> None:
  remote_path = "/data/params/d/NavigationDebugFlags"
  if flags is None:
    remote_remove(host, remote_path)
  else:
    remote_write_json(host, remote_path, flags)


def set_screen_recording(host: str, enabled: bool) -> None:
  value = "1" if enabled else "0"
  ssh(host, f"printf '{value}' > /data/params/d/ScreenRecording")


def clear_issue_debug(host: str) -> None:
  ssh(host, "mkdir -p /data/community && : > /data/community/iqpilot_issue_debug.txt")


def list_screen_recordings(host: str) -> list[str]:
  output = ssh(host, "ls -1t /data/media/0/screen_recordings/*.mp4 2>/dev/null || true")
  return [line.strip() for line in output.splitlines() if line.strip()]


def newest_recording_after(host: str, before: set[str]) -> str | None:
  after = list_screen_recordings(host)
  for candidate in after:
    if candidate not in before:
      return candidate
  return after[0] if after else None


def fetch_issue_debug(host: str, output_dir: Path) -> Path:
  local_path = output_dir / "iqpilot_issue_debug.txt"
  scp_from(host, "/data/community/iqpilot_issue_debug.txt", local_path)
  return local_path


def parse_issue_debug(path: Path) -> dict:
  counts = defaultdict(int)
  maxima = defaultdict(float)
  calibration_lines = 0

  if not path.exists():
    return {"counts": {}, "max_total_ms": {}, "calibration_lines": 0}

  for line in path.read_text(errors="replace").splitlines():
    if "calibrationd" in line:
      calibration_lines += 1
    for key, pattern in LAG_PATTERNS.items():
      match = pattern.search(line)
      if match:
        counts[key] += 1
        maxima[key] = max(maxima[key], float(match.group("total")))

  return {
    "counts": dict(counts),
    "max_total_ms": dict(maxima),
    "calibration_lines": calibration_lines,
  }


def run_remote_demo(host: str, scenario_dir: str, fixture: str, provider: str) -> str:
  cmd = (
    f"cd /data/openpilot && "
    f"scripts/iqpilot/run_device_nav_demo.sh --fixture {shlex.quote(fixture)} "
    f"--provider {shlex.quote(provider)} --output-dir {shlex.quote(scenario_dir)} --no-gif"
  )
  return ssh(host, cmd)


def run_remote_lag_probe(host: str, seconds: float, output_path: str) -> None:
  cmd = (
    "cd /data/openpilot && "
    f"PYTHONPATH=. python3 tools/diagnostics/lag_probe.py --seconds {seconds:.1f} > {shlex.quote(output_path)} 2>&1"
  )
  ssh(host, cmd)


def fetch_latest_demo_video(host: str, scenario_dir: str, output_dir: Path) -> Path | None:
  remote_video = f"{scenario_dir}/nav_demo.mp4"
  try:
    local_path = output_dir / "nav_demo.mp4"
    scp_from(host, remote_video, local_path)
    return local_path
  except subprocess.CalledProcessError:
    return None


def fetch_remote_file(host: str, remote_path: str, output_dir: Path, local_name: str) -> Path | None:
  local_path = output_dir / local_name
  try:
    scp_from(host, remote_path, local_path)
    return local_path
  except subprocess.CalledProcessError:
    return None


def summarize_video(video_path: Path, output_dir: Path) -> dict | None:
  if not video_path or not video_path.exists():
    return None
  payload = run([
    "python3",
    str(VIDEO_AUDIT),
    str(video_path),
    "--output-dir",
    str(output_dir / "video_audit"),
  ])
  return json.loads(payload)


def run_live_capture(host: str, seconds: float) -> tuple[str | None, str | None]:
  before = set(list_screen_recordings(host))
  set_screen_recording(host, True)
  try:
    time.sleep(seconds)
  finally:
    set_screen_recording(host, False)
  time.sleep(3.0)
  remote_video = newest_recording_after(host, before)
  probe_remote = "/data/community/nav_lag_probe.txt"
  try:
    run_remote_lag_probe(host, min(seconds, 20.0), probe_remote)
  except subprocess.CalledProcessError:
    probe_remote = None
  return remote_video, probe_remote


def scenario_flags(name: str) -> dict | None:
  if name not in SCENARIOS:
    raise KeyError(f"unknown scenario: {name}")
  return SCENARIOS[name]


def main() -> None:
  parser = argparse.ArgumentParser(description="Run nav lag feature matrix on a comma device and collect videos/logs.")
  parser.add_argument("--host", default="arman3x", help="SSH host alias")
  parser.add_argument("--mode", choices=["live", "demo"], default="live", help="Capture live screen recording or deterministic UI nav demo")
  parser.add_argument("--duration", type=float, default=20.0, help="Live capture duration in seconds")
  parser.add_argument("--fixture", default="bolingbrook-carol-stream", help="Fixture alias/path for demo mode")
  parser.add_argument("--provider", default="offline", choices=["offline", "cached", "mapbox"], help="Provider for demo mode")
  parser.add_argument("--scenarios", nargs="+", default=["default", "all_false"], help="Scenario names to run")
  parser.add_argument("--output-dir", type=Path, default=Path("nav_lag_matrix_runs"), help="Local artifact directory")
  args = parser.parse_args()

  run_root = args.output_dir / time.strftime("%Y%m%d_%H%M%S")
  run_root.mkdir(parents=True, exist_ok=True)
  summary = {
    "host": args.host,
    "mode": args.mode,
    "fixture": args.fixture,
    "provider": args.provider,
    "scenarios": [],
  }

  for scenario_name in args.scenarios:
    flags = scenario_flags(scenario_name)
    scenario_dir = run_root / scenario_name
    scenario_dir.mkdir(parents=True, exist_ok=True)
    clear_issue_debug(args.host)
    set_nav_flags(args.host, flags)
    time.sleep(2.0)

    remote_probe = None
    local_video = None
    if args.mode == "demo":
      remote_dir = f"/data/nav_demo_tests/{scenario_name}_{int(time.time())}"
      demo_stdout = run_remote_demo(args.host, remote_dir, args.fixture, args.provider)
      (scenario_dir / "demo_stdout.txt").write_text(demo_stdout)
      local_video = fetch_latest_demo_video(args.host, remote_dir, scenario_dir)
    else:
      remote_video, remote_probe = run_live_capture(args.host, args.duration)
      if remote_video:
        local_video = fetch_remote_file(args.host, remote_video, scenario_dir, Path(remote_video).name)

    iqdebug_path = fetch_issue_debug(args.host, scenario_dir)
    probe_path = None
    if remote_probe:
      probe_path = fetch_remote_file(args.host, remote_probe, scenario_dir, "lag_probe.txt")

    video_summary = summarize_video(local_video, scenario_dir) if local_video else None
    debug_summary = parse_issue_debug(iqdebug_path)

    scenario_summary = {
      "scenario": scenario_name,
      "flags": flags,
      "video": str(local_video) if local_video else None,
      "probe": str(probe_path) if probe_path else None,
      "issue_debug": str(iqdebug_path),
      "debug_summary": debug_summary,
      "video_summary": video_summary,
    }
    summary["scenarios"].append(scenario_summary)
    (scenario_dir / "summary.json").write_text(json.dumps(scenario_summary, indent=2, sort_keys=True) + "\n")

  summary_path = run_root / "summary.json"
  summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
  print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
  main()

#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BASEDIR = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))

if BASEDIR not in sys.path:
  sys.path.insert(0, BASEDIR)


def _kill_openpilot() -> None:
  subprocess.run(["tmux", "kill-session", "-t", "comma"],
                 capture_output=True, timeout=10)
  try:
    os.unlink("/tmp/safe_staging_overlay.lock")
  except FileNotFoundError:
    pass


def _restart_openpilot() -> None:
  import shlex
  launch = shlex.quote(os.path.join(BASEDIR, "launch_openpilot.sh"))
  subprocess.run(
    f"tmux new -s comma -d \"bash -lc {launch}\"",
    shell=True, timeout=10,
  )


def _run_eps_script(action: str) -> tuple[str, str, bool]:
  script = os.path.join(BASEDIR, "selfdrive", "debug", "car", "vw_mqb_config.py")
  try:
    proc = subprocess.run(
      [sys.executable, script, action],
      capture_output=True,
      text=True,
      timeout=30,
    )
  except subprocess.TimeoutExpired:
    return "", "Timeout: EPS did not respond. Check vehicle ignition is on.", False
  except Exception as exc:
    return "", str(exc), False

  output = proc.stdout or ""
  stderr = (proc.stderr or "").strip()

  _error_markers = (
    "Timeout opening session",
    "Timeout fetching data",
    "Error fetching data",
    "Configuration changes not yet supported",
    "Security access failed",
    "Make sure the comma processes are stopped",
    "Writing new configuration failed",
    "Reading back updated coding failed",
  )
  found_error = next((m for m in _error_markers if m in output), None)
  if found_error:
    error_lines = [l.strip() for l in output.splitlines()
                   if l.strip() and any(m in l for m in _error_markers)]
    error_msg = "\n".join(error_lines) if error_lines else found_error
    if "Make sure the comma processes are stopped" in error_msg:
      error_msg = "EPS communication failed. Make sure the comma processes are stopped and retry."
    return output, error_msg, False

  if stderr and proc.returncode != 0:
    return output, stderr, False

  if action == "show":
    success = "EPS diagnostic data" in output
  else:
    success = "EPS configuration successfully updated" in output

  return output, "", success


def main() -> None:
  action = sys.argv[1].lower() if len(sys.argv) > 1 else "show"
  if action not in ("show", "enable", "disable"):
    action = "show"

  try:
    from openpilot.common.params import Params
    params = Params()
  except Exception:
    params = None

  result: dict = {"action": action, "success": False, "output": "", "error": ""}

  try:
    _kill_openpilot()

    time.sleep(2)

    output, error, success = _run_eps_script(action)
    result["output"]  = output
    result["error"]   = error
    result["success"] = success

  except Exception as exc:
    result["error"] = str(exc)

  if params is not None:
    try:
      has_fresh_data = ("EPS diagnostic data" in result.get("output", "")
                        or result.get("success"))
      if has_fresh_data:
        params.put("VWLKASCodingResult", json.dumps(result))
      else:
        prev_raw = params.get("VWLKASCodingResult")
        if not prev_raw:
          params.put("VWLKASCodingResult", json.dumps(result))
        else:
          try:
            prev = json.loads(prev_raw if isinstance(prev_raw, str)
                              else prev_raw.decode("utf-8", errors="replace"))
            prev["shown"] = False  # force dialog to re-appear with new error
          except Exception:
            prev = {}
          error_overlay = {**prev,
                           "action": action,
                           "success": False,
                           "error": result["error"],
                           "shown": False}
          params.put("VWLKASCodingResult", json.dumps(error_overlay))
      params.put_bool("VWLKASCodingActive", False)
    except Exception:
      pass

  try:
    _restart_openpilot()
  except Exception:
    pass


if __name__ == "__main__":
  main()

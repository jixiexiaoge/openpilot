import os
import threading
import time
from datetime import datetime
from pathlib import Path

from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths


DEBUG_FILENAME = "iqpilot_issue_debug.txt"
DEBUG_PATH = Path(Paths.comma_home()) / "community" / DEBUG_FILENAME if PC else Path("/data/community") / DEBUG_FILENAME

_lock = threading.Lock()
_last_log_times: dict[str, float] = {}


def log_issue(tag: str, message: str) -> None:
  try:
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
      with open(DEBUG_PATH, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        f.write(f"[{timestamp}] [{tag}] {message}\n")
  except OSError:
    pass


def log_issue_limited(key: str, tag: str, message: str, interval_sec: float = 1.0) -> None:
  now = time.monotonic()
  with _lock:
    last = _last_log_times.get(key, 0.0)
    if now - last < interval_sec:
      return
    _last_log_times[key] = now

  log_issue(tag, message)


def clear_issue_debug_log() -> None:
  try:
    os.remove(DEBUG_PATH)
  except OSError:
    pass

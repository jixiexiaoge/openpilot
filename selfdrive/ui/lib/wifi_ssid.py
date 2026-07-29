import time
import threading
import subprocess

# Shared, throttled current-Wi-Fi-SSID lookup for the status bars (home pill + onroad sidebar).
# The SSID isn't in deviceState, so we shell out to NetworkManager on a background thread and cache
# the result; the render thread only ever reads the cached string.

_ssid = ""
_last_fetch = 0.0
_fetching = False
_lock = threading.Lock()
REFRESH_SECONDS = 10.0


def _read_ssid() -> str:
  try:
    out = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                         capture_output=True, text=True, timeout=4).stdout
    for line in out.splitlines():
      if line.startswith("yes:"):
        name = line.split(":", 1)[1].strip()
        if name:
          return name
  except Exception:
    pass
  try:
    name = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=4).stdout.strip()
    if name:
      return name
  except Exception:
    pass
  return ""


def _fetch() -> None:
  global _ssid, _last_fetch, _fetching
  name = _read_ssid()
  with _lock:
    _ssid = name
    _last_fetch = time.monotonic()
    _fetching = False


def current_ssid(on_wifi: bool) -> str:
  """Return the connected SSID (or "" if unknown / not on Wi-Fi). Kicks a throttled background
  refresh; never blocks the caller."""
  global _fetching
  if not on_wifi:
    return ""
  with _lock:
    if not _fetching and time.monotonic() - _last_fetch > REFRESH_SECONDS:
      _fetching = True
      threading.Thread(target=_fetch, daemon=True).start()
    return _ssid

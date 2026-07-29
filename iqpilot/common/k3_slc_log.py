from datetime import datetime

from openpilot.common.swaglog import cloudlog

K3_SLC_LOG_FILE = "/data/openpilot/k3_slc.txt"


def k3_slc_log(message: str) -> None:
  try:
    with open(K3_SLC_LOG_FILE, "a") as f:
      timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
      f.write(f"[{timestamp}] {message}\n")
      f.flush()
  except Exception as e:
    cloudlog.error(f"[K3_SLC] Failed to write debug log: {e}")

import os

from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware.hw import Paths

PRESERVE_ATTR_NAME = b"user.preserve"
PRESERVE_ATTR_VALUE = b"1"


def recover_unclean_segments(log_root: str | None = None) -> list[str]:
  # Segments with leftover .lock files are from a loggerd that never closed
  # cleanly (power cut, crash). The video/log data in them is valid up to the
  # last durable sync. Clear the stale locks so the deleter can manage them
  # again, and preserve them: footage from an unclean shutdown is exactly the
  # footage a dashcam must not throw away.
  root = log_root if log_root is not None else Paths.log_root()
  recovered = []
  try:
    dirs = os.listdir(root)
  except OSError:
    return recovered

  for d in dirs:
    seg_path = os.path.join(root, d)
    if not os.path.isdir(seg_path):
      continue
    try:
      locks = [f for f in os.listdir(seg_path) if f.endswith(".lock")]
      if not locks:
        continue
      for lock in locks:
        os.unlink(os.path.join(seg_path, lock))
      setxattr = getattr(os, "setxattr", None)  # not available on darwin
      if setxattr is not None:
        try:
          setxattr(seg_path, PRESERVE_ATTR_NAME, PRESERVE_ATTR_VALUE)
        except OSError:
          pass
      recovered.append(d)
    except OSError:
      cloudlog.exception(f"crash_recovery: failed to recover {seg_path}")

  if recovered:
    cloudlog.event("crash_recovery.recovered_unclean_segments", segments=sorted(recovered), error=True)
  return recovered

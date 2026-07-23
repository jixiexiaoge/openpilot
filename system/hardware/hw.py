import os
import platform
from pathlib import Path

from openpilot.system.hardware import PC

DEFAULT_DOWNLOAD_CACHE_ROOT = "/tmp/comma_download_cache"

class Paths:
  _persist_root_cache: str | None = None

  @staticmethod
  def _is_writable_persist_root(path: str) -> bool:
    try:
      os.makedirs(path, exist_ok=True)
      comma_dir = os.path.join(path, "comma")
      os.makedirs(comma_dir, exist_ok=True)

      probe_path = os.path.join(comma_dir, ".rw_probe")
      with open(probe_path, "w") as f:
        f.write("1")
      os.remove(probe_path)
      return True
    except OSError:
      return False

  @staticmethod
  def comma_home() -> str:
    return os.path.join(str(Path.home()), ".comma" + os.environ.get("OPENPILOT_PREFIX", ""))

  @staticmethod
  def log_root() -> str:
    if os.environ.get('LOG_ROOT', False):
      return os.environ['LOG_ROOT']
    elif PC:
      return str(Path(Paths.comma_home()) / "media" / "0" / "realdata")
    else:
      return '/data/media/0/realdata/'

  @staticmethod
  def log_root_external() -> str:
    return '/mnt/external_realdata/'

  @staticmethod
  def swaglog_root() -> str:
    if PC:
      return os.path.join(Paths.comma_home(), "log")
    else:
      return "/data/log/"

  @staticmethod
  def swaglog_ipc() -> str:
    return "ipc:///tmp/logmessage" + os.environ.get("OPENPILOT_PREFIX", "")

  @staticmethod
  def download_cache_root() -> str:
    if os.environ.get('COMMA_CACHE', False):
      return os.environ['COMMA_CACHE'] + "/"
    return DEFAULT_DOWNLOAD_CACHE_ROOT + os.environ.get("OPENPILOT_PREFIX", "") + "/"

  @staticmethod
  def persist_root() -> str:
    if PC:
      return os.path.join(Paths.comma_home(), "persist")

    if Paths._persist_root_cache is not None:
      return Paths._persist_root_cache

    for candidate in ("/persist", "/data/persist"):
      if Paths._is_writable_persist_root(candidate):
        Paths._persist_root_cache = candidate
        return candidate

    # Keep previous behavior as a last resort.
    Paths._persist_root_cache = "/persist"
    return Paths._persist_root_cache

  @staticmethod
  def stats_root() -> str:
    if PC:
      return str(Path(Paths.comma_home()) / "stats")
    else:
      return "/data/stats/"

  @staticmethod
  def stats_iq_root() -> str:
    if PC:
      return str(Path(Paths.comma_home()) / "stats")
    else:
      return "/data/stats_iq/"

  @staticmethod
  def config_root() -> str:
    if PC:
      return Paths.comma_home()
    else:
      return "/tmp/.comma"

  @staticmethod
  def shm_path() -> str:
    if PC and platform.system() == "Darwin":
      return "/tmp"  # This is not really shared memory on macOS, but it's the closest we can get
    return "/dev/shm"

  @staticmethod
  def model_root() -> str:
    if PC:
      return str(Path(Paths.comma_home()) / "media" / "0" / "models")
    else:
      return "/data/media/0/models"

  @staticmethod
  def crash_log_root() -> str:
    if PC:
      return str(Path(Paths.comma_home()) / "community" / "crashes")
    else:
      return "/data/community/crashes"

  @staticmethod
  def mapd_root() -> str:
    if PC:
      return str(Path(Paths.comma_home()) / "media" / "0" / "osm")
    else:
      return "/data/media/0/osm"

  @staticmethod
  def screen_recordings_root() -> str:
    if PC:
      return str(Path(Paths.comma_home()) / "media" / "0" / "screen_recordings")
    else:
      return "/data/media/0/screen_recordings"

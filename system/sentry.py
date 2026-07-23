"""Install exception handler for process crash."""
import os
import shutil
import traceback
from datetime import datetime
import sentry_sdk
from enum import Enum
from sentry_sdk.integrations.threading import ThreadingIntegration

from openpilot.common.params import Params
from openpilot.iqpilot.konn3kt.registration import UNREGISTERED_DONGLE_ID
from openpilot.system.hardware import HARDWARE
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog
from openpilot.system.version import get_build_metadata, get_version

CRASHES_DIR = Paths.crash_log_root()
CRASH_UPLOADS_DIR = os.path.join(Paths.log_root(), "crash")


class SentryProject(Enum):
  # python project
  SELFDRIVE = "https://186a6736b7927e5ae9b92c869ba81b6b@o1138119.ingest.us.sentry.io/4508660076052480"
  # native project
  SELFDRIVE_NATIVE = SELFDRIVE


def _sentry_enabled() -> bool:
  return os.getenv("IQPILOT_ENABLE_SENTRY", "0") == "1"


def _ensure_dir(path: str) -> None:
  os.makedirs(path, exist_ok=True)


def _queue_crash_upload(src: str, name: str | None = None) -> None:
  try:
    _ensure_dir(CRASH_UPLOADS_DIR)
    dest_name = name or os.path.basename(src)
    shutil.copyfile(src, os.path.join(CRASH_UPLOADS_DIR, dest_name))
  except Exception:
    cloudlog.exception("error when attempting to queue crash upload")


def report_tombstone(fn: str, message: str, contents: str) -> None:
  cloudlog.error({'tombstone': message})

  if not _sentry_enabled():
    return

  with sentry_sdk.configure_scope() as scope:
    set_user()
    scope.set_extra("tombstone_fn", fn)
    scope.set_extra("tombstone", contents)
    sentry_sdk.capture_message(message=message)
    sentry_sdk.flush()


def capture_exception(*args, **kwargs) -> None:
  cloudlog.error("crash", exc_info=kwargs.get('exc_info', 1))

  try:
    save_exception(traceback.format_exc())

    if not _sentry_enabled():
      return

    set_user()
    sentry_sdk.capture_exception(*args, **kwargs)
    sentry_sdk.flush()  # https://github.com/getsentry/sentry-python/issues/291
  except Exception:
    cloudlog.exception("sentry exception")


def save_exception(content: str) -> None:
  try:
    _ensure_dir(CRASHES_DIR)
    commit = (get_build_metadata().openpilot.git_commit or "nocommit")[:8]

    dated_fn = os.path.join(CRASHES_DIR, datetime.now().strftime("%Y-%m-%d--%H-%M-%S.log"))
    files = [
      dated_fn,
      os.path.join(CRASHES_DIR, "error.log")
    ]

    for fn in files:
      with open(fn, 'w') as f:
        if os.path.basename(fn) == "error.log":
          lines = content.splitlines()[-3:]
          f.write("\n".join(lines))
        else:
          f.write(content)

    upload_name = f"{os.path.splitext(os.path.basename(dated_fn))[0]}_{commit}_python.log"
    _queue_crash_upload(dated_fn, upload_name)
    cloudlog.error(f"logged crash to {files}")
  except Exception:
    cloudlog.exception("error when attempting to save exception")


def capture_fingerprint_mock() -> None:
  try:
    set_user()
    message = "car doesn't match any fingerprints"
    sentry_sdk.capture_message(message=message, level="error")
    sentry_sdk.flush()
  except Exception as e:
    cloudlog.exception(f"sentry fingerprint MOCK exception: {e}")


def capture_fingerprint(candidate: str, car_name: str) -> None:
  try:
    set_user()
    sentry_sdk.set_tag("carFingerprint", candidate)
    sentry_sdk.set_tag("carName", car_name)

    message = f"Fingerprinted {candidate}"
    sentry_sdk.capture_message(message=message, level="info")
    sentry_sdk.flush()
  except Exception as e:
    cloudlog.exception(f"sentry fingerprint exception: {e}")


def set_tag(key: str, value: str) -> None:
  sentry_sdk.set_tag(key, value)


def set_user() -> None:
  dongle_id, git_username = get_properties()
  sentry_sdk.set_user({"id": dongle_id, "name": git_username})


def get_properties() -> tuple[str, str]:
  params = Params()
  hardware_serial: str = params.get("HardwareSerial") or ""
  git_username: str = params.get("GithubUsername") or ""
  dongle_id: str = params.get("DongleId") or f"{UNREGISTERED_DONGLE_ID}-{hardware_serial}"

  return dongle_id, git_username


def init(project: SentryProject) -> bool:
  if not _sentry_enabled():
    cloudlog.info("Sentry disabled, using local crash logging + konn3kt uploader")
    return False

  build_metadata = get_build_metadata()

  env = build_metadata.channel_type
  dongle_id, git_username = get_properties()

  integrations = []
  if project == SentryProject.SELFDRIVE:
    integrations.append(ThreadingIntegration(propagate_hub=True))

  sentry_sdk.init(project.value,
                  default_integrations=False,
                  release=get_version(),
                  integrations=integrations,
                  traces_sample_rate=1.0,
                  max_value_length=8192,
                  environment=env)

  sentry_sdk.set_user({"id": dongle_id, "name": git_username})
  sentry_sdk.set_tag("dirty", build_metadata.openpilot.is_dirty)
  sentry_sdk.set_tag("origin", build_metadata.openpilot.git_origin)
  sentry_sdk.set_tag("branch", build_metadata.channel)
  sentry_sdk.set_tag("commit", build_metadata.openpilot.git_commit)
  sentry_sdk.set_tag("device", HARDWARE.get_device_type())

  return True

from enum import IntEnum
import os
import requests
import threading
import time
from pathlib import Path

from openpilot.common.api import api_get
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot.konn3kt.registration import UNREGISTERED_DONGLE_ID, get_cached_dongle_id, ensure_dev_pairing_identity
from openpilot.selfdrive.ui.lib.api_helpers import get_token
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths


class PrimeType(IntEnum):
  UNKNOWN = -2
  UNPAIRED = -1
  NONE = 0
  MAGENTA = 1
  LITE = 2
  BLUE = 3
  MAGENTA_NEW = 4
  PURPLE = 5


class PrimeState:
  FETCH_INTERVAL = 5.0  # seconds between API calls
  API_TIMEOUT = 10.0  # seconds for API requests
  SLEEP_INTERVAL = 0.5  # seconds to sleep between checks in the worker thread

  def __init__(self):
    self._params = Params()
    self._lock = threading.Lock()
    self._session = requests.Session()  # reuse session to reduce SSL handshake overhead
    # Must be computed at runtime (OPENPILOT_PREFIX can change paths).
    # Keep a writable fallback in /tmp in case /persist becomes read-only.
    self._konn3kt_state_paths = [
      Path(Paths.persist_root()) / "comma" / "konn3kt_prime_type",
      Path(Paths.config_root()) / "konn3kt_prime_type",
    ]

    if PC and os.getenv("KONN3KT_DEV_PAIRING") == "1":
      try:
        ensure_dev_pairing_identity(self._params, force_reset=os.getenv("KONN3KT_DEV_PAIRING_RESET") == "1")
        # Avoid stale comma-stock PrimeType making the UI look paired.
        self._write_cached_state(PrimeType.UNPAIRED)
      except Exception as e:
        cloudlog.error(f"dev pairing identity setup failed: {e}")

    self.prime_type: PrimeType = self._load_initial_state()

    self._running = False
    self._thread = None

  def _write_cached_state(self, prime_type: PrimeType) -> None:
    payload = str(int(prime_type))
    for path in self._konn3kt_state_paths:
      try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
        return
      except OSError:
        # Try next fallback path.
        continue
      except Exception:
        cloudlog.exception("failed to write konn3kt pairing cache")
        return
    cloudlog.warning("failed to write konn3kt pairing cache to any path")

  def _load_initial_state(self) -> PrimeType:
    # IMPORTANT: do not use Params('PrimeType') here.
    # Stock/Connect also uses it, and it being "0" would incorrectly hide pairing UI.
    prime_type_str = os.getenv("PRIME_TYPE")
    try:
      if prime_type_str is not None:
        return PrimeType(int(prime_type_str))
    except (ValueError, TypeError):
      pass
    for path in self._konn3kt_state_paths:
      try:
        if path.is_file():
          return PrimeType(int(path.read_text().strip()))
      except Exception:
        cloudlog.exception("failed to read konn3kt pairing cache")
    return PrimeType.UNKNOWN

  def _fetch_prime_status(self) -> None:
    dongle_id = get_cached_dongle_id(self._params, prefer_readonly=True)
    if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
      return

    try:
      identity_token = get_token(dongle_id)
      response = api_get(f"v1.1/devices/{dongle_id}", timeout=self.API_TIMEOUT, access_token=identity_token, session=self._session)
      if response.status_code == 200:
        data = response.json()
        is_paired = data.get("is_paired", False)
        prime_type = data.get("prime_type", 0)
        self.set_type(PrimeType(prime_type) if is_paired else PrimeType.UNPAIRED)
      elif response.status_code == 404:
        self.set_type(PrimeType.UNPAIRED)
    except Exception as e:
      cloudlog.error(f"Failed to fetch prime status: {e}")

  def set_type(self, prime_type: PrimeType) -> None:
    with self._lock:
      if prime_type != self.prime_type:
        self.prime_type = prime_type
        self._write_cached_state(prime_type)
        cloudlog.info(f"Prime type updated to {prime_type}")

  def _worker_thread(self) -> None:
    from openpilot.selfdrive.ui.ui_state import ui_state, device
    while self._running:
      if not ui_state.started and device._awake:
        self._fetch_prime_status()

      for _ in range(int(self.FETCH_INTERVAL / self.SLEEP_INTERVAL)):
        if not self._running:
          break
        time.sleep(self.SLEEP_INTERVAL)

  def start(self) -> None:
    if self._thread and self._thread.is_alive():
      return
    self._running = True
    self._thread = threading.Thread(target=self._worker_thread, daemon=True)
    self._thread.start()

  def stop(self) -> None:
    self._running = False
    if self._thread and self._thread.is_alive():
      self._thread.join(timeout=1.0)

  def get_type(self) -> PrimeType:
    with self._lock:
      return self.prime_type

  def is_prime(self) -> bool:
    with self._lock:
      return bool(self.prime_type > PrimeType.NONE)

  def is_paired(self) -> bool:
    with self._lock:
      return self.prime_type > PrimeType.UNPAIRED

  def __del__(self):
    self.stop()

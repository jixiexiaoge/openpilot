from enum import IntEnum
import os
import threading
import time
from pathlib import Path

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.common.time_helpers import system_time_valid
from openpilot.iqpilot.konn3kt.cloud_client import Konn3ktApi
from openpilot.iqpilot.konn3kt.registration import UNREGISTERED_DONGLE_ID, get_cached_dongle_id, ensure_dev_pairing_identity
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths


class PairState(IntEnum):
  UNKNOWN = -2
  UNPAIRED = -1
  PAIRED = 0


class PrimeState:
  FETCH_INTERVAL = 5.0  # seconds between konn3kt pairing checks
  API_TIMEOUT = 10.0  # seconds for konn3kt API requests
  SLEEP_INTERVAL = 0.5  # seconds to sleep between checks in the worker thread

  def __init__(self):
    self._params = Params()
    self._lock = threading.Lock()
    # Must be computed at runtime (OPENPILOT_PREFIX can change paths).
    # Keep a writable fallback in /tmp in case /persist becomes read-only.
    self._konn3kt_state_paths = [
      Path(Paths.persist_root()) / "comma" / "konn3kt_prime_type",
      Path(Paths.config_root()) / "konn3kt_prime_type",
    ]

    if PC and os.getenv("KONN3KT_DEV_PAIRING") == "1":
      try:
        ensure_dev_pairing_identity(self._params, force_reset=os.getenv("KONN3KT_DEV_PAIRING_RESET") == "1")
        self._write_cached_state(PairState.UNPAIRED)
      except Exception as e:
        cloudlog.error(f"dev pairing identity setup failed: {e}")

    self.pair_state: PairState = self._load_initial_state()

    self._running = False
    self._thread = None

  def _write_cached_state(self, pair_state: PairState) -> None:
    payload = str(int(pair_state))
    for path in self._konn3kt_state_paths:
      try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
        return
      except OSError:
        continue
      except Exception:
        cloudlog.exception("failed to write konn3kt pairing cache")
        return
    cloudlog.warning("failed to write konn3kt pairing cache to any path")

  def _coerce(self, value: int | None) -> PairState:
    if value is None:
      return PairState.UNKNOWN
    if value >= 0:
      return PairState.PAIRED
    if value == PairState.UNPAIRED:
      return PairState.UNPAIRED
    return PairState.UNKNOWN

  def _load_initial_state(self) -> PairState:
    env_val = os.getenv("PRIME_TYPE")
    if env_val is not None:
      try:
        return self._coerce(int(env_val))
      except (ValueError, TypeError):
        pass
    for path in self._konn3kt_state_paths:
      try:
        if path.is_file():
          return self._coerce(int(path.read_text().strip()))
      except Exception:
        cloudlog.exception("failed to read konn3kt pairing cache")
    return PairState.UNKNOWN

  def _refresh_pair_status(self) -> None:
    dongle_id = get_cached_dongle_id(self._params, prefer_readonly=True)
    if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
      return

    # the JWT can't be minted until the clock is NTP-synced; at boot skip
    # quietly instead of error-spamming every retry
    if not system_time_valid():
      return

    try:
      api = Konn3ktApi(dongle_id)
      resp = api.get(f"v1.1/devices/{dongle_id}", timeout=self.API_TIMEOUT, access_token=api.get_token())
      if resp.status_code == 200:
        paired = bool(resp.json().get("is_paired", False))
        self.set_paired(paired)
      elif resp.status_code == 404:
        self.set_paired(False)
    except Exception as e:
      cloudlog.error(f"failed to fetch konn3kt pairing status: {e}")

  def set_paired(self, paired: bool) -> None:
    new_state = PairState.PAIRED if paired else PairState.UNPAIRED
    with self._lock:
      if new_state != self.pair_state:
        self.pair_state = new_state
        self._write_cached_state(new_state)
        cloudlog.info(f"konn3kt pairing updated to {new_state}")

  def _worker_thread(self) -> None:
    from openpilot.selfdrive.ui.ui_state import ui_state, device
    while self._running:
      if not ui_state.started and device._awake:
        self._refresh_pair_status()

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

  def is_paired(self) -> bool:
    with self._lock:
      return self.pair_state > PairState.UNPAIRED

  def __del__(self):
    self.stop()

#!/usr/bin/env python3
import os
import time
import json
import jwt
import re
import secrets
from typing import cast
from pathlib import Path

from datetime import datetime, timedelta, UTC
from openpilot.common.api import api_get, get_key_pair
from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog


UNREGISTERED_DONGLE_ID = "UnregisteredDevice"

_DONGLE_ID_RE = re.compile(r"^[a-fA-F0-9]{16}$")
IMEI_WAIT_TIMEOUT = 15.0


def _read_persist_dongle_id() -> str | None:
  p = Path(Paths.persist_root()) / "comma" / "dongle_id"
  try:
    if not p.is_file():
      return None
    s = p.read_text().strip()
    return s or None
  except Exception:
    cloudlog.exception("failed to read persist dongle_id")
    return None


def get_cached_dongle_id(params: Params | None = None, prefer_readonly: bool = True) -> str | None:
  ro = _read_persist_dongle_id()
  if is_valid_dongle_id(ro):
    ro = ro.lower()
  if prefer_readonly and ro:
    return ro
  p = Params() if params is None else params
  v = p.get("DongleId")
  if v and v != UNREGISTERED_DONGLE_ID:
    return v.lower() if is_valid_dongle_id(v) else v
  return ro or None
def is_valid_dongle_id(dongle_id: str | None) -> bool:
  return bool(dongle_id and _DONGLE_ID_RE.fullmatch(dongle_id))
def get_or_create_dongle_id(params: Params | None = None, prefer_readonly: bool = True) -> str:
  p = Params() if params is None else params
  dongle_id = get_cached_dongle_id(p, prefer_readonly=prefer_readonly)
  if dongle_id and dongle_id != UNREGISTERED_DONGLE_ID:
    return dongle_id
  dongle_id = secrets.token_hex(8)
  p.put("DongleId", dongle_id)
  cloudlog.warning(f"generated new DongleId={dongle_id} (no readonly dongle_id found)")
  return dongle_id
def ensure_dev_pairing_identity(params: Params | None = None, force_reset: bool = False) -> dict[str, str]:
  p = Params() if params is None else params

  persist_dir = Path(Paths.persist_root()) / "comma"
  persist_dir.mkdir(parents=True, exist_ok=True)

  dongle_path = persist_dir / "dongle_id"
  priv_path = persist_dir / "id_rsa"
  pub_path = persist_dir / "id_rsa.pub"

  if force_reset:
    for fp in (dongle_path, priv_path, pub_path):
      try:
        fp.unlink(missing_ok=True)
      except Exception:
        cloudlog.exception(f"failed to remove {fp}")
    try:
      (persist_dir / "konn3kt_prime_type").unlink(missing_ok=True)
    except Exception:
      pass
    try:
      p.remove("PrimeType")
    except Exception:
      pass
  forced_dongle = os.getenv("KONN3KT_DEV_DONGLE_ID")
  dongle_id = forced_dongle.strip().lower() if forced_dongle else None
  if dongle_id and not is_valid_dongle_id(dongle_id):
    cloudlog.error("KONN3KT_DEV_DONGLE_ID must be 16 hex chars")
    dongle_id = None
  if dongle_id is None:
    existing = None
    try:
      existing = dongle_path.read_text().strip().lower() if dongle_path.is_file() else None
    except Exception:
      cloudlog.exception("failed reading existing dev dongle_id")
    dongle_id = existing if is_valid_dongle_id(existing) else secrets.token_hex(8)
  try:
    dongle_path.write_text(dongle_id)
  except Exception:
    cloudlog.exception("failed writing dev dongle_id")
  p.put("DongleId", dongle_id)
  p.put("HardwareSerial", p.get("HardwareSerial") or f"DEV-{dongle_id}")
  if force_reset or (not priv_path.is_file()) or (not pub_path.is_file()):
    try:
      from cryptography.hazmat.primitives import serialization
      from cryptography.hazmat.primitives.asymmetric import rsa
      key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
      priv_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
      )
      pub_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
      )
      priv_path.write_bytes(priv_bytes)
      pub_path.write_bytes(pub_bytes)
    except Exception:
      cloudlog.exception("failed generating dev RSA keys")
      raise
  return {
    "dongle_id": dongle_id,
    "serial": p.get("HardwareSerial") or f"DEV-{dongle_id}",
    "persist_dir": str(persist_dir),
  }
def is_registered_device() -> bool:
  dongle = Params().get("DongleId")
  return dongle not in (None, UNREGISTERED_DONGLE_ID)


def _normalize_imei(value: str | None) -> str:
  return value or ""


def get_registration_identifiers(wait_timeout: float = IMEI_WAIT_TIMEOUT, show_spinner: bool = False) -> tuple[str, str, str]:
  serial = HARDWARE.get_serial()
  spinner = Spinner() if show_spinner else None
  start_time = time.monotonic()
  imei1: str | None = None
  imei2: str | None = None

  while time.monotonic() - start_time < wait_timeout:
    try:
      imei1, imei2 = HARDWARE.get_imei(0), HARDWARE.get_imei(1)
      if imei1 or imei2:
        break
    except RuntimeError as e:
      if "no modems" in str(e).lower():
        cloudlog.warning("No cellular modem available, proceeding without IMEI")
        break
      cloudlog.exception("Error getting imei, trying again...")
    except Exception:
      cloudlog.exception("Error getting imei, trying again...")
    time.sleep(1)

  imei1 = _normalize_imei(imei1)
  imei2 = _normalize_imei(imei2)

  if not imei1 and not imei2:
    cloudlog.warning(f"proceeding with serial-only registration for serial={serial}")
  if spinner is not None:
    spinner.update(f"registering device - serial: {serial}, IMEI: ({imei1 or None}, {imei2 or None})")
    spinner.close()

  return serial, imei1, imei2


def register(show_spinner=False) -> str | None:
  """
  All devices built since March 2024 come with all
  info stored in /persist/. This is kept around
  only for devices built before then.

  With a backend update to take serial number instead
  of dongle ID to some endpoints, this can be removed
  entirely.
  """
  params = Params()

  dongle_id: str | None = get_cached_dongle_id(params, prefer_readonly=True)
  if dongle_id in ("", UNREGISTERED_DONGLE_ID):
    dongle_id = None

  # Create registration token, in the future, this key will make JWTs directly
  jwt_algo, private_key, public_key = get_key_pair()

  if not public_key:
    dongle_id = UNREGISTERED_DONGLE_ID
    cloudlog.warning("missing public key")
  elif dongle_id is None:
    if show_spinner:
      spinner = Spinner()
      spinner.update("registering device")

    serial, imei1, imei2 = get_registration_identifiers(wait_timeout=IMEI_WAIT_TIMEOUT, show_spinner=False)

    backoff = 0
    start_time = time.monotonic()
    while True:
      try:
        register_token = jwt.encode({'register': True, 'exp': datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)},
                                    cast(str, private_key), algorithm=jwt_algo)
        cloudlog.info("getting pilotauth")
        cloudlog.info("getting pilotauth")
        resp = api_get("v2/pilotauth/", method='POST', timeout=15,
                       imei=imei1, imei2=imei2, serial=serial, public_key=public_key, register_token=register_token)

        if resp.status_code in (400, 402, 403):
          cloudlog.info(f"Unable to register device, got {resp.status_code}")
          dongle_id = UNREGISTERED_DONGLE_ID
        else:
          dongleauth = json.loads(resp.text)
          dongle_id = dongleauth["dongle_id"]
        break
      except Exception:
        cloudlog.exception("failed to authenticate")
        backoff = min(backoff + 1, 15)
        time.sleep(backoff)

      if time.monotonic() - start_time > 60 and show_spinner:
        spinner.update(f"registering device - serial: {serial}, IMEI: ({imei1}, {imei2})")
        return UNREGISTERED_DONGLE_ID  # hotfix to prevent an infinite wait for registration

    if show_spinner:
      spinner.update(f"registering device - serial: {serial}, IMEI: ({imei1 or None}, {imei2 or None})")
      spinner.close()

  if dongle_id:
    params.put("DongleId", dongle_id)
    set_offroad_alert("Offroad_UnregisteredHardware", False)
  return dongle_id


if __name__ == "__main__":
  print(register())

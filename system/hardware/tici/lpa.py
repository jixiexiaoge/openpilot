#!/usr/bin/env python3
# SGP.22 v2.3: https://www.gsma.com/solutions-and-impact/technologies/esim/wp-content/uploads/2021/07/SGP.22-v2.3.pdf

import argparse
import atexit
import base64
import hashlib
import json
import math
import os
import re
import requests
import serial
import subprocess
import sys
import time

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from openpilot.common.time_helpers import system_time_valid
from openpilot.system.hardware.base import LPABase, LPAError, LPAProfileNotFoundError, Profile

GSMA_CI_BUNDLE = str(Path(__file__).parent / 'gsma_ci_bundle.pem')


DEFAULT_DEVICE = "/dev/modem_at0"
DEFAULT_BAUD = 9600
DEFAULT_TIMEOUT = 5.0
# https://euicc-manual.osmocom.org/docs/lpa/applet-id/
ISDR_AID = "A0000005591010FFFFFFFF8900000100"
ES10X_MSS = 120
MM = "org.freedesktop.ModemManager1"
MM_MODEM = MM + ".Modem"

# TLV Tags
TAG_ICCID = 0x5A
TAG_STATUS = 0x80
TAG_EUICC_INFO = 0xBF20
TAG_PREPARE_DOWNLOAD = 0xBF21
TAG_PROFILE_INFO_LIST = 0xBF2D
TAG_EUICC_CHALLENGE = 0xBF2E
TAG_SET_NICKNAME = 0xBF29
TAG_LIST_NOTIFICATION = 0xBF28
TAG_RETRIEVE_NOTIFICATION = 0xBF2B
TAG_NOTIFICATION_METADATA = 0xBF2F
TAG_NOTIFICATION_SENT = 0xBF30
TAG_ENABLE_PROFILE = 0xBF31
TAG_DISABLE_PROFILE = 0xBF32
TAG_DELETE_PROFILE = 0xBF33
TAG_BPP = 0xBF36
TAG_PROFILE_INSTALL_RESULT = 0xBF37
TAG_AUTH_SERVER = 0xBF38
TAG_CANCEL_SESSION = 0xBF41

STATE_LABELS = {0: "disabled", 1: "enabled", 255: "unknown"}
ICON_LABELS = {0: "jpeg", 1: "png", 255: "unknown"}
CLASS_LABELS = {0: "test", 1: "provisioning", 2: "operational", 255: "unknown"}
PROFILE_ERROR_CODES = {
  0x01: "iccidOrAidNotFound", 0x02: "profileNotInDisabledState",
  0x03: "disallowedByPolicy", 0x04: "wrongProfileReenabling",
  0x05: "catBusy", 0x06: "undefinedError",
}
AUTH_SERVER_ERROR_CODES = {
  0x01: "eUICCVerificationFailed", 0x02: "eUICCCertificateExpired",
  0x03: "eUICCCertificateRevoked", 0x05: "invalidServerSignature",
  0x06: "euiccCiPKUnknown", 0x0A: "matchingIdRefused",
  0x10: "insufficientMemory",
}
BPP_COMMAND_NAMES = {
  0: "initialiseSecureChannel", 1: "configureISDP", 2: "storeMetadata",
  3: "storeMetadata2", 4: "replaceSessionKeys", 5: "loadProfileElements",
}
BPP_ERROR_REASONS = {
  1: "incorrectInputValues", 2: "invalidSignature", 3: "invalidTransactionId",
  4: "unsupportedCrtValues", 5: "unsupportedRemoteOperationType",
  6: "unsupportedProfileClass", 7: "scp03tStructureError", 8: "scp03tSecurityError",
  9: "iccidAlreadyExistsOnEuicc", 10: "insufficientMemoryForProfile",
  11: "installInterrupted", 12: "peProcessingError", 13: "dataMismatch",
  14: "invalidNAA",
}
CANCEL_SESSION_REASON = {
  0: "endUserRejection", 1: "postponed", 2: "timeout",
  3: "pprNotAllowed", 127: "undefinedReason",
}

ESIM_TLS_BUNDLE_ENV = "IQPILOT_ESIM_CA_BUNDLE"
ESIM_QESIM_INIT_ENV = "IQPILOT_ESIM_QESIM_INIT"
ESIM_EXCLUSIVE_MODEM_ENV = "IQPILOT_ESIM_EXCLUSIVE_MODEM"


def _ensure_dbus_import():
  try:
    import dbus  # noqa: F401
    return
  except ModuleNotFoundError:
    dist_packages = "/usr/lib/python3/dist-packages"
    if dist_packages not in sys.path and os.path.isdir(dist_packages):
      sys.path.append(dist_packages)
    import dbus  # noqa: F401


def _tls_verify_option() -> bool | str:
  # Default to the GSMA CI bundle used by the reference eSIM branch.
  # Allow explicit override for local testing or forced system trust behavior.
  override = os.getenv(ESIM_TLS_BUNDLE_ENV, "").strip()
  if not override:
    return GSMA_CI_BUNDLE
  if override.lower() in ("0", "false", "off"):
    return False
  if override.lower() in ("1", "true", "on", "system"):
    return True
  return override


def b64e(data: bytes) -> str:
  return base64.b64encode(data).decode("ascii")


def b64d(s: str) -> bytes:
  return base64.b64decode(base64_trim(s))


def _decode_apdu_response_blob(raw: str, label: str) -> bytes:
  filtered = re.sub(r"[^0-9A-Fa-f]", "", raw)
  if len(filtered) < 2 or len(filtered) % 2:
    raise RuntimeError(f"Malformed {label} response payload")
  return bytes.fromhex(filtered)


class AtClient:
  def __init__(self, device: str, baud: int, timeout: float, verbose: bool) -> None:
    self._device = device
    self._baud = baud
    self._timeout = timeout
    self.verbose = verbose
    self.channel: str | None = None
    self._serial: serial.Serial | None = None
    self._use_csim = False
    self._has_qesim = False
    self._qesim_lpa_enabled = False
    try:
      self._serial = serial.Serial(device, baudrate=baud, timeout=timeout)
      self._disable_echo()
    except (serial.SerialException, PermissionError, OSError):
      self._serial = None
      if self.verbose:
        print(f"!! using ModemManager DBus AT transport for {device}", file=sys.stderr)

  def close(self) -> None:
    try:
      if self.channel:
        try:
          self.query(f"AT+CCHC={self.channel}")
        except Exception as e:
          if self.verbose:
            print(f"!! ignoring channel close failure: {e}", file=sys.stderr)
        finally:
          self.channel = None
    finally:
      if self._serial is not None:
        self._serial.close()

  @staticmethod
  def _is_busy_open_error(error: Exception) -> bool:
    text = str(error).lower()
    return "errno 16" in text or "device or resource busy" in text

  def _disable_echo(self) -> None:
    if self._serial is None:
      return
    self._serial.reset_input_buffer()
    self._serial.write(b"ATE0\r")
    time.sleep(0.1)
    self._serial.reset_input_buffer()

  def _send(self, cmd: str) -> None:
    if self.verbose:
      print(f">> {cmd}", file=sys.stderr)
    assert self._serial is not None
    self._serial.write((cmd + "\r").encode("ascii"))

  def _expect(self) -> list[str]:
    lines: list[str] = []
    while True:
      assert self._serial is not None
      raw = self._serial.readline()
      if not raw:
        raise TimeoutError("AT command timed out")
      line = raw.decode(errors="ignore").strip()
      if not line:
        continue
      if self.verbose:
        print(f"<< {line}", file=sys.stderr)
      if line == "OK":
        return lines
      if line == "ERROR":
        raise RuntimeError("AT command failed")
      if "ERROR" in line and line.startswith("+"):
        # Catch +CME ERROR / +CMS ERROR and similar modem-specific failures.
        raise RuntimeError(f"AT command failed: {line}")
      lines.append(line)

  def _get_modem(self):
    _ensure_dbus_import()
    import dbus

    bus = dbus.SystemBus()
    mm = bus.get_object(MM, '/org/freedesktop/ModemManager1')
    objects = mm.GetManagedObjects(dbus_interface="org.freedesktop.DBus.ObjectManager", timeout=self._timeout)
    modem_paths = [path for path in objects.keys() if "/Modem/" in str(path)]
    if not modem_paths:
      raise RuntimeError("ModemManager returned no modems")
    return bus.get_object(MM, modem_paths[0])

  def _dbus_query(self, cmd: str) -> list[str]:
    if self.verbose:
      print(f"DBUS >> {cmd}", file=sys.stderr)
    try:
      result = str(self._get_modem().Command(cmd, math.ceil(self._timeout), dbus_interface=MM_MODEM, timeout=self._timeout))
    except Exception as e:
      raise RuntimeError(f"AT command failed: {e}") from e
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    if self.verbose:
      for line in lines:
        print(f"DBUS << {line}", file=sys.stderr)
    return lines

  def _reconnect_serial(self) -> None:
    self.channel = None
    try:
      if self._serial is not None:
        self._serial.close()
    except Exception:
      pass
    self._serial = serial.Serial(self._device, baudrate=self._baud, timeout=self._timeout)
    self._disable_echo()

  def query(self, cmd: str) -> list[str]:
    if self._serial is None:
      return self._dbus_query(cmd)
    try:
      self._send(cmd)
      return self._expect()
    except (OSError, serial.SerialException) as e:
      try:
        self._reconnect_serial()
        self._send(cmd)
        return self._expect()
      except Exception:
        raise RuntimeError(f"AT transport error ({cmd}): {e}") from e
    except TimeoutError as e:
      raise TimeoutError(f"AT command timed out ({cmd})") from e
    except RuntimeError as e:
      raise RuntimeError(f"AT command failed ({cmd}): {e}") from e

  def _supports_qesim(self) -> bool:
    try:
      lines = self.query("AT+QESIM=?")
    except Exception:
      return False
    return any(line.startswith("+QESIM:") for line in lines)

  def _set_quectel_lpa_mode(self) -> None:
    self._has_qesim = self._supports_qesim()
    self._qesim_lpa_enabled = False
    if not self._has_qesim:
      return

    # Some Quectel firmwares require enabling internal LPA mode before
    # ISO7816 channel open commands (CCHO/CGLA) will succeed.
    lpa_enable_cmds = (
      'AT+QESIM="lpa_enable",1',
      'AT+QESIM="lpa_enable"',
    )
    for cmd in lpa_enable_cmds:
      try:
        self.query(cmd)
        self._qesim_lpa_enabled = True
        break
      except Exception:
        continue

    # Keep BIP auth enabled when supported; this is needed by some firmware
    # revisions for profile download/auth paths.
    try:
      lines = self.query('AT+QCFG="bip/auth"?')
      needs_enable = any('"bip/auth",0' in line for line in lines)
      if needs_enable:
        self.query('AT+QCFG="bip/auth",1')
    except Exception:
      pass

  def ensure_capabilities(self) -> None:
    if self._serial is None:
      return

    # Some modem firmwares reject command test forms (e.g. AT+CCHO=?)
    # while still supporting real execution. Keep these probes non-fatal.
    self.query("AT")
    # Keep IQ-specific QESIM initialization opt-in for debugging only.
    # Default behavior should match upstream greatgitsby/esim transport flow.
    if os.getenv(ESIM_QESIM_INIT_ENV, "").strip() == "1":
      try:
        self.query("AT+CMEE=2")
      except Exception:
        pass
      self._set_quectel_lpa_mode()
    for command in ("AT+CCHO", "AT+CCHC", "AT+CGLA", "AT+CSIM"):
      try:
        self.query(f"{command}=?")
      except Exception as e:
        if self.verbose:
          print(f"!! capability probe failed for {command}: {e}", file=sys.stderr)

  def open_isdr(self) -> None:
    try:
      self.query(f'AT+CCHC=1')
    except Exception:
      pass
    ccho_candidates = [
      f'AT+CCHO="{ISDR_AID}"',
      f"AT+CCHO={ISDR_AID}",
    ]
    for cmd in ccho_candidates:
      try:
        lines = self.query(cmd)
      except Exception:
        continue
      for line in lines:
        if line.startswith("+CCHO:") and (ch := line.split(":", 1)[1].strip()):
          self.channel = ch
          return

    # Fallback for modems that reject CCHO but allow APDUs over basic channel.
    self.channel = "0"
    aid_len = len(ISDR_AID) // 2
    select_isdr = bytes.fromhex(f"00A40400{aid_len:02X}{ISDR_AID}")
    try:
      _, sw1, sw2 = self.send_apdu(select_isdr)
      if (sw1, sw2) == (0x90, 0x00):
        return
      raise RuntimeError(f"ISD-R SELECT failed on basic channel SW={sw1:02X}{sw2:02X}")
    except Exception:
      self.channel = None
    # Final fallback for modems that only support APDU via CSIM.
    try:
      _, sw1, sw2 = self._send_csim_apdu(select_isdr)
      if (sw1, sw2) == (0x90, 0x00):
        self._use_csim = True
        self.channel = "csim"
        if self.verbose:
          print("!! using CSIM APDU transport fallback", file=sys.stderr)
        return
      raise RuntimeError(f"ISD-R SELECT failed on CSIM SW={sw1:02X}{sw2:02X}")
    except Exception:
      self.channel = None
      if self._has_qesim and not self._qesim_lpa_enabled and os.getenv(ESIM_QESIM_INIT_ENV, "").strip() == "1":
        raise RuntimeError(
          "Modem exposes AT+QESIM but rejects LPA enable and ISD-R access; "
          "this firmware/SKU likely does not provide usable eSIM functionality"
        )
      raise RuntimeError("Failed to access eUICC ISD-R (CCHO/CGLA/CSIM all failed)")

  def send_apdu(self, apdu: bytes) -> tuple[bytes, int, int]:
    for attempt in range(3):
      try:
        if not self.channel:
          self.open_isdr()
        if self._use_csim:
          return self._send_csim_apdu(apdu)
        hex_payload = apdu.hex().upper()
        cmd = f'AT+CGLA={self.channel},{len(hex_payload)},"{hex_payload}"'
        for query_attempt in range(2):
          for line in self.query(cmd):
            if line.startswith("+CGLA:"):
              parts = line.split(":", 1)[1].split(",", 1)
              if len(parts) == 2:
                data = _decode_apdu_response_blob(parts[1].strip().strip('"'), "+CGLA")
                if len(data) >= 2:
                  return data[:-2], data[-2], data[-1]
          if query_attempt == 0:
            time.sleep(0.2)
        raise RuntimeError("Missing +CGLA response")
      except RuntimeError:
        self.channel = None
        self._use_csim = False
        if attempt == 2:
          raise
        time.sleep(1 + attempt)
    raise RuntimeError("send_apdu failed")

  def _send_csim_apdu(self, apdu: bytes) -> tuple[bytes, int, int]:
    hex_payload = apdu.hex().upper()
    cmd = f'AT+CSIM={len(hex_payload)},"{hex_payload}"'
    for attempt in range(2):
      for line in self.query(cmd):
        if line.startswith("+CSIM:"):
          parts = line.split(":", 1)[1].split(",", 1)
          if len(parts) == 2:
            data = _decode_apdu_response_blob(parts[1].strip().strip('"'), "+CSIM")
            if len(data) >= 2:
              return data[:-2], data[-2], data[-1]
      if attempt == 0:
        time.sleep(0.2)
    raise RuntimeError("Missing +CSIM response")


# --- TLV utilities ---

def iter_tlv(data: bytes, with_positions: bool = False) -> Generator:
  idx, length = 0, len(data)
  while idx < length:
    start_pos = idx
    tag = data[idx]
    idx += 1
    if tag & 0x1F == 0x1F:  # Multi-byte tag
      tag_value = tag
      while idx < length:
        next_byte = data[idx]
        idx += 1
        tag_value = (tag_value << 8) | next_byte
        if not (next_byte & 0x80):
          break
    else:
      tag_value = tag
    if idx >= length:
      break
    size = data[idx]
    idx += 1
    if size & 0x80:  # Multi-byte length
      num_bytes = size & 0x7F
      if idx + num_bytes > length:
        break
      size = int.from_bytes(data[idx : idx + num_bytes], "big")
      idx += num_bytes
    if idx + size > length:
      break
    value = data[idx : idx + size]
    idx += size
    yield (tag_value, value, start_pos, idx) if with_positions else (tag_value, value)


def find_tag(data: bytes, target: int) -> bytes | None:
  return next((v for t, v in iter_tlv(data) if t == target), None)


def encode_tlv(tag: int, value: bytes) -> bytes:
  tag_bytes = bytes([(tag >> 8) & 0xFF, tag & 0xFF]) if tag > 255 else bytes([tag])
  vlen = len(value)
  if vlen <= 127:
    return tag_bytes + bytes([vlen]) + value
  length_bytes = vlen.to_bytes((vlen.bit_length() + 7) // 8, "big")
  return tag_bytes + bytes([0x80 | len(length_bytes)]) + length_bytes + value


def tbcd_to_string(raw: bytes) -> str:
  return "".join(str(n) for b in raw for n in (b & 0x0F, b >> 4) if n <= 9)


def string_to_tbcd(s: str) -> bytes:
  digits = [int(c) for c in s if c.isdigit()]
  return bytes(digits[i] | ((digits[i + 1] if i + 1 < len(digits) else 0xF) << 4) for i in range(0, len(digits), 2))


def base64_trim(s: str) -> str:
  return "".join(c for c in s if c not in "\n\r \t")


# --- Shared helpers ---

def _int_bytes(n: int) -> bytes:
  """Encode a positive integer as minimal big-endian bytes (at least 1 byte)."""
  return n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")


def _extract_status(response: bytes, tag: int, name: str) -> int:
  """Extract the status byte from a tagged ES10x response."""
  root = find_tag(response, tag)
  if root is None:
    raise RuntimeError(f"Missing {name}Response")
  status = find_tag(root, TAG_STATUS)
  if status is None:
    raise RuntimeError(f"Missing status in {name}Response")
  return status[0]


# Profile field decoders: TLV tag -> (field_name, decoder)
_PROFILE_FIELDS = {
  TAG_ICCID: ("iccid", tbcd_to_string),
  0x4F: ("isdpAid", lambda v: v.hex().upper()),
  0x9F70: ("profileState", lambda v: STATE_LABELS.get(v[0], "unknown")),
  0x90: ("profileNickname", lambda v: v.decode("utf-8", errors="ignore") or None),
  0x91: ("serviceProviderName", lambda v: v.decode("utf-8", errors="ignore") or None),
  0x92: ("profileName", lambda v: v.decode("utf-8", errors="ignore") or None),
  0x93: ("iconType", lambda v: ICON_LABELS.get(v[0], "unknown")),
  0x94: ("icon", b64e),
  0x95: ("profileClass", lambda v: CLASS_LABELS.get(v[0], "unknown")),
}


def _decode_profile_fields(data: bytes) -> dict:
  """Parse known profile metadata TLV fields into a dict."""
  result = {}
  for tag, value in iter_tlv(data):
    if (field := _PROFILE_FIELDS.get(tag)):
      result[field[0]] = field[1](value)
  return result


# Notification field decoders: TLV tag -> (field_name, decoder)
_NOTIF_FIELDS = {
  TAG_STATUS: ("seqNumber", lambda v: int.from_bytes(v, "big")),
  0x81: ("profileManagementOperation", lambda v: next((m for m in [0x80, 0x40, 0x20, 0x10] if len(v) >= 2 and v[1] & m), 0xFF)),
  0x0C: ("notificationAddress", lambda v: v.decode("utf-8", errors="ignore")),
  TAG_ICCID: ("iccid", tbcd_to_string),
}


# --- ES10x command transport ---

def es10x_command(client: AtClient, data: bytes) -> bytes:
  response = bytearray()
  sequence = 0
  offset = 0
  while offset < len(data):
    chunk = data[offset : offset + ES10X_MSS]
    offset += len(chunk)
    is_last = offset == len(data)
    apdu = bytes([0x80, 0xE2, 0x91 if is_last else 0x11, sequence & 0xFF, len(chunk)]) + chunk
    segment, sw1, sw2 = client.send_apdu(apdu)
    response.extend(segment)
    while True:
      if sw1 == 0x61:  # More data available
        segment, sw1, sw2 = client.send_apdu(bytes([0x80, 0xC0, 0x00, 0x00, sw2 or 0]))
        response.extend(segment)
        continue
      if (sw1 & 0xF0) == 0x90:
        break
      raise RuntimeError(f"APDU failed with SW={sw1:02X}{sw2:02X}")
    sequence += 1
  return bytes(response)


# --- ES9P HTTP ---

def es9p_request(smdp_address: str, endpoint: str, payload: dict, error_prefix: str = "Request") -> dict:
  if not system_time_valid():
    raise RuntimeError("System time is not set; TLS certificate validation requires a valid clock")
  url = f"https://{smdp_address}/gsma/rsp2/es9plus/{endpoint}"
  headers = {"User-Agent": "gsma-rsp-lpad", "X-Admin-Protocol": "gsma/rsp/v2.3.0", "Content-Type": "application/json"}
  resp = requests.post(url, json=payload, headers=headers, timeout=30, verify=_tls_verify_option())
  resp.raise_for_status()
  if not resp.content:
    return {}
  data = resp.json()
  if "header" in data and "functionExecutionStatus" in data["header"]:
    status = data["header"]["functionExecutionStatus"]
    if status.get("status") == "Failed":
      sd = status.get("statusCodeData", {})
      raise RuntimeError(f"{error_prefix} failed: {sd.get('reasonCode', 'unknown')}/{sd.get('subjectCode', 'unknown')} - {sd.get('message', 'unknown')}")
  return data


# --- Profile operations ---

def decode_profiles(blob: bytes) -> list[dict]:
  root = find_tag(blob, TAG_PROFILE_INFO_LIST)
  if root is None:
    raise RuntimeError("Missing ProfileInfoList")
  list_ok = find_tag(root, 0xA0)
  if list_ok is None:
    return []
  defaults = {name: None for name, _ in _PROFILE_FIELDS.values()}
  return [{**defaults, **_decode_profile_fields(value)} for tag, value in iter_tlv(list_ok) if tag == 0xE3]


def list_profiles(client: AtClient) -> list[dict]:
  return decode_profiles(es10x_command(client, bytes.fromhex("BF2D00")))


def _profile_op(client: AtClient, tag: int, iccid: str, refresh: bool, action: str) -> None:
  inner = encode_tlv(TAG_ICCID, string_to_tbcd(iccid))
  if tag != TAG_DELETE_PROFILE:
    if not refresh:
      inner += encode_tlv(0x81, b'\x00')
    inner = encode_tlv(0xA0, inner)
  code = _extract_status(es10x_command(client, encode_tlv(tag, inner)), tag, f"{action.capitalize()}Profile")
  if code == 0x00:
    return
  if code == 0x02 and tag != TAG_DELETE_PROFILE:
    print(f"profile {iccid} already {action}d")
    return
  raise RuntimeError(f"{action.capitalize()}Profile failed: {PROFILE_ERROR_CODES.get(code, 'unknown')} (0x{code:02X})")


def enable_profile(client: AtClient, iccid: str, refresh: bool = True) -> None:
  _profile_op(client, TAG_ENABLE_PROFILE, iccid, refresh, "enable")


def disable_profile(client: AtClient, iccid: str, refresh: bool = True) -> None:
  _profile_op(client, TAG_DISABLE_PROFILE, iccid, refresh, "disable")


def delete_profile(client: AtClient, iccid: str) -> None:
  _profile_op(client, TAG_DELETE_PROFILE, iccid, True, "delete")


def set_profile_nickname(client: AtClient, iccid: str, nickname: str) -> None:
  nickname_bytes = nickname.encode("utf-8")
  if len(nickname_bytes) > 64:
    raise ValueError("Profile nickname must be 64 bytes or less")
  content = encode_tlv(TAG_ICCID, string_to_tbcd(iccid)) + encode_tlv(0x90, nickname_bytes)
  code = _extract_status(es10x_command(client, encode_tlv(TAG_SET_NICKNAME, content)), TAG_SET_NICKNAME, "SetNickname")
  if code == 0x01:
    raise RuntimeError(f"profile {iccid} not found")
  if code != 0x00:
    raise RuntimeError(f"SetNickname failed with status 0x{code:02X}")


# --- Notifications ---

def list_notifications(client: AtClient) -> list[dict]:
  response = es10x_command(client, encode_tlv(TAG_LIST_NOTIFICATION, b""))
  root = find_tag(response, TAG_LIST_NOTIFICATION)
  if root is None:
    raise RuntimeError("Missing ListNotificationResponse")
  metadata_list = find_tag(root, 0xA0)
  if metadata_list is None:
    return []
  notifications: list[dict] = []
  for tag, value in iter_tlv(metadata_list):
    if tag != TAG_NOTIFICATION_METADATA:
      continue
    notification = {"seqNumber": None, "profileManagementOperation": None, "notificationAddress": None, "iccid": None}
    for t, v in iter_tlv(value):
      if (field := _NOTIF_FIELDS.get(t)):
        notification[field[0]] = field[1](v)
    if notification["seqNumber"] is not None and notification["profileManagementOperation"] is not None and notification["notificationAddress"]:
      notifications.append(notification)
  return notifications


def retrieve_notification(client: AtClient, seq_number: int) -> dict:
  request = encode_tlv(TAG_RETRIEVE_NOTIFICATION, encode_tlv(0xA0, encode_tlv(TAG_STATUS, _int_bytes(seq_number))))
  response = es10x_command(client, request)
  root = find_tag(response, TAG_RETRIEVE_NOTIFICATION)
  if root is None:
    raise RuntimeError("Invalid RetrieveNotificationsListResponse")
  a0_content = find_tag(root, 0xA0)
  if a0_content is None:
    raise RuntimeError("Invalid RetrieveNotificationsListResponse")
  pending_notif, pending_tag = None, None
  for tag, value in iter_tlv(a0_content):
    if tag in (TAG_PROFILE_INSTALL_RESULT, 0x30):
      pending_notif, pending_tag = value, tag
      break
  if pending_notif is None:
    raise RuntimeError("Missing PendingNotification")
  if pending_tag == TAG_PROFILE_INSTALL_RESULT:
    result_data = find_tag(pending_notif, 0xBF27)
    notif_meta = find_tag(result_data, TAG_NOTIFICATION_METADATA) if result_data else None
  else:
    notif_meta = find_tag(pending_notif, TAG_NOTIFICATION_METADATA)
  if notif_meta is None:
    raise RuntimeError("Missing NotificationMetadata")
  addr = find_tag(notif_meta, 0x0C)
  if addr is None:
    raise RuntimeError("Missing notificationAddress")
  return {"notificationAddress": addr.decode("utf-8", errors="ignore"), "b64_PendingNotification": b64e(pending_notif)}


def remove_notification(client: AtClient, seq_number: int) -> None:
  response = es10x_command(client, encode_tlv(TAG_NOTIFICATION_SENT, encode_tlv(TAG_STATUS, _int_bytes(seq_number))))
  root = find_tag(response, TAG_NOTIFICATION_SENT)
  if root is None:
    raise RuntimeError("Invalid NotificationSentResponse")
  status = find_tag(root, TAG_STATUS)
  if status is None or int.from_bytes(status, "big") != 0:
    raise RuntimeError("RemoveNotificationFromList failed")


def process_notifications(client: AtClient) -> None:
  for notification in list_notifications(client):
    seq_number, smdp_address = notification["seqNumber"], notification["notificationAddress"]
    if not seq_number or not smdp_address:
      continue
    try:
      notif_data = retrieve_notification(client, seq_number)
      es9p_request(smdp_address, "handleNotification", {"pendingNotification": notif_data["b64_PendingNotification"]}, "HandleNotification")
      remove_notification(client, seq_number)
    except Exception:
      pass


# --- Authentication & Download ---

def get_challenge_and_info(client: AtClient) -> tuple[bytes, bytes]:
  challenge_resp = es10x_command(client, encode_tlv(TAG_EUICC_CHALLENGE, b""))
  root = find_tag(challenge_resp, TAG_EUICC_CHALLENGE)
  if root is None:
    raise RuntimeError("Missing GetEuiccDataResponse")
  challenge = find_tag(root, TAG_STATUS)
  if challenge is None:
    raise RuntimeError("Missing challenge in response")
  info_resp = es10x_command(client, encode_tlv(TAG_EUICC_INFO, b""))
  if not info_resp.startswith(bytes([0xBF, 0x20])):
    raise RuntimeError("Missing GetEuiccInfo1Response")
  return challenge, info_resp


def authenticate_server(client: AtClient, b64_signed1: str, b64_sig1: str, b64_pk_id: str, b64_cert: str, matching_id: str | None = None) -> str:
  # Build request
  tac = bytes([0x35, 0x29, 0x06, 0x11])
  device_info = encode_tlv(TAG_STATUS, tac) + encode_tlv(0xA1, b"")
  ctx_inner = b""
  if matching_id:
    ctx_inner += encode_tlv(TAG_STATUS, matching_id.encode("utf-8"))
  ctx_inner += encode_tlv(0xA1, device_info)
  content = base64.b64decode(b64_signed1) + base64.b64decode(b64_sig1) + base64.b64decode(b64_pk_id) + base64.b64decode(b64_cert) + encode_tlv(0xA0, ctx_inner)
  request = encode_tlv(TAG_AUTH_SERVER, content)

  response = es10x_command(client, request)
  if not response.startswith(bytes([0xBF, 0x38])):
    raise RuntimeError("Invalid AuthenticateServerResponse")

  # Check for eUICC-side errors
  root = find_tag(response, TAG_AUTH_SERVER)
  if root is not None:
    error_tag = find_tag(root, 0xA1)
    if error_tag is not None:
      code = int.from_bytes(error_tag, "big") if error_tag else 0
      desc = AUTH_SERVER_ERROR_CODES.get(code, "unknown")
      raise RuntimeError(f"AuthenticateServer rejected by eUICC: {desc} (0x{code:02X})")

  return b64e(response)


def prepare_download(client: AtClient, b64_signed2: str, b64_sig2: str, b64_cert: str, cc: str | None = None) -> str:
  smdp_signed2 = base64.b64decode(b64_signed2)
  smdp_signature2 = base64.b64decode(b64_sig2)
  smdp_certificate = base64.b64decode(b64_cert)
  smdp_signed2_root = find_tag(smdp_signed2, 0x30)
  if smdp_signed2_root is None:
    raise RuntimeError("Invalid smdpSigned2")
  transaction_id = find_tag(smdp_signed2_root, TAG_STATUS)
  cc_required_flag = find_tag(smdp_signed2_root, 0x01)
  if transaction_id is None or cc_required_flag is None:
    raise RuntimeError("Invalid smdpSigned2")
  content = smdp_signed2 + smdp_signature2
  if int.from_bytes(cc_required_flag, "big") != 0:
    if not cc:
      raise RuntimeError("Confirmation code required but not provided")
    content += encode_tlv(0x04, hashlib.sha256(hashlib.sha256(cc.encode("utf-8")).digest() + transaction_id).digest())
  content += smdp_certificate
  response = es10x_command(client, encode_tlv(TAG_PREPARE_DOWNLOAD, content))
  if not response.startswith(bytes([0xBF, 0x21])):
    raise RuntimeError("Invalid PrepareDownloadResponse")
  return b64e(response)


def _parse_tlv_header_len(data: bytes) -> int:
  """Return the combined tag + length header size for a TLV element."""
  tag_len = 2 if data[0] & 0x1F == 0x1F else 1
  length_byte = data[tag_len]
  return tag_len + (1 + (length_byte & 0x7F) if length_byte & 0x80 else 1)


def load_bpp(client: AtClient, b64_bpp: str) -> dict:
  bpp = b64d(b64_bpp)
  if not bpp.startswith(bytes([0xBF, 0x36])):
    raise RuntimeError("Invalid BoundProfilePackage")

  bpp_root_value = None
  for tag, value, start, end in iter_tlv(bpp, with_positions=True):
    if tag == TAG_BPP:
      bpp_root_value = value
      bpp_value_start = start + _parse_tlv_header_len(bpp[start:end])
      break
  if bpp_root_value is None:
    raise RuntimeError("Invalid BoundProfilePackage")

  chunks = []
  for tag, value, start, end in iter_tlv(bpp_root_value, with_positions=True):
    if tag == 0xBF23:
      chunks.append(bpp[0 : bpp_value_start + end])
    elif tag == 0xA0:
      chunks.append(bpp[bpp_value_start + start : bpp_value_start + end])
    elif tag in (0xA1, 0xA3):
      hdr_len = _parse_tlv_header_len(bpp_root_value[start:end])
      chunks.append(bpp[bpp_value_start + start : bpp_value_start + start + hdr_len])
      for _, _, child_start, child_end in iter_tlv(value, with_positions=True):
        chunks.append(value[child_start:child_end])
    elif tag == 0xA2:
      chunks.append(bpp[bpp_value_start + start : bpp_value_start + end])

  result = {"seqNumber": 0, "success": False, "bppCommandId": None, "errorReason": None}
  for chunk in chunks:
    response = es10x_command(client, chunk)
    if not response:
      continue
    root = find_tag(response, TAG_PROFILE_INSTALL_RESULT)
    if not root:
      continue
    result_data = find_tag(root, 0xBF27)
    if not result_data:
      break
    notif_meta = find_tag(result_data, TAG_NOTIFICATION_METADATA)
    if notif_meta:
      seq_num = find_tag(notif_meta, TAG_STATUS)
      if seq_num:
        result["seqNumber"] = int.from_bytes(seq_num, "big")
    final_result = find_tag(result_data, 0xA2)
    if final_result:
      for tag, value in iter_tlv(final_result):
        if tag == 0xA0:
          result["success"] = True
        elif tag == 0xA1:
          bpp_cmd = find_tag(value, TAG_STATUS)
          if bpp_cmd:
            result["bppCommandId"] = int.from_bytes(bpp_cmd, "big")
          err = find_tag(value, 0x81)
          if err:
            result["errorReason"] = int.from_bytes(err, "big")
    break  # ProfileInstallResult received — eUICC session is finalized
  if not result["success"] and result["errorReason"] is not None:
    cmd_name = BPP_COMMAND_NAMES.get(result["bppCommandId"], f"unknown({result['bppCommandId']})")
    err_name = BPP_ERROR_REASONS.get(result["errorReason"], f"unknown({result['errorReason']})")
    raise RuntimeError(f"Profile installation failed at {cmd_name}: {err_name} (bppCommandId={result['bppCommandId']}, errorReason={result['errorReason']})")
  return result


def parse_metadata(b64_metadata: str) -> dict:
  root = find_tag(b64d(b64_metadata), 0xBF25)
  if root is None:
    raise RuntimeError("Invalid profileMetadata")
  defaults = {"iccid": None, "serviceProviderName": None, "profileName": None, "iconType": None, "icon": None, "profileClass": None}
  return {**defaults, **_decode_profile_fields(root)}


def cancel_session(client: AtClient, transaction_id: bytes, reason: int = 127) -> str:
  content = encode_tlv(0x80, transaction_id) + encode_tlv(0x81, bytes([reason]))
  response = es10x_command(client, encode_tlv(TAG_CANCEL_SESSION, content))
  return b64e(response)


def parse_lpa_activation_code(activation_code: str) -> tuple[str, str, str]:
  if not activation_code.startswith("LPA:"):
    raise ValueError("Invalid activation code format")

  parts = activation_code[4:].split("$")
  if len(parts) != 3:
    raise ValueError("Invalid activation code format")

  version, smdp, matching_id = [p.strip() for p in parts]
  if version != "1":
    raise ValueError("Unsupported activation code version")
  if len(smdp) == 0 or "." not in smdp:
    raise ValueError("Invalid SM-DP+ address in activation code")
  if len(matching_id) == 0:
    raise ValueError("Missing matching ID in activation code")
  return version, smdp, matching_id


def download_profile(client: AtClient, activation_code: str) -> str:
  _, smdp, matching_id = parse_lpa_activation_code(activation_code)

  challenge, euicc_info = get_challenge_and_info(client)

  payload = {"smdpAddress": smdp, "euiccChallenge": b64e(challenge), "euiccInfo1": b64e(euicc_info)}
  if matching_id:
    payload["matchingId"] = matching_id
  auth = es9p_request(smdp, "initiateAuthentication", payload, "Authentication")
  tx_id = base64_trim(auth.get("transactionId", ""))
  tx_id_bytes = base64.b64decode(tx_id) if tx_id else b""

  try:
    b64_auth_resp = authenticate_server(
      client, base64_trim(auth.get("serverSigned1", "")), base64_trim(auth.get("serverSignature1", "")),
      base64_trim(auth.get("euiccCiPKIdToBeUsed", "")), base64_trim(auth.get("serverCertificate", "")),
      matching_id=matching_id)

    cli = es9p_request(smdp, "authenticateClient", {"transactionId": tx_id, "authenticateServerResponse": b64_auth_resp}, "Authentication")
    metadata = parse_metadata(base64_trim(cli.get("profileMetadata", "")))
    iccid = str(metadata.get("iccid") or "")
    print(f'Downloading profile: {iccid} - {metadata["serviceProviderName"]} - {metadata["profileName"]}')

    b64_prep = prepare_download(
      client, base64_trim(cli.get("smdpSigned2", "")), base64_trim(cli.get("smdpSignature2", "")), base64_trim(cli.get("smdpCertificate", "")))

    bpp = es9p_request(smdp, "getBoundProfilePackage", {"transactionId": tx_id, "prepareDownloadResponse": b64_prep}, "GetBoundProfilePackage")

    result = load_bpp(client, base64_trim(bpp.get("boundProfilePackage", "")))
    if result["success"]:
      print(f"Profile installed successfully (seqNumber: {result['seqNumber']})")
      return iccid
    else:
      raise RuntimeError(f"Profile installation failed: {result}")
  except Exception:
    if tx_id_bytes:
      b64_cancel_resp = ""
      try:
        b64_cancel_resp = cancel_session(client, tx_id_bytes)
      except Exception:
        pass
      try:
        es9p_request(smdp, "cancelSession", {
          "transactionId": tx_id,
          "cancelSessionResponse": b64_cancel_resp,
        }, "CancelSession")
      except Exception:
        pass
    raise


class TiciLPA(LPABase):
  handles_modem_restart = True
  _instance = None

  def __new__(cls, *args, **kwargs):
    if cls._instance is None:
      cls._instance = super().__new__(cls)
    return cls._instance

  def __init__(self, interface: Literal["qmi", "at"] = "at", device: str = DEFAULT_DEVICE, baud: int = DEFAULT_BAUD,
               timeout: float = DEFAULT_TIMEOUT, verbose: bool = False):
    if getattr(self, "_initialized", False):
      self.verbose = verbose or self.verbose
      return
    # This backend is AT-only. Keep interface arg for compatibility with existing CLI/call sites.
    self.interface = interface
    self.device = device
    self.baud = baud
    self.timeout = timeout
    self.verbose = verbose
    self._last_good_device = device
    self._euicc_present_cache: bool | None = None
    from openpilot.system.hardware.tici.hardware import get_device_type
    self._is_eg25 = get_device_type() in ("tizi",)
    self._client: AtClient | None = None
    self._initialized = True
    # _client is opened lazily via _ensure_client() on first actual eSIM operation.
    # Do NOT call _open_ready_client() here: on pSIM devices (no eUICC) it retries
    # for 10–30 s against the AT port, blocking hw_state_thread and starving the
    # network-type polling loop that drives the WiFi/LTE sidebar indicator.
    atexit.register(self.close)

  def close(self) -> None:
    if self._client is not None:
      try:
        self._client.close()
      finally:
        self._client = None

  @staticmethod
  def _set_modemmanager_running(running: bool) -> None:
    action = "start" if running else "stop"
    subprocess.check_call(["sudo", "systemctl", action, "ModemManager"])

  @staticmethod
  def _is_modemmanager_running() -> bool:
    res = subprocess.run(["systemctl", "is-active", "ModemManager"],
                         capture_output=True, text=True, check=False)
    return res.stdout.strip() == "active"

  def _probe_euicc_present(self) -> bool | None:
    if self._euicc_present_cache is not None:
      return self._euicc_present_cache

    if self._is_modemmanager_running():
      return None

    restarted_modemmanager = False
    try:
      res = subprocess.run(
        ["sudo", "qmicli", "-p", "-d", "/dev/cdc-wdm0", "--uim-get-slot-status"],
        capture_output=True, text=True, check=False, timeout=12,
      )
      output = f"{res.stdout}\n{res.stderr}"
      if "Is eUICC: yes" in output:
        self._euicc_present_cache = True
      elif "Is eUICC: no" in output:
        self._euicc_present_cache = False
      else:
        self._euicc_present_cache = None
    except Exception:
      self._euicc_present_cache = None
    finally:
      if restarted_modemmanager:
        self._set_modemmanager_running(True)
        time.sleep(2.0)

    return self._euicc_present_cache

  @staticmethod
  def _ttyusb2_mm_ignored() -> bool:
    # AGNOS PR 521 marks ttyUSB2 with ID_MM_PORT_IGNORE=1 for EG25.
    # If missing, ModemManager may contend with direct AT eSIM operations.
    if not os.path.exists("/dev/ttyUSB2"):
      return False
    try:
      res = subprocess.run(
        ["udevadm", "info", "-q", "property", "-n", "/dev/ttyUSB2"],
        capture_output=True, text=True, check=False,
      )
      if res.returncode != 0:
        return False
      return "ID_MM_PORT_IGNORE=1" in res.stdout
    except Exception:
      return False

  def _ensure_client(self) -> AtClient:
    if self._client is None:
      self._client = self._open_ready_client()
    return self._client

  @contextmanager
  def _open_client(self):
    yield self._ensure_client()

  def _open_ready_client(self) -> AtClient:
    euicc_present = self._probe_euicc_present()
    if euicc_present is False:
      raise LPAError("Modem reports no eUICC support on this unit (QMI: Is eUICC: no)")

    last_error: Exception | None = None
    recovery_attempted = False
    for attempt in range(1, 6):
      for device in self._candidate_devices():
        client: AtClient | None = None
        try:
          if self.verbose:
            print(f"!! trying modem AT device: {device} (attempt {attempt})", file=sys.stderr)
          client = AtClient(device, self.baud, self.timeout, self.verbose)
          client.ensure_capabilities()
          client.open_isdr()
          self._last_good_device = device
          if self.verbose:
            print(f"!! selected modem AT device: {device}", file=sys.stderr)
          return client
        except Exception as e:
          if self.verbose:
            print(f"!! modem AT device failed: {device}: {e}", file=sys.stderr)
          last_error = e
          if client is not None:
            try:
              client.close()
            except Exception:
              pass
      if not recovery_attempted and last_error is not None and self._should_recover_isdr(last_error):
        recovery_attempted = self._recover_isdr_access()
        if recovery_attempted:
          continue
      # Give modem a moment to finish startup / channel release.
      time.sleep(min(0.4 * attempt, 1.5))
    assert last_error is not None
    raise last_error

  def _candidate_devices(self) -> list[str]:
    if self.device and not os.path.exists(self.device):
      return [self.device]

    candidates = [
      self._last_good_device,
      self.device,
      "/dev/modem_at0",
      "/dev/ttyUSB3",
      "/dev/ttyUSB2",
      "/dev/ttyUSB1",
      "/dev/ttyUSB0",
    ]
    ordered: list[str] = []
    for dev in candidates:
      should_include = dev in (self.device, "/dev/modem_at0") or os.path.exists(dev)
      if dev and dev not in ordered and should_include:
        ordered.append(dev)
    return ordered if ordered else [self.device]

  @staticmethod
  def _to_profile(data: dict) -> Profile:
    return Profile(
      iccid=str(data.get("iccid") or ""),
      nickname=str(data.get("profileNickname") or ""),
      enabled=str(data.get("profileState") or "") == "enabled",
      provider=str(data.get("serviceProviderName") or ""),
    )

  def _clear_cat_busy(self) -> None:
    time.sleep(3)
    try:
      self._ensure_client().query('AT+QSTKRSP=254')
    except Exception:
      pass
    time.sleep(1)
    try:
      self._ensure_client().query('AT+CFUN=4')
    except Exception:
      pass
    time.sleep(2)
    try:
      self._ensure_client().query('AT+CFUN=1')
    except Exception:
      pass
    self._ensure_client().channel = None
    time.sleep(5)

  def _wait_for_modem(self, timeout: float = 45.0) -> None:
    start = time.monotonic()
    last_error: Exception | None = None
    while time.monotonic() - start < timeout:
      try:
        self.close()
        self._client = self._open_ready_client()
        return
      except Exception as e:
        last_error = e
        time.sleep(2)
    if last_error is not None:
      raise RuntimeError("Modem did not recover after reboot") from last_error
    raise RuntimeError("Modem did not recover after reboot")

  def _restart_modem(self) -> None:
    client = self._ensure_client()
    for cmd in ('AT+CFUN=0', 'AT+CFUN=1,1'):
      try:
        client.query(cmd)
      except Exception:
        pass
    client.channel = None
    client._use_csim = False
    self._wait_for_modem()

  @staticmethod
  def _should_recover_isdr(error: Exception) -> bool:
    message = str(error).lower()
    markers = (
      "failed to open isd-r",
      "failed to access euicc isd-r",
      "simfilenotfound",
      "at+ccho",
      "at+cgla",
    )
    return any(marker in message for marker in markers)

  def _recover_isdr_access(self) -> bool:
    was_modemmanager_running = self._is_modemmanager_running()
    self.close()
    try:
      if was_modemmanager_running:
        self._set_modemmanager_running(False)
        time.sleep(2.0)

      for cmd in (
        ["sudo", "qmicli", "-p", "-d", "/dev/cdc-wdm0", "--uim-reset"],
        ["sudo", "qmicli", "-p", "-d", "/dev/cdc-wdm0", "--uim-sim-power-off=1"],
        ["sudo", "qmicli", "-p", "-d", "/dev/cdc-wdm0", "--uim-sim-power-on=1"],
      ):
        subprocess.check_call(cmd)
        time.sleep(2.0)

      self._euicc_present_cache = None
      return True
    except Exception as e:
      if self.verbose:
        print(f"!! ISD-R recovery failed: {e}", file=sys.stderr)
      return False
    finally:
      if was_modemmanager_running:
        self._set_modemmanager_running(True)
        time.sleep(2.0)

  def _with_lpa_error(self, fn):
    last_error: Exception | None = None
    recovery_attempted = False
    for attempt in range(3):
      try:
        return fn()
      except LPAError:
        raise
      except RuntimeError as e:
        last_error = e
        if "does not provide usable esim functionality" in str(e).lower():
          raise LPAError(str(e)) from e
        if not recovery_attempted and self._should_recover_isdr(e):
          recovery_attempted = self._recover_isdr_access()
          if recovery_attempted:
            continue
        if self._is_transient_transport_error(str(e)) and attempt == 0:
          self._wait_for_modem()
          continue
        raise LPAError(str(e)) from e
      except (OSError, serial.SerialException) as e:
        last_error = e
        if not recovery_attempted and self._should_recover_isdr(e):
          recovery_attempted = self._recover_isdr_access()
          if recovery_attempted:
            continue
        if self._is_transient_transport_error(str(e)) and attempt == 0:
          self._wait_for_modem()
          continue
        raise LPAError(f"AT transport error: {e}") from e
      except TimeoutError as e:
        raise LPAError(f"AT modem timeout: {e}") from e
      except ValueError as e:
        raise LPAError(str(e)) from e
    assert last_error is not None
    raise LPAError(str(last_error))

  @staticmethod
  def _is_transient_transport_error(message: str) -> bool:
    lower = message.lower()
    transient_markers = (
      "broken pipe",
      "resource busy",
      "input/output error",
      "device disconnected",
      "device reports readiness to read but returned no data",
      "transport error",
      "missing +cgla response",
      "missing +csim response",
      "malformed +cgla response payload",
      "malformed +csim response payload",
      "non-hexadecimal number found in fromhex",
    )
    return any(m in lower for m in transient_markers)

  def list_profiles(self) -> list[Profile]:
    def _run() -> list[Profile]:
      return [self._to_profile(p) for p in list_profiles(self._ensure_client())]
    return self._with_lpa_error(_run)

  def get_active_profile(self) -> Profile | None:
    return next((p for p in self.list_profiles() if p.enabled), None)

  def _validate_profile_exists(self, iccid: str) -> None:
    if not any(p.iccid == iccid for p in self.list_profiles()):
      raise LPAProfileNotFoundError(f"profile {iccid} does not exist")

  def _is_bootstrapped(self) -> bool:
    return not any(self.is_comma_profile(p.iccid) for p in self.list_profiles())

  def _ensure_switchable_profile(self, iccid: str) -> None:
    if self.is_comma_profile(iccid):
      return

    if not self._is_bootstrapped():
      raise LPAError(
        "Delete the existing Comma pSIM profile before activating a user eSIM profile"
      )

  def _process_notifications_after_delete(self, client: AtClient, iccid: str) -> None:
    try:
      process_notifications(client)
      return
    except Exception as error:
      notification_error = error

    self._restart_modem()

    try:
      deleted = not any(p.iccid == iccid for p in self.list_profiles())
    except Exception:
      raise RuntimeError(
        "Profile delete may have succeeded, but modem notification cleanup failed; "
        "refresh profiles and retry if needed"
      ) from notification_error

    if deleted:
      return

    raise RuntimeError(
      "Profile delete did not finish cleanly; refresh profiles and retry"
    ) from notification_error

  def _process_notifications_after_state_change(
    self,
    validator,
    recovery_message: str,
    failure_message: str,
  ) -> None:
    try:
      process_notifications(self._ensure_client())
      return
    except Exception as notification_error:
      pass

    self._wait_for_modem()

    try:
      if validator():
        return
    except Exception:
      raise RuntimeError(recovery_message) from notification_error

    raise RuntimeError(failure_message) from notification_error

  def delete_profile(self, iccid: str) -> None:
    self._validate_profile_exists(iccid)
    active = self.get_active_profile()
    if active is not None and active.iccid == iccid:
      raise LPAError("cannot delete active profile, switch to another profile first")

    def _run() -> None:
      client = self._ensure_client()
      try:
        delete_profile(client, iccid)
      except RuntimeError as error:
        if "catbusy" in str(error).lower():
          self._clear_cat_busy()
          delete_profile(client, iccid)
        else:
          raise
      self._process_notifications_after_delete(client, iccid)

    self._with_lpa_error(_run)

  def bootstrap(self) -> None:
    comma_profiles = [p for p in self.list_profiles() if self.is_comma_profile(p.iccid)]
    if not comma_profiles:
      return

    def _run() -> None:
      client = self._ensure_client()
      for profile in comma_profiles:
        if profile.enabled:
          disable_profile(client, profile.iccid, refresh=True)
          process_notifications(client)
        delete_profile(client, profile.iccid)
        process_notifications(client)
      self._restart_modem()

    self._with_lpa_error(_run)

  def download_profile(self, qr: str, nickname: str | None = None) -> None:
    # Strict upfront validation to provide immediate user feedback.
    parse_lpa_activation_code(qr)
    before = {p.iccid for p in self.list_profiles()}

    def _run() -> None:
      client = self._ensure_client()
      iccid = download_profile(client, qr)
      self._process_notifications_after_state_change(
        lambda: any(profile.iccid == iccid for profile in self.list_profiles()),
        "Profile add may have succeeded, but modem notification cleanup failed; refresh profiles",
        "Profile add did not finish cleanly; refresh profiles and retry",
      )

    self._with_lpa_error(_run)

    if nickname:
      after = self.list_profiles()
      new_profile = next((p for p in after if p.iccid not in before), None)
      if new_profile is not None and new_profile.iccid:
        self.nickname_profile(new_profile.iccid, nickname)

  def nickname_profile(self, iccid: str, nickname: str) -> None:
    self._validate_profile_exists(iccid)

    def _run() -> None:
      set_profile_nickname(self._ensure_client(), iccid, nickname)
    self._with_lpa_error(_run)

  def switch_profile(self, iccid: str) -> None:
    self._validate_profile_exists(iccid)
    self._ensure_switchable_profile(iccid)
    active = self.get_active_profile()
    if active is not None and active.iccid == iccid:
      return

    def _run() -> None:
      client = self._ensure_client()
      use_refresh = self._is_eg25
      try:
        enable_profile(client, iccid, refresh=use_refresh)
      except RuntimeError as error:
        if "catbusy" in str(error).lower():
          self._clear_cat_busy()
          enable_profile(client, iccid, refresh=use_refresh)
        else:
          raise
      client.channel = None
      client._use_csim = False
      if use_refresh:
        self._wait_for_modem()
      else:
        self._restart_modem()
      self._process_notifications_after_state_change(
        lambda: any(profile.iccid == iccid and profile.enabled for profile in self.list_profiles()),
        "Profile switch may have succeeded, but modem notification cleanup failed; refresh profiles",
        "Profile switch did not finish cleanly; refresh profiles and retry",
      )
    self._with_lpa_error(_run)

  # Compatibility methods retained for old tests/scripts.
  def process_notifications(self) -> None:
    def _run() -> None:
      process_notifications(self._ensure_client())
    self._with_lpa_error(_run)

  def enable_profile(self, iccid: str, refresh: bool = True) -> None:
    self._validate_profile_exists(iccid)

    def _run() -> None:
      client = self._ensure_client()
      enable_profile(client, iccid, refresh=refresh)
      client.channel = None
      client._use_csim = False
      self._wait_for_modem()
      self._process_notifications_after_state_change(
        lambda: any(profile.iccid == iccid and profile.enabled for profile in self.list_profiles()),
        "Profile enable may have succeeded, but modem notification cleanup failed; refresh profiles",
        "Profile enable did not finish cleanly; refresh profiles and retry",
      )
    self._with_lpa_error(_run)

  def disable_profile(self, iccid: str, refresh: bool = True) -> None:
    self._validate_profile_exists(iccid)

    def _run() -> None:
      client = self._ensure_client()
      disable_profile(client, iccid, refresh=refresh)
      client.channel = None
      client._use_csim = False
      self._wait_for_modem()
      self._process_notifications_after_state_change(
        lambda: any(profile.iccid == iccid and not profile.enabled for profile in self.list_profiles()),
        "Profile disable may have succeeded, but modem notification cleanup failed; refresh profiles",
        "Profile disable did not finish cleanly; refresh profiles and retry",
      )
    self._with_lpa_error(_run)


# --- CLI ---

def main() -> None:
  parser = argparse.ArgumentParser(description="Minimal AT-only LPA implementation")
  parser.add_argument("--device", default=DEFAULT_DEVICE)
  parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
  parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
  parser.add_argument("--verbose", action="store_true")
  parser.add_argument("--enable", type=str)
  parser.add_argument("--disable", type=str)
  parser.add_argument("--delete", type=str, metavar="ICCID", help="Delete a disabled profile")
  parser.add_argument("--no-refresh", action="store_true", help="Skip REFRESH after enable/disable")
  parser.add_argument("--set-nickname", nargs=2, metavar=("ICCID", "NICKNAME"))
  parser.add_argument("--list-notifications", action="store_true")
  parser.add_argument("--process-notifications", action="store_true")
  parser.add_argument("--download", type=str, metavar="CODE")
  args = parser.parse_args()

  lpa = TiciLPA(device=args.device, baud=args.baud, timeout=args.timeout, verbose=args.verbose)

  if args.enable:
    lpa.enable_profile(args.enable, refresh=not args.no_refresh)
  elif args.disable:
    lpa.disable_profile(args.disable, refresh=not args.no_refresh)
  elif args.delete:
    lpa.delete_profile(args.delete)
  elif args.set_nickname:
    lpa.nickname_profile(args.set_nickname[0], args.set_nickname[1])
  elif args.list_notifications:
    with lpa._open_client() as client:
      print(json.dumps(list_notifications(client), indent=2))
    return
  elif args.process_notifications:
    lpa.process_notifications()
    return
  elif args.download:
    lpa.download_profile(args.download)

  profiles_out = [{
    "iccid": p.iccid,
    "profileNickname": p.nickname,
    "profileState": "enabled" if p.enabled else "disabled",
    "serviceProviderName": p.provider,
  } for p in lpa.list_profiles()]
  print(json.dumps(profiles_out, indent=2))


if __name__ == "__main__":
  main()

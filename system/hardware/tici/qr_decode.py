import ctypes
import hashlib
import os
import subprocess
from pathlib import Path

import numpy as np

try:
  from pyzbar.pyzbar import decode as _pyzbar_decode
except Exception:
  _pyzbar_decode = None


ROOT = Path(__file__).resolve().parents[3]
QUIRC_LIB_DIR = ROOT / "third_party" / "quirc" / "lib"
HELPER_C = Path(__file__).with_name("qr_decode_quirc.c")
BUILD_DIR = ROOT / ".run" / "cache" / "esim_qr"
SO_PATH = BUILD_DIR / "libiqpilot_quirc_decode.so"

_LIB: ctypes.CDLL | None = None


def _build_decoder() -> bool:
  BUILD_DIR.mkdir(parents=True, exist_ok=True)
  cmd = [
    os.environ.get("CC", "cc"),
    "-O2",
    "-shared",
    "-fPIC",
    str(HELPER_C),
    str(QUIRC_LIB_DIR / "quirc.c"),
    str(QUIRC_LIB_DIR / "identify.c"),
    str(QUIRC_LIB_DIR / "decode.c"),
    str(QUIRC_LIB_DIR / "version_db.c"),
    "-I",
    str(QUIRC_LIB_DIR),
    "-o",
    str(SO_PATH),
  ]
  try:
    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    return True
  except Exception:
    return False


def _load_decoder() -> ctypes.CDLL | None:
  global _LIB
  if _LIB is not None:
    return _LIB

  if not SO_PATH.exists():
    if not _build_decoder():
      return None

  try:
    lib = ctypes.CDLL(str(SO_PATH))
    lib.iqpilot_decode_qr_gray.argtypes = [
      ctypes.POINTER(ctypes.c_uint8),
      ctypes.c_int,
      ctypes.c_int,
      ctypes.c_char_p,
      ctypes.c_int,
    ]
    lib.iqpilot_decode_qr_gray.restype = ctypes.c_int
    _LIB = lib
    return _LIB
  except Exception:
    return None


def decode_qr(image: bytes | np.ndarray, width: int | None = None, height: int | None = None) -> list[str]:
  """
  Decode QR payloads from a grayscale image.
  Accepts:
  - ndarray shape (H, W), uint8
  - bytes + explicit width/height
  """
  arr: np.ndarray
  if isinstance(image, np.ndarray):
    if image.ndim != 2:
      raise ValueError("decode_qr expects grayscale ndarray with shape (H, W)")
    arr = np.ascontiguousarray(image, dtype=np.uint8)
    h, w = arr.shape
  else:
    if width is None or height is None:
      raise ValueError("width and height are required when passing raw bytes")
    arr = np.frombuffer(image, dtype=np.uint8).reshape((height, width))
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape

  if _pyzbar_decode is not None:
    try:
      pyzbar_results = _pyzbar_decode(arr)
      payloads = []
      for result in pyzbar_results:
        payload = result.data.decode("utf-8", errors="ignore").strip()
        if payload:
          payloads.append(payload)
      if payloads:
        return payloads
    except Exception:
      pass

  lib = _load_decoder()
  if lib is None:
    return []

  out_size = 8192
  out_buf = ctypes.create_string_buffer(out_size)
  count = lib.iqpilot_decode_qr_gray(
    arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
    int(w),
    int(h),
    out_buf,
    out_size,
  )
  if count <= 0:
    return []

  raw = out_buf.value.decode("utf-8", errors="ignore")
  return [line.strip() for line in raw.splitlines() if line.strip()]


def validate_lpa_activation_code(payload: str) -> tuple[bool, str]:
  if not payload.startswith("LPA:"):
    return False, "QR does not contain an LPA activation code"

  parts = payload[4:].split("$")
  if len(parts) != 3:
    return False, "Invalid LPA format"

  version, smdp, matching = [p.strip() for p in parts]
  if version != "1":
    return False, "Unsupported LPA version"
  if len(smdp) == 0 or "." not in smdp:
    return False, "Invalid SM-DP+ address"
  if len(matching) == 0:
    return False, "Missing matching ID"
  return True, ""


def stable_code_key(payload: str) -> str:
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()

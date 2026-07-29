try:
  from openpilot.common.params_pyx import Params, ParamKeyFlag, ParamKeyType, UnknownKeyName
except ImportError:
  import os
  import threading
  from enum import IntEnum, IntFlag

  class UnknownKeyName(Exception):
    pass

  class ParamKeyFlag(IntFlag):
    # must stay in lockstep with enum ParamKeyFlag in common/params.h
    PERSISTENT = 0x02
    CLEAR_ON_MANAGER_START = 0x04
    CLEAR_ON_ONROAD_TRANSITION = 0x08
    CLEAR_ON_OFFROAD_TRANSITION = 0x10
    DONT_LOG = 0x20
    DEVELOPMENT_ONLY = 0x40
    CLEAR_ON_IGNITION_ON = 0x80
    ALL = 0xFFFFFFFF

  class ParamKeyType(IntEnum):
    STRING = 0
    BOOL = 1
    INT = 2
    FLOAT = 3
    TIME = 4
    JSON = 5
    BYTES = 6

  class Params:
    def __init__(self, path: str = ""):
      root = path or os.environ.get("PARAMS_ROOT", "/data/params")
      # keys live under <root>/d (comma.sh sets up the d -> d_tmp symlink on a fresh boot)
      self._d = os.path.join(root, "d")
      self._lock = threading.Lock()

    def _p(self, key):
      if isinstance(key, bytes):
        key = key.decode()
      return os.path.join(self._d, key)

    def check_key(self, key):
      return True

    def get(self, key, block: bool = False, return_default: bool = False, encoding=None):
      try:
        with open(self._p(key), "rb") as f:
          dat = f.read()
      except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return None
      if encoding is not None:
        return dat.decode(encoding)
      # params_pyx returns string-typed values decoded; default to utf-8, fall back to raw bytes
      try:
        return dat.decode("utf-8")
      except UnicodeDecodeError:
        return dat

    def get_bool(self, key, block: bool = False) -> bool:
      try:
        with open(self._p(key), "rb") as f:
          return f.read() == b"1"
      except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return False

    def get_int(self, key, block: bool = False) -> int:
      value = self.get(key, block=block)
      return int(value) if value else 0

    def get_float(self, key, block: bool = False) -> float:
      value = self.get(key, block=block)
      return float(value) if value else 0.0

    def put(self, key, dat):
      if isinstance(dat, str):
        dat = dat.encode("utf-8")
      with self._lock:
        os.makedirs(self._d, exist_ok=True)
        p = self._p(key)
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
          f.write(dat)
          f.flush()
          os.fsync(f.fileno())
        os.rename(tmp, p)

    def put_bool(self, key, val: bool):
      self.put(key, b"1" if val else b"0")

    def put_int(self, key, val: int):
      self.put(key, str(val))

    def put_float(self, key, val: float):
      self.put(key, str(val))

    def put_nonblocking(self, key, dat):
      self.put(key, dat)

    def put_bool_nonblocking(self, key, val: bool):
      self.put_bool(key, val)

    def put_int_nonblocking(self, key, val: int):
      self.put_int(key, val)

    def put_float_nonblocking(self, key, val: float):
      self.put_float(key, val)

    def remove(self, key):
      try:
        os.remove(self._p(key))
      except FileNotFoundError:
        pass

    def clear_all(self, tx_type=None):
      pass

    def get_param_path(self, key: str = "") -> str:
      return self._p(key) if key else self._d

    def all_keys(self):
      try:
        return [k.encode() for k in os.listdir(self._d)]
      except FileNotFoundError:
        return []

assert Params
assert ParamKeyFlag
assert ParamKeyType
assert UnknownKeyName

if __name__ == "__main__":
  import sys

  params = Params()
  key = sys.argv[1]
  assert params.check_key(key), f"unknown param: {key}"

  if len(sys.argv) == 3:
    val = sys.argv[2]
    print(f"SET: {key} = {val}")
    params.put(key, val)
  elif len(sys.argv) == 2:
    print(f"GET: {key} = {params.get(key)}")

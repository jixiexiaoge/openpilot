#!/usr/bin/env python3
"""
Konn3kt BLE Setup transport (Phase A) — runs inside the setup zipapp, before any
IQ.Pilot install. Advertises the device on the setup screen so the konn3kt app
can drive Wi-Fi + install over Bluetooth. Self-contained (the compiled
ble-transportd bundle lives on the wiped /data and is unavailable here); uses the
AGNOS system python's gi/BlueZ D-Bus, mirroring the settings transport's GATT +
fragmentation + auth so the app can share client code.

See konn3kt_private/docs/konn3kt_ble_setup_protocol.md for the wire contract.
"""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

def _import_gi():
  # In setup mode /data is wiped, so the installed system's gi symlink
  # (/data/openpilot/gi) is gone and the venv has no gi of its own. The real gi
  # dist-package + GI typelibs live in the rootfs and survive reset — make them
  # importable before falling over. Works unchanged on an installed device too.
  import sys
  try:
    import gi  # noqa: F401
  except Exception:
    for extra in ("/usr/lib/python3/dist-packages", "/usr/lib/python3.12/dist-packages"):
      import os
      if os.path.isdir(os.path.join(extra, "gi")) and extra not in sys.path:
        sys.path.append(extra)
    import gi  # noqa: F401
  gi.require_version("Gio", "2.0")
  from gi.repository import Gio, GLib
  return gi, Gio, GLib


try:
  gi, Gio, GLib = _import_gi()
  _GI_AVAILABLE = True
except Exception:
  _GI_AVAILABLE = False

BLUEZ_SERVICE = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPS_IFACE = "org.freedesktop.DBus.Properties"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADV_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
LE_ADV_IFACE = "org.bluez.LEAdvertisement1"
DEVICE_IFACE = "org.bluez.Device1"
ADAPTER_IFACE = "org.bluez.Adapter1"

SETUP_SERVICE_UUID = "73f2c700-5e40-4d0d-8b7f-fde61f729100"
SETUP_CONTROL_CHAR_UUID = "73f2c701-5e40-4d0d-8b7f-fde61f729100"
SETUP_REQUEST_CHAR_UUID = "73f2c702-5e40-4d0d-8b7f-fde61f729100"
SETUP_RESPONSE_CHAR_UUID = "73f2c703-5e40-4d0d-8b7f-fde61f729100"
# 16-bit ServiceData UUID for the advertisement — a 128-bit service UUID PLUS
# 128-bit service data overflows the 31-byte legacy adv budget, so the setupId
# rides in a compact 16-bit ServiceData AD instead (the full 128-bit service is
# still the GATT service, discovered after connect). BlueZ expands "fe01" to the
# Bluetooth base UUID; the app reads it as 0000fe01-0000-1000-8000-00805f9b34fb.
SETUP_SERVICE_DATA_UUID = "0000fe01-0000-1000-8000-00805f9b34fb"

PROTOCOL_VERSION = 1
FRAME_HEADER = struct.Struct(">IHH")
MAX_FRAGMENT_PAYLOAD = 180
ADAPTER_WAIT_TIMEOUT_S = 8.0
BLUEZ_REGISTER_TIMEOUT_MS = 15000
SESSION_IDLE_TIMEOUT_S = 120
SEQ_REPLAY_WINDOW = 128
HELLO_MAX_SKEW_MS = 300_000
MAX_AUTH_FAILURES = 5
AUTH_LOCKOUT_S = 30.0


def setup_id_for_serial(serial: str) -> str:
  return hashlib.sha256(f"k3setup:{serial}".encode("utf-8")).hexdigest()[:16]


def _derive_setup_bdaddr(serial: str) -> str:
  raw = bytearray(hashlib.sha256(f"konn3kt-bdaddr:{serial}".encode("utf-8")).digest()[:6])
  raw[0] = (raw[0] | 0x02) & 0xFE
  return ":".join(f"{x:02X}" for x in raw)


def _json_safe(value: Any) -> Any:
  if isinstance(value, float):
    return value if math.isfinite(value) else None
  if isinstance(value, dict):
    return {str(k): _json_safe(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [_json_safe(v) for v in value]
  return value


def _canonical(value: Any) -> bytes:
  return json.dumps(_json_safe(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _safe_json(data: dict[str, Any]) -> bytes:
  return _canonical(data)


def _hmac_hex(key: bytes, payload: bytes) -> str:
  return hmac.new(key, payload, hashlib.sha256).hexdigest()


class SetupAuthError(Exception):
  pass


# ---------------------------------------------------------------------------
# Session / auth (6-digit code, mirrors settings-transport HKDF + replay window)
# ---------------------------------------------------------------------------
@dataclass
class SetupSession:
  client_id: str
  setup_id: str
  client_nonce: str
  device_nonce: str
  session_id: str
  authenticated: bool = False
  session_key: bytes = b""
  last_seen: float = 0.0
  highest_seq: int = 0
  seen_seq_mask: int = 0


class SetupSessionManager:
  def __init__(self, setup_id: str, code_getter: Callable[[], str]):
    self._setup_id = setup_id
    self._code_getter = code_getter
    self._sessions: dict[str, SetupSession] = {}
    self._auth_failures = 0
    self._lockout_until = 0.0
    self._lock = threading.Lock()

  def prune(self) -> None:
    now = time.monotonic()
    with self._lock:
      for cid in [c for c, s in self._sessions.items() if (now - s.last_seen) > SESSION_IDLE_TIMEOUT_S]:
        self._sessions.pop(cid, None)

  def begin_hello(self, client_id: str, setup_id: str, client_nonce: str, timestamp_ms: int) -> dict[str, Any]:
    if setup_id != self._setup_id:
      raise SetupAuthError("setup_id_mismatch")
    now_ms = int(time.time() * 1000)
    # NOTE: deliberately NO timestamp-skew check here. A freshly-reset device has
    # no network, so its clock is arbitrarily wrong (often weeks off) — a skew
    # check would reject every real setup. The 6-digit on-screen code is the
    # actual authorization and the per-session nonce prevents replay, so the
    # timestamp is informational only.
    session = SetupSession(
      client_id=client_id,
      setup_id=self._setup_id,
      client_nonce=str(client_nonce),
      device_nonce=secrets.token_hex(8),
      session_id=secrets.token_hex(8),
      last_seen=time.monotonic(),
    )
    with self._lock:
      self._sessions[client_id] = session
    return {
      "type": "helloAck",
      "protocolVersion": PROTOCOL_VERSION,
      "setupId": self._setup_id,
      "deviceNonce": session.device_nonce,
      "sessionId": session.session_id,
      "codeRequired": True,
      "timestampMs": now_ms,
    }

  def _session_key(self, session: SetupSession, code: str) -> bytes:
    salt = f"{session.client_nonce}:{session.device_nonce}:{session.session_id}:{self._setup_id}".encode("utf-8")
    prk = hmac.new(salt, f"k3setup:{code}".encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(prk, b"konn3kt-ble-setup-v1\x01", hashlib.sha256).digest()

  def authenticate(self, client_id: str, session_id: str, timestamp_ms: int, proof_hex: str) -> dict[str, Any]:
    if time.monotonic() < self._lockout_until:
      raise SetupAuthError("auth_locked_out")
    session = self._sessions.get(client_id)
    if session is None or session.session_id != session_id:
      raise SetupAuthError("unknown_session")
    code = str(self._code_getter() or "")
    key = self._session_key(session, code)
    expected = _hmac_hex(key, _canonical({"role": "client-auth", "sessionId": session_id, "timestampMs": int(timestamp_ms)}))
    if not hmac.compare_digest(expected, str(proof_hex or "").strip().lower()):
      self._auth_failures += 1
      if self._auth_failures >= MAX_AUTH_FAILURES:
        self._lockout_until = time.monotonic() + AUTH_LOCKOUT_S
        self._auth_failures = 0
      raise SetupAuthError("auth_failed")
    self._auth_failures = 0
    session.authenticated = True
    session.session_key = key
    session.highest_seq = 0
    session.seen_seq_mask = 0
    session.last_seen = time.monotonic()
    return {
      "type": "authOk",
      "sessionId": session_id,
      "setupId": self._setup_id,
      "timestampMs": int(time.time() * 1000),
      "proof": _hmac_hex(key, _canonical({"role": "device-auth", "sessionId": session_id, "timestampMs": int(timestamp_ms)})),
    }

  def validate_request(self, client_id: str, session_id: str) -> SetupSession:
    session = self._sessions.get(client_id)
    if session is None or not session.authenticated:
      raise SetupAuthError("session_not_authenticated")
    if session.session_id != session_id:
      raise SetupAuthError("session_id_mismatch")
    session.last_seen = time.monotonic()
    return session

  def _check_seq(self, session: SetupSession, seq: int) -> None:
    seq = int(seq)
    if seq <= 0:
      raise SetupAuthError("seq_invalid")
    if seq > session.highest_seq:
      return
    offset = session.highest_seq - seq
    if offset >= SEQ_REPLAY_WINDOW or (session.seen_seq_mask >> offset) & 1:
      raise SetupAuthError("seq_replayed")

  def _consume_seq(self, session: SetupSession, seq: int) -> None:
    seq = int(seq)
    if seq > session.highest_seq:
      shift = seq - session.highest_seq
      session.seen_seq_mask = ((session.seen_seq_mask << shift) | 1) & ((1 << SEQ_REPLAY_WINDOW) - 1)
      session.highest_seq = seq
    else:
      session.seen_seq_mask |= 1 << (session.highest_seq - seq)

  def validate_signed_request(self, client_id: str, session_id: str, request_id: Any, seq: int, method: str, params: Any, mac_hex: str) -> SetupSession:
    session = self.validate_request(client_id, session_id)
    if not session.session_key:
      raise SetupAuthError("missing_session_key")
    self._check_seq(session, seq)
    payload = _canonical({"id": request_id, "method": method, "params": params, "seq": int(seq), "sessionId": session_id, "type": "request"})
    if not hmac.compare_digest(_hmac_hex(session.session_key, payload), str(mac_hex or "").strip().lower()):
      raise SetupAuthError("request_mac_invalid")
    self._consume_seq(session, seq)
    return session

  def build_response(self, session: SetupSession | None, request_id: Any, seq: int | None, *, result: Any = None, error: str | None = None) -> dict[str, Any]:
    rtype = "error" if error is not None else "response"
    env: dict[str, Any] = {"type": rtype, "id": request_id}
    if error is not None:
      env["error"] = error
    else:
      env["result"] = result
    if session is not None and session.session_key and seq is not None:
      payload = error if error is not None else result
      env["seq"] = int(seq)
      env["mac"] = _hmac_hex(session.session_key, _canonical({"id": request_id, "payload": payload, "seq": int(seq), "sessionId": session.session_id, "type": rtype}))
    return env


# ---------------------------------------------------------------------------
# GATT plumbing (adapted from the proven settings transport, + ServiceData adv)
# ---------------------------------------------------------------------------
def _variant(sig: str, val: Any):
  return GLib.Variant(sig, val)


def frame_payload(payload: bytes) -> list[bytes]:
  if not payload:
    payload = b"{}"
  chunk = max(1, MAX_FRAGMENT_PAYLOAD - FRAME_HEADER.size)
  chunks = [payload[i:i + chunk] for i in range(0, len(payload), chunk)] or [b""]
  total, count = len(payload), len(chunks)
  return [FRAME_HEADER.pack(total, idx, count) + c for idx, c in enumerate(chunks)]


@dataclass
class _Reassembly:
  total_length: int
  fragment_count: int
  chunks: dict[int, bytes] = field(default_factory=dict)

  def add(self, idx: int, payload: bytes) -> bytes | None:
    self.chunks[idx] = payload
    if len(self.chunks) != self.fragment_count:
      return None
    return b"".join(self.chunks[i] for i in range(self.fragment_count))[:self.total_length]


OM_XML = '<node><interface name="org.freedesktop.DBus.ObjectManager"><method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" name="objects" direction="out"/></method></interface></node>'
PROPS_XML = '<node><interface name="org.freedesktop.DBus.Properties"><method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method><method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method></interface></node>'
SERVICE_XML = '<node><interface name="org.bluez.GattService1"><property name="UUID" type="s" access="read"/><property name="Primary" type="b" access="read"/><property name="Characteristics" type="ao" access="read"/></interface></node>'
CHAR_XML = '<node><interface name="org.bluez.GattCharacteristic1"><method name="ReadValue"><arg type="a{sv}" direction="in"/><arg type="ay" direction="out"/></method><method name="WriteValue"><arg type="ay" direction="in"/><arg type="a{sv}" direction="in"/></method><method name="StartNotify"/><method name="StopNotify"/><property name="UUID" type="s" access="read"/><property name="Service" type="o" access="read"/><property name="Flags" type="as" access="read"/><property name="Value" type="ay" access="read"/><property name="Notifying" type="b" access="read"/></interface></node>'
ADV_XML = '<node><interface name="org.bluez.LEAdvertisement1"><method name="Release"/><property name="Type" type="s" access="read"/><property name="ServiceUUIDs" type="as" access="read"/><property name="LocalName" type="s" access="read"/><property name="ServiceData" type="a{sv}" access="read"/><property name="Includes" type="as" access="read"/></interface></node>'


class _Exported:
  def __init__(self, path, xml, methods=None, properties=None):
    self.path = path
    self.node = Gio.DBusNodeInfo.new_for_xml(xml)
    self.methods = methods or {}
    self.properties = properties or {}
    self.ids: list[int] = []

  def register(self, bus):
    for iface in self.node.interfaces:
      self.ids.append(bus.register_object(self.path, iface, self._call, self._get, None))

  def unregister(self, bus):
    for i in self.ids:
      try:
        bus.unregister_object(i)
      except Exception:
        pass
    self.ids.clear()

  def _call(self, conn, sender, path, iface, method, params, invocation):
    handler = self.methods.get((iface, method))
    if handler is None:
      invocation.return_dbus_error("org.konn3kt.Error", f"unsupported:{iface}.{method}")
      return
    try:
      result = handler(params)
      invocation.return_value(result)
    except Exception as e:
      invocation.return_dbus_error("org.konn3kt.Error", str(e))

  def _get(self, conn, sender, path, iface, name):
    props = self.properties.get(iface, {})
    return props[name]() if name in props else None


class SetupBleServer:
  """Advertise + serve the setup GATT service. Single central (1:1 setup)."""

  def __init__(self, *, serial: str, on_control: Callable[[bytes], bytes | None], on_request: Callable[[bytes], bytes | None]):
    self.serial = serial
    self.setup_id = setup_id_for_serial(serial)
    self.local_name = f"IQSetup-{serial[-6:]}"
    self.on_control = on_control
    self.on_request = on_request
    self.bus = None
    self.adapter_path: str | None = None
    self.context = None
    self.loop = None
    self._thread: threading.Thread | None = None
    self._ready = threading.Event()
    self._error: Exception | None = None
    self.running = False
    self._install_in_progress = False
    self._root = f"/io/konn3kt/setup/p{os.getpid()}"
    self._objects: list[_Exported] = []
    self._notify = {"control": False, "response": False}
    self._values = {"control": b"", "request": b"", "response": b""}
    self._reassembly: dict[str, _Reassembly] = {}

  # ---- lifecycle -----------------------------------------------------------
  def start(self, timeout_s: float = 30.0) -> None:
    if not _GI_AVAILABLE:
      raise RuntimeError("gi_unavailable")
    if self.running:
      return
    self._ensure_unique_bdaddr()
    self._thread = threading.Thread(target=self._run, name="setup_ble_gatt", daemon=True)
    self._thread.start()
    if not self._ready.wait(timeout=timeout_s):
      raise RuntimeError("setup_ble_start_timeout")
    if self._error is not None:
      raise self._error

  def stop(self) -> None:
    try:
      if self.context is not None:
        GLib.idle_add(self._stop_on_loop)
      if self._thread is not None:
        self._thread.join(timeout=3.0)
    except Exception:
      pass
    self.running = False

  def set_install_in_progress(self, active: bool) -> None:
    self._install_in_progress = bool(active)

  # ---- BD address ----------------------------------------------------------
  def _run_priv(self, args: list[str], timeout_s: float = 10.0) -> bool:
    cmds = ([args] if os.geteuid() == 0 else [["sudo", "-n", *args], args])
    for cmd in cmds:
      try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_s, check=False)
        if p.returncode == 0:
          return True
      except Exception:
        continue
    return False

  def _read_bdaddr(self) -> str | None:
    try:
      out = subprocess.run(["hciconfig", "hci0"], stdout=subprocess.PIPE, text=True, timeout=5.0, check=False).stdout
      m = re.search(r"BD Address:\s*([0-9A-Fa-f:]{17})", out or "")
      return m.group(1).upper() if m else None
    except Exception:
      return None

  def _ensure_unique_bdaddr(self) -> None:
    current = self._read_bdaddr()
    if not current or not current.startswith("00:00:00:00"):
      return
    target = _derive_setup_bdaddr(self.serial)
    octets = [f"0x{p}" for p in target.split(":")]
    if not self._run_priv(["hcitool", "-i", "hci0", "cmd", "0x3f", "0x0014", *octets]):
      return
    time.sleep(0.5)
    self._run_priv(["hciconfig", "hci0", "reset"])
    time.sleep(1.5)
    self._run_priv(["systemctl", "restart", "bluetooth.service"], timeout_s=20.0)
    time.sleep(2.0)

  # ---- main loop -----------------------------------------------------------
  def _run(self):
    self.context = GLib.MainContext()
    self.loop = GLib.MainLoop.new(self.context, False)
    self.context.push_thread_default()
    try:
      src = GLib.idle_source_new()
      src.set_callback(self._startup)
      src.attach(self.context)
      self.loop.run()
    except Exception as e:
      self._error = e
      self._ready.set()
    finally:
      try:
        self.context.pop_thread_default()
      except Exception:
        pass

  def _find_adapter(self) -> str | None:
    objs = self._managed_objects()
    for path, ifaces in objs.items():
      if GATT_MANAGER_IFACE in ifaces and LE_ADV_MANAGER_IFACE in ifaces and ADAPTER_IFACE in ifaces:
        return path
    return None

  def _managed_objects(self) -> dict:
    reply = self.bus.call_sync(BLUEZ_SERVICE, "/", DBUS_OM_IFACE, "GetManagedObjects", None,
                               GLib.VariantType.new("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 5000, None)
    u = reply.unpack()
    return u[0] if isinstance(u, tuple) else u

  def _startup(self, *_):
    try:
      self._dbg("startup begin")
      self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
      # ensure powered
      try:
        self.adapter_path = None
        start = time.monotonic()
        while time.monotonic() - start < ADAPTER_WAIT_TIMEOUT_S:
          self.adapter_path = self._find_adapter()
          if self.adapter_path:
            break
          time.sleep(0.5)
        if not self.adapter_path:
          raise RuntimeError("bluetooth_adapter_not_found")
        self._set_powered()
      except Exception:
        raise
      self._dbg("adapter=%s, registering objects" % self.adapter_path)
      self._register_objects()
      self._dbg("objects registered, calling RegisterApplication")
      self._register_with_bluez()
      self._dbg("RegisterApplication call issued")
    except Exception as e:
      import traceback as _tb
      self._dbg("startup EXC: %r\n%s" % (e, _tb.format_exc()))
      self._error = e
      self._stop_on_loop()
      if self.loop:
        self.loop.quit()
      self._ready.set()
    return False

  def _set_powered(self):
    try:
      self.bus.call_sync(BLUEZ_SERVICE, self.adapter_path, DBUS_PROPS_IFACE, "Set",
                         GLib.Variant("(ssv)", (ADAPTER_IFACE, "Powered", GLib.Variant("b", True))),
                         None, Gio.DBusCallFlags.NONE, 5000, None)
    except Exception:
      pass

  # paths
  @property
  def _app_path(self): return self._root
  @property
  def _service_path(self): return self._root + "/service0"
  @property
  def _control_path(self): return self._service_path + "/char0"
  @property
  def _request_path(self): return self._service_path + "/char1"
  @property
  def _response_path(self): return self._service_path + "/char2"
  @property
  def _adv_path(self): return self._root + "/advertisement0"

  def _char_props(self, uuid, flags, kind):
    return {GATT_CHRC_IFACE: {
      "UUID": lambda: _variant("s", uuid),
      "Service": lambda: _variant("o", self._service_path),
      "Flags": lambda: _variant("as", flags),
      "Value": lambda: _variant("ay", list(self._values[kind])),
      "Notifying": lambda: _variant("b", self._notify.get(kind, False)),
    }}

  def _service_data_variant(self):
    flags = 0x01 | (0x02 if self._install_in_progress else 0x00)
    data = bytes([PROTOCOL_VERSION, flags]) + bytes.fromhex(self.setup_id)
    return _variant("a{sv}", {SETUP_SERVICE_DATA_UUID: GLib.Variant("ay", list(data))})

  def _register_objects(self):
    chars = [self._control_path, self._request_path, self._response_path]
    service_props = {GATT_SERVICE_IFACE: {
      "UUID": lambda: _variant("s", SETUP_SERVICE_UUID),
      "Primary": lambda: _variant("b", True),
      "Characteristics": lambda: _variant("ao", chars),
    }}
    # Keep the adv within the 31-byte legacy budget: 16-bit ServiceData (setupId)
    # + a short LocalName, no 128-bit ServiceUUID, no tx-power. The app scans by
    # the ServiceData UUID and matches setupId locally against its known serials.
    adv_props = {LE_ADV_IFACE: {
      "Type": lambda: _variant("s", "peripheral"),
      "LocalName": lambda: _variant("s", "IQSetup"),
      "ServiceData": self._service_data_variant,
    }}

    def mk_props(path, pmap):
      def get_prop(params):
        iface, name = params.unpack()
        getter = pmap.get(iface, {}).get(name)
        if getter is None:
          raise RuntimeError(f"unknown_property:{iface}.{name}")
        return GLib.Variant("(v)", (getter(),))
      def get_all(params):
        (iface,) = params.unpack()
        pm = pmap.get(iface)
        if pm is None:
          raise RuntimeError(f"unknown_interface:{iface}")
        return GLib.Variant("(a{sv})", ({k: g() for k, g in pm.items()},))
      return _Exported(path, PROPS_XML, methods={(DBUS_PROPS_IFACE, "Get"): get_prop, (DBUS_PROPS_IFACE, "GetAll"): get_all})

    app = _Exported(self._app_path, OM_XML, methods={(DBUS_OM_IFACE, "GetManagedObjects"): self._get_managed})
    service = _Exported(self._service_path, SERVICE_XML, properties=service_props)
    control = self._mk_char("control", self._control_path, SETUP_CONTROL_CHAR_UUID, ["write", "notify"])
    request = self._mk_char("request", self._request_path, SETUP_REQUEST_CHAR_UUID, ["write", "write-without-response"])
    response = self._mk_char("response", self._response_path, SETUP_RESPONSE_CHAR_UUID, ["notify"])
    adv = _Exported(self._adv_path, ADV_XML, methods={(LE_ADV_IFACE, "Release"): lambda _: None}, properties=adv_props)

    self._objects = [
      app, mk_props(self._app_path, {}),
      service, mk_props(self._service_path, service_props),
      control, mk_props(self._control_path, self._char_props(SETUP_CONTROL_CHAR_UUID, ["write", "notify"], "control")),
      request, mk_props(self._request_path, self._char_props(SETUP_REQUEST_CHAR_UUID, ["write", "write-without-response"], "request")),
      response, mk_props(self._response_path, self._char_props(SETUP_RESPONSE_CHAR_UUID, ["notify"], "response")),
      adv, mk_props(self._adv_path, adv_props),
    ]
    for o in self._objects:
      o.register(self.bus)

  def _mk_char(self, kind, path, uuid, flags):
    def read_value(_params):
      return GLib.Variant("(ay)", (list(self._values[kind]),))

    def write_value(params):
      value, options = params.unpack()
      payload = bytes(int(x) & 0xFF for x in value) if isinstance(value, (list, tuple)) else bytes(value or b"")
      full = self._consume_fragment(kind, payload)
      if full is None:
        return None
      self._values[kind] = full
      if kind == "control":
        resp = self.on_control(full)
        if resp:
          self.notify("control", resp)
      elif kind == "request":
        # Handle on a worker so a slow op (wifi scan, connect) never stalls BLE.
        threading.Thread(target=self._handle_request_worker, args=(full,), daemon=True).start()
      return None

    def start_notify(_params):
      self._notify[kind] = True
      return None

    def stop_notify(_params):
      self._notify[kind] = False
      return None

    return _Exported(path, CHAR_XML, methods={
      (GATT_CHRC_IFACE, "ReadValue"): read_value,
      (GATT_CHRC_IFACE, "WriteValue"): write_value,
      (GATT_CHRC_IFACE, "StartNotify"): start_notify,
      (GATT_CHRC_IFACE, "StopNotify"): stop_notify,
    }, properties=self._char_props(uuid, flags, kind))

  def _handle_request_worker(self, full: bytes):
    try:
      resp = self.on_request(full)
      if resp:
        self.notify("response", resp)
    except Exception:
      pass

  def _get_managed(self, _params):
    managed = {
      self._service_path: {GATT_SERVICE_IFACE: {
        "UUID": _variant("s", SETUP_SERVICE_UUID), "Primary": _variant("b", True),
        "Characteristics": _variant("ao", [self._control_path, self._request_path, self._response_path])}},
      self._control_path: {GATT_CHRC_IFACE: {"UUID": _variant("s", SETUP_CONTROL_CHAR_UUID), "Service": _variant("o", self._service_path), "Flags": _variant("as", ["write", "notify"])}},
      self._request_path: {GATT_CHRC_IFACE: {"UUID": _variant("s", SETUP_REQUEST_CHAR_UUID), "Service": _variant("o", self._service_path), "Flags": _variant("as", ["write", "write-without-response"])}},
      self._response_path: {GATT_CHRC_IFACE: {"UUID": _variant("s", SETUP_RESPONSE_CHAR_UUID), "Service": _variant("o", self._service_path), "Flags": _variant("as", ["notify"])}},
    }
    return GLib.Variant("(a{oa{sa{sv}}})", (managed,))

  def _consume_fragment(self, kind, fragment):
    if len(fragment) < FRAME_HEADER.size:
      raise RuntimeError("fragment_too_small")
    total, idx, count = FRAME_HEADER.unpack(fragment[:FRAME_HEADER.size])
    if count <= 0 or idx >= count:
      raise RuntimeError("invalid_fragment_header")
    st = self._reassembly.get(kind)
    if st is None or st.total_length != total or st.fragment_count != count:
      st = _Reassembly(total_length=total, fragment_count=count)
      self._reassembly[kind] = st
    payload = st.add(idx, fragment[FRAME_HEADER.size:])
    if payload is not None:
      self._reassembly.pop(kind, None)
    return payload

  def notify(self, kind: str, payload: bytes):
    path = {"control": self._control_path, "response": self._response_path}.get(kind)
    if not self.running or self.bus is None or not self._notify.get(kind) or path is None:
      return
    for fragment in frame_payload(payload):
      self._values[kind] = fragment
      try:
        self.bus.emit_signal(None, path, DBUS_PROPS_IFACE, "PropertiesChanged",
                             GLib.Variant("(sa{sv}as)", (GATT_CHRC_IFACE, {"Value": _variant("ay", list(fragment))}, [])))
      except Exception:
        pass

  def refresh_advertisement(self):
    """Re-emit ServiceData (e.g. install-in-progress flag flipped)."""
    if not self.running or self.bus is None:
      return
    try:
      self.bus.emit_signal(None, self._adv_path, DBUS_PROPS_IFACE, "PropertiesChanged",
                           GLib.Variant("(sa{sv}as)", (LE_ADV_IFACE, {"ServiceData": self._service_data_variant()}, [])))
    except Exception:
      pass

  # ---- bluez registration --------------------------------------------------
  def _register_with_bluez(self):
    self.bus.call(BLUEZ_SERVICE, self.adapter_path, GATT_MANAGER_IFACE, "RegisterApplication",
                  GLib.Variant("(oa{sv})", (self._app_path, {})), None, Gio.DBusCallFlags.NONE,
                  BLUEZ_REGISTER_TIMEOUT_MS, None, self._on_app_registered, None)

  def _on_app_registered(self, conn, result, _ud):
    try:
      (conn or self.bus).call_finish(result)
      self._dbg("app_registered OK adv_path=%s" % self._adv_path)
    except GLib.GError as e:
      self._dbg("app_registered GError: %s" % e)
      if "AlreadyExists" not in str(e):
        self._error = e
        self._stop_on_loop()
        if self.loop:
          self.loop.quit()
        self._ready.set()
        return
    self.bus.call(BLUEZ_SERVICE, self.adapter_path, LE_ADV_MANAGER_IFACE, "RegisterAdvertisement",
                  GLib.Variant("(oa{sv})", (self._adv_path, {})), None, Gio.DBusCallFlags.NONE,
                  BLUEZ_REGISTER_TIMEOUT_MS, None, self._on_adv_registered, None)

  def _dbg(self, msg):
    try:
      import os as _os
      fd = _os.open("/data/setup_test/setup_ble_dbg.log", _os.O_WRONLY | _os.O_CREAT | _os.O_APPEND, 0o644)
      _os.write(fd, (msg + "\n").encode())
      _os.close(fd)
    except Exception:
      pass

  def _on_adv_registered(self, conn, result, _ud):
    try:
      (conn or self.bus).call_finish(result)
      self._dbg("adv_registered OK")
    except GLib.GError as e:
      self._dbg("adv_registered GError: %s" % e)
      if "AlreadyExists" not in str(e):
        self._error = e
        self._stop_on_loop()
        if self.loop:
          self.loop.quit()
        self._ready.set()
        return
    self.running = True
    self._error = None
    self._ready.set()

  def _clear_registrations(self):
    if self.bus is None or self.adapter_path is None:
      return
    for iface, method, arg in (
      (LE_ADV_MANAGER_IFACE, "UnregisterAdvertisement", self._adv_path),
      (GATT_MANAGER_IFACE, "UnregisterApplication", self._app_path),
    ):
      try:
        self.bus.call_sync(BLUEZ_SERVICE, self.adapter_path, iface, method, GLib.Variant("(o)", (arg,)),
                           None, Gio.DBusCallFlags.NONE, 3000, None)
      except Exception:
        pass

  def _stop_on_loop(self):
    if self.bus is not None and self.adapter_path is not None:
      self._clear_registrations()
    if self.bus is not None:
      for o in reversed(self._objects):
        try:
          o.unregister(self.bus)
        except Exception:
          pass
    self._objects.clear()
    self.running = False
    if self.loop:
      try:
        self.loop.quit()
      except Exception:
        pass

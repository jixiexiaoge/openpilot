#!/usr/bin/env python3
"""
Konn3kt setup BLE controller — owns the setup session, dispatches the setup
operations against the real device (Wi-Fi via WifiManager, hardware/cellular via
HARDWARE, install via an injected trigger), and exposes the 6-digit code + a
small observable status the setup UI renders.

Runs inside the setup zipapp. See konn3kt_ble_setup_protocol.md.
"""
import json
import secrets
import threading
import time
import urllib.request
from typing import Any, Callable

from openpilot.system.ui.lib.setup_ble import (
  SetupBleServer,
  SetupSessionManager,
  SetupAuthError,
  PROTOCOL_VERSION,
)
from openpilot.system.ui.lib.os_update import OsUpdateCoordinator

NETWORK_CHECK_URL = "https://openpilot.comma.ai"
IQPILOT_CHANNELS = {"release": "IQLvbs/release", "beta": "IQLvbs/beta"}

# Setup ops served over BLE (Phase A only — deliberately tiny, no shell/params).
SETUP_METHODS = {
  "getSetupInfo",
  "scanWifi",
  "connectWifi",
  "forgetWifi",
  "getNetworkStatus",
  "startInstall",
  "getInstallProgress",
  "confirmOsUpdate",
  "ping",
}


def _new_code() -> str:
  return f"{secrets.randbelow(1_000_000):06d}"


class SetupController:
  def __init__(self, *, serial: str, hardware: Any, wifi_manager: Any,
               on_start_install: Callable[[str], None], version: str = ""):
    self.serial = serial
    self.hardware = hardware
    self.wifi = wifi_manager
    self.on_start_install = on_start_install
    self.version = version

    self._code = _new_code()
    self._code_lock = threading.Lock()
    self.session_manager: SetupSessionManager | None = None
    self.server: SetupBleServer | None = None

    # Observable UI state
    self._lock = threading.Lock()
    self.phone_active = False          # a phone has authenticated
    self.install_state = "idle"        # idle|downloading|os_update_required|os_updating|installing|failed|rebooting
    self.install_percent = 0
    self.install_error = ""
    self.os_from = ""                  # current IQ.OS version when an OS update is needed
    self.os_to = ""                    # target IQ.OS version
    self.os_update = OsUpdateCoordinator()  # bridges install thread <-> phone confirm
    self._enabled = False

  # ---- code ----------------------------------------------------------------
  @property
  def code(self) -> str:
    with self._code_lock:
      return self._code

  def _rotate_code(self) -> None:
    with self._code_lock:
      self._code = _new_code()

  # ---- lifecycle -----------------------------------------------------------
  def start(self) -> bool:
    if self._enabled:
      return True
    self._enabled = True
    threading.Thread(target=self._start_blocking, name="setup_ble_start", daemon=True).start()
    return True

  def _start_blocking(self) -> None:
    self.session_manager = SetupSessionManager(self._setup_id(), lambda: self.code)
    server = SetupBleServer(
      serial=self.serial,
      on_control=self._on_control,
      on_request=self._on_request,
    )
    try:
      server.start()
    except Exception as e:
      print(f"[setup_ble] start failed: {e}")
      return
    self.server = server
    if self.wifi is not None:
      try:
        self.wifi.set_active(True)
      except Exception:
        pass
    print(f"[setup_ble] advertising setupId={self._setup_id()} name=IQSetup-{self.serial[-6:]}")

  def stop(self) -> None:
    self._enabled = False
    if self.server is not None:
      try:
        self.server.stop()
      except Exception:
        pass
      self.server = None

  def _setup_id(self) -> str:
    from openpilot.system.ui.lib.setup_ble import setup_id_for_serial
    return setup_id_for_serial(self.serial)

  # ---- observable state ----------------------------------------------------
  def snapshot(self) -> dict[str, Any]:
    with self._lock:
      return {
        "phone_active": self.phone_active,
        "install_state": self.install_state,
        "install_percent": self.install_percent,
        "install_error": self.install_error,
        "osFrom": self.os_from,
        "osTo": self.os_to,
      }

  def set_install_progress(self, state: str, percent: int = 0, error: str = "",
                           os_from: str | None = None, os_to: str | None = None) -> None:
    with self._lock:
      self.install_state = state
      self.install_percent = int(percent)
      self.install_error = error
      if os_from is not None:
        self.os_from = os_from
      if os_to is not None:
        self.os_to = os_to
      cur_from, cur_to = self.os_from, self.os_to
    if self.server is not None:
      self.server.set_install_in_progress(state in ("downloading", "os_updating", "installing", "rebooting"))
      self.server.refresh_advertisement()
      # push unsolicited progress event to a connected phone
      self.server.notify("response", json.dumps({
        "type": "event", "event": "installProgress",
        "state": state, "percent": int(percent), "error": error,
        "osFrom": cur_from, "osTo": cur_to,
      }, separators=(",", ":")).encode("utf-8"))

  # ---- control (hello/auth/ping) -------------------------------------------
  def _on_control(self, payload: bytes) -> bytes | None:
    try:
      msg = json.loads(payload.decode("utf-8"))
      mtype = str(msg.get("type") or "")
      client_id = "central"  # single central for setup
      self.session_manager.prune()
      if mtype == "hello":
        resp = self.session_manager.begin_hello(
          client_id=client_id,
          setup_id=str(msg.get("setupId") or ""),
          client_nonce=str(msg.get("clientNonce") or ""),
          timestamp_ms=int(msg.get("timestampMs") or 0),
        )
        # The code is generated once at setup start and shown persistently on the
        # device screen (Chromecast-style) — it must NOT change mid-pairing, or
        # the code the user is reading becomes stale the instant they connect.
        return json.dumps(resp, separators=(",", ":")).encode("utf-8")
      if mtype == "auth":
        resp = self.session_manager.authenticate(
          client_id=client_id,
          session_id=str(msg.get("sessionId") or ""),
          timestamp_ms=int(msg.get("timestampMs") or 0),
          proof_hex=str(msg.get("proof") or ""),
        )
        with self._lock:
          self.phone_active = True
        return json.dumps(resp, separators=(",", ":")).encode("utf-8")
      if mtype == "ping":
        sid = str(msg.get("sessionId") or "")
        self.session_manager.validate_request(client_id, sid)
        return json.dumps({"type": "pong", "sessionId": sid, "timestampMs": int(time.time() * 1000)}, separators=(",", ":")).encode("utf-8")
      raise SetupAuthError("unsupported_control_message")
    except SetupAuthError as e:
      return json.dumps({"type": "error", "error": str(e)}, separators=(",", ":")).encode("utf-8")
    except Exception as e:
      return json.dumps({"type": "error", "error": str(e)}, separators=(",", ":")).encode("utf-8")

  # ---- request (authenticated ops) -----------------------------------------
  def _on_request(self, payload: bytes) -> bytes | None:
    request_id = None
    session = None
    seq = None
    try:
      msg = json.loads(payload.decode("utf-8"))
      request_id = msg.get("id")
      method = str(msg.get("method") or "")
      # MAC must be verified over params EXACTLY as sent (None when omitted) —
      # coercing to {} here would diverge from the client's canonical JSON.
      params = msg.get("params")
      seq = int(msg.get("seq") or 0)
      session = self.session_manager.validate_signed_request(
        "central", str(msg.get("sessionId") or ""), request_id, seq, method, params, str(msg.get("mac") or ""),
      )
      if method not in SETUP_METHODS:
        raise SetupAuthError(f"method_not_allowed:{method}")
      result = self._dispatch(method, params or {})
      return json.dumps(self.session_manager.build_response(session, request_id, seq, result=result), separators=(",", ":")).encode("utf-8")
    except SetupAuthError as e:
      env = self.session_manager.build_response(session, request_id, seq, error=str(e)) if session else {"type": "error", "id": request_id, "error": str(e)}
      return json.dumps(env, separators=(",", ":")).encode("utf-8")
    except Exception as e:
      env = self.session_manager.build_response(session, request_id, seq, error=str(e)) if session else {"type": "error", "id": request_id, "error": str(e)}
      return json.dumps(env, separators=(",", ":")).encode("utf-8")

  def _dispatch(self, method: str, params: dict) -> Any:
    if method == "ping":
      return {"ok": True}
    if method == "getSetupInfo":
      return self._setup_info()
    if method == "scanWifi":
      return {"networks": self._scan_wifi()}
    if method == "connectWifi":
      return self._connect_wifi(str(params.get("ssid") or ""), str(params.get("password") or ""))
    if method == "forgetWifi":
      return self._forget_wifi(str(params.get("ssid") or ""))
    if method == "getNetworkStatus":
      return self._network_status()
    if method == "startInstall":
      return self._start_install(str(params.get("channel") or "release"))
    if method == "getInstallProgress":
      s = self.snapshot()
      return {"state": s["install_state"], "percent": s["install_percent"], "error": s["install_error"],
              "osFrom": s["osFrom"], "osTo": s["osTo"]}
    if method == "confirmOsUpdate":
      # Phone approved flashing the newer IQ.OS — unblock the install thread.
      self.os_update.confirm()
      return {"confirmed": True}
    raise SetupAuthError(f"method_not_allowed:{method}")

  # ---- op implementations --------------------------------------------------
  def _setup_info(self) -> dict[str, Any]:
    cellular = self._cellular_status()
    net = self._network_status()
    voltage_ok = True
    try:
      v = self.hardware.get_voltage() if self.hardware else None
      if v is not None:
        voltage_ok = v > 8_000  # mV; matches setup low-voltage threshold spirit
    except Exception:
      pass
    hw = "mici" if self._is_mici() else "tici"
    return {
      "serial": self.serial,
      "setupId": self._setup_id(),
      "hardware": hw,
      "version": self.version,
      "voltageOk": voltage_ok,
      "cellular": cellular,
      "wifiConnected": net["wifiConnected"],
      "internetReachable": net["internetReachable"],
    }

  def _is_mici(self) -> bool:
    try:
      return getattr(self.hardware, "__class__", type("x", (), {})).__name__.lower().startswith("mici") or \
             bool(getattr(self.hardware, "is_mici", lambda: False)())
    except Exception:
      return False

  def _scan_wifi(self) -> list[dict[str, Any]]:
    if self.wifi is None:
      return []
    try:
      self.wifi.set_active(True)
    except Exception:
      pass
    nets = []
    try:
      for n in self.wifi.get_networks():
        nets.append({
          "ssid": n.ssid,
          "strength": int(n.strength),
          "security": int(n.security_type),
          "connected": bool(n.is_connected),
          "saved": bool(n.is_saved),
        })
    except Exception:
      pass
    return nets

  def _connect_wifi(self, ssid: str, password: str) -> dict[str, Any]:
    if not ssid:
      return {"success": False, "error": "missing_ssid"}
    if self.wifi is None:
      return {"success": False, "error": "wifi_unavailable"}
    try:
      self.wifi.connect_to_network(ssid, password)
      return {"success": True}
    except Exception as e:
      return {"success": False, "error": str(e)}

  def _forget_wifi(self, ssid: str) -> dict[str, Any]:
    if self.wifi is None:
      return {"success": False, "error": "wifi_unavailable"}
    try:
      self.wifi.forget_connection(ssid)
      return {"success": True}
    except Exception as e:
      return {"success": False, "error": str(e)}

  def _cellular_status(self) -> dict[str, Any]:
    present = False
    active = False
    operator = None
    try:
      if self.hardware is not None and hasattr(self.hardware, "get_network_type"):
        from openpilot.system.hardware.tici.hardware import NetworkType
        nt = self.hardware.get_network_type()
        active = nt in (NetworkType.cell2G, NetworkType.cell3G, NetworkType.cell4G, NetworkType.cell5G)
        present = active
      if self.hardware is not None and hasattr(self.hardware, "get_sim_info"):
        sim = self.hardware.get_sim_info()
        present = present or bool(sim and sim.get("sim_id"))
        operator = (sim or {}).get("network_type")
    except Exception:
      pass
    return {"present": present, "active": active, "operator": operator}

  def _network_status(self) -> dict[str, Any]:
    wifi_connected = False
    ssid = None
    try:
      if self.wifi is not None:
        for n in self.wifi.get_networks():
          if n.is_connected:
            wifi_connected = True
            ssid = n.ssid
            break
    except Exception:
      pass
    cellular = self._cellular_status()
    internet = False
    try:
      urllib.request.urlopen(NETWORK_CHECK_URL, timeout=3)
      internet = True
    except Exception:
      internet = False
    return {
      "wifiConnected": wifi_connected,
      "ssid": ssid,
      "cellularActive": cellular["active"],
      "internetReachable": internet,
    }

  def _start_install(self, channel: str) -> dict[str, Any]:
    if channel not in IQPILOT_CHANNELS:
      return {"started": False, "error": "invalid_channel"}
    net = self._network_status()
    if not net["internetReachable"]:
      return {"started": False, "error": "no_internet"}
    try:
      self.set_install_progress("downloading", 0)
      self.on_start_install(IQPILOT_CHANNELS[channel])
      return {"started": True, "channel": channel}
    except Exception as e:
      self.set_install_progress("failed", 0, str(e))
      return {"started": False, "error": str(e)}

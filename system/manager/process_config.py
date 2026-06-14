import os
import operator
import platform
from pathlib import Path

from cereal import car, custom
from openpilot.common.params import Params
from openpilot.system.hardware import HARDWARE, PC, TICI
from openpilot.system.hardware.hw import Paths
from openpilot.system.manager.process import PythonProcess, NativeProcess, DaemonProcess

from openpilot.iqpilot.models.helpers import get_active_model_runner
from iqpilot.konn3kt.utils import hephaestus_ready

WEBCAM = os.getenv("USE_WEBCAM") is not None

def driverview(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started or params.get_bool("IsDriverViewEnabled")

def driver_monitoring(started: bool, params: Params, CP: car.CarParams) -> bool:
  if os.path.exists('/tmp/lite_hw'):
    return False
  return driverview(started, params, CP)

def notcar(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and CP.notCar

def iscar(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and not CP.notCar

def logging(started: bool, params: Params, CP: car.CarParams) -> bool:
  run = (not CP.notCar) or not params.get_bool("DisableLogging")
  return started and run and params.get_bool("DashcamEnabled")

def ublox_available() -> bool:
  if HARDWARE.get_device_type() == "tizi" or os.path.exists('/tmp/lite_hw'):
    return False

  quectel_override = Path(Paths.persist_root()) / "comma" / "use-quectel-gps"
  return os.path.exists('/dev/ttyHS0') and not quectel_override.exists()

def ublox(started: bool, params: Params, CP: car.CarParams) -> bool:
  use_ublox = ublox_available()
  if use_ublox != params.get_bool("UbloxAvailable"):
    params.put_bool("UbloxAvailable", use_ublox)
  return started and use_ublox

def joystick(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and params.get_bool("JoystickDebugMode")

def not_joystick(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and not params.get_bool("JoystickDebugMode")

def long_maneuver(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and params.get_bool("LongitudinalManeuverMode")

def not_long_maneuver(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and not params.get_bool("LongitudinalManeuverMode")

def lat_maneuver(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and params.get_bool("LateralManeuverMode")

def not_lat_maneuver(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and not params.get_bool("LateralManeuverMode")

def qcomgps(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and not ublox_available()

def always_run(started: bool, params: Params, CP: car.CarParams) -> bool:
  return True

def only_onroad(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started

def navd_onroad(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and params.get_bool("NavigationEnabled")

def navrenderd_onroad(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and params.get_bool("NavigationEnabled") and params.get_bool("OnScreenNavigation")

def iqmapd_needed(params: Params) -> bool:
  return (
    params.get_bool("RoadNameToggle")
    or params.get_bool("ShowSpeedLimits")
    or params.get_bool("SpeedLimitController")
    or params.get_bool("EnableSpeedLimitControl")
    or params.get_bool("EnableSpeedLimitPredicative")
    # mapd v2 curve-speed gating — reverted from merge 353be8b (re-add by hand with mapd v2):
    # or params.get_bool("MapCurveSpeedController")
    # or params.get_bool("VisionCurveSpeedController")
  )

def iqmapd_onroad(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and params.get_bool("NavigationEnabled") and iqmapd_needed(params)

def mapd_onroad(started: bool, params: Params, CP: car.CarParams) -> bool:
  return started and iqmapd_needed(params)

def only_offroad(started: bool, params: Params, CP: car.CarParams) -> bool:
  return not started

def livestream(started: bool, params: Params, CP: car.CarParams) -> bool:
  # Konn3kt Live View: hephaestusd sets IsLiveStreaming when a viewer connects, so the
  # manager brings up the stream encoder (and camerad/webrtcd when offroad) and tears them
  # down cleanly when the session ends — no subprocess management inside hephaestusd.
  return params.get_bool("IsLiveStreaming")

def is_snpe_model(started, params, CP: car.CarParams) -> bool:
  """Check if the active model runner is SNPE."""
  return bool(get_active_model_runner(params, not started) == custom.IQModelManager.Runner.snpe)

def is_tinygrad_model(started, params, CP: car.CarParams) -> bool:
  """Check if the active model runner is SNPE."""
  return bool(get_active_model_runner(params, not started) == custom.IQModelManager.Runner.tinygrad)

def is_stock_model(started, params, CP: car.CarParams) -> bool:
  """Check if the active model runner is stock."""
  return bool(get_active_model_runner(params, not started) == custom.IQModelManager.Runner.stock)

def hephaestus_ready_shim(started, params, CP: car.CarParams) -> bool:
  return hephaestus_ready(params)

def uploader_ready(started: bool, params: Params, CP: car.CarParams) -> bool:
  if not params.get_bool("OnroadUploads"):
    return only_offroad(started, params, CP)

  return always_run(started, params, CP)

def or_(*fns):
  return lambda *args: operator.or_(*(fn(*args) for fn in fns))

def and_(*fns):
  return lambda *args: operator.and_(*(fn(*args) for fn in fns))

procs = [
  NativeProcess("loggerd", "system/loggerd", ["./loggerd"], logging),
  NativeProcess("encoderd", "system/loggerd", ["./encoderd"], only_onroad),
  NativeProcess("stream_encoderd", "system/loggerd", ["./encoderd", "--stream"], or_(notcar, livestream)),
  PythonProcess("logmessaged", "system.logmessaged", always_run, restart_if_crash=True),

  NativeProcess("camerad", "system/camerad", ["./camerad"], or_(driverview, livestream), enabled=not WEBCAM),
  PythonProcess("webcamerad", "tools.webcam.camerad", driverview, enabled=WEBCAM),
  PythonProcess("proclogd", "system.proclogd", only_onroad, enabled=platform.system() != "Darwin"),
  PythonProcess("journald", "system.journald", only_onroad, platform.system() != "Darwin"),
  PythonProcess("micd", "system.micd", iscar),
  PythonProcess("timed", "system.timed", always_run, enabled=not PC),

  PythonProcess("modeld", "selfdrive.modeld.modeld", and_(only_onroad, is_stock_model)),
  PythonProcess("dmonitoringmodeld", "selfdrive.modeld.dmonitoringmodeld", driver_monitoring, enabled=(WEBCAM or not PC)),

  PythonProcess("sensord", "system.sensord.sensord", only_onroad, enabled=not PC),
  PythonProcess("ui", "selfdrive.ui.ui", always_run, restart_if_crash=True),
  PythonProcess("soundd", "selfdrive.ui.soundd", driverview),
  PythonProcess("locationd", "selfdrive.locationd.locationd", only_onroad),
  NativeProcess("_pandad", "selfdrive/pandad", ["./pandad"], always_run, enabled=False),
  PythonProcess("calibrationd", "selfdrive.locationd.calibrationd", only_onroad),
  PythonProcess("torqued", "selfdrive.locationd.torqued", only_onroad),
  PythonProcess("controlsd", "selfdrive.controls.controlsd", and_(not_joystick, iscar)),
  PythonProcess("joystickd", "tools.joystick.joystickd", or_(joystick, notcar)),
  PythonProcess("selfdrived", "selfdrive.selfdrived.selfdrived", only_onroad),
  PythonProcess("card", "selfdrive.car.card", only_onroad),
  PythonProcess("deleter", "system.loggerd.deleter", always_run),
  PythonProcess("dmonitoringd", "selfdrive.monitoring.dmonitoringd", driver_monitoring, enabled=(WEBCAM or not PC)),
  PythonProcess("qcomgpsd", "system.qcomgpsd.qcomgpsd", qcomgps, enabled=TICI),
  PythonProcess("pandad", "selfdrive.pandad.pandad", always_run),
  PythonProcess("paramsd", "selfdrive.locationd.paramsd", only_onroad),
  PythonProcess("lagd", "selfdrive.locationd.lagd", only_onroad),
  PythonProcess("ubloxd", "system.ubloxd.ubloxd", ublox, enabled=TICI),
  PythonProcess("pigeond", "system.ubloxd.pigeond", ublox, enabled=TICI),
  PythonProcess("plannerd", "selfdrive.controls.plannerd", not_long_maneuver),
  PythonProcess("maneuversd", "tools.longitudinal_maneuvers.maneuversd", long_maneuver),
  PythonProcess("lateral_maneuversd", "tools.lateral_maneuvers.lateral_maneuversd", lat_maneuver),
  PythonProcess("radard", "selfdrive.controls.radard", only_onroad),
  PythonProcess("hardwared", "system.hardware.hardwared", always_run, restart_if_crash=True),
  PythonProcess("tombstoned", "system.tombstoned", always_run, enabled=not PC),
  PythonProcess("updated", "system.updated.updated", only_offroad, enabled=not PC),
  PythonProcess("uploader", "system.loggerd.uploader", uploader_ready),
  PythonProcess("statsd", "system.statsd", always_run),
  PythonProcess("feedbackd", "selfdrive.ui.feedback.feedbackd", and_(only_onroad, not_lat_maneuver)),

  # debug procs
  NativeProcess("bridge", "cereal/messaging", ["./bridge"], notcar),
  PythonProcess("webrtcd", "system.webrtc.webrtcd", or_(iscar, livestream)),
  PythonProcess("webjoystick", "tools.bodyteleop.web", notcar),
]

# iqpilot
procs += [
  # Models
  PythonProcess("models_manager", "iqpilot.models.manager", only_offroad),
  NativeProcess("modeld_snpe", "iqpilot/modeld", ["./modeld"], and_(only_onroad, is_snpe_model)),
  NativeProcess("modeld_tinygrad", "iqpilot/modeld_v2", ["./modeld"], and_(only_onroad, is_tinygrad_model)),

  PythonProcess("backup_manager_k3", "iqpilot.konn3kt.backups.manager", and_(only_offroad, hephaestus_ready_shim)),
  PythonProcess("navd", "iqpilot.navd.navd", navd_onroad, restart_if_crash=True),
  PythonProcess("navrenderd", "iqpilot.navd.navrenderd", navrenderd_onroad, restart_if_crash=True),
  # mapd v2 reverted from merge 353be8b / mapd nuked — re-add these with the mapd schema:
  # PythonProcess("iqmapd", "iqpilot.navd.iqmapd", iqmapd_onroad, restart_if_crash=True),
  PythonProcess("nav_webserver", "iqpilot.navd.web_server", navd_onroad, restart_if_crash=True),

  # mapd  (nuked with merge 353be8b revert — re-add with the mapd v2 schema)
  # NativeProcess("mapd", "third_party/mapd_pfeiferj", ["./mapd"], mapd_onroad),
  # PythonProcess("mapd_manager", "iqpilot.mapd.mapd_manager", only_offroad),

  # locationd
  NativeProcess("locationd_llk", "iqpilot/selfdrive/locationd", ["./locationd"], only_onroad),
]

managed_processes = {p.name: p for p in procs}

# pytest attempts to execute shell scripts while collecting
collect_ignore_glob = [
  "iqdbc/safety/tests/misra/*.sh",
  "iqdbc/safety/tests/misra/cppcheck/",
]

# --- host test harness -------------------------------------------------------
# tesla/volkswagen carstate+carcontroller import the closed-source ALC / odometer
# runtime via import_verified_module(), which gates on a rootfs integrity manifest
# that only exists on-device. Off-device (host CI / dev), install minimal stubs so
# the whole car interface set is importable and test_car_interfaces can collect and
# run. On-device the manifest is present and these stubs are never installed, so the
# real verified modules are used.
import os as _os

if not _os.path.exists("/usr/libexec/iqpilot/runtime_integrity.json"):
  import sys as _sys
  import types as _types

  def _stub_module(name, attrs):
    mod = _types.ModuleType(name)
    for key, value in attrs.items():
      setattr(mod, key, value)
    _sys.modules[name] = mod

  _noop = lambda *args, **kwargs: None  # noqa: E731

  class _VehicleOdometerStoreStub:
    def __init__(self, *args, **kwargs):
      pass

    def record(self, km):
      return km

  _stub_module("iqpilot_private.konn3kt.iqlvbs.vehicle_state",
               {"VehicleOdometerStore": _VehicleOdometerStoreStub})
  _stub_module("iqpilot_private.konn3kt.iqlvbs.alc", {
    "angle_lateral_control_enabled": lambda *a, **k: False,
    "update_vw_alc": _noop,
    "append_private_apd": _noop,
    "update_mqb_carstate_alc_state": _noop,
    "update_mlb_carstate_alc_state": _noop,
    "update_pq_carstate_alc_state": _noop,
  })
  _stub_module("iqpilot_private.konn3kt.iqlvbs.iqlvbs_commander", {
    "update_turn_signals": _noop,
  })
  _stub_module("iqpilot_private.konn3kt.hephaestus.vw_pq_flasher", {})

  try:
    from openpilot.system.proprietary_runtime import _verified_import as _vi
    _real_import_verified_module = _vi.import_verified_module

    def _import_verified_module(bundle, module):
      return _sys.modules.get(module) or _real_import_verified_module(bundle, module)

    _vi.import_verified_module = _import_verified_module
  except Exception:
    pass
# --- end host test harness ---------------------------------------------------

_ABSTRACT_BASES = frozenset(("CarSafetyTest", "AolSafetyTestBase", "SafetyTest", "SafetyTestBase"))

def _method_from_base(cls, method_name):
  for klass in cls.__mro__:
    if method_name in klass.__dict__:
      return klass.__name__ in _ABSTRACT_BASES
  return True

_NEEDS_LKAS = frozenset((
  "test_enable_control_allowed_with_aol_button",
  "test_enable_control_allowed_with_aol_button_and_disable_with_main_cruise",
  "test_engage_with_brake_pressed_0_aol_button",
))
_NEEDS_ACC_STATE = frozenset((
  "test_enable_control_allowed_with_manual_acc_main_on_state",
  "test_enable_control_allowed_with_aol_button_and_disable_with_main_cruise",
  "test_engage_with_brake_pressed_1_acc_main_on",
))

def pytest_collection_modifyitems(items):
  keep = []
  for item in items:
    cls = item.cls
    if cls is None:
      keep.append(item)
      continue
    if cls.__name__.endswith("Base"):
      continue
    if "regen" in item.name and _method_from_base(cls, "_user_regen_msg"):
      continue
    if item.name in _NEEDS_LKAS and _method_from_base(cls, "_lkas_button_msg"):
      continue
    if item.name in _NEEDS_ACC_STATE and _method_from_base(cls, "_acc_state_msg"):
      continue
    keep.append(item)
  items[:] = keep

# pytest attempts to execute shell scripts while collecting
collect_ignore_glob = [
  "iqdbc/safety/tests/misra/*.sh",
  "iqdbc/safety/tests/misra/cppcheck/",
]

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

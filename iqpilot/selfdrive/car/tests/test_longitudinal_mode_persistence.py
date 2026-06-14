from cereal import custom
from opendbc.car import structs

from openpilot.iqpilot.selfdrive.car.interfaces import _cleanup_unsupported_params


class DummyParams:
  def __init__(self):
    self.removed: list[str] = []
    self.values: dict[str, object] = {}

  def remove(self, key: str) -> None:
    self.removed.append(key)

  def get_bool(self, key: str) -> bool:
    return bool(self.values.get(key, False))

  def get(self, key: str, return_default: bool = False):
    return self.values.get(key)

  def put(self, key: str, value) -> None:
    self.values[key] = value


class TestLongitudinalModePersistence:
  def test_iq_dynamic_mode_is_not_removed_when_openpilot_long_is_unavailable(self):
    params = DummyParams()
    cp = structs.CarParams()
    cp.openpilotLongitudinalControl = False
    cp.steerControlType = structs.CarParams.SteerControlType.torque

    cp_iq = custom.IQCarParams()
    cp_iq.pcmCruiseSpeed = True

    _cleanup_unsupported_params(cp, cp_iq, params)

    assert "IQDynamicMode" not in params.removed
    assert "CustomAccIncrementsEnabled" in params.removed

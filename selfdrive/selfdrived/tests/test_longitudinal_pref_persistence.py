from cereal import car

from openpilot.selfdrive.selfdrived.selfdrived import _cleanup_startup_params


class DummyParams:
  def __init__(self):
    self.removed: list[str] = []

  def remove(self, key: str) -> None:
    self.removed.append(key)


class TestLongitudinalPrefPersistence:
  def test_startup_cleanup_preserves_persistent_longitudinal_preferences(self):
    params = DummyParams()
    cp = car.CarParams()
    cp.alphaLongitudinalAvailable = False
    cp.openpilotLongitudinalControl = False

    _cleanup_startup_params(cp, params)

    assert params.removed == []

from cereal import car

from openpilot.selfdrive.selfdrived.selfdrived import _cleanup_startup_params, get_sanitize_int_param


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

  def test_invalid_personality_is_clamped_before_use(self):
    class ParamsWithInvalidPersonality:
      def __init__(self):
        self.value = 3

      def get(self, key: str, return_default: bool = False) -> int:
        assert key == "LongitudinalPersonality"
        return self.value

      def put(self, key: str, value: int) -> None:
        assert key == "LongitudinalPersonality"
        self.value = value

    params = ParamsWithInvalidPersonality()
    assert get_sanitize_int_param("LongitudinalPersonality", 0, 2, params) == 2
    assert params.value == 2

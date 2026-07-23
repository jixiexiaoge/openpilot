import pytest

from openpilot.selfdrive.controls.lib.drive_helpers import DEFAULT_STOPPING_SPEED, should_stop


class TestShouldStop:
  @pytest.mark.parametrize("v_ego, expected", [
    (DEFAULT_STOPPING_SPEED - 0.01, True),
    (DEFAULT_STOPPING_SPEED, False),
  ])
  def test_upstream_default(self, v_ego, expected):
    assert should_stop(v_ego, -0.1) == expected

  @pytest.mark.parametrize("stopping_speed", [0.55 / 3.6, 1.5 / 3.6])
  def test_car_override(self, stopping_speed):
    assert should_stop(stopping_speed - 0.01, -0.1, stopping_speed)
    assert not should_stop(stopping_speed, -0.1, stopping_speed)

  def test_requires_deceleration(self):
    assert not should_stop(0.0, 0.1, 1.0)

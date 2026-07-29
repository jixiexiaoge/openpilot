import pytest

from iqdbc.car.volkswagen.interface import CarInterface
from iqdbc.car.volkswagen.values import (
  CAR, PASSAT_B7_STOP_ACCEL, PASSAT_B7_STOPPING_SPEED, PQ_STOPPING_SPEED,
  VolkswagenFlags, apply_pq_stopping_accel, get_longitudinal_stopping_speed_override,
)


@pytest.mark.parametrize("candidate, flags, expected", [
  (CAR.VOLKSWAGEN_PASSAT_B7, VolkswagenFlags.PQ, PASSAT_B7_STOPPING_SPEED),
  (CAR.VOLKSWAGEN_JETTA_MK6, VolkswagenFlags.PQ, PQ_STOPPING_SPEED),
  (CAR.VOLKSWAGEN_GOLF_MK7, 0, 0.0),
  (CAR.VOLKSWAGEN_ID4_MK1, VolkswagenFlags.MEB, 0.0),
])
def test_stopping_speed_override(candidate, flags, expected):
  assert get_longitudinal_stopping_speed_override(candidate, flags) == expected


def test_passat_b7_stop_accel_is_exact():
  assert apply_pq_stopping_accel(CAR.VOLKSWAGEN_PASSAT_B7, -0.2, True) == PASSAT_B7_STOP_ACCEL == -0.55
  assert apply_pq_stopping_accel(CAR.VOLKSWAGEN_PASSAT_B7, -0.2, False) == -0.2
  assert apply_pq_stopping_accel(CAR.VOLKSWAGEN_JETTA_MK6, -0.2, True) == -0.2


@pytest.mark.parametrize("candidate", [
  CAR.VOLKSWAGEN_JETTA_MK6,
  CAR.VOLKSWAGEN_PASSAT_NMS,
])
def test_pq_longitudinal_feedforward_uses_active_schema_field(candidate):
  fingerprint = {bus: {} for bus in range(8)}
  cp = CarInterface.get_params(candidate, fingerprint, [], alpha_long=True, is_release=False, docs=False)
  assert cp.longitudinalTuning.kf == pytest.approx(1.2)

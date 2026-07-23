import pytest

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

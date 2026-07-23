"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from types import SimpleNamespace

import numpy as np

from openpilot.iqpilot.selfdrive.constructiond import (
  ANALYSIS_PERIOD,
  ENTER_HITS,
  HIT_FRAC,
  HOLD_SEC,
  LUMA_MIN,
  WASH_FRAC,
  ConstructionZoneDetector,
  State,
  orange_fraction,
)

# barrel orange / yellow paint chroma as measured on-device (see module docstring)
BARREL_U, BARREL_V = 88, 178
PAINT_U, PAINT_V = 84, 159


def _nv12_buf(width=1928, height=1208, patches=()):
  stride = width
  uv_offset = stride * height
  data = np.full(uv_offset + stride * (height // 2), 128, dtype=np.uint8)
  data[:uv_offset] = 120  # mid luma
  uv = data[uv_offset:].reshape(height // 2, stride)
  for r0, r1, c0, c1, u, v in patches:
    uv[r0:r1, 2 * c0:2 * c1:2] = u
    uv[r0:r1, 2 * c0 + 1:2 * c1:2] = v
  return SimpleNamespace(data=data, width=width, height=height, stride=stride, uv_offset=uv_offset)


def test_orange_fraction_fires_on_barrel_chroma():
  ch, cw = 1208 // 2, 1928 // 2
  buf = _nv12_buf(patches=[(int(0.6 * ch), int(0.6 * ch) + 20, int(0.5 * cw), int(0.5 * cw) + 20, BARREL_U, BARREL_V)])
  assert orange_fraction(buf)[0] > HIT_FRAC


def test_orange_fraction_rejects_yellow_paint_chroma():
  ch, cw = 1208 // 2, 1928 // 2
  buf = _nv12_buf(patches=[(int(0.6 * ch), int(0.9 * ch), int(0.2 * cw), int(0.4 * cw), PAINT_U, PAINT_V)])
  assert orange_fraction(buf)[0] == 0.0


def test_orange_fraction_ignores_sky_region():
  buf = _nv12_buf(patches=[(0, 100, 100, 300, BARREL_U, BARREL_V)])
  assert orange_fraction(buf)[0] == 0.0


def test_detector_enters_after_persistent_hits_and_holds():
  det = ConstructionZoneDetector()
  t = 0.0
  assert not det.update(0.0, t)
  for _ in range(ENTER_HITS - 1):
    t += ANALYSIS_PERIOD
    assert not det.update(2 * HIT_FRAC, t)
  assert det.state == State.pending

  t += ANALYSIS_PERIOD
  assert det.update(2 * HIT_FRAC, t)
  assert det.state == State.active

  # barrel-free stretch inside the zone: stays active through the hold window
  t += HOLD_SEC - 1.0
  assert det.update(0.0, t)

  # past the hold: releases
  t += HOLD_SEC + 1.0
  assert not det.update(0.0, t)
  assert det.state == State.inactive


def test_detector_single_hit_does_not_enter():
  det = ConstructionZoneDetector()
  det.update(2 * HIT_FRAC, 0.0)
  for i in range(20):
    assert not det.update(0.0, 1.0 + i * ANALYSIS_PERIOD)


def test_detector_ignores_global_orange_wash():
  det = ConstructionZoneDetector()
  for i in range(10):
    assert not det.update(2 * WASH_FRAC, i * ANALYSIS_PERIOD)
  assert det.state == State.inactive


def test_orange_fraction_reports_roi_luma():
  buf = _nv12_buf()
  frac, luma = orange_fraction(buf)
  assert abs(luma - 120.0) < 1.0  # _nv12_buf fills Y with 120


def test_detector_night_luma_gates_hits():
  det = ConstructionZoneDetector()
  # night: retroreflective amber markers pass the chroma test but must not enter
  for i in range(20):
    assert not det.update(2 * HIT_FRAC, i * ANALYSIS_PERIOD, luma=LUMA_MIN - 30.0)
  assert det.state == State.inactive
  # same signal in daylight enters
  for i in range(ENTER_HITS):
    det.update(2 * HIT_FRAC, 100.0 + i * ANALYSIS_PERIOD, luma=LUMA_MIN + 30.0)
  assert det.state == State.active


def test_detector_low_speed_gates_entry_but_not_hold():
  from openpilot.iqpilot.selfdrive.constructiond import MIN_ENTER_SPEED
  det = ConstructionZoneDetector()
  # parked/lot speeds: orange never enters
  for i in range(20):
    assert not det.update(2 * HIT_FRAC, i * ANALYSIS_PERIOD, luma=120.0, v_ego=3.0)
  assert det.state == State.inactive
  # at speed: enters
  t = 100.0
  for i in range(ENTER_HITS):
    det.update(2 * HIT_FRAC, t + i * ANALYSIS_PERIOD, luma=120.0, v_ego=MIN_ENTER_SPEED + 5.0)
  assert det.state == State.active
  # slowing inside the zone: still held
  assert det.update(0.0, t + 30.0, luma=120.0, v_ego=2.0)

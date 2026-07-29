#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/

constructiond: work-zone detector for Speed Limit Assist.

Samples the road camera at ~2 Hz and looks for work-zone orange (barrels, drums,
diamond signs) in the NV12 chroma plane. Sunlit yellow lane paint renders with
nearly identical hue to barrel orange on this camera, but its red chroma (V)
saturates below ~168 while retroreflective barrel orange reaches 170-190, so the
V floor is the load-bearing threshold — do not lower it without re-running the
paint/barrel separation sweep on real footage.
"""
from collections import deque

import time

import numpy as np

import cereal.messaging as messaging
from cereal import custom
from msgq.visionipc import VisionIpcClient, VisionStreamType
from openpilot.common.swaglog import cloudlog

State = custom.IQConstructionZone.State

ANALYSIS_PERIOD = 0.5

# fractions of the chroma plane; excludes sky and hood
ROI_TOP, ROI_BOTTOM = 0.40, 0.94
ROI_LEFT, ROI_RIGHT = 0.04, 0.96

V_MIN = 170     # paint tops out ~168 in every DAYLIGHT condition sampled
CB_MIN = 16
HUE_LO, HUE_HI = 0.65, 2.0  # (V-128)/(128-U): yellow paint ~0.4, barrel orange ~0.7-1.5, red ~3.0

# Daylight-only gate: retroreflective amber markers (guardrail chevrons, object
# markers) blaze past V_MIN under headlights at night — 137px on one chevron on
# real footage — and there is no night work-zone ground truth to tune against.
# Night ROI mean luma measured ~36-38, validated daytime footage 84-98.
LUMA_MIN = 65.0

# hits only accumulate at highway-approach speeds: brightly lit lots (truck
# stops) can pass the luma gate at night with orange signage, and the clamp is
# meaningless below it anyway. An already-active zone still holds while slowed.
MIN_ENTER_SPEED = 13.4  # m/s (~30 mph)

HIT_FRAC = 3.0e-4
WASH_FRAC = 0.10  # more orange than this is scene lighting (sunset), not objects
ENTER_HITS = 3
ENTER_WINDOW = 10  # analyses (~5 s)
HOLD_SEC = 120.0   # barrel-free stretches inside a zone last minutes; hold through them


def orange_fraction(buf) -> tuple[float, float]:
  """Returns (hot-orange fraction, mean luma) of the road ROI."""
  h, w, stride, uv_off = buf.height, buf.width, buf.stride, buf.uv_offset
  ch, cw = h // 2, w // 2
  uv = buf.data[uv_off:uv_off + ch * stride].reshape(ch, stride)

  r0, r1 = int(ROI_TOP * ch), int(ROI_BOTTOM * ch)
  c0, c1 = int(ROI_LEFT * cw), int(ROI_RIGHT * cw)
  step = 2 if cw > 700 else 1

  u = uv[r0:r1:step, 2 * c0:2 * c1:2 * step].astype(np.int16)
  v = uv[r0:r1:step, 2 * c0 + 1:2 * c1:2 * step].astype(np.int16)

  cb = 128 - u
  cr = v - 128
  mask = (v >= V_MIN) & (cb >= CB_MIN) & (cr >= HUE_LO * cb) & (cr <= HUE_HI * cb)

  y_plane = buf.data[:h * stride].reshape(h, stride)
  luma = float(y_plane[2 * r0:2 * r1:4, 2 * c0:2 * c1:8].mean())

  return float(mask.mean()), luma


class ConstructionZoneDetector:
  def __init__(self):
    self.recent = deque(maxlen=ENTER_WINDOW)
    self.last_hit_t: float | None = None
    self.active = False
    self.frac = 0.0

  @property
  def state(self):
    if self.active:
      return State.active
    if any(self.recent):
      return State.pending
    return State.inactive

  def seconds_since_hit(self, now: float) -> float:
    if self.last_hit_t is None:
      return -1.0
    return now - self.last_hit_t

  def update(self, frac: float, now: float, luma: float = 255.0, v_ego: float = 255.0) -> bool:
    self.frac = frac
    hit = (HIT_FRAC <= frac <= WASH_FRAC) and luma >= LUMA_MIN and v_ego >= MIN_ENTER_SPEED
    self.recent.append(hit)
    if hit:
      self.last_hit_t = now

    if self.active:
      if self.last_hit_t is None or (now - self.last_hit_t) > HOLD_SEC:
        self.active = False
        self.recent.clear()
    elif sum(self.recent) >= ENTER_HITS:
      self.active = True
    return self.active


def main():
  pm = messaging.PubMaster(["iqConstructionZone"])
  car_state_sock = messaging.sub_sock("carState", conflate=True)
  detector = ConstructionZoneDetector()
  v_ego = 0.0

  vipc = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_ROAD, True)
  while not vipc.connect(False):
    time.sleep(0.5)
  cloudlog.info("constructiond: connected to road camera stream")

  while True:
    t0 = time.monotonic()
    buf = vipc.recv(200)
    if buf is None:
      # no publish on camera stall: SLC sees us stale and releases the clamp
      continue

    cs = messaging.recv_one_or_none(car_state_sock)
    if cs is not None:
      v_ego = cs.carState.vEgo

    frac, luma = orange_fraction(buf)
    detector.update(frac, t0, luma, v_ego)

    msg = messaging.new_message("iqConstructionZone")
    msg.valid = True
    cz = msg.iqConstructionZone
    cz.state = detector.state
    cz.active = detector.active
    cz.orangeFraction = frac
    cz.secondsSinceHit = detector.seconds_since_hit(t0)
    pm.send("iqConstructionZone", msg)

    time.sleep(max(0.0, ANALYSIS_PERIOD - (time.monotonic() - t0)))


if __name__ == "__main__":
  main()

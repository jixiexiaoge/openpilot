#!/usr/bin/env python3
"""Closed-loop offline harness for the maneuver daemons.

Runs maneuversd / lateral_maneuversd as real subprocesses over msgq, drives them with a
synthetic vehicle, and records every message to an rlog that generate_report.py can read.
Used to validate the maneuver tooling without a car.
"""
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

import numpy as np
import zstandard as zstd

from cereal import car, messaging
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL, Ratekeeper
from openpilot.common.basedir import BASEDIR

PUB_100HZ = ('carState', 'carControl', 'carOutput', 'controlsState', 'selfdriveState')
PUB_20HZ = ('modelV2', 'livePose', 'liveParameters')
SUB = ('alertDebug', 'longitudinalPlan', 'lateralManeuverPlan')

STEER_RATIO = 15.0
WHEELBASE = 2.78


class LongPlan(NamedTuple):
  aTarget: float
  shouldStop: bool


class LatPlan(NamedTuple):
  desiredCurvature: float


class Plant:
  """Vehicle model. Subclasses consume the daemon's plan and fill the published messages."""

  sim = None
  PLAN = 'longitudinalPlan'

  def __init__(self, v_ego: float = 0.0):
    self.v_ego = v_ego
    self.a_ego = 0.0
    self.curvature = 0.0           # commanded, controlsState.desiredCurvature
    self.achieved_curvature = 0.0  # measured, controlsState.curvature
    self.lat_accel = 0.0
    self.long_active = True
    self.lat_active = True

  def step(self, dt: float, plan) -> None:
    raise NotImplementedError

  def _angle(self, curvature: float) -> float:
    return math.degrees(curvature * WHEELBASE * STEER_RATIO)

  def _torque(self, curvature: float) -> float:
    return float(np.clip(curvature * max(self.v_ego, 1.0) ** 2 / 3.0, -1.0, 1.0))

  def fill_car_state(self, cs) -> None:
    cs.vEgo = float(self.v_ego)
    cs.vEgoRaw = float(self.v_ego)
    cs.vEgoCluster = float(self.v_ego)
    cs.aEgo = float(self.a_ego)
    cs.standstill = self.v_ego < 0.01
    cs.steeringAngleDeg = self._angle(self.achieved_curvature)
    cs.cruiseState.enabled = True
    cs.cruiseState.available = True
    cs.cruiseState.speed = float(max(self.v_ego, 1.0))

  def fill_car_control(self, cc) -> None:
    cc.enabled = True
    cc.latActive = self.lat_active
    cc.longActive = self.long_active
    cc.orientationNED = [0.0, 0.0, 0.0]
    cc.actuators.curvature = float(self.curvature)
    cc.actuators.accel = float(self.a_ego)
    cc.actuators.steeringAngleDeg = self._angle(self.curvature)
    cc.actuators.torque = self._torque(self.curvature)


class ManeuverSim:
  def __init__(self, module: str, plant: Plant, fingerprint: str = "TOYOTA_SIENNA",
               max_maneuvers: int = 0, timeout: float = 600.0, verbose: bool = True):
    self.module = module
    self.plant = plant
    plant.sim = self
    self.fingerprint = fingerprint
    self.max_maneuvers = max_maneuvers
    self.timeout = timeout
    self.verbose = verbose

    self.events: list[bytes] = []
    self.alert1 = ''
    self.alert2 = ''
    self.seen_maneuvers: list[str] = []
    self.finished = False

  def _write_car_params(self):
    CP = car.CarParams.new_message()
    CP.carFingerprint = self.fingerprint
    CP.brand = "toyota"
    CP.openpilotLongitudinalControl = True
    CP.autoResumeSng = True
    CP.steerRatio = STEER_RATIO
    CP.wheelbase = WHEELBASE
    Params().put("CarParams", CP.to_bytes())
    return CP

  def _head_events(self, CP):
    init = messaging.new_message('initData')
    init.valid = True
    init.initData.gitCommit = "simulated"
    init.initData.gitBranch = "sim"
    init.initData.gitRemote = "iqpilot-sim"
    self.events.append(init.to_bytes())

    cpm = messaging.new_message('carParams')
    cpm.valid = True
    cpm.carParams = CP
    self.events.append(cpm.to_bytes())

  def _launch(self):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BASEDIR) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.Popen([sys.executable, "-c", f"from {self.module} import main; main()"],
                            cwd=str(BASEDIR), env=env, start_new_session=True)

  def _on_alert(self, ad):
    text1, text2 = ad.alertText1, ad.alertText2
    if (text1, text2) != (self.alert1, self.alert2):
      if self.verbose:
        print(f"  [{time.monotonic() - self.t_start:6.1f}s] {text1!r} | {text2!r}")
      if text2 and text2 not in self.seen_maneuvers:
        self.seen_maneuvers.append(text2)
      if text1 == 'Maneuvers Finished':
        self.finished = True
    self.alert1, self.alert2 = text1, text2

  def run(self, out: Path) -> Path:
    self._head_events(self._write_car_params())

    pm = messaging.PubMaster(list(PUB_100HZ) + list(PUB_20HZ))
    socks = {s: messaging.sub_sock(s, conflate=False, timeout=0) for s in SUB}

    proc = self._launch()
    self.t_start = time.monotonic()
    rk = Ratekeeper(int(1.0 / DT_CTRL), print_delay_threshold=None)

    plans: dict[str, object | None] = {'longitudinalPlan': None, 'lateralManeuverPlan': None}
    frame = 0
    try:
      while True:
        for s, sock in socks.items():
          while True:
            raw = sock.receive(non_blocking=True)
            if raw is None:
              break
            self.events.append(raw)
            evt = messaging.log_from_bytes(raw)
            if s == 'alertDebug':
              self._on_alert(evt.alertDebug)
            elif s == 'longitudinalPlan':
              plans[s] = LongPlan(evt.longitudinalPlan.aTarget, evt.longitudinalPlan.shouldStop)
            elif s == 'lateralManeuverPlan':
              plans[s] = LatPlan(evt.lateralManeuverPlan.desiredCurvature) if evt.valid else None

        self.plant.step(DT_CTRL, plans[self.plant.PLAN])

        for s in PUB_100HZ:
          raw = self._build(s).to_bytes()
          self.events.append(raw)
          pm.send(s, raw)

        if frame % 5 == 0:
          for s in PUB_20HZ:
            raw = self._build(s).to_bytes()
            self.events.append(raw)
            pm.send(s, raw)

        frame += 1
        if self.finished:
          break
        if self.max_maneuvers and len(self.seen_maneuvers) > self.max_maneuvers:
          break
        if time.monotonic() - self.t_start > self.timeout:
          print("  timed out")
          break
        rk.keep_time()
    finally:
      if proc.poll() is None:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
      for sock in socks.values():
        del sock

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(zstd.compress(b"".join(self.events), 10))
    return out

  def _build(self, s: str):
    msg = messaging.new_message(s)
    msg.valid = True
    if s == 'carState':
      self.plant.fill_car_state(msg.carState)
    elif s == 'carControl':
      self.plant.fill_car_control(msg.carControl)
    elif s == 'carOutput':
      msg.carOutput.actuatorsOutput.accel = float(self.plant.a_ego)
      msg.carOutput.actuatorsOutput.curvature = float(self.plant.curvature)
      msg.carOutput.actuatorsOutput.steeringAngleDeg = self.plant._angle(self.plant.achieved_curvature)
      msg.carOutput.actuatorsOutput.torque = self.plant._torque(self.plant.achieved_curvature)
    elif s == 'controlsState':
      msg.controlsState.curvature = float(self.plant.achieved_curvature)
      msg.controlsState.desiredCurvature = float(self.plant.curvature)
    elif s == 'selfdriveState':
      msg.selfdriveState.enabled = True
      msg.selfdriveState.active = True
      msg.selfdriveState.state = 'enabled'
    elif s == 'modelV2':
      msg.modelV2.frameId = 0
      msg.modelV2.action.desiredCurvature = 0.0
    elif s == 'livePose':
      msg.livePose.accelerationDevice.x = float(self.plant.a_ego)
      msg.livePose.accelerationDevice.y = float(self.plant.lat_accel)
      msg.livePose.velocityDevice.x = float(self.plant.v_ego)
      msg.livePose.inputsOK = True
      msg.livePose.posenetOK = True
      msg.livePose.sensorsOK = True
    elif s == 'liveParameters':
      msg.liveParameters.valid = True
      msg.liveParameters.roll = 0.0
      msg.liveParameters.steerRatio = STEER_RATIO
    return msg

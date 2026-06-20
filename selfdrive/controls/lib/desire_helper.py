from collections import deque

import numpy as np
from cereal import custom, log

from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.iqpilot.selfdrive.controls.lib.helpers.lane_change import AutoLaneChangeController, AutoLaneChangeMode
from openpilot.iqpilot.selfdrive.controls.lib.helpers.lane_turn import LaneTurnController

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection
TurnDirection = custom.IQModelDataV2.TurnDirection
NavManeuverPhase = custom.IQNavState.ManeuverPhase
NavDirection = custom.NavDirection
NavCommand = custom.IQNavState.Command

LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS
LANE_CHANGE_SPEED_MIN_KPH = LANE_CHANGE_SPEED_MIN * CV.MS_TO_KPH
LANE_CHANGE_TIME_MAX = 10.
BLINKER_NONE = 0
BLINKER_LEFT = 1
BLINKER_RIGHT = 2

DESIRES = {
  LaneChangeDirection.none: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.none,
    LaneChangeState.laneChangeFinishing: log.Desire.none,
  },
  LaneChangeDirection.left: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.laneChangeLeft,
    LaneChangeState.laneChangeFinishing: log.Desire.laneChangeLeft,
  },
  LaneChangeDirection.right: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.laneChangeRight,
    LaneChangeState.laneChangeFinishing: log.Desire.laneChangeRight,
  },
}

TURN_DESIRES = {
  TurnDirection.none: log.Desire.none,
  TurnDirection.turnLeft: log.Desire.turnLeft,
  TurnDirection.turnRight: log.Desire.turnRight,
}

KEEP_DESIRES = {
  TurnDirection.none: log.Desire.none,
  TurnDirection.turnLeft: log.Desire.keepLeft,
  TurnDirection.turnRight: log.Desire.keepRight,
}

SIDE_CONFIRM_FRAMES = int(0.2 / DT_MDL)
BLINDSPOT_HOLD_FRAMES = int(2.0 / DT_MDL)
MODEL_TURN_SPEED_DEFAULT_KPH = 200.0
LANE_AVAILABLE_MIN_WIDTH = 2.5
LANE_AVAILABLE_MAX_WIDTH = 5.5
MIN_LANE_INFO_FOR_CHANGE = 20
IQP_NAV_INFLUENCE_ENABLED = False


def _safe_param_get_int(params: Params, key: str, default: int = 0) -> int:
  try:
    value = params.get(key, return_default=True)
    return default if value is None else int(value)
  except Exception:
    return default


def _safe_param_get_float(params: Params, key: str, default: float = 0.0) -> float:
  try:
    value = params.get(key, return_default=True)
    return default if value is None else float(value)
  except Exception:
    return default


class IQNavSideState:
  def __init__(self, side: str):
    self.side = side
    self.reset()

  def reset(self) -> None:
    self.lane_width = 0.0
    self.lane_width_diff = 0.0
    self.edge_distance = 0.0
    self.edge_distance_far = 0.0
    self.current_lane_prob = 1.0
    self.current_lane_missing = False
    self.lane_available_count = 0
    self.edge_available_count = 0
    self.lane_available = False
    self.edge_available = False
    self.lane_change_available_geom = False
    self.lane_change_available = False
    self.lane_available_trigger = False
    self.lane_appeared = False
    self.side_object_detected = False
    self.object_detected_count = 0
    self.blindspot_hold_counter = 0
    self.bsd_detected_now = False
    self.lane_line_info_raw = 0
    self.lane_line_info_mod = 0
    self.last_lane_line_mod = 0
    self.lane_line_info_edge_detect = False
    self.last_lane_available = False
    self.last_edge_available = False
    self._lane_width_queue: deque[float] = deque(maxlen=int(1.0 / DT_MDL))
    self._lane_width_sum = 0.0

  @staticmethod
  def _safe_y(line, index: int) -> float | None:
    if line is None or not hasattr(line, "y") or len(line.y) <= index:
      return None
    return float(line.y[index])

  def update_lane_geometry(self, modeldata) -> None:
    if modeldata is None or not hasattr(modeldata, "laneLines") or len(modeldata.laneLines) < 4 or not hasattr(modeldata, "roadEdges") or len(modeldata.roadEdges) < 2:
      self.reset()
      return

    if self.side == "left":
      outer_idx, current_idx, edge_idx = 0, 1, 0
    else:
      outer_idx, current_idx, edge_idx = 3, 2, 1

    outer_line = modeldata.laneLines[outer_idx]
    current_line = modeldata.laneLines[current_idx]
    road_edge = modeldata.roadEdges[edge_idx]
    lane_probs = getattr(modeldata, "laneLineProbs", [])
    outer_prob = float(lane_probs[outer_idx]) if len(lane_probs) > outer_idx else 0.0
    current_prob = float(lane_probs[current_idx]) if len(lane_probs) > current_idx else 0.0

    far_idx = min(10, max(0, len(getattr(current_line, "y", [])) - 1))
    outer_y = self._safe_y(outer_line, 0)
    current_y = self._safe_y(current_line, 0)
    edge_y = self._safe_y(road_edge, 0)
    current_far_y = self._safe_y(current_line, far_idx)
    edge_far_y = self._safe_y(road_edge, far_idx)

    lane_width_now = abs(current_y - outer_y) if current_y is not None and outer_y is not None else 0.0
    edge_distance = abs(edge_y - current_y) if edge_y is not None and current_y is not None else 0.0
    edge_distance_far = abs(edge_far_y - current_far_y) if edge_far_y is not None and current_far_y is not None else edge_distance

    if len(self._lane_width_queue) == self._lane_width_queue.maxlen:
      self._lane_width_sum -= self._lane_width_queue.popleft()
    self._lane_width_queue.append(lane_width_now)
    self._lane_width_sum += lane_width_now
    self.lane_width = self._lane_width_sum / max(1, len(self._lane_width_queue))
    self.lane_width_diff = (self._lane_width_queue[-1] - self._lane_width_queue[0]) if len(self._lane_width_queue) >= 2 else 0.0

    self.edge_distance = edge_distance
    self.edge_distance_far = edge_distance_far
    self.current_lane_prob = current_prob
    self.current_lane_missing = current_prob < 0.3

    lane_valid = outer_prob > 0.5 and LANE_AVAILABLE_MIN_WIDTH < self.lane_width < LANE_AVAILABLE_MAX_WIDTH
    edge_valid = edge_distance > LANE_AVAILABLE_MIN_WIDTH and edge_distance_far > LANE_AVAILABLE_MIN_WIDTH

    self.lane_available_count = min(SIDE_CONFIRM_FRAMES * 2, self.lane_available_count + 1) if lane_valid else max(0, self.lane_available_count - 1)
    self.edge_available_count = min(SIDE_CONFIRM_FRAMES * 2, self.edge_available_count + 1) if edge_valid else max(0, self.edge_available_count - 1)

    self.lane_available = self.lane_available_count >= SIDE_CONFIRM_FRAMES
    self.edge_available = self.edge_available_count >= SIDE_CONFIRM_FRAMES
    self.update_lane_line_info()

  def update_lane_line_info(self) -> None:
    edge_transition = self.edge_available and not self.last_edge_available
    lane_opening = self.lane_width_diff > 0.8 and self.lane_width < self.edge_distance
    self.lane_line_info_edge_detect = edge_transition or lane_opening or (self.current_lane_missing and self.edge_distance_far > 4.0)
    lane_line_info_raw = 10 if (self.lane_available or self.edge_available or self.lane_line_info_edge_detect) else 30
    self.lane_line_info_raw = lane_line_info_raw
    mod = lane_line_info_raw % 10
    self.lane_line_info_mod = mod
    self.last_lane_line_mod = mod

  def update_obstacles(self, v_ego: float, radar_obj, blindspot_detected: bool, ignore_bsd: bool, bsd_hold_sec: float = 2.0) -> None:
    side_object_dist = 255.0
    if radar_obj is not None and bool(getattr(radar_obj, "status", False)):
      d_rel = float(getattr(radar_obj, "dRel", 255.0))
      v_lead = float(getattr(radar_obj, "vLead", 0.0))
      side_object_dist = d_rel + v_lead * 4.0

    object_detected = side_object_dist < (v_ego * 3.0)
    if object_detected:
      self.object_detected_count = max(1, self.object_detected_count + 1)
    else:
      self.object_detected_count = min(-1, self.object_detected_count - 1)
    self.side_object_detected = self.object_detected_count > int(-0.3 / DT_MDL)

    self.bsd_detected_now = bool(blindspot_detected)
    if self.bsd_detected_now and not ignore_bsd:
      self.blindspot_hold_counter = int(bsd_hold_sec / DT_MDL)
    else:
      self.blindspot_hold_counter = max(0, self.blindspot_hold_counter - 1)

  def compute_lane_change_available(self, ignore_bsd: bool) -> None:
    lane_line_info_ok = self.lane_line_info_raw < MIN_LANE_INFO_FOR_CHANGE
    self.lane_change_available_geom = (self.lane_available or self.edge_available or self.lane_line_info_edge_detect) and lane_line_info_ok
    bsd_active = (self.blindspot_hold_counter > 0) and (not ignore_bsd)
    self.lane_change_available = self.lane_change_available_geom and (not self.side_object_detected) and (not bsd_active)

  def update_triggers(self) -> None:
    self.lane_available_trigger = self.lane_width_diff > 0.8 and self.lane_width < self.edge_distance
    appeared_now = self.lane_available_count >= SIDE_CONFIRM_FRAMES
    self.lane_appeared = (self.lane_appeared or appeared_now) and (self.edge_distance < 4.0)

  def commit_last(self) -> None:
    self.last_lane_available = self.lane_available
    self.last_edge_available = self.edge_available


def classify_iq_maneuver_type(blinker_state: int, carstate, side: IQNavSideState | None, turn_desire_state: bool,
                              nav_phase: int, model_turn_speed_kph: float, old_type: str) -> str:
  if blinker_state == BLINKER_NONE:
    return "none"
  if nav_phase in (NavManeuverPhase.turnPrepare, NavManeuverPhase.turnActive):
    return "turn"
  if nav_phase in (NavManeuverPhase.highwayPrepare, NavManeuverPhase.highwayCommit):
    return "lane_change"
  if side is None:
    return old_type

  v_kph = float(getattr(carstate, "vEgo", 0.0)) * CV.MS_TO_KPH
  # Hard limit: above 20 mph always triggers lane change, never a desire
  if v_kph >= LANE_CHANGE_SPEED_MIN_KPH:
    return "lane_change"
  accel = float(getattr(carstate, "aEgo", 0.0))
  score_turn = 0
  if v_kph < 30.0:
    score_turn += 1
  elif v_kph < 40.0 and accel < -1.0:
    score_turn += 1
  if v_kph < 40.0 and (not side.lane_available) and (not side.edge_available):
    score_turn += 1
  if v_kph < 40.0 and side.lane_available_count < int(0.5 / DT_MDL):
    score_turn += 1
  if turn_desire_state:
    score_turn += 1
  if model_turn_speed_kph < max(20.0, v_kph + 3.0):
    score_turn += 1
  if side.edge_distance_far > 4.0 and score_turn >= 2:
    return "turn"
  return "lane_change"


class DesireHelper:
  def __init__(self):
    self.params = Params()
    self.frame = 0

    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.lane_change_ll_prob = 1.0
    self.keep_pulse_timer = 0.0
    self.prev_one_blinker = False
    self.prev_desire_enabled = False
    self.desire = log.Desire.none
    self.desire_disable_count = 0
    self.lane_change_delay = 0.0
    self.maneuver_type = "none"
    self.turn_direction = TurnDirection.none
    self.enable_turn_desires = True
    self.turn_desire_state = False
    self.turn_disable_count = 0
    self.model_turn_speed = MODEL_TURN_SPEED_DEFAULT_KPH

    self.alc = AutoLaneChangeController(self)
    self.lane_turn_controller = LaneTurnController(self)
    self.lane_turn_direction = TurnDirection.none
    self.nav_turn_direction = TurnDirection.none
    self.nav_keep_direction = TurnDirection.none
    self.nav_virtual_blinker_direction = LaneChangeDirection.none
    self.nav_maneuver_phase = NavManeuverPhase.none
    self.nav_trigger_key = ""
    self.nav_trigger_changed = False

    self.left_side = IQNavSideState("left")
    self.right_side = IQNavSideState("right")
    self.lane_change_available_left = False
    self.lane_change_available_right = False

    self.blinker_ignore = False
    self.driver_blinker_state = BLINKER_NONE
    self.nav_blinker_state = BLINKER_NONE
    self.nav_lane_change_count = 0
    self.nav_command_index_last = -1
    self.nav_conflict_state = 0
    self.nav_atc_type = ""

    self.auto_lane_change_enable = False
    self.next_lane_change = False

    self.lane_change_need_torque = 0
    self.lane_change_bsd = 0
    self.lane_change_continuous = False
    self.model_turn_speed_factor = 0.0
    self.desire_log = ""

  def _update_params_periodic(self) -> None:
    if self.frame % 100 == 0:
      self.lane_change_need_torque = _safe_param_get_int(self.params, "LaneChangeNeedTorque", 0)
      self.lane_change_bsd = _safe_param_get_int(self.params, "LaneChangeBsd", 0)
      self.lane_change_delay = _safe_param_get_float(self.params, "LaneChangeDelay", 0.0) * 0.1
      self.lane_change_continuous = _safe_param_get_int(self.params, "LaneChangeContinuous", 0) > 0
      self.model_turn_speed_factor = _safe_param_get_float(self.params, "ModelTurnSpeedFactor", 0.0) * 0.1

  def _make_model_turn_speed(self, modeldata) -> None:
    velocity = getattr(modeldata, "velocity", None)
    if self.model_turn_speed_factor > 0.0 and velocity is not None and len(getattr(velocity, "t", [])) > 0 and len(getattr(velocity, "x", [])) > 0:
      try:
        model_turn_speed = np.interp(self.model_turn_speed_factor, velocity.t, velocity.x) * CV.MS_TO_KPH * 1.2
        self.model_turn_speed = self.model_turn_speed * 0.9 + float(model_turn_speed) * 0.1
        return
      except Exception:
        pass
    self.model_turn_speed = MODEL_TURN_SPEED_DEFAULT_KPH

  def _check_desire_state(self, modeldata, carstate) -> None:
    self.turn_desire_state = False
    desire_state = getattr(getattr(modeldata, "meta", None), "desireState", [])
    if len(desire_state) > max(int(log.Desire.turnLeft), int(log.Desire.turnRight)):
      self.turn_desire_state = (desire_state[log.Desire.turnLeft] + desire_state[log.Desire.turnRight]) > 0.1

    orientation_rate = getattr(getattr(modeldata, "orientationRate", None), "z", [])
    current_rate = abs(orientation_rate[5]) if len(orientation_rate) > 5 else 0.0
    future_rate = abs(orientation_rate[15]) if len(orientation_rate) > 15 else current_rate
    if self.maneuver_type == "turn" and abs(float(getattr(carstate, "steeringAngleDeg", 0.0))) > 80.0 and future_rate < current_rate:
      self.turn_disable_count = int(10.0 / DT_MDL)
    else:
      self.turn_disable_count = max(0, self.turn_disable_count - 1)

  def _update_driver_blinker(self, carstate):
    state = int(bool(getattr(carstate, "leftBlinker", False))) * BLINKER_LEFT + int(bool(getattr(carstate, "rightBlinker", False))) * BLINKER_RIGHT
    changed = state != self.driver_blinker_state
    self.driver_blinker_state = state
    enabled = state in (BLINKER_LEFT, BLINKER_RIGHT)
    if self.lane_change_need_torque < 0:
      enabled = False
    return state, changed, enabled

  def _nav_direction_to_blinker(self, direction: int) -> int:
    if direction == NavDirection.left:
      return BLINKER_LEFT
    if direction == NavDirection.right:
      return BLINKER_RIGHT
    return BLINKER_NONE

  def _update_nav_blinker(self, nav_state, driver_blinker_state: int):
    nav_blinker_state = BLINKER_NONE
    nav_desire_enabled = False
    atc_type = ""

    if not IQP_NAV_INFLUENCE_ENABLED:
      self.nav_conflict_state = 0
      self.nav_atc_type = ""
      self.nav_lane_change_count = 0
      return nav_blinker_state, nav_desire_enabled

    if nav_state is None or not getattr(nav_state, "active", False):
      self.nav_conflict_state = 0
      self.nav_atc_type = ""
      self.nav_lane_change_count = 0
      return nav_blinker_state, nav_desire_enabled

    command = getattr(nav_state, "command", NavCommand.none)
    command_direction = getattr(nav_state, "commandDirection", NavDirection.none)
    command_index = int(getattr(nav_state, "commandIndex", 0))
    phase = getattr(nav_state, "maneuverPhase", NavManeuverPhase.none)
    maneuver_direction = getattr(nav_state, "maneuverDirection", NavDirection.none)

    self.nav_lane_change_count = max(0, self.nav_lane_change_count - 1)

    if self.nav_lane_change_count > 0:
      nav_blinker_state = self.nav_blinker_state
      atc_type = f"iq highway {('left' if self.nav_blinker_state == BLINKER_LEFT else 'right')}"
    elif command == NavCommand.laneChange and command_index != self.nav_command_index_last and command_direction in (NavDirection.left, NavDirection.right):
      self.nav_command_index_last = command_index
      self.nav_lane_change_count = int(0.2 / DT_MDL)
      self.nav_blinker_state = self._nav_direction_to_blinker(command_direction)
      nav_blinker_state = self.nav_blinker_state
      atc_type = f"iq highway {('left' if command_direction == NavDirection.left else 'right')}"
    elif phase in (NavManeuverPhase.turnPrepare, NavManeuverPhase.turnActive) and maneuver_direction in (NavDirection.left, NavDirection.right):
      if self.nav_conflict_state != 2:
        nav_blinker_state = self._nav_direction_to_blinker(maneuver_direction)
        self.nav_conflict_state = 1
        self.blinker_ignore = False
      atc_type = f"iq turn {('left' if maneuver_direction == NavDirection.left else 'right')}"
    elif phase in (NavManeuverPhase.highwayPrepare, NavManeuverPhase.highwayCommit) and maneuver_direction in (NavDirection.left, NavDirection.right):
      if self.nav_conflict_state != 2:
        nav_blinker_state = self._nav_direction_to_blinker(maneuver_direction)
        self.nav_conflict_state = 1
      atc_type = f"iq highway {('left' if maneuver_direction == NavDirection.left else 'right')}"
    else:
      self.nav_conflict_state = 0

    if driver_blinker_state != BLINKER_NONE and nav_blinker_state != BLINKER_NONE and driver_blinker_state != nav_blinker_state:
      nav_blinker_state = BLINKER_NONE
      self.nav_conflict_state = 2

    nav_desire_enabled = nav_blinker_state in (BLINKER_LEFT, BLINKER_RIGHT)
    if driver_blinker_state == BLINKER_NONE:
      self.blinker_ignore = False
    if self.blinker_ignore:
      nav_blinker_state = BLINKER_NONE
      nav_desire_enabled = False

    if atc_type != self.nav_atc_type:
      nav_desire_enabled = False
    self.nav_atc_type = atc_type
    self.nav_blinker_state = nav_blinker_state
    return nav_blinker_state, nav_desire_enabled

  def _process_sides(self, carstate, modeldata, radar_state) -> None:
    ignore_bsd = self.lane_change_bsd < 0
    left_radar = getattr(radar_state, "leadLeft", None) if radar_state is not None else None
    right_radar = getattr(radar_state, "leadRight", None) if radar_state is not None else None

    self.left_side.update_lane_geometry(modeldata)
    self.right_side.update_lane_geometry(modeldata)
    self.left_side.update_obstacles(float(getattr(carstate, "vEgo", 0.0)), left_radar, bool(getattr(carstate, "leftBlindspot", False)), ignore_bsd)
    self.right_side.update_obstacles(float(getattr(carstate, "vEgo", 0.0)), right_radar, bool(getattr(carstate, "rightBlindspot", False)), ignore_bsd)
    self.left_side.compute_lane_change_available(ignore_bsd)
    self.right_side.compute_lane_change_available(ignore_bsd)
    self.left_side.update_triggers()
    self.right_side.update_triggers()
    self.lane_change_available_left = self.left_side.lane_change_available
    self.lane_change_available_right = self.right_side.lane_change_available

  def _get_selected_side(self, blinker_state: int):
    if blinker_state == BLINKER_LEFT:
      return self.left_side
    if blinker_state == BLINKER_RIGHT:
      return self.right_side
    return None

  def _should_process_sides(self, carstate, nav_state, driver_enabled: bool, nav_enabled: bool) -> bool:
    nav_guidance_active = False
    if IQP_NAV_INFLUENCE_ENABLED:
      nav_active = bool(nav_state is not None and getattr(nav_state, "active", False))
      nav_phase = getattr(nav_state, "maneuverPhase", NavManeuverPhase.none) if nav_active else NavManeuverPhase.none
      nav_command = getattr(nav_state, "command", NavCommand.none) if nav_active else NavCommand.none
      nav_guidance_active = nav_phase != NavManeuverPhase.none or \
        bool(getattr(nav_state, "shouldSendTurnDesire", False)) or \
        bool(getattr(nav_state, "shouldSendLanePositioning", False)) or \
        nav_command == NavCommand.laneChange

    return (
      driver_enabled or
      nav_enabled or
      bool(getattr(carstate, "leftBlinker", False)) or
      bool(getattr(carstate, "rightBlinker", False)) or
      self.lane_change_state != LaneChangeState.off or
      self.maneuver_type != "none" or
      self.nav_lane_change_count > 0 or
      self.auto_lane_change_enable or
      self.next_lane_change or
      nav_guidance_active
    )

  def _sync_nav_fields(self, nav_state) -> None:
    self.nav_turn_direction = TurnDirection.none
    self.nav_keep_direction = TurnDirection.none
    self.nav_virtual_blinker_direction = LaneChangeDirection.none
    self.nav_maneuver_phase = NavManeuverPhase.none
    self.nav_trigger_changed = False

    if not IQP_NAV_INFLUENCE_ENABLED:
      self.nav_trigger_key = ""
      return

    if nav_state is None or not getattr(nav_state, "active", False):
      self.nav_trigger_key = ""
      return

    self.nav_maneuver_phase = getattr(nav_state, "maneuverPhase", NavManeuverPhase.none)
    nav_direction = getattr(nav_state, "maneuverDirection", NavDirection.none)
    if nav_direction == NavDirection.left:
      self.nav_virtual_blinker_direction = LaneChangeDirection.left
    elif nav_direction == NavDirection.right:
      self.nav_virtual_blinker_direction = LaneChangeDirection.right

    if getattr(nav_state, "shouldSendTurnDesire", False):
      self.nav_turn_direction = getattr(nav_state, "turnDesireDirection", TurnDirection.none)
    if getattr(nav_state, "shouldSendLanePositioning", False):
      self.nav_keep_direction = getattr(nav_state, "lanePositioningDirection", TurnDirection.none)

    trigger_key = ""
    if self.nav_maneuver_phase == NavManeuverPhase.turnActive:
      trigger_key = f"turn:{nav_direction}"
    elif self.nav_maneuver_phase == NavManeuverPhase.highwayCommit:
      trigger_key = f"highway:{nav_direction}"

    if trigger_key:
      self.nav_trigger_changed = trigger_key != self.nav_trigger_key
      self.nav_trigger_key = trigger_key
    else:
      self.nav_trigger_key = ""

  @staticmethod
  def get_lane_change_direction(carstate, nav_virtual_direction=LaneChangeDirection.none):
    if getattr(carstate, "leftBlinker", False):
      return LaneChangeDirection.left
    if getattr(carstate, "rightBlinker", False):
      return LaneChangeDirection.right
    return nav_virtual_direction

  def update(self, carstate, lateral_active, lane_change_prob, nav_state=None, modeldata=None, radar_state=None):
    self.frame += 1
    self._update_params_periodic()
    self._make_model_turn_speed(modeldata)
    self.alc.update_params()
    self.lane_turn_controller.update_params()
    v_ego = float(getattr(carstate, "vEgo", 0.0))

    self._sync_nav_fields(nav_state)

    self.lane_turn_controller.update_lane_turn(
      blindspot_left=bool(getattr(carstate, "leftBlindspot", False)),
      blindspot_right=bool(getattr(carstate, "rightBlindspot", False)),
      left_blinker=bool(getattr(carstate, "leftBlinker", False)),
      right_blinker=bool(getattr(carstate, "rightBlinker", False)),
      v_ego=v_ego,
    )
    self.lane_turn_direction = self.lane_turn_controller.get_turn_direction()

    driver_state, _, driver_enabled = self._update_driver_blinker(carstate)
    nav_state_blinker, nav_enabled = self._update_nav_blinker(nav_state, driver_state)
    should_process_sides = self._should_process_sides(carstate, nav_state, driver_enabled, nav_enabled)
    if should_process_sides:
      self._process_sides(carstate, modeldata, radar_state)
    else:
      self.left_side.reset()
      self.right_side.reset()
      self.lane_change_available_left = False
      self.lane_change_available_right = False

    self._check_desire_state(modeldata, carstate)

    self.nav_lane_change_count = max(0, self.nav_lane_change_count)
    self.lane_change_delay = max(0.0, self.lane_change_delay - DT_MDL)

    below_lane_change_speed = v_ego < LANE_CHANGE_SPEED_MIN
    desire_enabled = driver_enabled or nav_enabled
    blinker_state = driver_state if driver_enabled else nav_state_blinker
    one_blinker = blinker_state in (BLINKER_LEFT, BLINKER_RIGHT)
    side = self._get_selected_side(blinker_state)

    self.maneuver_type = classify_iq_maneuver_type(
      blinker_state,
      carstate,
      side,
      self.turn_desire_state,
      self.nav_maneuver_phase,
      self.model_turn_speed,
      self.maneuver_type,
    ) if desire_enabled else "none"

    auto_lane_change_trigger = False
    if desire_enabled and side is not None:
      if self.nav_lane_change_count > 0:
        auto_lane_change_trigger = side.lane_change_available
      else:
        auto_lane_change_trigger = (
          self.auto_lane_change_enable and
          side.edge_available and
          (side.lane_available_trigger or side.lane_appeared or side.lane_line_info_edge_detect) and
          (not side.side_object_detected) and
          (side.blindspot_hold_counter == 0)
        )
      self.desire_log = (
        f"{side.side}:ALC={self.auto_lane_change_enable},"
        f"L={side.lane_available},E={side.edge_available},"
        f"T={side.lane_available_trigger},A={side.lane_appeared},"
        f"OBJ={side.side_object_detected},BSD={side.blindspot_hold_counter > 0}"
      )
    else:
      self.auto_lane_change_enable = False
      self.next_lane_change = False

    if not lateral_active or self.lane_change_timer > LANE_CHANGE_TIME_MAX or self.alc.lane_change_set_timer == AutoLaneChangeMode.OFF:
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.turn_direction = TurnDirection.none
      self.maneuver_type = "none"
    elif self.desire_disable_count > 0:
      self.desire_disable_count = max(0, self.desire_disable_count - 1)
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.turn_direction = TurnDirection.none
      self.maneuver_type = "none"
    else:
      if desire_enabled and self.maneuver_type == "turn" and self.enable_turn_desires:
        self.lane_change_state = LaneChangeState.off
        if self.turn_disable_count > 0:
          self.turn_direction = TurnDirection.none
          self.lane_change_direction = LaneChangeDirection.none
        else:
          self.turn_direction = TurnDirection.turnLeft if blinker_state == BLINKER_LEFT else TurnDirection.turnRight
          self.lane_change_direction = self.turn_direction
      else:
        self.turn_direction = TurnDirection.none

        if self.lane_change_state == LaneChangeState.off:
          if desire_enabled and not self.prev_desire_enabled and not below_lane_change_speed and side is not None:
            self.lane_change_state = LaneChangeState.preLaneChange
            self.lane_change_ll_prob = 1.0
            self.lane_change_direction = self.get_lane_change_direction(carstate, self.nav_virtual_blinker_direction)
            self.lane_change_delay = max(self.lane_change_delay, 0.0)
            self.auto_lane_change_enable = not side.lane_available
            self.next_lane_change = False

        elif self.lane_change_state == LaneChangeState.preLaneChange:
          self.lane_change_direction = self.get_lane_change_direction(carstate, self.nav_virtual_blinker_direction)
          side = self._get_selected_side(blinker_state)

          torque_cond = (
            getattr(carstate, "steeringTorque", 0.0) > 0 and blinker_state == BLINKER_LEFT or
            getattr(carstate, "steeringTorque", 0.0) < 0 and blinker_state == BLINKER_RIGHT
          )
          torque_applied = bool(getattr(carstate, "steeringPressed", False)) and torque_cond

          ignore_bsd = self.lane_change_bsd < 0
          block_lanechange_bsd = self.lane_change_bsd == 1
          bsd_active = side is not None and side.blindspot_hold_counter > 0 and (not ignore_bsd)

          if side is not None and ((not side.lane_available) or side.lane_available_count < int(2.0 / DT_MDL)):
            self.auto_lane_change_enable = True

          self.alc.update_lane_change(blindspot_detected=bsd_active, brake_pressed=bool(getattr(carstate, "brakePressed", False)))

          if driver_enabled and torque_applied and not below_lane_change_speed and (side is None or not side.lane_change_available_geom):
            self.lane_change_state = LaneChangeState.laneChangeStarting
          elif (driver_enabled and self.alc.auto_lane_change_allowed and not below_lane_change_speed
                and side is not None and not side.lane_change_available_geom
                and not bsd_active and not side.side_object_detected
                and self.lane_change_need_torque <= 0 and not self.next_lane_change):
            # Nudgeless/auto timer parity with the torque path above: when the model is not
            # confident about the adjacent lane geometry, the torque escape can still start a
            # lane change but the auto timer previously could not, so nudgeless silently degraded
            # to "nudge required". Allow the elapsed auto timer to start here too, still gated by
            # blindspot + side-object safety and the torque-required / consecutive-change settings.
            self.lane_change_state = LaneChangeState.laneChangeStarting
          elif not desire_enabled or below_lane_change_speed or side is None:
            self.lane_change_state = LaneChangeState.off
            self.lane_change_direction = LaneChangeDirection.none
          elif nav_enabled and self.nav_maneuver_phase == NavManeuverPhase.highwayCommit and side.lane_change_available:
            self.lane_change_state = LaneChangeState.laneChangeStarting
          else:
            start_gate = ((side.lane_change_available_geom and self.lane_change_delay == 0.0) or side.lane_line_info_edge_detect)
            if start_gate:
              if bsd_active:
                if torque_applied and not block_lanechange_bsd:
                  self.lane_change_state = LaneChangeState.laneChangeStarting
              elif self.lane_change_need_torque > 0 or self.next_lane_change:
                if torque_applied:
                  self.lane_change_state = LaneChangeState.laneChangeStarting
              elif torque_applied or auto_lane_change_trigger or side.lane_line_info_edge_detect or self.alc.auto_lane_change_allowed:
                if side.lane_change_available:
                  self.lane_change_state = LaneChangeState.laneChangeStarting

        elif self.lane_change_state == LaneChangeState.laneChangeStarting:
          self.lane_change_ll_prob = max(self.lane_change_ll_prob - 2 * DT_MDL, 0.0)
          if lane_change_prob < 0.02 and self.lane_change_ll_prob < 0.01:
            self.lane_change_state = LaneChangeState.laneChangeFinishing

        elif self.lane_change_state == LaneChangeState.laneChangeFinishing:
          self.lane_change_ll_prob = min(self.lane_change_ll_prob + DT_MDL, 1.0)
          if self.lane_change_ll_prob > 0.99:
            self.lane_change_direction = LaneChangeDirection.none
            # Driver-initiated changes are one-shot by default: return to normal lane keeping
            # and require a fresh blinker activation to change again, instead of staying armed in
            # preLaneChange while the blinker is still on (which reads as "still wants to change").
            # LaneChangeContinuous restores held-blinker chaining (still torque-gated via
            # next_lane_change). Nav multi-lane maneuvers always re-arm so they can chain.
            nav_chaining = nav_enabled and not driver_enabled
            driver_chaining = driver_enabled and self.lane_change_continuous
            if desire_enabled and (nav_chaining or driver_chaining):
              self.lane_change_state = LaneChangeState.preLaneChange
              self.next_lane_change = True
            else:
              self.lane_change_state = LaneChangeState.off

    if self.lane_change_state in (LaneChangeState.off, LaneChangeState.preLaneChange):
      self.lane_change_timer = 0.0
    else:
      self.lane_change_timer += DT_MDL

    steering_pressed_cancel = bool(getattr(carstate, "steeringPressed", False)) and (
      (getattr(carstate, "steeringTorque", 0.0) < 0 and blinker_state == BLINKER_LEFT) or
      (getattr(carstate, "steeringTorque", 0.0) > 0 and blinker_state == BLINKER_RIGHT)
    )
    if steering_pressed_cancel and self.lane_change_state != LaneChangeState.off:
      self.lane_change_direction = LaneChangeDirection.none
      self.lane_change_state = LaneChangeState.off
      self.blinker_ignore = True
      self.desire_disable_count = int(0.2 / DT_MDL)

    if self.turn_direction != TurnDirection.none:
      self.desire = TURN_DESIRES[self.turn_direction]
      self.lane_change_direction = self.turn_direction
    elif self.nav_maneuver_phase == NavManeuverPhase.turnActive and self.turn_disable_count == 0:
      self.desire = TURN_DESIRES.get(self.nav_turn_direction, log.Desire.none)
    elif self.lane_turn_direction != TurnDirection.none:
      self.desire = TURN_DESIRES[self.lane_turn_direction]
    else:
      self.desire = DESIRES[self.lane_change_direction][self.lane_change_state]

    if self.lane_change_state in (LaneChangeState.off, LaneChangeState.laneChangeStarting):
      self.keep_pulse_timer = 0.0
    elif self.lane_change_state == LaneChangeState.preLaneChange:
      self.keep_pulse_timer += DT_MDL
      if self.keep_pulse_timer > 1.0:
        self.keep_pulse_timer = 0.0
      elif self.desire in (log.Desire.keepLeft, log.Desire.keepRight):
        self.desire = log.Desire.none

    self.prev_one_blinker = one_blinker
    self.prev_desire_enabled = desire_enabled
    self.left_side.commit_last()
    self.right_side.commit_last()
    self.alc.update_state()

"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Consolidated IQ.Pilot onroad overlays. Every HUD widget that decorates the
driving view — the accel strip, blind-spot flags, speed readout, road-name
capsule, turn indicators, nav-provider badge and lead chevron labels — lives
here and paints through the shared canvas facade. Grouping them keeps one
import surface and one drawing vocabulary for the whole overlay layer.
"""
import math
import time

import numpy as np
import pyray as rl

from cereal import car, custom
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.onroad.hud_renderer import COLORS, FONT_SIZES, UI_CONFIG
from openpilot.selfdrive.ui.mici.onroad.alert_renderer import IconSide, TURN_SIGNAL_BLINK_PERIOD
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.iqpilot.lib import canvas
from iqdbc.car.volkswagen.values import VolkswagenFlags


# --- shared state access -----------------------------------------------------

def _feed():
  return ui_state.sm


def _speed_scale() -> float:
  return CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH


# ============================================================================
#  Accel strip
# ============================================================================
_STRIP_WIDTH = 28
_STRIP_CEILING = 0.85
_STRIP_EMA = 5.0
_STRIP_GO = canvas.shade(0, 245, 0, 200)
_STRIP_STOP = canvas.shade(245, 0, 0, 200)


class RocketFuel:
  def __init__(self):
    self._eased = 0.0

  def _reach(self) -> float:
    mag = abs(self._eased)
    return 0.0 if mag == 0.0 else max(0.0, _STRIP_CEILING - 0.1 / mag)

  def render(self, rect, sm) -> None:
    if not ui_state.rocket_fuel:
      return
    self._eased += (sm['carState'].aEgo - self._eased) / _STRIP_EMA
    reach = self._reach() * rect.height / 2.0
    if reach <= 0.0:
      return
    mid = rect.y + rect.height / 2.0
    top, tint = (mid - reach, _STRIP_GO) if self._eased > 0.0 else (mid, _STRIP_STOP)
    canvas.slab(rect.x, top, _STRIP_WIDTH, reach, tint)


# ============================================================================
#  Blind-spot flags
# ============================================================================
_BS_INSET = 20
_BS_DROP = 100
_BS_MIN = 0.01


class _BlindSide:
  def __init__(self, name: str):
    self.texture = gui_app.texture(f'icons_mici/onroad/blind_spot_{name}.png', 108, 128)
    self.glow = FirstOrderFilter(0, 0.15, 1 / gui_app.target_fps)
    self.on_left = name == "left"

  def feed(self, present: bool):
    self.glow.update(1.0 if present else 0.0)

  def lit(self) -> bool:
    return self.glow.x > _BS_MIN

  def place(self, rect):
    tex = self.texture
    x = rect.x + _BS_INSET if self.on_left else rect.x + rect.width - _BS_INSET - tex.width
    canvas.stamp(tex, x, rect.y + _BS_DROP, canvas.shade(255, 255, 255, int(255 * self.glow.x)))


class BlindSpotIndicators:
  def __init__(self):
    self._left = _BlindSide("left")
    self._right = _BlindSide("right")

  def update(self) -> None:
    cs = _feed()['carState']
    self._left.feed(cs.leftBlindspot)
    self._right.feed(cs.rightBlindspot)

  @property
  def detected(self) -> bool:
    return self._left.lit() or self._right.lit()

  def render(self, rect) -> None:
    if not ui_state.blindspot:
      return
    for side in (self._left, self._right):
      if side.lit():
        side.place(rect)


# ============================================================================
#  Speed readout
# ============================================================================
_MQB_CLUSTER_EXEMPT = (VolkswagenFlags.PQ | VolkswagenFlags.MLB | VolkswagenFlags.MEB |
                       VolkswagenFlags.MEB_GEN2 | VolkswagenFlags.MQB_EVO)


class SpeedRenderer:
  def __init__(self):
    self.speed: float = 0.0
    self._cluster_ever_live: bool = False
    self._heavy = gui_app.font(FontWeight.BOLD)
    self._mid = gui_app.font(FontWeight.MEDIUM)

  def _source_speed(self, cs) -> float:
    cp = ui_state.CP
    if cp is not None and cp.brand == "volkswagen" and not (cp.flags & _MQB_CLUSTER_EXEMPT):
      return cs.vEgoCluster
    self._cluster_ever_live = self._cluster_ever_live or cs.vEgoCluster != 0.0
    return cs.vEgoCluster if self._cluster_ever_live else cs.vEgo

  def update(self) -> None:
    self.speed = max(0.0, self._source_speed(_feed()['carState']) * _speed_scale())

  def _stack(self, face, text: str, size: int, rect, top: float, color) -> float:
    extent = canvas.span(face, text, size)
    canvas.glyphs(face, text, canvas.Pt(rect.x + (rect.width - extent.x) / 2, top), size, color)
    return extent.y

  def render(self, rect) -> None:
    top = rect.y + 52
    number_h = self._stack(self._heavy, str(round(self.speed)), FONT_SIZES.current_speed, rect, top, COLORS.WHITE)
    unit = tr("km/h") if ui_state.is_metric else tr("mph")
    self._stack(self._mid, unit, FONT_SIZES.speed_unit, rect, top + number_h - 10, COLORS.WHITE_TRANSLUCENT)


# ============================================================================
#  Road-name capsule
# ============================================================================
def clip_to_width(font, words: str, size: int, limit: float) -> str:
  if canvas.span(font, words, size).x <= limit:
    return words
  trimmed = words
  while len(trimmed) > 3 and canvas.span(font, trimmed + "...", size).x > limit:
    trimmed = trimmed[:-1]
  return trimmed + "..."


class RoadNameBanner(Widget):
  TYPE_SIZE = 46
  FLOOR_WIDTH = 200
  SIDE_PAD = 40
  MARGIN = 40
  DROP = -4
  BAR_H = 60
  CURVE = 0.2
  SEGS = 10
  BACKDROP_A = 120
  INK_A = 200
  INNER_PAD = 20

  def __init__(self):
    super().__init__()
    self.road_name = ""
    self._face = gui_app.font(FontWeight.SEMI_BOLD)

  def update(self):
    sm = _feed()
    if sm.recv_frame["carState"] < ui_state.started_frame:
      return
    if sm.updated["iqLiveData"]:
      self.road_name = sm["iqLiveData"].roadName

  def _render(self, rect):
    if not self.road_name or not ui_state.road_name_toggle:
      return
    natural = canvas.span(self._face, self.road_name, self.TYPE_SIZE).x
    bar_w = max(self.FLOOR_WIDTH, min(natural + self.SIDE_PAD, rect.width - self.MARGIN))
    bar = canvas.Box(rect.x + (rect.width - bar_w) / 2, rect.y + self.DROP, bar_w, self.BAR_H)
    canvas.panel(bar, self.CURVE, self.SEGS, canvas.shade(0, 0, 0, self.BACKDROP_A))
    label = clip_to_width(self._face, self.road_name, self.TYPE_SIZE, bar.width - self.INNER_PAD)
    extent = canvas.span(self._face, label, self.TYPE_SIZE)
    canvas.glyphs(self._face, label,
                  canvas.Pt(bar.x + (bar.width - extent.x) / 2, bar.y + (bar.height - extent.y) / 2),
                  self.TYPE_SIZE, canvas.shade(255, 255, 255, self.INK_A))


RoadNameRenderer = RoadNameBanner
ellipsize = clip_to_width


# ============================================================================
#  Turn indicators
# ============================================================================
from dataclasses import dataclass, field

_ARROW = 'signal'
_WARN = 'blind_spot'


@dataclass(frozen=True)
class TurnSignalConfig:
  left_x: int = 80
  left_y: int = 190
  right_x: int = 80
  right_y: int = 190
  size: int = 150


class _IndicatorLamp(Widget):
  def __init__(self, direction: IconSide):
    super().__init__()
    self.mode: str | None = None
    self._epoch = 0.0
    self._glow = FirstOrderFilter(0.0, 0.3, 1 / gui_app.target_fps)
    self._art = {
      _ARROW: gui_app.texture(f'icons_mici/onroad/turn_signal_{direction}.png', 120, 109),
      _WARN: gui_app.texture(f'icons_mici/onroad/blind_spot_{direction}.png', 120, 109),
    }

  def set_mode(self, mode: str | None):
    if mode != self.mode or mode is None:
      self._epoch = 0.0
    self.mode = mode

  def _pulse(self) -> int:
    # onroad/offroad run at different target_fps (set_target_fps only takes effect after this
    # widget is constructed at offroad startup), so re-derive dt each frame instead of trusting
    # the fps baked in at __init__ — otherwise the glow decays ~3x too slowly onroad and never
    # visibly dims before the next reset, reading as a static-on arrow instead of a blink.
    self._glow.dt = 1 / gui_app.target_fps
    self._glow.update_alpha(0.3)
    if time.monotonic() - self._epoch > TURN_SIGNAL_BLINK_PERIOD:
      self._epoch = time.monotonic()
      self._glow.x = 255 * 2
    else:
      self._glow.update(255 * 0.2)
    return int(min(self._glow.x, 255))

  def _render(self, _):
    if self.mode is None:
      return
    alpha = self._pulse() if self.mode == _ARROW else 255
    tex = self._art[self.mode]
    canvas.stamp(tex, self._rect.x + (self._rect.width - tex.width) / 2,
                 self._rect.y + (self._rect.height - tex.height) / 2, canvas.shade(255, 255, 255, alpha))


def _lamp_modes(event_name: str, cs, remembered):
  if event_name == 'preLaneChangeLeft':
    return _ARROW, None, IconSide.left
  if event_name == 'preLaneChangeRight':
    return None, _ARROW, IconSide.right
  if event_name == 'laneChange':
    if remembered == IconSide.left:
      return _ARROW, None, remembered
    if remembered == IconSide.right:
      return None, _ARROW, remembered
    return None, None, remembered
  if event_name == 'laneChangeBlocked':
    side = IconSide.left if cs.leftBlinker else IconSide.right if cs.rightBlinker else remembered
    if side == IconSide.left:
      return _WARN, None, remembered
    if side == IconSide.right:
      return None, _WARN, remembered
    return None, None, remembered
  left = _WARN if cs.leftBlindspot else _ARROW if cs.leftBlinker else None
  right = _WARN if cs.rightBlindspot else _ARROW if cs.rightBlinker else None
  return left, right, None


class TurnSignalController:
  def __init__(self, config: TurnSignalConfig | None = None):
    self._config = config or TurnSignalConfig()
    self._lamps = {IconSide.left: _IndicatorLamp(IconSide.left),
                   IconSide.right: _IndicatorLamp(IconSide.right)}
    self._remembered: IconSide | None = None

  def update(self):
    sm = _feed()
    alert = sm['selfdriveState'].alertType
    event_name = alert.split('/')[0] if alert else ''
    left, right, self._remembered = _lamp_modes(event_name, sm['carState'], self._remembered)
    self._lamps[IconSide.left].set_mode(left)
    self._lamps[IconSide.right].set_mode(right)

  def render(self, rect):
    if not ui_state.turn_signals:
      return
    c = self._config
    mid_x = rect.x + rect.width / 2
    spots = {
      IconSide.left: canvas.Box(mid_x - c.left_x - c.size, rect.y + c.left_y, c.size, c.size),
      IconSide.right: canvas.Box(mid_x + c.right_x, rect.y + c.right_y, c.size, c.size),
    }
    for side, lamp in self._lamps.items():
      if lamp.mode is not None:
        lamp.render(spots[side])

  @property
  def config(self) -> TurnSignalConfig:
    return self._config

  @config.setter
  def config(self, new_config: TurnSignalConfig):
    self._config = new_config


# ============================================================================
#  Nav-influence provider badge
# ============================================================================
_PROVIDER_TAGS = {0: "", 1: "NAV", 2: "MBX", 3: "VIS", 4: "OSM"}
_NAV_TEX_W, _NAV_TEX_H = 256, 128
_NAV_BADGE_W = 160
_NAV_FONT = 36
_NAV_SHIFT = -260


class NavInfluenceRenderer(Widget):
  def __init__(self):
    super().__init__()
    self.engaged = False
    self.valid = False
    self.provider = 0
    self.long_override = False
    self._streak = 0
    self.font = gui_app.font(FontWeight.BOLD)
    self._offscreen = rl.load_render_texture(_NAV_TEX_W, _NAV_TEX_H)

  def update(self):
    sm = _feed()
    if sm.updated["iqPlan"]:
      nav = sm["iqPlan"].iqNavState.nav
      self.engaged = nav.engaged
      self.valid = nav.valid
      self.provider = getattr(nav.provider, "raw", nav.provider)
    if sm.updated["carControl"]:
      self.long_override = sm["carControl"].cruiseControl.override
    self._streak = self._streak + 1 if (self.engaged and self.valid) else 0

  def _blinked_off(self) -> bool:
    fps = gui_app.target_fps
    return self.engaged and (self._streak % fps) < (fps / 2.5)

  def _bake(self, label: str):
    extent = canvas.span(self.font, label, _NAV_FONT)
    badge = canvas.Box((_NAV_TEX_W - _NAV_BADGE_W) // 2, (_NAV_TEX_H - extent.y - 10) // 2,
                       _NAV_BADGE_W, int(extent.y + 10))
    rl.begin_texture_mode(self._offscreen)
    rl.clear_background(canvas.CLEAR)
    canvas.panel(badge, 0.2, 10, COLORS.OVERRIDE if self.long_override else canvas.shade(0, 255, 0, 255))
    rl.rl_set_blend_factors(rl.RL_ZERO, rl.RL_ONE_MINUS_SRC_ALPHA, 0x8006)
    rl.rl_set_blend_mode(rl.BLEND_CUSTOM)
    canvas.glyphs(self.font, label,
                  canvas.Pt(badge.x + (badge.width - extent.x) / 2, badge.y + (badge.height - extent.y) / 2),
                  _NAV_FONT, canvas.WHITE)
    rl.rl_set_blend_mode(rl.BLEND_ALPHA)
    rl.end_texture_mode()

  def _render(self, rect):
    if not self.valid or self._blinked_off():
      return
    label = _PROVIDER_TAGS.get(int(self.provider), "NAV")
    if not label:
      return
    self._bake(label)
    ax = rect.x + rect.width / 2 + _NAV_SHIFT - _NAV_TEX_W / 2
    ay = (rect.height / 4 - 40) - _NAV_TEX_H / 2
    canvas.stamp_scaled(self._offscreen.texture, canvas.Box(0, 0, _NAV_TEX_W, -_NAV_TEX_H),
                        canvas.Box(ax, ay, _NAV_TEX_W, _NAV_TEX_H), canvas.Pt(0, 0), 0, canvas.WHITE)


# ============================================================================
#  Lead chevron labels
# ============================================================================
class ChevronOptions:
  OFF = 0
  DISTANCE_ONLY = 1
  SPEED_ONLY = 2
  TTC_ONLY = 3
  ALL = 4


_CH_FONT = 40
_CH_LINE = 50
_CH_MARGIN = 20
_CH_FADE_DOWN = 0.05
_CH_FADE_UP = 0.1
_CH_DEDUP = 3.0


def _gap_label(d_rel: float, _v_abs: float) -> str:
  val = max(0.0, d_rel)
  return f"{val:.0f} m" if ui_state.is_metric else f"{val * 3.28084:.0f} ft"


def _pace_label(_d_rel: float, v_abs: float) -> str:
  unit = "km/h" if ui_state.is_metric else "mph"
  return f"{max(0.0, v_abs * _speed_scale()):.0f} {unit}"


def _ttc_label(d_rel: float, _v_abs: float, v_ego: float) -> str:
  ttc = (d_rel / v_ego) if (d_rel > 0 and v_ego > 0) else 0.0
  return f"{ttc:.1f} s" if 0 < ttc < 200 else "---"


_CH_METRICS = (
  ((ChevronOptions.DISTANCE_ONLY, ChevronOptions.ALL), lambda d, va, ve: _gap_label(d, va)),
  ((ChevronOptions.SPEED_ONLY, ChevronOptions.ALL), lambda d, va, ve: _pace_label(d, va)),
  ((ChevronOptions.TTC_ONLY, ChevronOptions.ALL), _ttc_label),
)


class ChevronMetrics:
  def __init__(self):
    self._alpha: float = 0.0
    self._font = gui_app.font(FontWeight.SEMI_BOLD)

  def update_alpha(self, has_lead: bool):
    self._alpha = float(np.clip(self._alpha + (_CH_FADE_UP if has_lead else -_CH_FADE_DOWN), 0.0, 1.0))

  def should_render(self) -> bool:
    return ui_state.chevron_metrics != ChevronOptions.OFF and self._alpha > 0.0

  @staticmethod
  def _marker_size(d_rel: float) -> float:
    return float(np.clip((25 * 30) / (d_rel / 3 + 30), 15.0, 30.0)) * 2.35

  def _labels(self, d_rel: float, v_rel: float, v_ego: float) -> list[str]:
    mode = ui_state.chevron_metrics
    return [fn(d_rel, v_rel + v_ego, v_ego) for modes, fn in _CH_METRICS if mode in modes]

  def _top_y(self, anchor_y: float, size: float, n: int, rect) -> float:
    y = anchor_y + size + 15
    block = n * _CH_LINE
    floor = rect.y + rect.height - _CH_MARGIN
    if y + block > floor:
      y = max(rect.y + _CH_MARGIN, min(anchor_y, floor) - 15 - block)
    return y

  def _stack(self, lines, cx: float, top: float, rect):
    a = self._alpha
    fg = canvas.shade(255, 255, 255, int(255 * a))
    shadow = canvas.shade(0, 0, 0, int(200 * a))
    floor = rect.y + rect.height - _CH_MARGIN
    for i, line in enumerate(lines):
      y = int(top + i * _CH_LINE)
      if y + _CH_LINE > floor:
        break
      w = canvas.span(self._font, line, _CH_FONT).x
      x = int(np.clip(cx - w / 2, rect.x + _CH_MARGIN, rect.x + rect.width - w - _CH_MARGIN))
      canvas.glyphs(self._font, line, canvas.Pt(x + 2, y + 2), _CH_FONT, shadow)
      canvas.glyphs(self._font, line, canvas.Pt(x, y), _CH_FONT, fg)

  def _one_lead(self, lead, marker, v_ego: float, rect):
    if not self.should_render() or marker.center is None:
      return
    lines = self._labels(lead.dRel, lead.vRel, v_ego)
    if not lines:
      return
    self._stack(lines, marker.center[0], self._top_y(marker.center[1], self._marker_size(lead.dRel), len(lines), rect), rect)

  @staticmethod
  def _active_leads(radar_state, markers):
    """Yield (lead, marker) for tracked leads with a projected marker, dropping a
    second lead that sits within the dedup band of the first."""
    tracked = []
    for lead, marker in zip((radar_state.leadOne, radar_state.leadTwo), markers, strict=False):
      if lead and lead.status and marker.center is not None:
        tracked.append((lead, marker))
    if len(tracked) == 2 and abs(tracked[0][0].dRel - tracked[1][0].dRel) <= _CH_DEDUP:
      tracked.pop()
    return tracked

  def draw_lead_status(self, sm, radar_state, rect, lead_vehicles):
    present = [radar_state.leadOne, radar_state.leadTwo]
    self.update_alpha(any(bool(x) and x.status for x in present))
    if not self.should_render():
      return
    v_ego = sm['carState'].vEgo
    for lead, marker in self._active_leads(radar_state, lead_vehicles):
      self._one_lead(lead, marker, v_ego, rect)


# ============================================================================
#  Developer telemetry bar
# ============================================================================

_TEAL = canvas.shade(0x0C, 0x94, 0x96, 0xFF)
_AMBER = canvas.shade(255, 188, 0, 255)
_GREEN = canvas.shade(0, 255, 0, 255)
_GREY = canvas.shade(145, 155, 149, 255)
_G = 9.81
_BAR_FONT = 38
_ANGLE_TYPES = (car.CarParams.SteerControlType.angle, car.CarParams.SteerControlType.curvatureDEPRECATED)


@dataclass
class Readout:
  """One bar cell: 'TAG value unit', with each part pre-measured for layout."""
  tag: str
  value: str
  unit: str = ""
  color: object = field(default_factory=lambda: canvas.WHITE)
  tag_text: str = ""
  value_text: str = ""
  unit_text: str = ""
  tag_w: float = 0.0
  value_w: float = 0.0
  unit_w: float = 0.0
  span: float = 0.0

  def size_up(self, font, px: int):
    self.tag_text = f"{self.tag} "
    self.value_text = self.value
    self.unit_text = f" {self.unit}" if self.unit else ""
    self.tag_w = canvas.span(font, self.tag_text, px, 0).x
    self.value_w = canvas.span(font, self.value_text, px, 0).x
    self.unit_w = canvas.span(font, self.unit_text, px, 0).x if self.unit else 0
    self.span = self.tag_w + self.value_w + self.unit_w

  # kept for external callers that used the old field/method names
  @property
  def total_width(self):
    return self.span

  def measure(self, font, px):
    self.size_up(font, px)


UiElement = Readout


# --- grading -----------------------------------------------------------------

def _banded(magnitude, warn, crit, ok):
  if magnitude > crit:
    return canvas.RED
  return _AMBER if magnitude > warn else ok


def _closing(v_rel):
  return _banded(-v_rel if v_rel < 0 else 0.0, 0.0, 4.4704, canvas.WHITE)


def _following(d_rel):
  if d_rel < 5:
    return canvas.RED
  return _AMBER if d_rel < 15 else canvas.WHITE


def _steer_tint(sm):
  if not sm['carControl'].latActive:
    return canvas.WHITE
  return _GREY if sm['carState'].steeringPressed else _TEAL


def _angle_tint(sm, deg):
  floor = _steer_tint(sm) if sm['carControl'].latActive else canvas.WHITE
  return _banded(abs(deg), 90.0, 180.0, floor)


def _yaw_offset(sm):
  return sm['liveParameters'].angleOffsetAverageDeg if sm.valid['liveParameters'] else 0.0


def _bank(sm):
  return sm['liveParameters'].roll if sm.valid['liveParameters'] else 0.0


def _units(is_metric):
  return (CV.MS_TO_KPH, "km/h") if is_metric else (CV.MS_TO_MPH, "mph")


def _fix(sm):
  for svc in ('gpsLocationExternal', 'gpsLocation'):
    if sm.valid[svc]:
      return sm[svc], svc
  return None, None


# --- probes (sm, is_metric) -> Readout ---------------------------------------

def steering_angle(sm, is_metric):
  deg = sm['carState'].steeringAngleDeg - _yaw_offset(sm)
  return Readout("R.S.", f"{deg:.1f}°", color=_angle_tint(sm, deg))


def desired_steering_angle(sm, is_metric):
  live = sm['carControl'].latActive
  off = _yaw_offset(sm)
  lat = sm['controlsState'].lateralControlState
  if lat.which() == 'angleState':
    want = lat.angleState.steeringAngleDesiredDeg - off
  else:
    want = sm['carControl'].actuators.steeringAngleDeg - off
  seen = sm['carState'].steeringAngleDeg - off
  tint = _banded(abs(seen), 90.0, 180.0, _TEAL) if live else canvas.WHITE
  return Readout("D.S.", f"{want:.1f}°" if live else "-", color=tint)


def desired_steering_pid(sm, is_metric):
  live = sm['carControl'].latActive
  off = _yaw_offset(sm)
  want = sm['controlsState'].lateralControlState.pidState.steeringAngleDesiredDeg - off
  seen = sm['carState'].steeringAngleDeg - off
  tint = _banded(abs(seen), 90.0, 180.0, _TEAL) if live else canvas.WHITE
  return Readout("D.S.", f"{want:.1f}°" if live else "-", color=tint)


def actual_lat_accel(sm, is_metric):
  a = sm['controlsState'].curvature * sm['carState'].vEgo ** 2 - _bank(sm) * _G
  return Readout("A.L.A.", f"{a:.2f}", "m/s^2", _steer_tint(sm))


def desired_lat_accel(sm, is_metric):
  live = sm['carControl'].latActive
  a = sm['controlsState'].desiredCurvature * sm['carState'].vEgo ** 2 - _bank(sm) * _G
  return Readout("D.L.A.", f"{a:.2f}" if live else "-", "m/s^2", _steer_tint(sm))


def a_ego(sm, is_metric):
  return Readout("L.ACC.", f"{sm['carState'].aEgo:.1f}", "m/s^2")


def lead_distance(sm, is_metric):
  lead = sm['radarState'].leadOne
  return Readout("REL DIST", "-", "m") if not lead.status else Readout("REL DIST", f"{lead.dRel:.0f}", "m", _following(lead.dRel))


def lead_rel_speed(sm, is_metric):
  lead = sm['radarState'].leadOne
  k, unit = _units(is_metric)
  return Readout("REL SPEED", "-", unit) if not lead.status else Readout("REL SPEED", f"{lead.vRel * k:.0f}", unit, _closing(lead.vRel))


def lead_speed(sm, is_metric):
  lead = sm['radarState'].leadOne
  k, unit = _units(is_metric)
  if not lead.status:
    return Readout("L.S.", "-", unit)
  return Readout("L.S.", f"{(lead.vRel + sm['carState'].vEgo) * k:.0f}", unit, _closing(lead.vRel))


def friction_coefficient(sm, is_metric):
  ltp = sm['liveTorqueParameters']
  return Readout("FRIC.", f"{ltp.frictionCoefficientFiltered:.3f}", color=_GREEN if ltp.liveValid else canvas.WHITE)


def lat_accel_factor(sm, is_metric):
  ltp = sm['liveTorqueParameters']
  return Readout("L.A.F.", f"{ltp.latAccelFactorFiltered:.3f}", color=_GREEN if ltp.liveValid else canvas.WHITE)


def eps_torque(sm, is_metric):
  return Readout("E.T.", f"{abs(sm['carState'].steeringTorqueEps):.1f}", "N·dm")


_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def bearing(sm, is_metric):
  fix, _ = _fix(sm)
  if fix is None or fix.bearingAccuracyDeg == 180.0:
    return Readout("B.D.", "OFF | -")
  heading = _COMPASS[int(((fix.bearingDeg + 22.5) % 360) // 45)]
  return Readout("B.D.", f"{heading} | {fix.bearingDeg:.0f}°")


def altitude(sm, is_metric):
  fix, svc = _fix(sm)
  if fix is None:
    return Readout("ALT.", "-", "m")
  acc = fix.horizontalAccuracy if svc == 'gpsLocationExternal' else 1.0
  return Readout("ALT.", f"{fix.altitude:.1f}" if acc != 0.0 else "-", "m")


def _desired_probe(sm):
  """The 'desired' cell tracks whichever lateral controller is live."""
  if sm['controlsState'].lateralControlState.which() == 'angleState':
    return desired_steering_angle
  if ui_state.CP is not None and ui_state.CP.steerControlType in _ANGLE_TYPES:
    return desired_steering_angle
  if sm['controlsState'].lateralControlState.which() == 'pidState':
    return desired_steering_pid
  return desired_lat_accel


class DeveloperUiRenderer(Widget):
  DEV_UI_OFF = 0
  DEV_UI_RIGHT = 1
  DEV_UI_BOTTOM = 2
  DEV_UI_BOTH = 3
  BOTTOM_BAR_HEIGHT = 61

  def __init__(self):
    super().__init__()
    self._face = gui_app.font(FontWeight.BOLD)
    self.dev_ui_mode = self.DEV_UI_OFF

  @staticmethod
  def get_bottom_dev_ui_offset():
    return DeveloperUiRenderer.BOTTOM_BAR_HEIGHT if ui_state.developer_ui != DeveloperUiRenderer.DEV_UI_OFF else 0

  def _update_state(self) -> None:
    self.dev_ui_mode = ui_state.developer_ui

  def _render(self, rect) -> None:
    if self.dev_ui_mode == self.DEV_UI_OFF:
      return
    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      return
    self._paint_bar(rect)

  def _gather(self, sm):
    probes = (_desired_probe(sm), actual_lat_accel, steering_angle, a_ego, lead_speed)
    cells = [probe(sm, ui_state.is_metric) for probe in probes]
    for cell in cells:
      cell.size_up(self._face, _BAR_FONT)
    return cells

  def _paint_bar(self, rect) -> None:
    height = self.BOTTOM_BAR_HEIGHT
    top = int(rect.y + rect.height - height)
    canvas.slab(rect.x, top, rect.width, height, canvas.shade(0, 0, 0, 100))

    cells = self._gather(ui_state.sm)
    slack = (rect.width - sum(c.span for c in cells)) / (len(cells) + 1)
    baseline = top + height // 2 - _BAR_FONT // 2

    cursor = rect.x + slack
    for cell in cells:
      self._paint_cell(cursor, baseline, cell)
      cursor += cell.span + slack

  def _paint_cell(self, x, y, cell) -> None:
    canvas.glyphs(self._face, cell.tag_text, canvas.Pt(x, y), _BAR_FONT, canvas.WHITE)
    canvas.glyphs(self._face, cell.value_text, canvas.Pt(x + cell.tag_w, y), _BAR_FONT, cell.color)
    if cell.unit:
      canvas.glyphs(self._face, cell.unit_text, canvas.Pt(x + cell.tag_w + cell.value_w, y), _BAR_FONT, canvas.WHITE)


# ============================================================================
#  Speed-limit sign (Vienna / MUTCD) + limit-ahead preview + assist arrows
# ============================================================================
_SL_M_TO_FT = 3.28084
_SL_M_TO_MI = 0.000621371
_SL_AHEAD_STEPS = 5
_SL_ASSIST = custom.IQPlan.SpeedLimit.AssistState
_SL_SOURCE = custom.IQPlan.SpeedLimit.Source
_SL_GREY = canvas.shade(145, 155, 149, 255)
_SL_DARK = canvas.shade(77, 77, 77, 255)
_SL_PANEL_BG = canvas.shade(0, 0, 0, 180)
_SL_PANEL_EDGE = canvas.shade(255, 255, 255, 100)


def _dim(color, alpha: float):
  return canvas.with_opacity(color, 255 * alpha)


class SpeedLimitRenderer(Widget):
  """Regulatory sign, upcoming-limit preview and pre-active nudge arrows."""

  def __init__(self):
    super().__init__()
    self.speed_limit = 0.0
    self.speed_limit_last = 0.0
    self.speed_limit_offset = 0.0
    self.speed_limit_valid = False
    self.speed_limit_last_valid = False
    self.speed_limit_final_last = 0.0
    self.speed_limit_source = _SL_SOURCE.none
    self.assist_state = _SL_ASSIST.disabled

    self.ahead_limit = 0.0
    self.ahead_dist = 0.0
    self._ahead_prev = 0.0
    self.ahead_valid = False
    self._ahead_streak = 0

    self.assist_frame = 0
    self.speed = 0.0
    self.set_speed = 0.0

    self._bold = gui_app.font(FontWeight.BOLD)
    self._demi = gui_app.font(FontWeight.SEMI_BOLD)
    self._norm = gui_app.font(FontWeight.NORMAL)
    self._pulse_ema = FirstOrderFilter(1.0, 0.5, 1 / gui_app.target_fps)

    px = 90
    self._up = gui_app.texture("../../iqpilot/selfdrive/assets/img_plus_arrow_up.png", px, px)
    self._down = gui_app.texture("../../iqpilot/selfdrive/assets/img_minus_arrow_down.png", px, px)

  @property
  def speed_limit_assist_state(self):
    return self.assist_state

  @property
  def _scale(self):
    return CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH

  def _take_plan(self, lp_iq):
    k = self._scale
    r = lp_iq.speedLimit.resolver
    self.speed_limit = r.speedLimit * k
    self.speed_limit_last = r.speedLimitLast * k
    self.speed_limit_offset = r.speedLimitOffset * k
    self.speed_limit_valid = r.speedLimitValid
    self.speed_limit_last_valid = r.speedLimitLastValid
    self.speed_limit_final_last = r.speedLimitFinalLast * k
    self.speed_limit_source = r.source
    self.assist_state = lp_iq.speedLimit.assist.state

  def _take_ahead(self, lmd):
    self.ahead_valid = lmd.speedLimitAheadValid
    self.ahead_limit = lmd.speedLimitAhead * self._scale
    self.ahead_dist = lmd.speedLimitAheadDistance
    if self.ahead_dist < self._ahead_prev:
      self._ahead_streak = min(_SL_AHEAD_STEPS, self._ahead_streak + 1)
    elif self.ahead_dist > self._ahead_prev:
      self._ahead_streak = max(0, self._ahead_streak - 1)
    self._ahead_prev = self.ahead_dist

  def update(self):
    sm = _feed()
    if sm.recv_frame["carState"] < ui_state.started_frame:
      return
    if sm.updated["iqPlan"]:
      self._take_plan(sm["iqPlan"])
    if sm.updated["iqLiveData"]:
      self._take_ahead(sm["iqLiveData"])
    cs = sm["carState"]
    self.set_speed = cs.cruiseState.speed * self._scale
    v_ego = cs.vEgoCluster if cs.vEgoCluster != 0.0 else cs.vEgo
    self.speed = max(0.0, v_ego * self._scale)

  def _spec(self):
    has_limit = self.speed_limit_valid or self.speed_limit_last_valid
    value = str(round(self.speed_limit_last)) if has_limit else "---"
    badge = ""
    if self.speed_limit_offset != 0:
      badge = f"{'' if self.speed_limit_offset > 0 else '-'}{round(abs(self.speed_limit_offset))}"
    warn = ui_state.speed_limit_mode >= 2  # SpeedLimitMode.warning
    over = has_limit and round(self.speed_limit_final_last) < round(self.speed)
    tint = canvas.RED if (warn and over) else (_SL_GREY if not self.speed_limit_valid else canvas.BLACK)
    return value, badge, tint, has_limit

  def _render(self, rect):
    if ui_state.speed_limit_mode == 0:  # SpeedLimitMode.off
      return
    w = UI_CONFIG.set_speed_width_metric if ui_state.is_metric else UI_CONFIG.set_speed_width_imperial
    sign = canvas.Box(rect.x + 60 - 6, rect.y + 45 + UI_CONFIG.set_speed_height + 12, w + 12, 160)
    if self.assist_state == _SL_ASSIST.preActive:
      self.assist_frame += 1
      pulse = 0.65 + 0.35 * math.sin(self.assist_frame * math.pi / gui_app.target_fps)
      self._sign(sign, self._pulse_ema.update(pulse))
      self._nudge_arrow(sign)
    else:
      self.assist_frame = 0
      self._pulse_ema.update(1.0)
      self._sign(sign)
      self._ahead(sign)

  def _sign(self, rect, alpha=1.0):
    value, badge, tint, has_limit = self._spec()
    (self._vienna if ui_state.is_metric else self._mutcd)(rect, value, badge, tint, has_limit, alpha)

  def _nudge_arrow(self, sign):
    delta = round(self.speed_limit_final_last) - round(self.set_speed)
    if delta == 0:
      return
    arrow = self._up if delta > 0 else self._down
    bounce = int(20 * math.sin(self.assist_frame * 2.0 * math.pi / (gui_app.target_fps * 2.5)))
    x = sign.x + (sign.width - arrow.width) / 2
    y = sign.y + (sign.height - arrow.height) / 2 + (bounce if delta > 0 else -bounce)
    canvas.stamp(arrow, x, y, canvas.WHITE)

  def _vienna(self, rect, value, badge, tint, has_limit, alpha=1.0):
    hub = canvas.Pt(rect.x + rect.width / 2, rect.y + rect.height / 2)
    radius = (rect.width + 18) / 2
    canvas.disc_at(hub, radius, _dim(canvas.WHITE, alpha))
    canvas.annulus(hub, radius * 0.80, radius, 0, 360, 36, _dim(canvas.RED, alpha))
    canvas.glyphs_centered(self._bold, value, 70 if len(value) >= 3 else 85, hub, _dim(tint, alpha))
    if badge and has_limit:
      br = radius * 0.4
      bc = canvas.Pt(rect.x + rect.width - br / 2, rect.y + br / 2)
      canvas.disc_at(bc, br, _dim(canvas.BLACK, alpha))
      canvas.annulus(bc, br - 3, br, 0, 360, 36, _dim(_SL_DARK, alpha))
      canvas.glyphs_centered(self._bold, badge, int(br * 2 * (0.5 if len(badge) < 3 else 0.45)), bc, _dim(canvas.WHITE, alpha))

  def _mutcd(self, rect, value, badge, tint, has_limit, alpha=1.0):
    canvas.panel(rect, 0.35, 10, _dim(canvas.WHITE, alpha))
    inner = canvas.Box(rect.x + 10, rect.y + 10, rect.width - 20, rect.height - 20)
    canvas.panel_outline(inner, 0.35, 10, 4, _dim(canvas.BLACK, alpha))
    mid = rect.x + rect.width / 2
    canvas.glyphs_centered(self._demi, "SPEED", 40, canvas.Pt(mid, rect.y + 40), _dim(canvas.BLACK, alpha))
    canvas.glyphs_centered(self._demi, "LIMIT", 40, canvas.Pt(mid, rect.y + 80), _dim(canvas.BLACK, alpha))
    canvas.glyphs_centered(self._bold, value, 90, canvas.Pt(mid, rect.y + 150), _dim(tint, alpha))
    if badge and has_limit:
      side = rect.width * 0.3
      overlap = side * 0.2
      chip = canvas.Box(rect.x + rect.width - side / 1.5 + overlap, rect.y - side / 1.25 + overlap, side, side)
      canvas.panel(chip, 0.35, 10, _dim(canvas.BLACK, alpha))
      canvas.panel_outline(chip, 0.35, 10, 6, _dim(_SL_DARK, alpha))
      canvas.glyphs_centered(self._bold, badge, int(side * (0.6 if len(badge) < 3 else 0.475)),
                             canvas.Pt(chip.x + side / 2, chip.y + side / 2), _dim(canvas.WHITE, alpha))

  def _ahead(self, sign):
    if not (self.ahead_valid and self.ahead_limit > 0 and self.ahead_limit != self.speed_limit_last and self._ahead_streak > 0):
      return
    panel = canvas.Box(sign.x + (sign.width - 170) / 2, sign.y + sign.height + 10, 170, 160)
    canvas.panel(panel, 0.35, 10, _SL_PANEL_BG)
    canvas.panel_outline(panel, 0.35, 10, 3, _SL_PANEL_EDGE)
    mid = panel.x + panel.width / 2
    canvas.glyphs_centered(self._demi, "AHEAD", 40, canvas.Pt(mid, panel.y + 28), _SL_GREY)
    canvas.glyphs_centered(self._bold, str(round(self.ahead_limit)), 70, canvas.Pt(mid, panel.y + 82), canvas.WHITE)
    canvas.glyphs_centered(self._norm, self._dist(self.ahead_dist), 36, canvas.Pt(mid, panel.y + 134), _SL_GREY)

  @staticmethod
  def _dist(d):
    if ui_state.is_metric:
      if d < 50:
        return tr("Near")
      if d >= 1000:
        return f"{d / 1000:.1f} km"
      return f"{int(round(d, -1) if d < 200 else round(d, -2))} m"
    ft = d * _SL_M_TO_FT
    if ft < 100:
      return tr("Near")
    if ft >= 900:
      return f"{d * _SL_M_TO_MI:.1f} mi"
    step = 50 if ft < 500 else 100
    return f"{int(round(ft / step) * step)} ft"

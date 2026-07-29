"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import requests
import threading
import time
import pyray as rl

from openpilot.common.api import api_get
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.common.time_helpers import system_time_valid
from openpilot.selfdrive.ui.lib.api_helpers import get_token
from openpilot.selfdrive.ui.ui_state import ui_state, device
from openpilot.iqpilot.konn3kt.registration import UNREGISTERED_DONGLE_ID
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

_STATS_PARAM = "ApiCache_DriveStats"
_POLL_SECONDS = 30


class _DriveStatsSource:
  """Owns the konn3kt drive-stats fetch. Seeds from the cached param, then keeps it fresh on a
  background poll while the device is offroad and awake. Read `snapshot` for the latest data."""

  def __init__(self):
    self._params = Params()
    self._http = requests.Session()
    self.snapshot = self._params.get(_STATS_PARAM) or {}
    self._alive = True
    self._worker = threading.Thread(target=self._poll, daemon=True)
    self._worker.start()

  def close(self) -> None:
    self._alive = False
    try:
      if self._worker.is_alive():
        self._worker.join(timeout=1.0)
    except Exception:
      pass

  def _poll(self) -> None:
    while self._alive:
      if not ui_state.started and device._awake:
        self._pull_once()
      time.sleep(_POLL_SECONDS)

  def _pull_once(self) -> None:
    try:
      dongle_id = self._params.get("DongleId")
      if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
        return
      # at boot the clock isn't NTP-synced, so the token can't be minted yet — skip quietly
      if not system_time_valid():
        return
      resp = api_get(f"v1.1/devices/{dongle_id}/stats", access_token=get_token(dongle_id), session=self._http)
      if resp.status_code == 200:
        payload = resp.json()
        self.snapshot = payload
        self._params.put(_STATS_PARAM, payload)
    except Exception as e:
      cloudlog.error(f"Failed to fetch drive stats: {e}")


class TripsLayout(Widget):
  PARAM_KEY = _STATS_PARAM        # retained for external references
  UPDATE_INTERVAL = _POLL_SECONDS

  _CARD_FILL = rl.Color(38, 40, 46, 255)
  _CARD_EDGE = rl.Color(255, 255, 255, 18)
  _ACCENT = rl.Color(30, 200, 168, 255)
  _ACCENT_DIM = rl.Color(93, 202, 165, 255)
  _UNIT = rl.Color(138, 139, 144, 255)
  _RULE = rl.Color(255, 255, 255, 16)

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._source = _DriveStatsSource()
    # one shared height so the three columns line up; tinted teal at draw time
    self._ic_drives = gui_app.texture("icons_mici/wheel.png", 64, 64, keep_aspect_ratio=True)
    self._ic_distance = gui_app.texture("icons/road.png", 88, 64, keep_aspect_ratio=True)
    self._ic_hours = gui_app.texture("../../iqpilot/selfdrive/assets/icons/clock.png", 64, 64, keep_aspect_ratio=True)

  def __del__(self):
    self._source.close()

  def _columns(self, bucket: dict, is_metric: bool):
    routes = int(bucket.get("routes", 0))
    distance = bucket.get("distance", 0)
    distance_val = int(distance * CV.MPH_TO_KPH) if is_metric else int(distance)
    hours = int(bucket.get("minutes", 0) / 60)
    dist_unit = tr("KM") if is_metric else tr("Miles")
    return (
      (self._ic_drives, str(routes), tr("Drives")),
      (self._ic_distance, str(distance_val), dist_unit),
      (self._ic_hours, str(hours), tr("Hours")),
    )

  def _paint_card(self, x, y, width, height, title, columns) -> None:
    card = rl.Rectangle(x, y, width, height)
    rl.draw_rectangle_rounded(card, 0.10, 20, self._CARD_FILL)
    rl.draw_rectangle_rounded_lines_ex(card, 0.10, 20, 2, self._CARD_EDGE)

    # heading: teal tick + muted-teal caption
    pad = 44
    label_y = y + 36
    tick_h = 30
    title_size = 34 * FONT_SCALE
    rl.draw_rectangle_rounded(rl.Rectangle(x + pad, label_y, 6, tick_h), 0.5, 6, self._ACCENT)
    rl.draw_text_ex(gui_app.font(FontWeight.BOLD), title,
                    rl.Vector2(x + pad + 22, label_y + (tick_h - title_size) / 2), title_size, 4, self._ACCENT_DIM)

    col_width = width / 3
    content_top = label_y + tick_h + 20
    content_bottom = y + height - 30

    number_font = gui_app.font(FontWeight.BOLD)
    unit_font = gui_app.font(FontWeight.MEDIUM)
    number_size = 84 * FONT_SCALE
    unit_size = 30 * FONT_SCALE
    unit_spacing = 2.0
    icon_gap = 16
    num_gap = 14

    # vertical rules between the three columns
    for i in (1, 2):
      dx = x + col_width * i
      rl.draw_line_ex(rl.Vector2(dx, content_top + 4), rl.Vector2(dx, content_bottom - 4), 1, self._RULE)

    for idx, (icon, value, unit) in enumerate(columns):
      center_x = x + col_width * idx + col_width / 2
      unit = unit.upper()
      val_w = measure_text_cached(number_font, value, int(number_size)).x
      unit_w = measure_text_cached(unit_font, unit, int(unit_size)).x + unit_spacing * max(0, len(unit) - 1)
      block_h = icon.height + icon_gap + number_size + num_gap + unit_size
      start_y = content_top + max(0.0, (content_bottom - content_top - block_h) / 2)
      rl.draw_texture(icon, int(center_x - icon.width / 2), int(start_y), self._ACCENT)
      num_y = start_y + icon.height + icon_gap
      rl.draw_text_ex(number_font, value, rl.Vector2(center_x - val_w / 2, num_y), number_size, 0, rl.WHITE)
      unit_y = num_y + number_size + num_gap
      rl.draw_text_ex(unit_font, unit, rl.Vector2(center_x - unit_w / 2, unit_y), unit_size, unit_spacing, self._UNIT)

  def _render(self, rect: rl.Rectangle):
    is_metric = self._params.get_bool("IsMetric")
    stats = self._source.snapshot
    spacing = 28
    card_height = (rect.height - spacing) / 2

    self._paint_card(rect.x, rect.y, rect.width, card_height, tr("ALL TIME"),
                     self._columns(stats.get("all", {}), is_metric))
    self._paint_card(rect.x, rect.y + card_height + spacing, rect.width, card_height, tr("PAST WEEK"),
                     self._columns(stats.get("week", {}), is_metric))
    return -1

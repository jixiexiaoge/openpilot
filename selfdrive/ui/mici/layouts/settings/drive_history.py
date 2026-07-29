"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

import threading
import time

import pyray as rl

from openpilot.common.api import api_get
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.lib.api_helpers import get_token
from openpilot.selfdrive.ui.ui_state import ui_state, device
from openpilot.iqpilot.konn3kt.registration import UNREGISTERED_DONGLE_ID
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.nav_widget import NavWidget

_ACCENT = rl.Color(0x3A, 0xDD, 0xC6, 255)
_CARD_BG = rl.Color(26, 27, 30, 255)
_LABEL = rl.Color(150, 150, 150, 255)


class TripsLayoutMici(NavWidget):
  PARAM_KEY = "ApiCache_DriveStats"
  UPDATE_INTERVAL = 30

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._stats = self._params.get(self.PARAM_KEY) or {}
    self._bold = gui_app.font(FontWeight.BOLD)
    self._medium = gui_app.font(FontWeight.MEDIUM)
    self._running = True
    self._thread = threading.Thread(target=self._update_loop, daemon=True)
    self._thread.start()

  def __del__(self):
    self._running = False

  def _fetch(self):
    try:
      dongle_id = self._params.get("DongleId")
      if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
        return
      resp = api_get(f"v1.1/devices/{dongle_id}/stats", access_token=get_token(dongle_id))
      if resp.status_code == 200:
        data = resp.json()
        self._stats = data
        self._params.put(self.PARAM_KEY, data)
    except Exception as e:
      cloudlog.error(f"trips: failed to fetch drive stats: {e}")

  def _update_loop(self):
    while self._running:
      if not ui_state.started and device._awake:
        self._fetch()
      time.sleep(self.UPDATE_INTERVAL)

  def _render_group(self, x, y, w, h, title, data, is_metric):
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.16, 8, _CARD_BG)
    rl.draw_text_ex(self._bold, title, rl.Vector2(x + 22, y + 12), 24, 0, _ACCENT)

    routes = int(data.get("routes", 0) or 0)
    distance = data.get("distance", 0) or 0
    dist = int(distance * CV.MPH_TO_KPH) if is_metric else int(distance)
    hours = int((data.get("minutes", 0) or 0) / 60)
    cols = [(str(routes), "drives"), (str(dist), "km" if is_metric else "mi"), (str(hours), "hours")]

    col_w = w / 3
    for i, (val, lbl) in enumerate(cols):
      cx = x + col_w * i + col_w / 2
      vs = measure_text_cached(self._bold, val, 46)
      rl.draw_text_ex(self._bold, val, rl.Vector2(cx - vs.x / 2, y + h / 2 - 28), 46, 0, rl.WHITE)
      ls = measure_text_cached(self._medium, lbl, 22)
      rl.draw_text_ex(self._medium, lbl, rl.Vector2(cx - ls.x / 2, y + h / 2 + 24), 22, 0, _LABEL)

  def _render(self, _):
    rect = self._rect
    is_metric = self._params.get_bool("IsMetric")
    stats = self._stats if isinstance(self._stats, dict) else {}
    pad = 12
    h = (rect.height - 3 * pad) / 2
    w = rect.width - 2 * pad
    x = rect.x + pad
    self._render_group(x, rect.y + pad, w, h, "ALL TIME", stats.get("all", {}), is_metric)
    self._render_group(x, rect.y + 2 * pad + h, w, h, "PAST WEEK", stats.get("week", {}), is_metric)

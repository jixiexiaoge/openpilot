import pyray as rl

from openpilot.selfdrive.ui.layouts.nav import _MapPreview
from openpilot.selfdrive.ui.lib.nav_helpers import current_or_last_gps_position
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

PANEL_BG = rl.Color(34, 36, 42, 255)
PANEL_BORDER = rl.Color(255, 255, 255, 26)
TEAL = rl.Color(16, 185, 169, 255)
MUTED = rl.Color(160, 160, 165, 255)
PANEL_ROUNDNESS = 0.16
PANEL_SEGMENTS = 24


class MapPanelWidget(Widget):
    def __init__(self):
        super().__init__()
        self._map = _MapPreview()
        self._last_lat = 0.0
        self._last_lon = 0.0

    def _render(self, rect: rl.Rectangle):
        rl.draw_rectangle_rounded(rect, PANEL_ROUNDNESS, PANEL_SEGMENTS, PANEL_BG)

        lat, lon, bearing, have_fix = current_or_last_gps_position()
        if have_fix:
            self._map.request(lat, lon, bearing, rect.width, rect.height)

        drew_map = self._map.draw(rect, roundness=PANEL_ROUNDNESS)
        rl.draw_rectangle_rounded_lines_ex(rect, PANEL_ROUNDNESS, PANEL_SEGMENTS, 2, PANEL_BORDER)
        if drew_map:
            font = gui_app.font(FontWeight.BOLD)
            label = "LAST KNOWN LOCATION"
            fs = 26
            spacing = 3
            text_size = measure_text_cached(font, label, fs, spacing)
            pill_w = text_size.x + 56
            pill_h = text_size.y + 24
            pill = rl.Rectangle(
                rect.x + (rect.width - pill_w) / 2,
                rect.y + rect.height - pill_h - 24,
                pill_w,
                pill_h,
            )
            text_x = pill.x + (pill.width - text_size.x) / 2
            text_y = pill.y + (pill.height - text_size.y) / 2
            rl.draw_rectangle_rounded(pill, 0.5, 18, rl.Color(0, 0, 0, 170))
            rl.draw_text_ex(font, label, rl.Vector2(int(text_x), int(text_y)), fs, spacing, TEAL)
        else:
            # No token or no fix — placeholder
            font = gui_app.font(FontWeight.MEDIUM)
            cx = rect.x + rect.width / 2
            cy = rect.y + rect.height / 2

            if not self._map.has_token():
                line1 = "Map unavailable"
                line2 = "Set MapboxToken to enable"
            elif not have_fix:
                line1 = "Waiting for GPS fix..."
                line2 = "No live or saved location"
            elif self._map.status() == "error":
                line1 = "Map unavailable"
                line2 = "Mapbox request failed"
            else:
                line1 = "Loading map..."
                line2 = "Fetching Mapbox preview"

            ts1 = measure_text_cached(font, line1, 46)
            rl.draw_text_ex(font, line1, rl.Vector2(int(cx - ts1.x / 2), int(cy - 40)), 46, 0, MUTED)
            if line2:
                ts2 = measure_text_cached(font, line2, 32)
                rl.draw_text_ex(
                    font,
                    line2,
                    rl.Vector2(int(cx - ts2.x / 2), int(cy + 20)),
                    32,
                    0,
                    rl.Color(120, 120, 125, 255),
                )

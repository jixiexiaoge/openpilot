import threading
import pyray as rl
from collections.abc import Callable

from openpilot.selfdrive.ui.widgets.screen_header import ScreenHeader, HEADER_HEIGHT
from openpilot.selfdrive.ui.lib.local_routes import list_local_routes, CAMERA_LABELS, format_local_time
from openpilot.selfdrive.ui.lib import cloud_routes_shim as cloud
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.scroll_panel import GuiScrollPanel
from openpilot.system.ui.widgets import Widget

MARGIN = 40
SPACING = 25
ROW_HEIGHT = 156
ROW_GAP = 22
BTN_SIZE = 120

ROW_BG = rl.Color(38, 40, 46, 255)
ROW_BORDER = rl.Color(255, 255, 255, 26)
PLAY_BG = rl.Color(16, 185, 169, 255)
SUBTEXT = rl.Color(158, 162, 170, 255)

# Upload-status badge colors.
BADGE_UPLOADED = rl.Color(16, 185, 129, 255)
BADGE_UPLOADING = rl.Color(234, 179, 8, 255)
BADGE_CLOUD = rl.Color(96, 132, 214, 255)
BADGE_LOCAL = rl.Color(90, 96, 108, 255)
BADGE_TEXT = rl.Color(10, 14, 18, 255)


class RoutesLayout(Widget):
  """Offroad Routes screen: local recorded routes + konn3kt cloud upload status / cloud-only routes."""

  def __init__(self):
    super().__init__()
    self._header = self._child(ScreenHeader(tr("Routes")))
    self._play_icon = gui_app.texture("icons/iq/play.png", 56, 56, keep_aspect_ratio=True)
    self._on_play: Callable[[str], None] | None = None
    self._scroll_panel = GuiScrollPanel()
    self._entries: list = []
    self._row_hitboxes: list[tuple[rl.Rectangle, object]] = []
    self._cloud_thread: threading.Thread | None = None
    self._cloud_generation = 0

  def set_on_back(self, cb: Callable[[], None]) -> None:
    self._header.set_on_back(cb)

  def set_on_play(self, cb: Callable[[str], None]) -> None:
    self._on_play = cb

  def show_event(self):
    super().show_event()
    local_routes = list_local_routes()
    # Show local routes immediately, then fold in cloud upload status / cloud-only routes async.
    self._entries = cloud.merge_routes(local_routes, [])
    self._start_cloud_fetch(local_routes)

  def _start_cloud_fetch(self, local_routes: list) -> None:
    if not cloud.cloud_available():
      return
    self._cloud_generation += 1
    generation = self._cloud_generation

    def _worker():
      dongle_id = cloud.get_dongle_id()
      cloud_routes = cloud.list_cloud_routes(dongle_id) if dongle_id else []
      if generation == self._cloud_generation:
        self._entries = cloud.merge_routes(local_routes, cloud_routes)

    self._cloud_thread = threading.Thread(target=_worker, daemon=True)
    self._cloud_thread.start()

  @staticmethod
  def _entry_title(entry) -> str:
    if entry.local is not None:
      return entry.local.label
    if entry.cloud is not None and entry.cloud.start_time > 0:
      return format_local_time(entry.cloud.start_time)
    return entry.name

  @staticmethod
  def _fmt_duration(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}:{sec:02d}"

  def _entry_subtitle_parts(self, entry) -> list[str]:
    if entry.local is not None:
      parts = [self._fmt_duration(entry.local.duration_s)]
      cams = ", ".join(CAMERA_LABELS.get(c, c).replace(" Cam", "") for c in entry.local.cameras)
      if cams:
        parts.append(cams)
      return parts
    if entry.cloud is not None:
      parts = []
      if entry.cloud.length_miles > 0:
        parts.append(f"{entry.cloud.length_miles:.1f} mi")
      parts.append(tr("Cloud only"))
      return parts
    return []

  @staticmethod
  def _draw_dotted(font, parts: list[str], x: float, y: float, size: int, color) -> None:
    cx = x
    for i, part in enumerate(parts):
      if i > 0:
        cx += 10
        rl.draw_circle(int(cx), int(y + size / 2), 3, rl.Color(color.r, color.g, color.b, 150))
        cx += 16
      rl.draw_text_ex(font, part, rl.Vector2(int(cx), int(y)), size, 0, color)
      cx += measure_text_cached(font, part, size).x

  def _render(self, rect: rl.Rectangle):
    header_rect = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - 2 * MARGIN, HEADER_HEIGHT)
    self._header.render(header_rect)

    x = rect.x + MARGIN
    w = rect.width - 2 * MARGIN
    list_top = header_rect.y + HEADER_HEIGHT + SPACING
    list_rect = rl.Rectangle(x, list_top, w, rect.y + rect.height - list_top - MARGIN)

    self._row_hitboxes = []
    font = gui_app.font(FontWeight.MEDIUM)
    if not self._entries:
      note = tr("No routes recorded")
      ns = measure_text_cached(font, note, 44)
      rl.draw_text_ex(font, note, rl.Vector2(int(rect.x + (rect.width - ns.x) / 2), int(list_top + 80)), 44, 0,
                      rl.Color(150, 150, 155, 255))
      return

    row_stride = ROW_HEIGHT + ROW_GAP
    content_rect = rl.Rectangle(list_rect.x, list_rect.y, list_rect.width, len(self._entries) * row_stride)
    offset = self._scroll_panel.update(list_rect, content_rect)

    rl.begin_scissor_mode(int(list_rect.x), int(list_rect.y), int(list_rect.width), int(list_rect.height))
    for i, entry in enumerate(self._entries):
      ry = list_rect.y + i * row_stride + offset
      row = rl.Rectangle(x, ry, w, ROW_HEIGHT)
      if not rl.check_collision_recs(row, list_rect):
        continue

      rl.draw_rectangle_rounded(row, 0.3, 20, ROW_BG)
      rl.draw_rectangle_rounded_lines_ex(row, 0.3, 20, 2, ROW_BORDER)

      title_size = 46
      subtitle_size = 30
      title = self._entry_title(entry)
      subtitle_parts = self._entry_subtitle_parts(entry)
      title_ts = measure_text_cached(font, title, title_size)
      text_y = ry + (ROW_HEIGHT - title_ts.y - subtitle_size - 10) / 2
      rl.draw_text_ex(font, title, rl.Vector2(int(x + 40), int(text_y)), title_size, 0, rl.WHITE)
      self._draw_dotted(font, subtitle_parts, x + 40, text_y + title_ts.y + 10, subtitle_size, SUBTEXT)

      cy = ry + ROW_HEIGHT / 2
      self._draw_status_badge(entry, x + w - 40 - BTN_SIZE - 24, cy, font)

      play_rect = rl.Rectangle(x + w - 40 - BTN_SIZE, cy - BTN_SIZE / 2, BTN_SIZE, BTN_SIZE)
      rl.draw_circle(int(play_rect.x + BTN_SIZE / 2), int(cy), BTN_SIZE / 2, PLAY_BG)
      rl.draw_texture(self._play_icon, int(play_rect.x + (BTN_SIZE - self._play_icon.width) / 2 + 4),
                      int(cy - self._play_icon.height / 2), rl.Color(8, 16, 16, 255))

      self._row_hitboxes.append((play_rect, entry))
    rl.end_scissor_mode()

  def _draw_status_badge(self, entry, right_x: float, cy: float, font) -> None:
    if entry.is_local and entry.upload_state == cloud.UPLOAD_UPLOADED:
      label, color = tr("Uploaded"), BADGE_UPLOADED
    elif entry.is_local and entry.upload_state == cloud.UPLOAD_UPLOADING:
      label, color = tr("Uploading"), BADGE_UPLOADING
    elif not entry.is_local and entry.is_cloud:
      label, color = tr("Cloud"), BADGE_CLOUD
    elif entry.is_local:
      label, color = tr("On device"), BADGE_LOCAL
    else:
      return

    fs = 24
    pad = 18
    tw = measure_text_cached(font, label, fs).x + pad * 2
    badge = rl.Rectangle(right_x - tw, cy - 20, tw, 40)
    rl.draw_rectangle_rounded(badge, 0.5, 12, color)
    rl.draw_text_ex(font, label, rl.Vector2(int(badge.x + pad), int(cy - fs / 2)), fs, 0, BADGE_TEXT)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if not self._scroll_panel.is_touch_valid():
      return
    for play_rect, entry in self._row_hitboxes:
      if rl.check_collision_point_rec(mouse_pos, play_rect):
        if self._on_play:
          self._on_play(entry.name)
        return

import pyray as rl
from collections.abc import Callable

from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

HEADER_HEIGHT = 130
BACK_BTN_SIZE = 110


class ScreenHeader(Widget):
  """Reusable offroad sub-screen header: a circular back button on the left and a title.

  Used by the Stats and NAV screens reached from the offroad launcher tiles.
  """

  BTN_COLOR = rl.Color(38, 40, 46, 255)
  BTN_PRESSED = rl.Color(54, 57, 65, 255)

  def __init__(self, title: str, on_back: Callable[[], None] | None = None):
    super().__init__()
    self._title = title
    self._on_back = on_back
    self._title_offset = 0  # extra space between back button and title (for inline buttons)
    self._back_icon = gui_app.texture("icons/iq/back.png", 56, 56, keep_aspect_ratio=True)
    self._back_rect = rl.Rectangle(0, 0, BACK_BTN_SIZE, BACK_BTN_SIZE)

  def set_on_back(self, cb: Callable[[], None]) -> None:
    self._on_back = cb

  def set_title(self, title: str) -> None:
    self._title = title

  def set_title_offset(self, offset: int) -> None:
    self._title_offset = offset

  def _render(self, rect: rl.Rectangle):
    self._back_rect = rl.Rectangle(rect.x, rect.y + (rect.height - BACK_BTN_SIZE) / 2, BACK_BTN_SIZE, BACK_BTN_SIZE)

    mouse_pos = rl.get_mouse_position()
    pressed = self.is_pressed and rl.check_collision_point_rec(mouse_pos, self._back_rect)
    rl.draw_rectangle_rounded(self._back_rect, 1.0, 20, self.BTN_PRESSED if pressed else self.BTN_COLOR)
    icon_x = int(self._back_rect.x + (BACK_BTN_SIZE - self._back_icon.width) / 2)
    icon_y = int(self._back_rect.y + (BACK_BTN_SIZE - self._back_icon.height) / 2)
    rl.draw_texture(self._back_icon, icon_x, icon_y, rl.WHITE)

    # Title, vertically centered, to the right of the back button
    font = gui_app.font(FontWeight.BOLD)
    title_size = measure_text_cached(font, self._title, 64)
    title_x = self._back_rect.x + BACK_BTN_SIZE + 36 + self._title_offset
    title_y = rect.y + (rect.height - title_size.y) / 2
    rl.draw_text_ex(font, self._title, rl.Vector2(int(title_x), int(title_y)), 64, 0, rl.WHITE)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if rl.check_collision_point_rec(mouse_pos, self._back_rect) and self._on_back:
      self._on_back()

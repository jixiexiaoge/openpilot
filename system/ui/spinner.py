#!/usr/bin/env python3
import pyray as rl
import select
import sys

from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.text import wrap_text
from openpilot.system.ui.widgets import Widget

# Constants
if gui_app.big_ui():
  PROGRESS_BAR_WIDTH = 1000
  PROGRESS_BAR_HEIGHT = 20
  TEXTURE_SIZE = 360
  WRAPPED_SPACING = 50
  CENTERED_SPACING = 150
else:
  PROGRESS_BAR_WIDTH = 268
  PROGRESS_BAR_HEIGHT = 10
  TEXTURE_SIZE = 140
  WRAPPED_SPACING = 10
  CENTERED_SPACING = 20
LOGO_SCALE = 0.82
LOGO_SIZE = int(TEXTURE_SIZE * LOGO_SCALE)
LOGO_Y_OFFSET = int(TEXTURE_SIZE * 0.04)
MARGIN_H = 100
FONT_SIZE = 96
LINE_HEIGHT = 104
DARKGRAY = (55, 55, 55, 255)
PROGRESS_START = rl.Color(0x1B, 0x94, 0x88, 0xFF)
PROGRESS_END = rl.Color(0xA3, 0x0B, 0x8C, 0xFF)


def clamp(value, min_value, max_value):
  return max(min(value, max_value), min_value)


def lerp_color(start: rl.Color, end: rl.Color, t: float) -> rl.Color:
  t = clamp(t, 0.0, 1.0)
  return rl.Color(
    int(round(start.r + (end.r - start.r) * t)),
    int(round(start.g + (end.g - start.g) * t)),
    int(round(start.b + (end.b - start.b) * t)),
    int(round(start.a + (end.a - start.a) * t)),
  )


class Spinner(Widget):
  def __init__(self):
    super().__init__()
    self._comma_texture = self._load_center_texture()
    self._progress: int | None = None
    self._wrapped_lines: list[str] = []

  @staticmethod
  def _load_center_texture():
    try:
      return gui_app.texture("images/k3_spinner.png", LOGO_SIZE, LOGO_SIZE)
    except Exception:
      return gui_app.texture("images/spinner_comma.png", LOGO_SIZE, LOGO_SIZE)

  def set_text(self, text: str) -> None:
    if text.isdigit():
      self._progress = clamp(int(text), 0, 100)
      self._wrapped_lines = []
    else:
      self._progress = None
      self._wrapped_lines = wrap_text(text, FONT_SIZE, gui_app.width - MARGIN_H)

  def _render(self, rect: rl.Rectangle):
    if self._wrapped_lines:
      # Calculate total height required for spinner and text
      spacing = WRAPPED_SPACING
      total_height = TEXTURE_SIZE + spacing + len(self._wrapped_lines) * LINE_HEIGHT
      center_y = (rect.height - total_height) / 2.0 + TEXTURE_SIZE / 2.0
    else:
      # Center spinner vertically
      spacing = CENTERED_SPACING
      center_y = rect.height / 2.0
    y_pos = center_y + TEXTURE_SIZE / 2.0 + spacing

    center = rl.Vector2(rect.width / 2.0, center_y)
    comma_position = rl.Vector2(center.x - LOGO_SIZE / 2.0, center.y - LOGO_SIZE / 2.0 + LOGO_Y_OFFSET)

    rl.draw_texture_v(self._comma_texture, comma_position, rl.WHITE)

    # Display the progress bar or text based on user input
    if self._progress is not None:
      bar = rl.Rectangle(center.x - PROGRESS_BAR_WIDTH / 2.0, y_pos, PROGRESS_BAR_WIDTH, PROGRESS_BAR_HEIGHT)
      rl.draw_rectangle_rounded(bar, 1, 10, DARKGRAY)

      bar.width *= self._progress / 100.0
      if bar.width > 0:
        radius = bar.height / 2.0
        if bar.width <= bar.height:
          fill_color = lerp_color(PROGRESS_START, PROGRESS_END, bar.width / PROGRESS_BAR_WIDTH)
          rl.draw_circle_v(rl.Vector2(bar.x + bar.width / 2.0, bar.y + radius), min(bar.width, bar.height) / 2.0, fill_color)
        else:
          rl.draw_circle_v(rl.Vector2(bar.x + radius, bar.y + radius), radius, PROGRESS_START)
          right_color = lerp_color(PROGRESS_START, PROGRESS_END, bar.width / PROGRESS_BAR_WIDTH)
          rl.draw_circle_v(rl.Vector2(bar.x + bar.width - radius, bar.y + radius), radius, right_color)
          rect_x = int(bar.x + radius)
          rect_y = int(bar.y)
          rect_width = int(max(0, bar.width - (2.0 * radius)))
          if rect_width > 0:
            rl.draw_rectangle_gradient_h(rect_x, rect_y, rect_width, int(bar.height), PROGRESS_START, right_color)
    elif self._wrapped_lines:
      for i, line in enumerate(self._wrapped_lines):
        text_size = measure_text_cached(gui_app.font(), line, FONT_SIZE)
        rl.draw_text_ex(gui_app.font(), line, rl.Vector2(center.x - text_size.x / 2, y_pos + i * LINE_HEIGHT),
                        FONT_SIZE, 0.0, rl.WHITE)


def _read_stdin():
  """Non-blocking read of available lines from stdin."""
  lines = []
  while True:
    rlist, _, _ = select.select([sys.stdin], [], [], 0.0)
    if not rlist:
      break
    line = sys.stdin.readline().strip()
    if line == "":
      break
    lines.append(line)
  return lines


def main():
  gui_app.init_window("Spinner")
  spinner = Spinner()
  for _ in gui_app.render():
    text_list = _read_stdin()
    if text_list:
      spinner.set_text(text_list[-1])

    spinner.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))


if __name__ == "__main__":
  main()

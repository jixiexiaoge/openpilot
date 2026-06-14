import pyray as rl
from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget


class ExperimentalModeButton(Widget):
  def __init__(self):
    super().__init__()

    self.img_width = 80
    self.horizontal_padding = 25
    self.button_height = 125

    self.params = Params()
    self.experimental_mode = self.params.get_bool("ExperimentalMode")
    self.iq_dynamic_mode = self.params.get_bool("IQDynamicMode")
    self.alpha_longitudinal_enabled = self.params.get_bool("AlphaLongitudinalEnabled")

    self.chill_pixmap = gui_app.texture("icons/couch.png", self.img_width, self.img_width)
    self.experimental_pixmap = gui_app.texture("icons_mici/experimental_mode_tizi.png", self.img_width, self.img_width)

  def show_event(self):
    self.experimental_mode = self.params.get_bool("ExperimentalMode")
    self.iq_dynamic_mode = self.params.get_bool("IQDynamicMode")
    self.alpha_longitudinal_enabled = self.params.get_bool("AlphaLongitudinalEnabled")

  def _get_gradient_colors(self):
    alpha = 0xCC if self.is_pressed else 0xFF

    if not self.alpha_longitudinal_enabled:
      return rl.Color(112, 112, 112, alpha), rl.Color(78, 78, 78, alpha)

    if self.experimental_mode:
      # IQ.Pilot / IQ.Dynamic active gradient
      return rl.Color(0x13, 0xC3, 0xE2, alpha), rl.Color(0xE2, 0x13, 0xAD, alpha)
    else:
      return rl.Color(20, 255, 171, alpha), rl.Color(35, 149, 255, alpha)

  def _draw_gradient_background(self, rect):
    start_color, end_color = self._get_gradient_colors()
    rl.draw_rectangle_gradient_h(int(rect.x), int(rect.y), int(rect.width), int(rect.height),
                                 start_color, end_color)

  def _render(self, rect):
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    self._draw_gradient_background(rect)
    rl.draw_rectangle_rounded_lines_ex(self._rect, 0.19, 10, 5, rl.BLACK)
    rl.end_scissor_mode()

    # Draw vertical separator line
    line_x = rect.x + rect.width - self.img_width - (2 * self.horizontal_padding)
    separator_color = rl.Color(0, 0, 0, 77)  # 0x4d = 77
    rl.draw_line_ex(rl.Vector2(line_x, rect.y), rl.Vector2(line_x, rect.y + rect.height), 3, separator_color)

    # Draw text label (left aligned)
    if not self.alpha_longitudinal_enabled:
      text = tr("STOCK ACC")
      font_size = 45
    else:
      if self.experimental_mode and self.iq_dynamic_mode:
        text = tr("IQ.DYNAMIC")
      elif self.experimental_mode:
        text = tr("IQ.PILOT")
      else:
        text = tr("IQ.STANDARD")
      font_size = 45

    text_x = rect.x + self.horizontal_padding
    text_y = rect.y + rect.height / 2 - font_size * FONT_SCALE // 2  # Center vertically

    rl.draw_text_ex(gui_app.font(FontWeight.NORMAL), text, rl.Vector2(int(text_x), int(text_y)), font_size, 0, rl.BLACK)

    # Draw icon (right aligned)
    icon_x = rect.x + rect.width - self.horizontal_padding - self.img_width
    icon_y = rect.y + (rect.height - self.img_width) / 2
    icon_rect = rl.Rectangle(icon_x, icon_y, self.img_width, self.img_width)

    # Draw current mode icon
    if not self.alpha_longitudinal_enabled:
      current_icon = self.chill_pixmap
    else:
      current_icon = self.experimental_pixmap if self.experimental_mode else self.chill_pixmap
    source_rect = rl.Rectangle(0, 0, current_icon.width, current_icon.height)
    rl.draw_texture_pro(current_icon, source_rect, icon_rect, rl.Vector2(0, 0), 0, rl.WHITE)

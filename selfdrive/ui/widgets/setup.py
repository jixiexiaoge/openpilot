import math
import pyray as rl
from openpilot.common.time_helpers import system_time_valid
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.widgets.pairing_dialog import PairingDialog
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
from openpilot.system.ui.widgets.button import Button, ButtonStyle

SETUP_CARD_BG = rl.Color(34, 36, 42, 255)
SETUP_CARD_BORDER = rl.Color(255, 255, 255, 26)
SETUP_ACCENT = rl.Color(16, 185, 169, 255)


class SetupWidget(Widget):
  def __init__(self):
    super().__init__()
    self._pairing_dialog: PairingDialog | None = None
    self._pair_device_btn = Button(lambda: tr("Pair device"), self._show_pairing, button_style=ButtonStyle.PRIMARY)

  def _render(self, rect: rl.Rectangle):
    if not ui_state.prime_state.is_paired():
      self._render_registration(rect)

  def _render_registration(self, rect: rl.Rectangle):
    """Render registration prompt."""

    t = rl.get_time()
    pulse = 0.5 + 0.5 * math.sin(t * 2.3)
    glow_alpha = int(24 + pulse * 34)
    border_alpha = int(28 + pulse * 38)

    glow_rect = rl.Rectangle(rect.x - 4, rect.y - 4, rect.width + 8, rect.height + 8)
    rl.draw_rectangle_rounded_lines_ex(glow_rect, 0.06, 24, 5, rl.Color(SETUP_ACCENT.r, SETUP_ACCENT.g, SETUP_ACCENT.b, glow_alpha))
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y, rect.width, rect.height), 0.06, 24, SETUP_CARD_BG)
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(rect.x, rect.y, rect.width, rect.height), 0.06, 24, 2, SETUP_CARD_BORDER)
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(rect.x, rect.y, rect.width, rect.height), 0.06, 24, 2,
                                       rl.Color(SETUP_ACCENT.r, SETUP_ACCENT.g, SETUP_ACCENT.b, border_alpha))

    x = rect.x + 64
    w = rect.width - 128

    font = gui_app.font(FontWeight.BOLD)
    title = tr("Finish Setup")
    title_size = measure_text_cached(font, title, 75)
    desc = tr("Pair your device in the Konn3kt app.")
    light_font = gui_app.font(FontWeight.NORMAL)
    wrapped = wrap_text(light_font, desc, 50, int(w))

    desc_line_h = 50 * FONT_SCALE
    content_h = title_size.y + 38 + len(wrapped) * desc_line_h + 30 + 200
    y = rect.y + (rect.height - content_h) / 2 - 44

    title_x = x + (w - title_size.x) / 2
    rl.draw_text_ex(font, title, rl.Vector2(int(title_x), int(y)), 75, 0, rl.WHITE)
    y += title_size.y + 38

    for line in wrapped:
      line_size = measure_text_cached(light_font, line, 50)
      line_x = x + (w - line_size.x) / 2
      rl.draw_text_ex(light_font, line, rl.Vector2(int(line_x), int(y)), 50, 0, rl.WHITE)
      y += desc_line_h

    button_rect = rl.Rectangle(x, y + 30, w, 200)
    cta_glow = rl.Rectangle(button_rect.x - 8, button_rect.y - 8, button_rect.width + 16, button_rect.height + 16)
    rl.draw_rectangle_rounded(cta_glow, 0.5, 24, rl.Color(SETUP_ACCENT.r, SETUP_ACCENT.g, SETUP_ACCENT.b, int(16 + pulse * 20)))
    self._pair_device_btn.render(button_rect)

  def _show_pairing(self):
    if not system_time_valid():
      dlg = alert_dialog(tr("Please connect to Wi-Fi to complete initial pairing"))
      gui_app.set_modal_overlay(dlg)
      return

    if not self._pairing_dialog:
      self._pairing_dialog = PairingDialog()
    gui_app.set_modal_overlay(self._pairing_dialog, lambda result: setattr(self, '_pairing_dialog', None))

  def __del__(self):
    if self._pairing_dialog:
      del self._pairing_dialog

import pyray as rl
from openpilot.system.ui.lib.application import FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.scroller_tici import Scroller

# Constants
MARGIN = 50
TITLE_FONT_SIZE = 70
ITEM_HEIGHT = 135
BUTTON_SPACING = 50
BUTTON_HEIGHT = 160
ITEM_SPACING = 50
LIST_ITEM_SPACING = 25

TEAL = rl.Color(16, 185, 169, 255)
OPTION_RADIUS = 28
DIALOG_BTN_RADIUS = 44
DISABLED_BTN_COLOR = rl.Color(45, 47, 52, 255)


def _latin_only(s: str) -> bool:
  # Names within Latin + Latin-1 + Latin Extended-A render cleanly in the normal UI font.
  return all(ord(c) < 0x250 for c in s)


class _OptionButton(Button):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.selected = False
    self._border_radius = OPTION_RADIUS

  def _render(self, _):
    if self.selected:
      roundness = self._border_radius / (min(self._rect.width, self._rect.height) / 2)
      rl.draw_rectangle_rounded(self._rect, roundness, 10, TEAL)
      self._label.render(self._rect)
    else:
      super()._render(_)


class MultiOptionDialog(Widget):
  def __init__(self, title, options, current="", option_font_weight=FontWeight.MEDIUM):
    super().__init__()
    self.title = title
    self.options = options
    self.current = current
    self.selection = current
    self._result: DialogResult = DialogResult.NO_ACTION

    # Create scroller with option buttons. Latin names use the normal font; everything
    # else (CJK, Cyrillic, Arabic, ...) keeps the broad-coverage font passed by the caller.
    self.option_buttons = [_OptionButton(option, click_callback=lambda opt=option: self._on_option_clicked(opt),
                                         font_weight=(FontWeight.MEDIUM if _latin_only(option) else option_font_weight),
                                         text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT, button_style=ButtonStyle.NORMAL,
                                         text_padding=50, elide_right=True) for option in options]
    self.scroller = Scroller(self.option_buttons, spacing=LIST_ITEM_SPACING)

    self.cancel_button = Button(lambda: tr("Cancel"), click_callback=lambda: self._set_result(DialogResult.CANCEL))
    self.select_button = Button(lambda: tr("Select"), click_callback=lambda: self._set_result(DialogResult.CONFIRM),
                                button_style=ButtonStyle.TRANSPARENT_WHITE_TEXT)
    self.cancel_button._border_radius = DIALOG_BTN_RADIUS
    self.select_button._border_radius = DIALOG_BTN_RADIUS

  def _set_result(self, result: DialogResult):
    self._result = result

  def _on_option_clicked(self, option):
    self.selection = option

  def _render(self, rect):
    dialog_rect = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - 2 * MARGIN, rect.height - 2 * MARGIN)
    rl.draw_rectangle_rounded(dialog_rect, 0.02, 20, rl.Color(30, 30, 30, 255))

    content_rect = rl.Rectangle(dialog_rect.x + MARGIN, dialog_rect.y + MARGIN,
                                dialog_rect.width - 2 * MARGIN, dialog_rect.height - 2 * MARGIN)

    gui_label(rl.Rectangle(content_rect.x, content_rect.y, content_rect.width, TITLE_FONT_SIZE), self.title, 70, font_weight=FontWeight.BOLD)

    # Options area
    options_y = content_rect.y + TITLE_FONT_SIZE + ITEM_SPACING
    options_h = content_rect.height - TITLE_FONT_SIZE - BUTTON_HEIGHT - 2 * ITEM_SPACING
    options_rect = rl.Rectangle(content_rect.x, options_y, content_rect.width, options_h)

    # Mark the selected option (teal highlight handled by _OptionButton)
    for i, option in enumerate(self.options):
      self.option_buttons[i].selected = (option == self.selection)
      self.option_buttons[i].set_rect(rl.Rectangle(0, 0, options_rect.width, ITEM_HEIGHT))

    self.scroller.render(options_rect)

    # Buttons
    button_y = content_rect.y + content_rect.height - BUTTON_HEIGHT
    button_w = (content_rect.width - BUTTON_SPACING) / 2

    cancel_rect = rl.Rectangle(content_rect.x, button_y, button_w, BUTTON_HEIGHT)
    self.cancel_button.render(cancel_rect)

    select_rect = rl.Rectangle(content_rect.x + button_w + BUTTON_SPACING, button_y, button_w, BUTTON_HEIGHT)
    select_enabled = self.selection != self.current
    self.select_button.set_enabled(select_enabled)
    sr = DIALOG_BTN_RADIUS / (min(select_rect.width, select_rect.height) / 2)
    rl.draw_rectangle_rounded(select_rect, sr, 10, TEAL if select_enabled else DISABLED_BTN_COLOR)
    self.select_button.render(select_rect)

    return self._result

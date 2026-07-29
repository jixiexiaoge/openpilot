import random
import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.selfdrive.ui.lib.motd import load_motds
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget

PANEL_BG    = rl.Color(34, 36, 42, 255)
PANEL_BORDER = rl.Color(255, 255, 255, 26)
TEAL_DIM    = rl.Color(16, 185, 169, 22)
TEXT_COLOR  = rl.Color(235, 235, 235, 255)
LABEL_COLOR = rl.Color(16, 185, 169, 255)


def _load_messages() -> list[str]:
    msgs = load_motds()
    random.shuffle(msgs)
    return msgs


class InspireWidget(Widget):
    def __init__(self):
        super().__init__()
        self._messages = _load_messages()
        self._idx = 0
        self._current: str = self._messages[0] if self._messages else "Drive safely. Stay focused."

    def _pick(self):
        if not self._messages:
            self._messages = _load_messages()
            self._idx = 0
        if self._messages:
            self._current = self._messages[self._idx % len(self._messages)]
            self._idx += 1

    def show_event(self):
        self._pick()

    def _render(self, rect: rl.Rectangle):
        rl.draw_rectangle_rounded(rect, 0.06, 24, PANEL_BG)
        rl.draw_rectangle_rounded_lines_ex(rect, 0.06, 24, 2, PANEL_BORDER)

        cx = rect.x + rect.width / 2
        cy = rect.y + rect.height / 2

        font = gui_app.font(FontWeight.MEDIUM)
        font_label = gui_app.font(FontWeight.BOLD)

        TEXT_FS = 52
        LABEL_FS = 24
        LABEL_H = 48
        max_w = int(rect.width - 80)

        wrapped = wrap_text(font, self._current, TEXT_FS, max_w)
        line_h = int(TEXT_FS * 1.3)
        total_text_h = len(wrapped) * line_h

        text_block_cy = cy - LABEL_H / 2
        text_y = text_block_cy - total_text_h / 2

        for i, line in enumerate(wrapped):
            lw = measure_text_cached(font, line, TEXT_FS).x
            rl.draw_text_ex(font, line,
                            rl.Vector2(int(cx - lw / 2), int(text_y + i * line_h)),
                            TEXT_FS, 0, TEXT_COLOR)

        label = "DAILY INSPIRATION"
        LABEL_SPACING = 3
        lw = measure_text_cached(font_label, label, LABEL_FS).x + len(label) * LABEL_SPACING
        label_x = int(cx - lw / 2)
        label_y = int(rect.y + rect.height - LABEL_H - 8)

        pill = rl.Rectangle(label_x - 20, label_y - 8, lw + 40, LABEL_FS + 16)
        rl.draw_rectangle_rounded(pill, 0.5, 12, TEAL_DIM)
        rl.draw_text_ex(font_label, label,
                        rl.Vector2(label_x, label_y),
                        LABEL_FS, LABEL_SPACING, LABEL_COLOR)

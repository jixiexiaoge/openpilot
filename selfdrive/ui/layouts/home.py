import time
import os
import pyray as rl
from collections.abc import Callable
from enum import IntEnum
from openpilot.common.params import Params
from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.widgets.offroad_alerts import UpdateAlert, OffroadAlert
from openpilot.selfdrive.ui.widgets.exp_mode_button import ExperimentalModeButton
from openpilot.selfdrive.ui.widgets.prime import PrimeWidget
from openpilot.selfdrive.ui.widgets.setup import SetupWidget
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr, trn
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle

HEADER_HEIGHT = 80
HEAD_BUTTON_FONT_SIZE = 40
CONTENT_MARGIN = 40
SPACING = 25
RIGHT_COLUMN_WIDTH = 750
REFRESH_INTERVAL = 10.0
CHANGELOG_REFRESH_INTERVAL = 15.0


class ChangelogWidget(Widget):
  PANEL_BG_COLOR = rl.Color(51, 51, 51, 255)
  BODY_COLOR = rl.Color(235, 235, 235, 255)
  HEADING_COLOR = rl.Color(255, 255, 255, 255)

  def __init__(self):
    super().__init__()
    self._show_all = False
    self._latest_text = ""
    self._all_text = ""
    self._render_latest: list[dict] = []
    self._render_all: list[dict] = []
    self._wrap_width = 0
    self._last_load = 0.0
    self._scroll_px = 0.0
    self._max_scroll = 0.0
    self._is_dragging = False
    self._drag_last_y = 0.0
    self._text_rect = rl.Rectangle(0, 0, 0, 0)
    self._btn_rect = rl.Rectangle(0, 0, 0, 0)
    self._latest_btn = Button("Latest", self._show_latest, button_style=ButtonStyle.PRIMARY, font_size=28)
    self._all_btn = Button("All", self._show_all_logs, button_style=ButtonStyle.NORMAL, font_size=28)
    self._load_changelog(force=True)

  def show_event(self):
    self._load_changelog(force=True)

  def _show_latest(self) -> None:
    self._show_all = False
    self._scroll_px = 0.0
    self._is_dragging = False

  def _show_all_logs(self) -> None:
    self._show_all = True
    self._scroll_px = 0.0
    self._is_dragging = False

  def _load_changelog(self, force: bool = False) -> None:
    now = time.monotonic()
    if not force and (now - self._last_load) < CHANGELOG_REFRESH_INTERVAL:
      return
    self._last_load = now

    paths = [os.path.join(BASEDIR, "CHANGELOG.md"), os.path.join(BASEDIR, "changelog.md")]
    content = ""
    for p in paths:
      try:
        with open(p, encoding="utf-8") as f:
          content = f.read().strip()
          if content:
            break
      except OSError:
        pass

    if not content:
      content = "No changelog found.\n\nAdd CHANGELOG.md to the project root."

    ordered = self._reorder_sections_newest_first(content)
    self._latest_text = self._build_latest_text(ordered)
    self._all_text = ordered
    self._render_latest = []
    self._render_all = []
    self._wrap_width = 0

  def _reorder_sections_newest_first(self, content: str) -> str:
    lines = content.splitlines()
    intro: list[str] = []
    sections: list[list[str]] = []
    current: list[str] | None = None

    for line in lines:
      if line.startswith("## "):
        if current is not None:
          sections.append(current)
        current = [line]
      else:
        if current is None:
          intro.append(line)
        else:
          current.append(line)

    if current is not None:
      sections.append(current)

    out: list[str] = []
    if intro:
      out.extend(intro)
      out.append("")

    for i, section in enumerate(reversed(sections)):
      out.extend(section)
      if i != len(sections) - 1:
        out.append("")

    return "\n".join(out).strip()

  def _build_latest_text(self, content: str) -> str:
    lines = content.splitlines()
    if not lines:
      return "No updates available."

    out: list[str] = []
    section_count = 0
    for line in lines:
      if line.startswith("## "):
        section_count += 1
        if section_count > 2:
          break
      out.append(line)
    return "\n".join(out).strip() or content

  @staticmethod
  def _clean_inline_markdown(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()

  def _build_render_lines(self, text: str, width: int) -> list[dict]:
    lines: list[dict] = []
    for raw in text.splitlines():
      stripped = raw.strip()
      if not stripped:
        lines.append({"text": "", "font_size": 16, "font_weight": FontWeight.NORMAL, "indent": 0, "color": self.BODY_COLOR, "height": 18})
        continue

      font_size = 34
      font_weight = FontWeight.NORMAL
      indent = 0
      color = self.BODY_COLOR
      text_line = stripped
      extra_spacing = 0

      if stripped.startswith("### "):
        text_line = self._clean_inline_markdown(stripped[4:])
        font_size = 34
        font_weight = FontWeight.BOLD
        color = self.HEADING_COLOR
        extra_spacing = 8
      elif stripped.startswith("## "):
        text_line = self._clean_inline_markdown(stripped[3:])
        font_size = 38
        font_weight = FontWeight.BOLD
        color = self.HEADING_COLOR
        extra_spacing = 10
      elif stripped.startswith("# "):
        text_line = self._clean_inline_markdown(stripped[2:])
        font_size = 42
        font_weight = FontWeight.BOLD
        color = self.HEADING_COLOR
        extra_spacing = 12
      elif stripped.startswith("- ") or stripped.startswith("* "):
        text_line = "• " + self._clean_inline_markdown(stripped[2:])
        font_size = 34
        indent = 8
      else:
        text_line = self._clean_inline_markdown(stripped)

      font = gui_app.font(font_weight)
      wrapped = wrap_text(font, text_line, font_size, max(50, width - indent))
      if not wrapped:
        wrapped = [text_line]

      for i, w in enumerate(wrapped):
        line_indent = indent if i == 0 else indent + 18
        line_h = int(font_size * 1.15)
        lines.append({
          "text": w,
          "font_size": font_size,
          "font_weight": font_weight,
          "indent": line_indent,
          "color": color,
          "height": line_h,
        })

      if extra_spacing > 0:
        lines.append({"text": "", "font_size": extra_spacing, "font_weight": FontWeight.NORMAL, "indent": 0, "color": self.BODY_COLOR, "height": extra_spacing})

    return lines

  def _ensure_wrapped(self, text_w: int):
    if text_w <= 0:
      return
    if self._wrap_width == text_w and self._render_latest and self._render_all:
      return
    self._wrap_width = text_w
    self._render_latest = self._build_render_lines(self._latest_text, text_w)
    self._render_all = self._build_render_lines(self._all_text, text_w)

  @staticmethod
  def _total_height(lines: list[dict]) -> int:
    return sum(line["height"] for line in lines)

  def _clamp_scroll(self):
    self._scroll_px = max(0.0, min(self._max_scroll, self._scroll_px))

  def _handle_mouse_press(self, mouse_pos: MousePos):
    if rl.check_collision_point_rec(mouse_pos, self._text_rect):
      self._is_dragging = True
      self._drag_last_y = mouse_pos.y

  def _handle_mouse_event(self, mouse_event):
    if not self._is_dragging or not mouse_event.left_down:
      return
    dy = mouse_event.pos.y - self._drag_last_y
    self._drag_last_y = mouse_event.pos.y
    self._scroll_px -= dy
    self._clamp_scroll()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    self._is_dragging = False

  def _render(self, rect: rl.Rectangle):
    self._load_changelog()
    rl.draw_rectangle_rounded(rect, 0.03, 20, self.PANEL_BG_COLOR)

    title_rect = rl.Rectangle(rect.x + 36, rect.y + 24, rect.width - 72, 50)
    gui_label(title_rect, "Latest Updates", 44, rl.WHITE, font_weight=FontWeight.BOLD, alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT)

    btn_w = 150
    btn_h = 54
    btn_gap = 12
    self._btn_rect = rl.Rectangle(rect.x + rect.width - (btn_w * 2) - btn_gap - 36, rect.y + 84, (btn_w * 2) + btn_gap, btn_h)
    latest_rect = rl.Rectangle(self._btn_rect.x, self._btn_rect.y, btn_w, btn_h)
    all_rect = rl.Rectangle(self._btn_rect.x + btn_w + btn_gap, self._btn_rect.y, btn_w, btn_h)

    self._latest_btn.set_button_style(ButtonStyle.PRIMARY if not self._show_all else ButtonStyle.NORMAL)
    self._all_btn.set_button_style(ButtonStyle.PRIMARY if self._show_all else ButtonStyle.NORMAL)
    self._latest_btn.render(latest_rect)
    self._all_btn.render(all_rect)

    self._text_rect = rl.Rectangle(rect.x + 36, rect.y + 154, rect.width - 72, rect.height - 182)
    self._ensure_wrapped(int(self._text_rect.width))

    lines = self._render_all if self._show_all else self._render_latest
    total_h = self._total_height(lines)
    self._max_scroll = max(0.0, total_h - self._text_rect.height)
    self._clamp_scroll()

    # Clip content region and draw formatted lines
    rl.begin_scissor_mode(int(self._text_rect.x), int(self._text_rect.y), int(self._text_rect.width), int(self._text_rect.height))
    y = self._text_rect.y - self._scroll_px
    for line in lines:
      line_h = line["height"]
      if line["text"] and (y + line_h) >= self._text_rect.y and y <= (self._text_rect.y + self._text_rect.height):
        font = gui_app.font(line["font_weight"])
        x = self._text_rect.x + line["indent"]
        rl.draw_text_ex(font, line["text"], rl.Vector2(x, y), line["font_size"], 0, line["color"])
      y += line_h
    rl.end_scissor_mode()

    if self._max_scroll > 0.0:
      hint = "Drag to scroll"
      hint_size = measure_text_cached(gui_app.font(FontWeight.NORMAL), hint, 24)
      hint_x = self._text_rect.x + self._text_rect.width - hint_size.x
      hint_y = rect.y + rect.height - 12 - hint_size.y
      rl.draw_text_ex(gui_app.font(FontWeight.NORMAL), hint, rl.Vector2(hint_x, hint_y), 24, 0, rl.Color(180, 180, 180, 220))


def _format_updater_description(description: str | None) -> str:
  brand = "IQ.Pilot"
  if not description:
    return brand

  cleaned = description.strip()
  lower = cleaned.lower()
  if lower.startswith("iqpilot"):
    cleaned = cleaned[len("iqpilot"):].lstrip(" -:/")

  if cleaned.lower().startswith(brand.lower()):
    return cleaned
  return f"{brand} {cleaned}" if cleaned else brand


class HomeLayoutState(IntEnum):
  HOME = 0
  UPDATE = 1
  ALERTS = 2


class HomeLayout(Widget):
  def __init__(self):
    super().__init__()
    self.params = Params()

    self.update_alert = UpdateAlert()
    self.offroad_alert = OffroadAlert()

    self._layout_widgets = {HomeLayoutState.UPDATE: self.update_alert, HomeLayoutState.ALERTS: self.offroad_alert}

    self.current_state = HomeLayoutState.HOME
    self.last_refresh = 0
    self.settings_callback: Callable[[], None] | None = None

    self.update_available = False
    self.alert_count = 0
    self._version_text = ""
    self._prev_update_available = False
    self._prev_alerts_present = False

    self.header_rect = rl.Rectangle(0, 0, 0, 0)
    self.content_rect = rl.Rectangle(0, 0, 0, 0)
    self.left_column_rect = rl.Rectangle(0, 0, 0, 0)
    self.right_column_rect = rl.Rectangle(0, 0, 0, 0)

    self.update_notif_rect = rl.Rectangle(0, 0, 200, HEADER_HEIGHT - 10)
    self.alert_notif_rect = rl.Rectangle(0, 0, 220, HEADER_HEIGHT - 10)

    self._prime_widget = PrimeWidget()
    self._setup_widget = SetupWidget()
    self._changelog_widget = ChangelogWidget()

    self._exp_mode_button = ExperimentalModeButton()
    self._setup_callbacks()

  def show_event(self):
    self._exp_mode_button.show_event()
    self._changelog_widget.show_event()
    self.last_refresh = time.monotonic()
    self._refresh()

  def _setup_callbacks(self):
    self.update_alert.set_dismiss_callback(lambda: self._set_state(HomeLayoutState.HOME))
    self.offroad_alert.set_dismiss_callback(lambda: self._set_state(HomeLayoutState.HOME))
    self._exp_mode_button.set_click_callback(lambda: self.settings_callback() if self.settings_callback else None)

  def set_settings_callback(self, callback: Callable):
    self.settings_callback = callback

  def _set_state(self, state: HomeLayoutState):
    # propagate show/hide events
    if state != self.current_state:
      if state == HomeLayoutState.HOME:
        self._exp_mode_button.show_event()

      if state in self._layout_widgets:
        self._layout_widgets[state].show_event()
      if self.current_state in self._layout_widgets:
        self._layout_widgets[self.current_state].hide_event()

    self.current_state = state

  def _render(self, rect: rl.Rectangle):
    current_time = time.monotonic()
    if current_time - self.last_refresh >= REFRESH_INTERVAL:
      self._refresh()
      self.last_refresh = current_time

    self._render_header()

    # Render content based on current state
    if self.current_state == HomeLayoutState.HOME:
      self._render_home_content()
    elif self.current_state == HomeLayoutState.UPDATE:
      self._render_update_view()
    elif self.current_state == HomeLayoutState.ALERTS:
      self._render_alerts_view()

  def _update_state(self):
    self.header_rect = rl.Rectangle(
      self._rect.x + CONTENT_MARGIN, self._rect.y + CONTENT_MARGIN, self._rect.width - 2 * CONTENT_MARGIN, HEADER_HEIGHT
    )

    content_y = self._rect.y + CONTENT_MARGIN + HEADER_HEIGHT + SPACING
    content_height = self._rect.height - CONTENT_MARGIN - HEADER_HEIGHT - SPACING - CONTENT_MARGIN

    self.content_rect = rl.Rectangle(
      self._rect.x + CONTENT_MARGIN, content_y, self._rect.width - 2 * CONTENT_MARGIN, content_height
    )

    right_width = min(880, self.content_rect.width * 0.45)
    left_width = self.content_rect.width - right_width - SPACING

    self.left_column_rect = rl.Rectangle(self.content_rect.x, self.content_rect.y, left_width, self.content_rect.height)

    self.right_column_rect = rl.Rectangle(
      self.content_rect.x + left_width + SPACING, self.content_rect.y, right_width, self.content_rect.height
    )

    self.update_notif_rect.x = self.header_rect.x
    self.update_notif_rect.y = self.header_rect.y + (self.header_rect.height - 60) // 2

    notif_x = self.header_rect.x + (220 if self.update_available else 0)
    self.alert_notif_rect.x = notif_x
    self.alert_notif_rect.y = self.header_rect.y + (self.header_rect.height - 60) // 2

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)

    if self.update_available and rl.check_collision_point_rec(mouse_pos, self.update_notif_rect):
      self._set_state(HomeLayoutState.UPDATE)
    elif self.alert_count > 0 and rl.check_collision_point_rec(mouse_pos, self.alert_notif_rect):
      self._set_state(HomeLayoutState.ALERTS)

  def _render_header(self):
    font = gui_app.font(FontWeight.MEDIUM)

    version_text_width = self.header_rect.width

    # Update notification button
    if self.update_available:
      version_text_width -= self.update_notif_rect.width

      # Highlight if currently viewing updates
      highlight_color = rl.Color(75, 95, 255, 255) if self.current_state == HomeLayoutState.UPDATE else rl.Color(54, 77, 239, 255)
      rl.draw_rectangle_rounded(self.update_notif_rect, 0.3, 10, highlight_color)

      text = tr("UPDATE")
      text_size = measure_text_cached(font, text, HEAD_BUTTON_FONT_SIZE)
      text_x = self.update_notif_rect.x + (self.update_notif_rect.width - text_size.x) // 2
      text_y = self.update_notif_rect.y + (self.update_notif_rect.height - text_size.y) // 2
      rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), HEAD_BUTTON_FONT_SIZE, 0, rl.WHITE)

    # Alert notification button
    if self.alert_count > 0:
      version_text_width -= self.alert_notif_rect.width

      # Highlight if currently viewing alerts
      highlight_color = rl.Color(255, 70, 70, 255) if self.current_state == HomeLayoutState.ALERTS else rl.Color(226, 44, 44, 255)
      rl.draw_rectangle_rounded(self.alert_notif_rect, 0.3, 10, highlight_color)

      alert_text = trn("{} ALERT", "{} ALERTS", self.alert_count).format(self.alert_count)
      text_size = measure_text_cached(font, alert_text, HEAD_BUTTON_FONT_SIZE)
      text_x = self.alert_notif_rect.x + (self.alert_notif_rect.width - text_size.x) // 2
      text_y = self.alert_notif_rect.y + (self.alert_notif_rect.height - text_size.y) // 2
      rl.draw_text_ex(font, alert_text, rl.Vector2(int(text_x), int(text_y)), HEAD_BUTTON_FONT_SIZE, 0, rl.WHITE)

    # Version text (right aligned)
    if self.update_available or self.alert_count > 0:
      version_text_width -= SPACING * 1.5

    version_rect = rl.Rectangle(self.header_rect.x + self.header_rect.width - version_text_width, self.header_rect.y,
                                version_text_width, self.header_rect.height)
    gui_label(version_rect, self._version_text, 48, rl.WHITE, alignment=rl.GuiTextAlignment.TEXT_ALIGN_RIGHT)

  def _render_home_content(self):
    self._render_left_column()
    self._render_right_column()

  def _render_update_view(self):
    self.update_alert.render(self.content_rect)

  def _render_alerts_view(self):
    self.offroad_alert.render(self.content_rect)

  def _render_left_column(self):
    self._prime_widget.render(self.left_column_rect)

  def _render_right_column(self):
    exp_height = 125
    exp_rect = rl.Rectangle(
      self.right_column_rect.x, self.right_column_rect.y, self.right_column_rect.width, exp_height
    )
    self._exp_mode_button.render(exp_rect)

    setup_rect = rl.Rectangle(
      self.right_column_rect.x,
      self.right_column_rect.y + exp_height + SPACING,
      self.right_column_rect.width,
      self.right_column_rect.height - exp_height - SPACING,
    )
    if ui_state.prime_state.is_paired():
      self._changelog_widget.render(setup_rect)
    else:
      self._setup_widget.render(setup_rect)

  def _refresh(self):
    self._version_text = self._get_version_text()
    update_available = self.update_alert.refresh()
    alert_count = self.offroad_alert.refresh()
    alerts_present = alert_count > 0

    # Show panels on transition from no alert/update to any alerts/update
    if not update_available and not alerts_present:
      self._set_state(HomeLayoutState.HOME)
    elif update_available and ((not self._prev_update_available) or (not alerts_present and self.current_state == HomeLayoutState.ALERTS)):
      self._set_state(HomeLayoutState.UPDATE)
    elif alerts_present and ((not self._prev_alerts_present) or (not update_available and self.current_state == HomeLayoutState.UPDATE)):
      self._set_state(HomeLayoutState.ALERTS)

    self.update_available = update_available
    self.alert_count = alert_count
    self._prev_update_available = update_available
    self._prev_alerts_present = alerts_present

  def _get_version_text(self) -> str:
    description = self.params.get("UpdaterCurrentDescription")
    return _format_updater_description(description)

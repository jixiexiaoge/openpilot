import pyray as rl
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import MiciLabel
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from dragonpilot.selfdrive.ui.dashy_qr import DashyQR


class DashyQRCode(Widget):
  def __init__(self):
    super().__init__()
    self._qr = DashyQR()

    self._title_label = MiciLabel(tr("scan to access"), font_size=32, font_weight=FontWeight.BOLD,
                                  color=rl.WHITE, wrap_text=True)
    self._subtitle_label = MiciLabel("dashy", font_size=48, font_weight=FontWeight.DISPLAY,
                                     color=rl.WHITE)
    self._or_label = MiciLabel(tr("or open browser"), font_size=24, font_weight=FontWeight.NORMAL,
                               color=rl.GRAY)
    self._url_label = MiciLabel("", font_size=24, font_weight=FontWeight.NORMAL,
                                color=rl.GRAY, wrap_text=True)

  def show_event(self):
    self._qr.force_update()

  def _render(self, rect: rl.Rectangle):
    # Skip if off-screen (scroller renders all items, add small buffer for float precision)
    if rect.x + rect.width < 1 or rect.x > gui_app.width - 1:
      return

    if self._qr.update():
      self._url_label.set_text(self._qr.url or "")

    # Left side: QR code (square, full height)
    if self._qr.texture:
      scale = rect.height / self._qr.texture.height
      pos = rl.Vector2(rect.x, rect.y)
      rl.draw_texture_ex(self._qr.texture, pos, 0.0, scale, rl.WHITE)

    # Right side: Text
    text_x = rect.x + rect.height + 16
    text_width = int(rect.width - text_x)

    # Title: "scan to access"
    self._title_label.set_width(text_width)
    self._title_label.set_position(text_x, rect.y)
    self._title_label.render()

    # Subtitle: "dashy"
    self._subtitle_label.set_position(text_x, rect.y + 32)
    self._subtitle_label.render()

    # "or open browser"
    self._or_label.set_position(text_x, rect.y + rect.height - 24 - 28)
    self._or_label.render()

    # URL
    self._url_label.set_width(text_width)
    self._url_label.set_position(text_x, rect.y + rect.height - 24)
    self._url_label.render()

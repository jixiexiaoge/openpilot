import pyray as rl
from collections.abc import Callable

from openpilot.iqpilot.ui.layouts.settings.trips import TripsLayout
from openpilot.selfdrive.ui.widgets.screen_header import ScreenHeader, HEADER_HEIGHT
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget

MARGIN = 40
SPACING = 25


class StatsLayout(Widget):
  """Offroad Stats screen: drive stats (miles / time / routes) with a back header."""

  def __init__(self):
    super().__init__()
    self._header = self._child(ScreenHeader(tr("Stats")))
    self._trips = self._child(TripsLayout())

  def set_on_back(self, cb: Callable[[], None]) -> None:
    self._header.set_on_back(cb)

  def _render(self, rect: rl.Rectangle):
    header_rect = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - 2 * MARGIN, HEADER_HEIGHT)
    self._header.render(header_rect)

    content_y = header_rect.y + HEADER_HEIGHT + SPACING
    content_rect = rl.Rectangle(
      rect.x + MARGIN, content_y, rect.width - 2 * MARGIN, rect.y + rect.height - content_y - MARGIN
    )
    self._trips.render(content_rect)

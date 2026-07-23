"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from openpilot.common.params import Params, UnknownKeyName
from openpilot.selfdrive.ui.mici.widgets.stock_button import BigButton, BigMultiToggle, BigToggle, BigParamControl


class SafeParamControl(BigParamControl):
  """BigParamControl that tolerates a param missing from the COMPILED params registry.

  A key added to params_keys.h only exists at runtime once params_pyx.so is rebuilt; a
  .py-only / stale prebuilt deploy leaves get_bool/put_bool raising UnknownKeyName, which
  would crash the UI on construction. Default to `default_on` for display and no-op the
  write instead of crashing — mirrors the plannerd defensive read in long_mpc.py.
  """

  def __init__(self, text: str, param: str, default_on: bool = True, toggle_callback=None):
    self._default_on = default_on
    BigToggle.__init__(self, text, "", toggle_callback=toggle_callback)
    self.param = param
    self.params = Params()
    self.set_checked(self._safe_get())

  def _safe_get(self) -> bool:
    try:
      return self.params.get_bool(self.param)
    except UnknownKeyName:
      return self._default_on

  def refresh(self):
    self.set_checked(self._safe_get())

  def _handle_mouse_release(self, mouse_pos):
    BigToggle._handle_mouse_release(self, mouse_pos)
    try:
      self.params.put_bool(self.param, self._checked)
    except UnknownKeyName:
      pass


class MappedParamToggle(BigMultiToggle):
  """Multi-option toggle whose options map to arbitrary param values (int or float, drum-style).

  Up to PILL_LIMIT options render as the stock vertical pill column; more options would
  overflow the box, so they instead show the current value as a sub-label and cycle on tap.
  """
  PILL_LIMIT = 4

  def __init__(self, text: str, param: str, options: list[str], values: list | None = None):
    super().__init__(text, options)
    self._param = param
    self._values = values if values is not None else list(range(len(options)))
    self._params = Params()
    self.refresh()

  def _value_only(self) -> bool:
    return len(self._options) > self.PILL_LIMIT

  def _width_hint(self) -> int:
    if self._value_only():
      return BigButton._width_hint(self)
    return super()._width_hint()

  def _draw_content(self, btn_x: float, btn_y: float, btn_width: float, btn_height: float):
    if self._value_only():
      BigButton._draw_content(self, btn_x, btn_y, btn_width, btn_height)
    else:
      super()._draw_content(btn_x, btn_y, btn_width, btn_height)

  def refresh(self):
    try:
      raw = self._params.get(self._param, return_default=True)
    except UnknownKeyName:
      raw = self._values[0]
    try:
      cur = float(raw)
    except (TypeError, ValueError):
      cur = float(self._values[0])
    idx = min(range(len(self._values)), key=lambda i: abs(float(self._values[i]) - cur))
    self.set_value(self._options[idx])

  def _handle_mouse_release(self, mouse_pos):
    super()._handle_mouse_release(mouse_pos)
    idx = self._options.index(self.value)
    try:
      self._params.put(self._param, self._values[idx])
    except UnknownKeyName:
      pass


class IQModeSelector(BigMultiToggle):
  """Longitudinal mode selector: Stock ACC / IQ.Standard / IQ.Dynamic / IQ.Pilot.

  A single tap cycles to the next mode and applies the matching param combo immediately.
  """
  OPTIONS = ["Stock ACC", "IQ.Standard", "IQ.Dynamic", "IQ.Pilot"]
  PERSONALITY_RELAXED = 2

  def __init__(self):
    super().__init__("IQ Mode", self.OPTIONS)
    self._params = Params()
    self.refresh()

  def _index(self) -> int:
    p = self._params
    if not p.get_bool("AlphaLongitudinalEnabled"):
      return 0
    if not p.get_bool("ExperimentalMode"):
      return 1
    return 2 if p.get_bool("IQDynamicMode") else 3

  def is_dynamic(self) -> bool:
    return self._index() == 2

  def refresh(self):
    self.set_value(self.OPTIONS[self._index()])

  def _apply(self, idx: int):
    p = self._params
    if idx == 0:
      p.put_bool("AlphaLongitudinalEnabled", False)
      p.put_bool("ExperimentalMode", False)
      p.put_bool("IQDynamicMode", False)
    elif idx == 1:
      p.put_bool("AlphaLongitudinalEnabled", True)
      p.put_bool("ExperimentalMode", False)
      p.put_bool("IQDynamicMode", False)
      p.put("LongitudinalPersonality", self.PERSONALITY_RELAXED)
    elif idx == 2:
      p.put_bool("AlphaLongitudinalEnabled", True)
      p.put_bool("ExperimentalMode", True)
      p.put_bool("IQDynamicMode", True)
    else:
      p.put_bool("AlphaLongitudinalEnabled", True)
      p.put_bool("ExperimentalMode", True)
      p.put_bool("IQDynamicMode", False)
    p.put_bool("OnroadCycleRequested", True)

  def _handle_mouse_release(self, mouse_pos):
    nxt = (self._index() + 1) % len(self.OPTIONS)
    self._apply(nxt)
    self.set_value(self.OPTIONS[nxt])

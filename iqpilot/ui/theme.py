"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

IQ.Pilot UI Theme — NeonTheme singleton
========================================
Stores the active accent/neon color as a hex string in Params["UIAccentColor"].
This allows:
  - hephaestusd to write the color via BLE/RPC from the Konn3kt companion app
  - Konn3kt-set themes to be reflected on-device in real time
  - Future per-driver theme profiles via Konn3kt

Default accent: #00FFF5 (cyan neon — the IQ.Pilot signature color)

Any UI component that wants the accent color calls:
    NeonTheme.glow()       -> rl.Color  (full brightness, inner ring)
    NeonTheme.glow_mid()   -> rl.Color  (60% alpha, mid ring)
    NeonTheme.glow_outer() -> rl.Color  (25% alpha, soft halo)
    NeonTheme.bg()         -> rl.Color  (darkened tint of accent for card bg)

Konn3kt / hephaestusd write interface:
    Params().put("UIAccentColor", "#00FFF5")   # any CSS hex string

The theme refreshes from Params every REFRESH_INTERVAL seconds so changes
propagate without a restart.
"""

import time
import pyray as rl

try:
  from openpilot.common.params import Params
except ImportError:
  Params = None

# How often (seconds) to re-read the accent color from Params
REFRESH_INTERVAL = 2.0

# IQ.Pilot default signature neon cyan
DEFAULT_ACCENT_HEX = "#00FFF5"


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
  """Parse a CSS hex color string like '#00FFF5' or '00FFF5' to (r, g, b)."""
  h = hex_str.strip().lstrip("#")
  if len(h) == 3:
    h = h[0] * 2 + h[1] * 2 + h[2] * 2
  if len(h) != 6:
    return (0x00, 0xFF, 0xF5)  # fallback to default
  try:
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
  except ValueError:
    return (0x00, 0xFF, 0xF5)


def _darken(r: int, g: int, b: int, factor: float = 0.08) -> tuple[int, int, int]:
  """Mix the accent toward black to create a card bg tint."""
  return (int(r * factor), int(g * factor), int(b * factor))


class _NeonTheme:
  """
  Singleton that holds and lazily refreshes the active neon accent color.
  All color properties are rl.Color objects ready for use in Raylib draw calls.
  """

  def __init__(self):
    self._params = Params() if Params else None
    self._last_refresh: float = 0.0
    self._hex: str = DEFAULT_ACCENT_HEX
    self._r, self._g, self._b = _hex_to_rgb(DEFAULT_ACCENT_HEX)
    self._refresh()

  # ------------------------------------------------------------------
  # Internal
  # ------------------------------------------------------------------

  def _refresh(self):
    self._last_refresh = time.monotonic()
    if self._params is None:
      return
    try:
      stored = self._params.get("UIAccentColor")
      if stored and isinstance(stored, str) and stored.strip():
        self._hex = stored.strip()
        self._r, self._g, self._b = _hex_to_rgb(self._hex)
    except Exception:
      pass  # keep previous value on any error

  def _maybe_refresh(self):
    if time.monotonic() - self._last_refresh >= REFRESH_INTERVAL:
      self._refresh()

  # ------------------------------------------------------------------
  # Public color accessors
  # ------------------------------------------------------------------

  def glow(self, alpha: int = 255) -> rl.Color:
    """Full-brightness inner glow / border color."""
    self._maybe_refresh()
    return rl.Color(self._r, self._g, self._b, alpha)

  def glow_mid(self, alpha: int = 130) -> rl.Color:
    """Mid-brightness second ring."""
    self._maybe_refresh()
    return rl.Color(self._r, self._g, self._b, alpha)

  def glow_outer(self, alpha: int = 45) -> rl.Color:
    """Soft outer halo."""
    self._maybe_refresh()
    return rl.Color(self._r, self._g, self._b, alpha)

  def bg(self) -> rl.Color:
    """Dark card background tinted with the accent color."""
    self._maybe_refresh()
    dr, dg, db = _darken(self._r, self._g, self._b, 0.08)
    # minimum darkness so the card is always readable
    dr = max(dr, 0x0A)
    dg = max(dg, 0x0A)
    db = max(db, 0x0A)
    return rl.Color(dr, dg, db, 255)

  def bg_pressed(self) -> rl.Color:
    """Slightly lighter card background for press state."""
    self._maybe_refresh()
    dr, dg, db = _darken(self._r, self._g, self._b, 0.13)
    dr = max(dr, 0x0D)
    dg = max(dg, 0x0D)
    db = max(db, 0x0D)
    return rl.Color(dr, dg, db, 255)

  @property
  def hex(self) -> str:
    """Current accent color as hex string, e.g. '#00FFF5'."""
    self._maybe_refresh()
    return self._hex

  # ------------------------------------------------------------------
  # Write interface (called by hephaestusd / Konn3kt theme handler)
  # ------------------------------------------------------------------

  def set_accent(self, hex_color: str):
    """
    Set a new accent color immediately and persist it to Params.
    hephaestusd / Konn3kt companion app should call this.

    Args:
        hex_color: CSS hex string, e.g. '#FF6B00' or '8B5CF6'
    """
    r, g, b = _hex_to_rgb(hex_color)
    self._r, self._g, self._b = r, g, b
    self._hex = "#" + hex_color.strip().lstrip("#").upper()
    self._last_refresh = time.monotonic()
    if self._params:
      try:
        self._params.put_nonblocking("UIAccentColor", self._hex)
      except Exception:
        pass


# Global singleton — import this everywhere
NeonTheme = _NeonTheme()

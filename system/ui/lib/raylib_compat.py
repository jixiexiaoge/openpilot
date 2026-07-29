"""Compatibility wrappers for raylib API differences between wheel generations.

PC dev environments install the pypi raylib 5.5 wheel, while devices ship a wheel
built from comma's raylib fork, which carries newer upstream API changes:

  - DrawCircleGradient takes a Vector2 center instead of int x/y
  - DrawRectangleGradientEx swapped its two right-corner color parameters
    (old: topLeft, bottomLeft, topRight, bottomRight
     new: topLeft, bottomLeft, bottomRight, topRight)
  - LoadFontData grew an int *glyphCount out-param and returns a compacted array
    (handled where it's used, in selfdrive/assets/fonts/process.py)

The wheel is a single snapshot, so one signature identifies the generation for all
of them. Detect it from the C function type via cffi rather than hardcoding either
variant — the pyray wrappers are *args shims and can't be introspected directly.
"""
import pyray as rl
import raylib as _raylib

_NEW_API = _raylib.ffi.typeof(_raylib.rl.DrawCircleGradient).args[0].cname != "int"


def draw_circle_gradient(center_x: float, center_y: float, radius: float, inner, outer) -> None:
  if _NEW_API:
    rl.draw_circle_gradient(rl.Vector2(center_x, center_y), radius, inner, outer)
  else:
    rl.draw_circle_gradient(int(center_x), int(center_y), radius, inner, outer)


def draw_rectangle_gradient_ex(rec, top_left, bottom_left, top_right, bottom_right) -> None:
  if _NEW_API:
    rl.draw_rectangle_gradient_ex(rec, top_left, bottom_left, bottom_right, top_right)
  else:
    rl.draw_rectangle_gradient_ex(rec, top_left, bottom_left, top_right, bottom_right)

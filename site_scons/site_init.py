import os
import sys

import SCons.Script.Main as _main

try:
  from site_tools import pretty as _pretty
except Exception:
  _pretty = None


def _tty():
  return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


_DIM = "\033[2;38;5;246m"
_BLUE = "\033[38;5;111m"
_GREEN = "\033[38;5;114m"
_RED = "\033[38;5;203m"
_RST = "\033[0m"

_PHASES = {
  "scons: Reading SConscript files ...":                          f"{_DIM}reading sconscripts…{_RST}",
  "scons: done reading SConscript files.":                        f"{_DIM}sconscripts read{_RST}",
  "scons: Building targets ...":                                  f"{_BLUE}building…{_RST}",
  "scons: done building targets.":                                f"{_GREEN}✓ build complete{_RST}",
  "scons: done building targets (errors occurred during build).": f"{_RED}✗ build failed{_RST}",
  "scons: writing .sconsign file.":                               f"{_DIM}writing .sconsign{_RST}",
  "scons: Cleaning targets ...":                                  f"{_DIM}cleaning…{_RST}",
  "scons: done cleaning targets.":                                f"{_GREEN}✓ clean complete{_RST}",
  "scons: done cleaning targets (errors occurred during clean).": f"{_RED}✗ clean failed{_RST}",
}


def _phase(text):
  if _tty() and isinstance(text, str) and text in _PHASES:
    return _PHASES[text]
  return text


def _clean(text):
  if not (_tty() and _pretty and isinstance(text, str)):
    return text
  for prefix in ("Removed directory ", "Removed "):
    if text.startswith(prefix):
      return _pretty._format("CLEAN", text[len(prefix):])
  return text


class _Restyle:
  # delegates unknown attrs (.set_mode etc.) to the wrapped DisplayEngine
  def __init__(self, orig, transform):
    self._orig = orig
    self._transform = transform

  def __call__(self, text, *args, **kwargs):
    return self._orig(self._transform(text), *args, **kwargs)

  def __getattr__(self, name):
    return getattr(self._orig, name)


if not isinstance(_main.progress_display, _Restyle):
  _main.progress_display = _Restyle(_main.progress_display, _phase)
if not isinstance(_main.display, _Restyle):
  _main.display = _Restyle(_main.display, _clean)


# drop only "Could not remove ... No such file" during clean; real errors still print
import builtins as _builtins


def _wrap_clean(orig):
  def wrapper(self, *args, **kwargs):
    if getattr(_builtins.print, "_iq_clean", False):
      return orig(self, *args, **kwargs)
    real = _builtins.print

    def filtered(*a, **k):
      if a and isinstance(a[0], str) and a[0].startswith("scons: Could not remove"):
        if "No such file" in " ".join(str(x) for x in a):
          return
      return real(*a, **k)
    filtered._iq_clean = True
    _builtins.print = filtered
    try:
      return orig(self, *args, **kwargs)
    finally:
      _builtins.print = real
  return wrapper


if not getattr(_main.CleanTask.fs_delete, "_iq_wrapped", False):
  _main.CleanTask.fs_delete = _wrap_clean(_main.CleanTask.fs_delete)
  _main.CleanTask.remove = _wrap_clean(_main.CleanTask.remove)
  _main.CleanTask.fs_delete._iq_wrapped = True
  _main.CleanTask.remove._iq_wrapped = True

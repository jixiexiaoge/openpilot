import os
import sys

from SCons.Action import Action
from SCons.Script import GetOption

_GRAD = {
  "CC":      ((95, 215, 255), (70, 130, 245)),
  "CXX":     ((95, 205, 255), (130, 110, 250)),
  "LINK":    ((95, 240, 150), (40, 200, 120)),
  "AR":      ((120, 235, 220), (40, 175, 185)),
  "RANLIB":  ((140, 240, 225), (45, 165, 180)),
  "SKIP":    ((150, 160, 185), (100, 110, 145)),
  "CLEAN":   ((200, 130, 145), (120, 120, 155)),
  "OBJCOPY": ((255, 200, 90), (255, 120, 50)),
  "SIGN":    ((255, 190, 90), (230, 80, 70)),
  "CYTHON":  ((215, 130, 255), (140, 80, 250)),
  "CAPNP":   ((255, 120, 225), (190, 90, 255)),
  "RCC":     ((200, 160, 255), (150, 110, 250)),
  "FONTS":   ((130, 190, 255), (90, 120, 250)),
  "GEN":     ((160, 160, 255), (120, 90, 250)),
  "CDB":     ((150, 175, 210), (105, 135, 185)),
  "MODEL":   ((255, 170, 70), (240, 60, 60)),
  "META":    ((255, 205, 110), (230, 130, 80)),
  "MOC":     ((255, 140, 205), (215, 90, 240)),
  "UIC":     ((255, 160, 190), (225, 110, 225)),
  "MO":      ((100, 235, 200), (55, 200, 155)),
}
_DEFAULT = ((120, 200, 255), (90, 140, 250))
_TARGET_RGB = (150, 152, 178)


def _mode():
  if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    return None
  if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
    return "true"
  return "256"


def _fg(rgb, mode):
  r, g, b = rgb
  if mode == "true":
    return f"\033[38;2;{r};{g};{b}m"
  if abs(r - g) < 12 and abs(g - b) < 12 and abs(r - b) < 12:
    idx = 232 + min(23, round((r + g + b) / 3 / 255 * 23))
  else:
    idx = 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)
  return f"\033[38;5;{idx}m"


def _gradient(word, start, end, mode):
  n = max(1, len(word) - 1)
  out = []
  for i, ch in enumerate(word):
    t = i / n
    rgb = tuple(int(s + (e - s) * t) for s, e in zip(start, end))
    out.append(f"\033[1m{_fg(rgb, mode)}{ch}")
  return "".join(out) + "\033[0m"


def _format(label, body):
  mode = _mode()
  if mode is None:
    return f"{label:>8}  {body}"
  start, end = _GRAD.get(label, _DEFAULT)
  pad = " " * max(0, 8 - len(label))
  word = _gradient(label, start, end, mode)
  return f"{pad}{word}  {_fg(_TARGET_RGB, mode)}{body}\033[0m"


def _line(label):
  return _format(label, "$TARGET")


def _verbose():
  try:
    return bool(GetOption("verbose"))
  except Exception:
    return False


def generate(env):
  def pretty_action(e, cmd, label, logfile=None, capture_stderr=False):
    if _verbose():
      return Action(cmd)
    if callable(cmd):
      return Action(cmd, _line(label))
    if logfile:
      cmd = f"{cmd} > {logfile}" + (" 2>&1" if capture_stderr else "")
    return Action(cmd, _line(label))
  env.AddMethod(pretty_action, "PrettyAction")
  env.AddMethod(lambda e, label, msg: _format(label, msg), "PrettyNote")

  # real errors are exceptions, not warnings, so they still surface with these ignored
  env["PYWARN"] = "" if _verbose() else "PYTHONWARNINGS=ignore::UserWarning"

  if _verbose():
    return

  try:
    import SCons.CacheDir as _cachedir
    _cachedir.CacheRetrieve.strfunction = lambda target, source, env: ""
  except Exception:
    pass

  env["CCCOMSTR"] = _line("CC")
  env["SHCCCOMSTR"] = _line("CC")
  env["CXXCOMSTR"] = _line("CXX")
  env["SHCXXCOMSTR"] = _line("CXX")
  env["ASCOMSTR"] = _line("CC")
  env["ASPPCOMSTR"] = _line("CC")
  env["LINKCOMSTR"] = _line("LINK")
  env["SHLINKCOMSTR"] = _line("LINK")
  env["ARCOMSTR"] = _line("AR")
  env["RANLIBCOMSTR"] = _line("RANLIB")
  env["CYTHONCOMSTR"] = _line("CYTHON")
  env["COMPILATIONDB_COMSTR"] = _line("CDB")
  env["QT3_MOCFROMHCOMSTR"] = _line("MOC")
  env["QT3_MOCFROMCXXCOMSTR"] = _line("MOC")
  env["QT3_UICCOMSTR"] = _line("UIC")


def exists(env):
  return True

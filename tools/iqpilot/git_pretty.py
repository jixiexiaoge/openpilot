#!/usr/bin/env python3
import os
import re
import sys

_GRAD = {
  "PULL":   ((95, 240, 150), (40, 200, 120)),
  "FETCH":  ((95, 205, 255), (130, 110, 250)),
  "SUBMOD": ((200, 160, 255), (150, 110, 250)),
  "RESET":  ((255, 190, 90), (230, 80, 70)),
  "BRANCH": ((95, 215, 255), (70, 130, 245)),
}
_TARGET_RGB = (150, 152, 178)
_GREEN = (120, 210, 130)
_DIM = "\033[2;38;5;246m"
_RST = "\033[0m"


def _mode():
  if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    return None
  return "true" if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit") else "256"


def _fg(rgb, mode):
  r, g, b = rgb
  if mode == "true":
    return f"\033[38;2;{r};{g};{b}m"
  if abs(r - g) < 12 and abs(g - b) < 12 and abs(r - b) < 12:
    idx = 232 + min(23, round((r + g + b) / 3 / 255 * 23))
  else:
    idx = 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)
  return f"\033[38;5;{idx}m"


def _grad(word, label, mode):
  start, end = _GRAD.get(label, _GRAD["FETCH"])
  n = max(1, len(word) - 1)
  out = [f"\033[1m{_fg(tuple(int(s + (e - s) * i / n) for s, e in zip(start, end)), mode)}{ch}"
         for i, ch in enumerate(word)]
  return "".join(out) + _RST


def _label(label, body, mode):
  pad = " " * max(0, 8 - len(label))
  return f"{pad}{_grad(label, label, mode)}  {_fg(_TARGET_RGB, mode)}{body}{_RST}"


def _restyle(line, mode):
  s = line.rstrip("\n")
  raw = re.sub(r"\033\[[0-9;]*m", "", s)  # match against de-colored text

  if raw == "Already up to date.":
    return f"{_fg(_GREEN, mode)}✓ already up to date{_RST}"
  m = re.match(r"Updating ([0-9a-f]+\.\.[0-9a-f]+)$", raw)
  if m:
    return _label("PULL", m.group(1), mode)
  if raw == "Fast-forward":
    return f"{_DIM}fast-forward{_RST}"
  m = re.match(r"HEAD is now at ([0-9a-f]+) (.*)$", raw)
  if m:
    return _label("RESET", f"{m.group(1)}  {m.group(2)}", mode)
  m = re.match(r"Submodule path '(.+)': checked out '([0-9a-f]+)'$", raw)
  if m:
    return _label("SUBMOD", f"{m.group(1)} @ {m.group(2)[:9]}", mode)
  m = re.match(r"Submodule '(.+)' \((.+)\) registered for path '(.+)'$", raw)
  if m:
    return _label("SUBMOD", f"{m.group(3)}  (registered)", mode)
  m = re.match(r"From (.+)$", raw)
  if m:
    return _label("FETCH", m.group(1), mode)
  m = re.match(r"\s*\*?\s*\[new (?:branch|tag)\]\s+(\S+)\s+->\s+(\S+)$", raw)
  if m:
    return _label("FETCH", f"new  {m.group(1)} → {m.group(2)}", mode)
  m = re.match(r"\s*\*\s+(?:branch|tag)\s+(\S+)\s+->\s+(\S+)$", raw)
  if m:
    return _label("FETCH", f"{m.group(1)} → {m.group(2)}", mode)
  m = re.match(r"\s*([0-9a-f]+\.\.[0-9a-f]+)\s+(\S+)\s+->\s+(\S+)$", raw)
  if m:
    return _label("FETCH", f"{m.group(1)}  {m.group(2)} → {m.group(3)}", mode)
  m = re.match(r"([* ]) +(\S+) +([0-9a-f]{7,})( .*)?$", raw)
  if m:
    cur, name, sha, msg = m.groups()
    star = f"{_fg(_GREEN, mode)}●{_RST} " if cur == "*" else "  "
    return f"{star}{_grad(name, 'BRANCH', mode)}  {_fg(_TARGET_RGB, mode)}{sha}{(msg or '')}{_RST}"
  return s


def main():
  mode = _mode()
  out = sys.stdout
  if mode is None:  # not a tty / NO_COLOR: passthrough
    for chunk in iter(lambda: sys.stdin.buffer.read(4096), b""):
      out.buffer.write(chunk)
      out.buffer.flush()
    return

  buf = ""
  stream = sys.stdin
  while True:
    ch = stream.read(1)
    if not ch:
      break
    if ch == "\r":       # progress fragment: emit live, untouched
      out.write(buf + "\r")
      out.flush()
      buf = ""
    elif ch == "\n":
      out.write(_restyle(buf, mode) + "\n")
      out.flush()
      buf = ""
    else:
      buf += ch
  if buf:
    out.write(_restyle(buf, mode))
    out.flush()


if __name__ == "__main__":
  try:
    main()
  except (BrokenPipeError, KeyboardInterrupt):
    pass

#!/usr/bin/env python3
# console path for the boot/manager tmux: must never die or block; on any error, forward raw.
import os
import re
import signal
import sys

try:
  signal.signal(signal.SIGPIPE, signal.SIG_IGN)
except Exception:
  pass

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_DROP = re.compile(
  r"(\x1b\[\?\d+[a-z])"
  r"|ln: failed to create symbolic link '[^']*(cursor-server|windsurf-server|vscode-server)"
  r"|^Last login:"
  r"|gbm_create_device\(\d+\): Info:"
  r"|No IRQs found for '"
  r"|^pid \d+'s (current|new) affinity list:"
  r"|kj/filesystem-disk-unix\.c\+\+:\d+: warning: PWD"
)
_CLOUDLOG = re.compile(r"^([\w./+-]+\.(?:cc|cpp|c|h|py)): (.*)$")
_ALREADY = re.compile(r"^\s*(?:\x1b\[[0-9;]*m)?\s*(CRIT|ERR|WARN|info|dbg)\b")
_ERRISH = re.compile(r"not supported|fail|error|invalid|cannot|timed out|timeout|unable", re.I)


def _sev(msg):
  return ("\033[1;38;5;203m", " ERR", "\033[1;38;5;210m") if _ERRISH.search(msg) \
    else ("\033[38;5;110m", "info", "")


def _restyle(line):
  if _DROP.search(line):
    return None
  if _ALREADY.match(line):
    return line
  m = _CLOUDLOG.match(re.sub(r"\x1b\[[0-9;]*m", "", line))
  if m and _COLOR:
    src, msg = m.group(1), m.group(2)
    lc, ln, mc = _sev(msg)
    body = f"{mc}{msg}\033[0m" if mc else msg
    return f"{lc}{ln}\033[0m  \033[2m{src}\033[0m  {body}"
  return line


def _emit(out, buf):
  styled = _restyle(buf)
  if styled is not None:
    out.write(styled + "\r\n"); out.flush()


def main():
  out = sys.stdout
  buf = ""
  pending_cr = False
  read = sys.stdin.buffer.read
  while True:
    try:
      ch = read(1)
    except Exception:
      break
    if not ch:
      break
    try:
      c = ch.decode("utf-8", "replace")
      if pending_cr:
        pending_cr = False
        if c == "\n":
          _emit(out, buf); buf = ""; continue
        out.write(buf + "\r"); out.flush(); buf = ""  # bare \r: progress
      if c == "\r":
        pending_cr = True
      elif c == "\n":
        _emit(out, buf); buf = ""
      else:
        buf += c
    except Exception:
      try:
        out.write(buf); out.flush()
      except Exception:
        pass
      buf = ""; pending_cr = False
  if pending_cr:
    out.write(buf + "\r"); out.flush()
  elif buf:
    try:
      styled = _restyle(buf)
      if styled is not None:
        out.write(styled); out.flush()
    except Exception:
      pass


if __name__ == "__main__":
  try:
    main()
  except Exception:
    try:
      import shutil
      shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)
    except Exception:
      pass

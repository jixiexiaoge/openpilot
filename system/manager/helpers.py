import errno
import fcntl
import os
import sys
import pathlib
import shutil
import signal
import subprocess
import tempfile
import threading

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params

def unblock_stdout() -> None:
  # get a non-blocking stdout
  child_pid, child_pty = os.forkpty()
  if child_pid != 0:  # parent

    # child is in its own process group, manually pass kill signals
    signal.signal(signal.SIGINT, lambda signum, frame: os.kill(child_pid, signal.SIGINT))
    signal.signal(signal.SIGTERM, lambda signum, frame: os.kill(child_pid, signal.SIGTERM))

    fcntl.fcntl(sys.stdout, fcntl.F_SETFL, fcntl.fcntl(sys.stdout, fcntl.F_GETFL) | os.O_NONBLOCK)

    while True:
      try:
        dat = os.read(child_pty, 4096)
      except OSError as e:
        if e.errno == errno.EIO:
          break
        continue

      if not dat:
        break

      try:
        sys.stdout.write(dat.decode('utf8'))
      except (OSError, UnicodeDecodeError):
        pass

    # os.wait() returns a tuple with the pid and a 16 bit value
    # whose low byte is the signal number and whose high byte is the exit status
    exit_status = os.wait()[1] >> 8
    os._exit(exit_status)


def write_onroad_params(started, params):
  params.put_bool("IsOnroad", started)
  params.put_bool("IsOffroad", not started)


def heal_param_perms():
  """Self-heal for a boot-bricking failure mode: a stray root process occasionally
  writes a param (seen with RouteCount/CurrentRoute) as root:root 0600, which manager
  (comma) then can't read — crashing save_bootlog and any param read. Detect params we
  don't own and chown them back + make them readable. Needs root to chown another user's
  file, so it shells to passwordless sudo (device grants it); best-effort, never raises,
  never blocks boot. No-op when everything is already ours (the common case: no sudo)."""
  try:
    param_path = Params().get_param_path()
    uid, gid = os.getuid(), os.getgid()
    stray = []
    for name in os.listdir(param_path):
      p = os.path.join(param_path, name)
      try:
        if os.stat(p).st_uid != uid:
          stray.append(p)
      except OSError:
        pass
    if stray:
      subprocess.run(["sudo", "-n", "chown", f"{uid}:{gid}", *stray], check=False, timeout=15,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      subprocess.run(["sudo", "-n", "chmod", "644", *stray], check=False, timeout=15,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  except Exception:
    pass


def save_bootlog():
  # copy current params
  tmp = tempfile.mkdtemp()
  params_dirname = pathlib.Path(Params().get_param_path()).name
  params_dir = os.path.join(tmp, params_dirname)

  # Params are rewritten atomically (unlink + rename) by other processes, so a
  # value can vanish between copytree's listing and the copy; a param may also be
  # unreadable (e.g. a root-owned RouteCount/CurrentRoute). Skip any file we can't
  # copy instead of raising — the bootlog snapshot is best-effort and must NOT block boot.
  def _copy_skip_missing(src, dst, *, follow_symlinks=True):
    try:
      shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
    except OSError:
      pass
  shutil.copytree(Params().get_param_path(), params_dir, dirs_exist_ok=True, copy_function=_copy_skip_missing)

  def fn(tmpdir):
    env = os.environ.copy()
    env['PARAMS_COPY_PATH'] = tmpdir
    subprocess.call("./bootlog", cwd=os.path.join(BASEDIR, "system/loggerd"), env=env)
    shutil.rmtree(tmpdir)
  t = threading.Thread(target=fn, args=(tmp, ))
  t.daemon = True
  t.start()

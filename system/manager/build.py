#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path

# NOTE: Do NOT import anything here that needs be built (e.g. params)
from openpilot.common.basedir import BASEDIR
from openpilot.common.spinner import Spinner
from openpilot.common.text_window import TextWindow
from openpilot.common.swaglog import cloudlog, add_file_handler
from openpilot.system.hardware import HARDWARE, AGNOS
from openpilot.system.version import get_build_metadata

MAX_CACHE_SIZE = 4e9 if "CI" in os.environ else 2e9
CACHE_DIR = Path("/data/scons_cache" if AGNOS else "/tmp/scons_cache")

TOTAL_SCONS_NODES = 5500
MAX_BUILD_PROGRESS = 100

def get_job_sequence() -> list[int]:
  env_override = os.environ.get("SCONS_MAX_JOBS")
  if env_override is not None:
    try:
      max_jobs = max(1, int(env_override))
    except ValueError:
      max_jobs = 1
  else:
    detected_jobs = os.cpu_count() or 2
    max_jobs = min(detected_jobs, 3 if AGNOS else detected_jobs)

  candidates = [max_jobs, max_jobs // 2, 1]
  jobs: list[int] = []
  for candidate in candidates:
    candidate = max(1, int(candidate))
    if candidate not in jobs:
      jobs.append(candidate)
  return jobs

def heal_submodules() -> None:
  # An interrupted install can leave a submodule's worktree EMPTY while its
  # git metadata (.git/modules/<name>, pinned HEAD) is fully present — git
  # even reports it clean. The build then fails in confusing ways (missing
  # tinygrad, missing compile3.py). Re-checkout is purely local: no network,
  # no auth, just materializing the worktree from the objects already on disk.
  gitmodules = Path(BASEDIR) / ".gitmodules"
  if not gitmodules.is_file():
    return  # vendored/prebuilt tree, no submodules
  try:
    out = subprocess.check_output(["git", "config", "-f", str(gitmodules), "--get-regexp", r"submodule\..*\.path"],
                                  cwd=BASEDIR, text=True)
  except (subprocess.CalledProcessError, OSError):
    return
  for line in out.splitlines():
    path = line.split(" ", 1)[1].strip()
    p = Path(BASEDIR) / path
    if p.is_dir() and not any(p.iterdir()):
      cloudlog.warning(f"submodule {path} worktree is empty, re-checking out from local objects")
      subprocess.run(["git", "submodule", "update", "--checkout", "--force", path], cwd=BASEDIR, check=False)


def build(spinner: Spinner, dirty: bool = False, minimal: bool = False) -> None:
  env = os.environ.copy()
  env['SCONS_PROGRESS'] = "1"

  heal_submodules()

  extra_args = ["--minimal"] if minimal else []

  if AGNOS:
    HARDWARE.set_power_save(False)
    os.sched_setaffinity(0, range(8))  # ensure we can use the isolcpus cores

  # building with all cores can result in using too
  # much memory, so retry with less parallelism
  compile_output: list[bytes] = []
  for n in get_job_sequence():
    compile_output.clear()
    scons: subprocess.Popen = subprocess.Popen(["scons", f"-j{int(n)}", "--cache-populate", *extra_args], cwd=BASEDIR, env=env, stderr=subprocess.PIPE)
    assert scons.stderr is not None

    # Read progress from stderr and update spinner
    while scons.poll() is None:
      try:
        line = scons.stderr.readline()
        if line is None:
          continue
        line = line.rstrip()

        prefix = b'progress: '
        if line.startswith(prefix):
          i = int(line[len(prefix):])
          spinner.update_progress(MAX_BUILD_PROGRESS * min(0.99, i / TOTAL_SCONS_NODES), 100.)
        elif len(line):
          compile_output.append(line)
          print(line.decode('utf8', 'replace'))
      except Exception:
        pass

    if scons.returncode == 0:
      spinner.update_progress(100, 100.)
      break

  if scons.returncode != 0:
    # Read remaining output
    if scons.stderr is not None:
      compile_output += scons.stderr.read().split(b'\n')

    # Build failed log errors
    error_s = b"\n".join(compile_output).decode('utf8', 'replace')
    add_file_handler(cloudlog)
    cloudlog.error("scons build failed\n" + error_s)

    # Show TextWindow
    spinner.close()
    if not os.getenv("CI"):
      with TextWindow("openpilot failed to build\n \n" + error_s) as t:
        t.wait_for_exit()
    exit(1)

  # enforce max cache size
  cache_files = [f for f in CACHE_DIR.rglob('*') if f.is_file()]
  cache_files.sort(key=lambda f: f.stat().st_mtime)
  cache_size = sum(f.stat().st_size for f in cache_files)
  for f in cache_files:
    if cache_size < MAX_CACHE_SIZE:
      break
    cache_size -= f.stat().st_size
    f.unlink()


if __name__ == "__main__":
  spinner = Spinner()
  spinner.update_progress(0, 100)
  build_metadata = get_build_metadata()
  build(spinner, build_metadata.openpilot.is_dirty, minimal = AGNOS)

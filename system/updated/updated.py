#!/usr/bin/env python3
import os
import re
import datetime
import subprocess
import psutil
import signal
import fcntl
import threading
from collections import defaultdict
from pathlib import Path

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.time_helpers import system_time_valid
from openpilot.common.markdown import parse_markdown
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
from openpilot.system.hardware import AGNOS, HARDWARE
from openpilot.system.version import get_build_metadata, IQ_BRANCH_MIGRATIONS


LOCK_FILE = os.getenv("UPDATER_LOCK_FILE", "/tmp/safe_staging_overlay.lock")
STAGING_ROOT = os.getenv("UPDATER_STAGING_ROOT", "/data/safe_staging")
OVERLAY_INIT = Path(os.path.join(BASEDIR, ".overlay_init"))

# do not allow to engage after this many hours onroad and this many routes
HOURS_NO_CONNECTIVITY_MAX = 27
ROUTES_NO_CONNECTIVITY_MAX = 84
# send an offroad prompt after this many hours onroad and this many routes
HOURS_NO_CONNECTIVITY_PROMPT = 23
ROUTES_NO_CONNECTIVITY_PROMPT = 80


class UserRequest:
  NONE = 0
  CHECK = 1
  FETCH = 2


class UpdateInstallMode:
  DOWNLOAD_ONLY = "download_only"
  DOWNLOAD_AND_INSTALL = "download_and_install"

class WaitTimeHelper:
  def __init__(self):
    self.ready_event = threading.Event()
    self.user_request = UserRequest.NONE
    signal.signal(signal.SIGHUP, self.update_now)
    signal.signal(signal.SIGUSR1, self.check_now)

  def update_now(self, signum: int, frame) -> None:
    cloudlog.info("caught SIGHUP, attempting to downloading update")
    self.user_request = UserRequest.FETCH
    self.ready_event.set()

  def check_now(self, signum: int, frame) -> None:
    cloudlog.info("caught SIGUSR1, checking for updates")
    self.user_request = UserRequest.CHECK
    self.ready_event.set()

  def sleep(self, t: float) -> None:
    self.ready_event.wait(timeout=t)

def write_time_to_param(params, param) -> None:
  t = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
  params.put(param, t)

def run(cmd: list[str], cwd: str | None = None) -> str:
  return subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT, encoding='utf8')


def has_git_repo(path: str) -> bool:
  return os.path.isdir(os.path.join(path, ".git"))


def cleanup_stale_overlay() -> None:
  try:
    merged = os.path.join(STAGING_ROOT, "merged")
    if os.path.ismount(merged):
      run(["sudo", "umount", "-l", merged])
    if os.path.isdir(STAGING_ROOT):
      run(["sudo", "rm", "-rf", STAGING_ROOT])
    OVERLAY_INIT.unlink(missing_ok=True)
  except Exception:
    cloudlog.exception("updater: failed to clean up stale overlay")


def parse_release_notes(basedir: str) -> bytes:
  try:
    with open(os.path.join(basedir, "CHANGELOG.md"), "rb") as f:
      r = f.read().split(b'\n\n', 1)[0]  # Slice latest release notes
    try:
      return bytes(parse_markdown(r.decode("utf-8")), encoding="utf-8")
    except Exception:
      return r + b"\n"
  except FileNotFoundError:
    pass
  except Exception:
    cloudlog.exception("failed to parse release notes")
  return b""


def get_agnos_target_versions(launch_env_dir: str) -> tuple[str, list[str]]:
  out = run([
    "bash", "-c",
    r'unset AGNOS_VERSION AGNOS_COMPAT_VERSIONS && source launch_env.sh && printf "%s\n%s\n" "${AGNOS_VERSION}" "${AGNOS_COMPAT_VERSIONS}"',
  ], launch_env_dir)
  lines = out.splitlines()
  expected_version = lines[0].strip() if len(lines) > 0 else ""
  compat_versions = [v.strip() for v in (lines[1] if len(lines) > 1 else "").split(",") if v.strip()]
  return expected_version, compat_versions


def agnos_version_allowed(current_version: str, expected_version: str, compat_versions: list[str]) -> bool:
  if current_version == expected_version or current_version.startswith(f"{expected_version}-"):
    return True

  return current_version in compat_versions

def configure_git_auth(cwd: str) -> None:
  """Install the IQ.Lvbs read-only git credential helper before any remote op.

  The IQ.Firewall blocks anonymous access to the git server (to stop bandwidth-
  wasting mirrors), so the fleet must authenticate. The read token + credential
  helper live in a proprietary, signed, compiled bundle
  (iqpilot_private.konn3kt.iqlvbs.git_remote); the token never appears in
  .git/config, argv, or this open-source file. On dev installs without the
  bundle this is a no-op and ambient git credentials are used."""
  try:
    from openpilot.system.proprietary_runtime._verified_import import import_verified_module
    import_verified_module("iqpilot_updater_private", "iqpilot_private.updater.git_remote").configure(cwd)
  except Exception:
    cloudlog.info("updater: proprietary git auth unavailable; using ambient git credentials")

  try:
    from openpilot.common.git_creds import configure as configure_user_creds
    configure_user_creds(cwd)
  except Exception:
    cloudlog.exception("updater: user git credentials unavailable")


def setup_git_options(cwd: str) -> None:
  # We sync FS object atimes (which NEOS doesn't use) and mtimes, but ctimes
  # are outside user control. Make sure Git is set up to ignore system ctimes,
  # because they change when we make hard links during finalize. Otherwise,
  # there is a lot of unnecessary churn. This appears to be a common need on
  # OSX as well: https://www.git-tower.com/blog/make-git-rebase-safe-on-osx/

  # We are using copytree to copy the directory, which also changes
  # inode numbers. Ignore those changes too.

  # Set protocol to the new version (default after git 2.26) to reduce data
  # usage on git fetch --dry-run from about 400KB to 18KB.
  git_cfg = [
    ("core.trustctime", "false"),
    ("core.checkStat", "minimal"),
    ("protocol.version", "2"),
    ("gc.auto", "0"),
    ("gc.autoDetach", "false"),
  ]
  for option, value in git_cfg:
    run(["git", "config", option, value], cwd)


def cleanup_stale_prebuilt_marker(cwd: str, branch: str) -> None:
  prebuilt_path = os.path.join(cwd, "prebuilt")
  if not os.path.exists(prebuilt_path):
    return

  tracked = True
  try:
    run(["git", "ls-files", "--error-unmatch", "prebuilt"], cwd)
  except subprocess.CalledProcessError:
    tracked = False

  if not tracked and not branch.endswith("-prebuilt"):
    os.remove(prebuilt_path)
    cloudlog.info("removed stale untracked prebuilt marker on non-prebuilt branch %s", branch)


def handle_agnos_update() -> None:
  from openpilot.system.hardware.tici.agnos import flash_agnos_update, get_target_slot_number

  cur_version = HARDWARE.get_os_version()
  device_type = HARDWARE.get_device_type()
  is_tici_c3 = device_type in ("tici", "three")
  updated_version, compat_versions = get_agnos_target_versions(BASEDIR)

  cloudlog.info(f"AGNOS version check: current={cur_version}, target={updated_version}, compat={compat_versions}")
  if agnos_version_allowed(cur_version, updated_version, compat_versions):
    return

  cloudlog.info(f"Beginning background installation for AGNOS {updated_version}")
  set_offroad_alert("Offroad_NeosUpdate", True)

  manifest_name = "agnos_tici_15_1.json" if is_tici_c3 else "agnos.json"
  manifest_path = os.path.join(BASEDIR, "system/hardware/tici", manifest_name)
  cloudlog.info(f"AGNOS manifest selected: device_type={device_type}, manifest={manifest_name}")
  target_slot_number = get_target_slot_number()
  flash_agnos_update(manifest_path, target_slot_number, cloudlog)
  set_offroad_alert("Offroad_NeosUpdate", False)


class Updater:
  def __init__(self):
    self.params = Params()
    self.branches = defaultdict(lambda: None)
    self._has_internet: bool = False

    # The commit/branch the running processes booted from. We update BASEDIR in
    # place, so this is what we diff against to know a reboot is needed.
    try:
      self.running_commit = self.get_commit_hash(BASEDIR)
      self.running_branch = self.get_branch(BASEDIR)
      self.running_description = self.get_description(BASEDIR)
    except Exception:
      cloudlog.exception("updater: failed to capture running version")
      self.running_commit = ""
      self.running_branch = ""
      self.running_description = ""

  @property
  def git_mode(self) -> bool:
    return has_git_repo(BASEDIR)

  @property
  def has_internet(self) -> bool:
    return self._has_internet

  @property
  def install_mode(self) -> str:
    mode = self.params.get("UpdaterInstallMode")
    if mode not in (UpdateInstallMode.DOWNLOAD_ONLY, UpdateInstallMode.DOWNLOAD_AND_INSTALL):
      return UpdateInstallMode.DOWNLOAD_AND_INSTALL
    return mode

  @property
  def target_branch(self) -> str:
    b: str | None = self.params.get("UpdaterTargetBranch")
    if b is None:
      b = self.get_branch(BASEDIR)
    b = IQ_BRANCH_MIGRATIONS.get((HARDWARE.get_device_type(), b), b)
    return b

  @property
  def update_ready(self) -> bool:
    """True when the code on disk differs from what's running -> reboot to apply.
    After a reboot this is False again, since running_* is recaptured at start."""
    if not self.git_mode:
      return False
    on_disk_commit = self.get_commit_hash(BASEDIR)
    on_disk_branch = self.get_branch(BASEDIR)
    return (on_disk_commit != self.running_commit) or (on_disk_branch != self.running_branch)

  @property
  def update_available(self) -> bool:
    """True when the code on disk is behind the remote target -> can download."""
    if not self.git_mode:
      return False
    if len(self.branches) == 0:
      return False
    target = self.target_branch
    on_disk_commit = self.get_commit_hash(BASEDIR)
    on_disk_branch = self.get_branch(BASEDIR)
    hash_mismatch = self.branches[target] is not None and on_disk_commit != self.branches[target]
    branch_mismatch = on_disk_branch != target
    return hash_mismatch or branch_mismatch

  def get_branch(self, path: str) -> str:
    if not has_git_repo(path):
      try:
        return get_build_metadata(path).channel
      except Exception:
        return ""
    return run(["git", "rev-parse", "--abbrev-ref", "HEAD"], path).rstrip()

  def get_commit_hash(self, path: str = BASEDIR) -> str:
    if not has_git_repo(path):
      try:
        return get_build_metadata(path).openpilot.git_commit
      except Exception:
        return ""
    return run(["git", "rev-parse", "HEAD"], path).rstrip()

  def get_description(self, basedir: str) -> str:
    if not os.path.exists(basedir):
      return ""

    version = ""
    branch = ""
    commit = ""
    commit_date = ""
    try:
      metadata = get_build_metadata(basedir)
      branch = metadata.channel
      commit = metadata.openpilot.git_commit[:7]
      version = metadata.openpilot.version
      commit_date = metadata.openpilot.git_commit_date
    except Exception:
      cloudlog.exception("updater.get_description")
    return f"{version} / {branch} / {commit} / {commit_date}"

  def set_params(self, update_success: bool, failed_count: int, exception: str | None) -> None:
    self.params.put("UpdateFailedCount", failed_count)
    self.params.put("UpdaterTargetBranch", self.target_branch)

    self.params.put_bool("UpdaterFetchAvailable", self.update_available)
    if len(self.branches):
      self.params.put("UpdaterAvailableBranches", ','.join(self.branches.keys()))

    last_uptime_onroad = self.params.get("UptimeOnroad", return_default=True)
    last_route_count = self.params.get("RouteCount", return_default=True)
    if update_success:
      self.params.put("LastUpdateTime", datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
      self.params.put("LastUpdateUptimeOnroad", last_uptime_onroad)
      self.params.put("LastUpdateRouteCount", last_route_count)

    if exception is None:
      self.params.remove("LastUpdateException")
    else:
      self.params.put("LastUpdateException", exception)

    # Current = what's running (captured at boot, stable until reboot).
    # New = what's on disk now (changes once we fetch in place).
    self.params.put("UpdaterCurrentDescription", self.running_description)
    self.params.put("UpdaterCurrentReleaseNotes", parse_release_notes(BASEDIR))
    self.params.put("UpdaterNewDescription", self.get_description(BASEDIR))
    self.params.put("UpdaterNewReleaseNotes", parse_release_notes(BASEDIR))
    self.params.put_bool("UpdateAvailable", self.update_ready)

    # Handle user prompt
    for alert in ("Offroad_UpdateFailed", "Offroad_ConnectivityNeeded", "Offroad_ConnectivityNeededPrompt"):
      set_offroad_alert(alert, False)

    build_metadata = get_build_metadata()
    if failed_count > 15 and exception is not None and self.has_internet:
      if build_metadata.tested_channel:
        extra_text = "Ensure the software is correctly installed. Uninstall and re-install if this error persists."
      else:
        extra_text = exception
      set_offroad_alert("Offroad_UpdateFailed", True, extra_text=extra_text)

  def check_for_update(self) -> None:
    cloudlog.info("checking for updates")

    if not self.git_mode:
      cloudlog.info("updater: baked non-git deployment detected; skipping git update check")
      self._has_internet = False
      self.branches = defaultdict(lambda: None)
      return

    excluded_branches = ('release2', 'release2-staging')

    # authenticate before the very first remote op (the internet probe below),
    # since anonymous access is firewalled
    configure_git_auth(BASEDIR)

    try:
      run(["git", "ls-remote", "origin", "HEAD"], BASEDIR)
      self._has_internet = True
    except subprocess.CalledProcessError:
      self._has_internet = False

    setup_git_options(BASEDIR)
    output = run(["git", "ls-remote", "--heads"], BASEDIR)

    self.branches = defaultdict(lambda: None)
    for line in output.split('\n'):
      ls_remotes_re = r'(?P<commit_sha>\b[0-9a-f]{5,40}\b)(\s+)(refs\/heads\/)(?P<branch_name>.*$)'
      x = re.fullmatch(ls_remotes_re, line.strip())
      if x is not None and x.group('branch_name') not in excluded_branches:
        self.branches[x.group('branch_name')] = x.group('commit_sha')

    cur_branch = self.get_branch(BASEDIR)
    cur_commit = self.get_commit_hash(BASEDIR)
    new_branch = self.target_branch
    new_commit = self.branches[new_branch]
    if (cur_branch, cur_commit) != (new_branch, new_commit):
      cloudlog.info(f"update available, {cur_branch} ({str(cur_commit)[:7]}) -> {new_branch} ({str(new_commit)[:7]})")
    else:
      cloudlog.info(f"up to date on {cur_branch} ({str(cur_commit)[:7]})")

  def fetch_update(self) -> None:
    if not self.git_mode:
      cloudlog.info("updater: baked non-git deployment detected; skipping git fetch")
      self.params.put("UpdaterState", "idle")
      return

    cloudlog.info("attempting git fetch and in-place reset")

    configure_git_auth(BASEDIR)

    self.params.put("UpdaterState", "downloading...")
    self.params.put_bool("UpdateAvailable", False)

    setup_git_options(BASEDIR)

    run(["git", "config", "--replace-all", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"], BASEDIR)

    branch = self.target_branch
    git_fetch_output = run(["git", "fetch", "origin", branch], BASEDIR)
    cloudlog.info("git fetch success: %s", git_fetch_output)

    cloudlog.info("git reset in progress")
    cmds = [
      ["git", "checkout", "--force", "--no-recurse-submodules", "-B", branch, "FETCH_HEAD"],
      ["git", "branch", "--set-upstream-to", f"origin/{branch}"],
      ["git", "reset", "--hard", "FETCH_HEAD"],
      ["git", "submodule", "sync"],
      ["git", "submodule", "update", "--init", "--recursive"],
      ["git", "submodule", "foreach", "--recursive", "git", "reset", "--hard"],
    ]
    r = [run(cmd, BASEDIR) for cmd in cmds]
    cloudlog.info("git reset success: %s", '\n'.join(r))
    cleanup_stale_prebuilt_marker(BASEDIR, branch)

    # TODO: show agnos download progress
    if AGNOS:
      handle_agnos_update()

    cloudlog.info("update applied to disk; reboot to finish")


def main() -> None:
  params = Params()

  if params.get_bool("DisableUpdates"):
    cloudlog.warning("updates are disabled by the DisableUpdates param")
    exit(0)

  with open(LOCK_FILE, 'w') as ov_lock_fd:
    try:
      fcntl.flock(ov_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
      raise RuntimeError("couldn't get overlay lock; is another instance running?") from e

    # Set low io priority
    proc = psutil.Process()
    if psutil.LINUX:
      proc.ionice(psutil.IOPRIO_CLASS_BE, value=7)

    cleanup_stale_overlay()

    if not params.get("InstallDate"):
      t = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
      params.put("InstallDate", t)

    updater = Updater()
    update_failed_count = 0 # TODO: Load from param?
    wait_helper = WaitTimeHelper()

    params.put("UpdaterState", "idle")
    params.put_bool("UpdateAvailable", False)

    # Run the update loop
    first_run = True
    while True:
      wait_helper.ready_event.clear()

      # Attempt an update
      exception = None
      try:
        # ensure we have some params written soon after startup
        updater.set_params(False, update_failed_count, exception)

        if not system_time_valid() or first_run:
          first_run = False
          wait_helper.sleep(60)
          continue

        update_failed_count += 1

        # check for update
        params.put("UpdaterState", "checking...")
        updater.check_for_update()

        # download update
        last_fetch = params.get("UpdaterLastFetchTime")
        timed_out = last_fetch is None or (datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - last_fetch > datetime.timedelta(days=3))
        user_requested_fetch = wait_helper.user_request == UserRequest.FETCH
        if params.get_bool("IsOnroad") and not user_requested_fetch:
          # the update download + AGNOS flash hold hundreds of MB; onroad that trips lowMemory,
          # so defer the heavy work until parked
          cloudlog.info("skipping fetch, device is onroad")
        elif params.get_bool("NetworkMetered") and not timed_out and not user_requested_fetch:
          cloudlog.info("skipping fetch, connection metered")
        elif wait_helper.user_request == UserRequest.CHECK:
          cloudlog.info("skipping fetch, only checking")
        elif updater.update_available or user_requested_fetch:
          updater.fetch_update()
          write_time_to_param(params, "UpdaterLastFetchTime")
          if updater.update_ready and updater.install_mode == UpdateInstallMode.DOWNLOAD_AND_INSTALL:
            cloudlog.info("update ready; auto-install mode enabled, triggering reboot")
            params.put_bool("DoReboot", True)
        else:
          cloudlog.info("already up to date, skipping fetch")
        update_failed_count = 0
      except subprocess.CalledProcessError as e:
        cloudlog.event(
          "update process failed",
          cmd=e.cmd,
          output=e.output,
          returncode=e.returncode
        )
        exception = f"command failed: {e.cmd}\n{e.output}"
      except Exception as e:
        cloudlog.exception("uncaught updated exception, shouldn't happen")
        exception = str(e)

      try:
        params.put("UpdaterState", "idle")
        update_successful = (update_failed_count == 0)
        updater.set_params(update_successful, update_failed_count, exception)
      except Exception:
        cloudlog.exception("uncaught updated exception while setting params, shouldn't happen")

      # infrequent attempts if we successfully updated recently
      wait_helper.user_request = UserRequest.NONE
      wait_helper.sleep(5*60 if update_failed_count > 0 else 1.5*60*60)


if __name__ == "__main__":
  main()

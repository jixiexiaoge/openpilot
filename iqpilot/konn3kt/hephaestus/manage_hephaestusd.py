"""
Copyright ©️ IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import importlib
import os
import time
from multiprocessing import Process

HEPHAESTUS_MGR_PID_PARAM = "HephaestusdPid"


def _cloudlog():
  try:
    from openpilot.common.swaglog import cloudlog
    return cloudlog
  except Exception:
    return None


def _log(level: str, msg: str) -> None:
  cl = _cloudlog()
  if cl is not None:
    try:
      getattr(cl, level)(msg)
      return
    except Exception:
      pass
  try:
    print(f"manage_hephaestusd[{level}]: {msg}", flush=True)
  except Exception:
    pass


def _lightweight_launcher(proc: str, name: str) -> None:
  try:
    mod = importlib.import_module(proc)
    try:
      from setproctitle import setproctitle
      setproctitle(proc)
    except Exception:
      pass
    cl = _cloudlog()
    if cl is not None:
      try:
        cl.bind(daemon=name)
      except Exception:
        pass
    mod.main()
  except KeyboardInterrupt:
    _log("warning", f"child {proc} got SIGINT")
  except Exception:
    _log("exception", f"child {proc} exception")
    raise


def _bind_global_best_effort(dongle_id_param: str) -> None:
  try:
    from openpilot.common.params import Params
    from openpilot.common.swaglog import cloudlog
    from openpilot.system.hardware import HARDWARE
  except Exception:
    return
  try:
    dongle_id = Params().get(dongle_id_param)
    try:
      from openpilot.system.version import get_build_metadata
      build_metadata = get_build_metadata()
      cloudlog.bind_global(dongle_id=dongle_id,
                           version=build_metadata.openpilot.version,
                           origin=build_metadata.openpilot.git_normalized_origin,
                           branch=build_metadata.channel,
                           commit=build_metadata.openpilot.git_commit,
                           dirty=build_metadata.openpilot.is_dirty,
                           device=HARDWARE.get_device_type())
    except Exception:
      cloudlog.bind_global(dongle_id=dongle_id, device=HARDWARE.get_device_type())
  except Exception:
    pass


def _remove_pid_param(pid_param: str) -> None:
  try:
    from openpilot.common.params import Params
    Params().remove(pid_param)
  except Exception:
    pass


def manage_hephaestusd(dongle_id_param: str, pid_param: str, process_name: str, target: str) -> None:
  _bind_global_best_effort(dongle_id_param)

  try:
    while 1:
      _log("info", f"starting {process_name} daemon")
      proc = Process(name=process_name, target=_lightweight_launcher, args=(target, process_name))
      proc.start()
      # Lower priority so BLE stack doesn't compete with OP's Python processes
      # on an already heavily loaded system (RT processes like pandad/modeld are unaffected)
      if proc.pid is not None:
        try:
          os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
        except OSError:
          pass
      proc.join()
      _log("info", f"{process_name} exited (exitcode={proc.exitcode})")
      if proc.exitcode == 174:
        time.sleep(30)
      else:
        time.sleep(5)
  except Exception:
    _log("exception", f"manage_{process_name}.exception")
  finally:
    _remove_pid_param(pid_param)


def main():
  manage_hephaestusd(dongle_id_param="DongleId", pid_param=HEPHAESTUS_MGR_PID_PARAM, process_name="hephaestusd",
                     target="iqpilot.konn3kt.hephaestus.hephaestusd")


if __name__ == '__main__':
  main()

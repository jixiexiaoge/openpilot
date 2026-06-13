"""
Copyright ©️ IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import importlib
import os
import time
from multiprocessing import Process

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE

HEPHAESTUS_MGR_PID_PARAM = "HephaestusdPid"


def _lightweight_launcher(proc: str, name: str) -> None:
  try:
    mod = importlib.import_module(proc)
    try:
      from setproctitle import setproctitle
      setproctitle(proc)
    except Exception:
      pass
    cloudlog.bind(daemon=name)
    mod.main()
  except KeyboardInterrupt:
    cloudlog.warning(f"child {proc} got SIGINT")
  except Exception:
    cloudlog.exception(f"child {proc} exception")
    raise


def manage_hephaestusd(dongle_id_param: str, pid_param: str, process_name: str, target: str) -> None:
  params = Params()
  dongle_id = params.get(dongle_id_param)

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

  try:
    while 1:
      cloudlog.info(f"starting {process_name} daemon")
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
      cloudlog.event(f"{process_name} exited", exitcode=proc.exitcode)
      if proc.exitcode == 174:
        time.sleep(30)
      else:
        time.sleep(5)
  except Exception:
    cloudlog.exception(f"manage_{process_name}.exception")
  finally:
    params.remove(pid_param)


def main():
  manage_hephaestusd(dongle_id_param="DongleId", pid_param=HEPHAESTUS_MGR_PID_PARAM, process_name="hephaestusd",
                     target="iqpilot.konn3kt.hephaestus.hephaestusd")


if __name__ == '__main__':
  main()

import os
import subprocess

from openpilot.common.params import Params

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "set_usb_storage.sh")


def apply_usb_storage_state(state: bool):
  Params().put_bool("UsbStorageEnabled", state)
  try:
    args = ["sudo", SCRIPT_PATH]
    if state:
      args.append("--rebuild")
    subprocess.Popen(args)
  except OSError:
    pass

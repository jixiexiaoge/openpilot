#!/usr/bin/env python3
import datetime
import os
import signal
import sys
import time
import traceback

from cereal import log
import cereal.messaging as messaging
import openpilot.system.sentry as sentry
from openpilot.common.params import Params, ParamKeyFlag
from openpilot.common.text_window import TextWindow
from openpilot.system.hardware import HARDWARE
from openpilot.system.manager.helpers import unblock_stdout, write_onroad_params, save_bootlog
from openpilot.system.manager.process import ensure_running
from openpilot.system.manager.process_config import managed_processes
from openpilot.system.athena.registration import register, UNREGISTERED_DONGLE_ID
from openpilot.common.swaglog import cloudlog, add_file_handler
from openpilot.system.version import get_build_metadata, terms_version, training_version
from openpilot.system.hardware.hw import Paths

def set_default_params():
  params = Params()
  for k in params.all_keys():
    default_value = params.get_default_value(k)
    if default_value is not None:
      params.put(k, default_value)
      print(f"SetToDefault[{k}]={default_value}")

def get_default_params_key():
  return Params().all_keys()
  #default_params = get_default_params()
  #all_keys = [key for key, _ in default_params]
  #return all_keys

def manager_init() -> None:
  save_bootlog()

  build_metadata = get_build_metadata()

  params = Params()
  params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)
  if build_metadata.release_channel:
    params.clear_all(ParamKeyFlag.DEVELOPMENT_ONLY)

  if params.get_bool("RecordFrontLock"):
    params.put_bool("RecordFront", True)

  # set unset params to their default value
  for k in params.all_keys():
    default_value = params.get_default_value(k)
    if default_value is not None and params.get(k) is None:
      params.put(k, default_value)

  # Create folders needed for msgq
  try:
    os.mkdir(Paths.shm_path())
  except FileExistsError:
    pass
  except PermissionError:
    print(f"WARNING: failed to make {Paths.shm_path()}")

  # set params
  serial = HARDWARE.get_serial()
  params.put("Version", build_metadata.openpilot.version)
  params.put("TermsVersion", terms_version)
  params.put("TrainingVersion", training_version)
  params.put("GitCommit", build_metadata.openpilot.git_commit)
  params.put("GitCommitDate", build_metadata.openpilot.git_commit_date)
  params.put("GitBranch", build_metadata.channel)
  params.put("GitRemote", build_metadata.openpilot.git_origin)
  params.put_bool("IsTestedBranch", build_metadata.tested_channel)
  params.put_bool("IsReleaseBranch", build_metadata.release_channel)
  params.put("HardwareSerial", serial)

  # set dongle id
  reg_res = register(show_spinner=True)
  if reg_res:
    dongle_id = reg_res
  else:
    raise Exception(f"Registration failed for device {serial}")
  os.environ['DONGLE_ID'] = dongle_id  # Needed for swaglog
  os.environ['GIT_ORIGIN'] = build_metadata.openpilot.git_normalized_origin # Needed for swaglog
  os.environ['GIT_BRANCH'] = build_metadata.channel # Needed for swaglog
  os.environ['GIT_COMMIT'] = build_metadata.openpilot.git_commit # Needed for swaglog

  if not build_metadata.openpilot.is_dirty:
    os.environ['CLEAN'] = '1'

  # init logging
  sentry.init(sentry.SentryProject.SELFDRIVE)
  cloudlog.bind_global(dongle_id=dongle_id,
                       version=build_metadata.openpilot.version,
                       origin=build_metadata.openpilot.git_normalized_origin,
                       branch=build_metadata.channel,
                       commit=build_metadata.openpilot.git_commit,
                       dirty=build_metadata.openpilot.is_dirty,
                       device=HARDWARE.get_device_type())

  # preimport all processes
  for p in managed_processes.values():
    p.prepare()


def manager_cleanup() -> None:
  # send signals to kill all procs
  for p in managed_processes.values():
    p.stop(block=False)

  # ensure all are killed
  for p in managed_processes.values():
    p.stop(block=True)

  cloudlog.info("everything is dead")

def read_rss_kb(pid: int) -> int:
  try:
    with open(f"/proc/{pid}/status") as f:
      for line in f:
        if line.startswith("VmRSS:"):
          return int(line.split()[1])  # kB
  except Exception:
    pass
  return 0

def manager_thread() -> None:
  cloudlog.bind(daemon="manager")
  cloudlog.info("manager start")
  cloudlog.info({"environ": os.environ})

  params = Params()

  ignore: list[str] = []
  if params.get("DongleId") in (None, UNREGISTERED_DONGLE_ID):
    ignore += ["manage_athenad", "uploader"]
  if os.getenv("NOBOARD") is not None:
    ignore.append("pandad")
  ignore += [x for x in os.getenv("BLOCK", "").split(",") if len(x) > 0]

  if params.get_bool("HardwareC3xLite"):
    ignore += ["micd", "soundd", "loggerd"]
    params.put_bool("RecordAudio", False)

  sm = messaging.SubMaster(['deviceState', 'carParams', 'pandaStates'], poll='deviceState')
  pm = messaging.PubMaster(['managerState'])

  write_onroad_params(False, params)
  print(f"################# ignore process list: {ignore} #################")
  ensure_running(managed_processes.values(), False, params=params, CP=sm['carParams'], not_run=ignore)

  print_timer = 0

  started_prev = False
  ignition_prev = False

  while True:
    sm.update(1000)
    now = time.monotonic()

    started = sm['deviceState'].started

    if started and not started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
    elif not started and started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)

    ignition = any(ps.ignitionLine or ps.ignitionCan for ps in sm['pandaStates'] if ps.pandaType != log.PandaState.PandaType.unknown)
    if ignition and not ignition_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)

    # update onroad params, which drives pandad's safety setter thread
    if started != started_prev:
      write_onroad_params(started, params)

    started_prev = started
    ignition_prev = ignition

    ensure_running(managed_processes.values(), started, params=params, CP=sm['carParams'], not_run=ignore)

    running = ' '.join("{}{}\u001b[0m".format("\u001b[32m" if p.proc.is_alive() else "\u001b[31m", p.name)
                       for p in managed_processes.values() if p.proc)
    print_timer = (print_timer + 1)%10
    if print_timer == 0:
      print(running)
    cloudlog.debug(running)

    # send managerState
    msg = messaging.new_message('managerState', valid=True)
    msg.managerState.processes = [p.get_process_state_msg() for p in managed_processes.values()]
    pm.send('managerState', msg)

    # Exit main loop when uninstall/shutdown/reboot is needed
    shutdown = False
    for param in ("DoUninstall", "DoShutdown", "DoReboot"):
      if params.get_bool(param):
        shutdown = True
        params.put("LastManagerExitReason", f"{param} {datetime.datetime.now()}")
        cloudlog.warning(f"Shutting down manager - {param} set")

    if shutdown:
      break

def compile_pending_model() -> None:
  """Check for pending model compilation and compile if needed"""
  from pathlib import Path
  import subprocess
  import shutil

  MODELS_TMP_DIR = Path("/data/models_tmp")
  MODELS_DIR = Path("/data/models")
  MODELS_BACKUP_DIR = Path("/data/models_backup")

  if not MODELS_TMP_DIR.exists():
    return

  # Check if ONNX files exist (on_policy 또는 policy 둘 중 하나 필요)
  vision_onnx = MODELS_TMP_DIR / "driving_vision.onnx"
  on_policy_onnx = MODELS_TMP_DIR / "driving_on_policy.onnx"
  policy_onnx = MODELS_TMP_DIR / "driving_policy.onnx"
  has_on_policy = on_policy_onnx.exists()
  has_policy = policy_onnx.exists()

  if not vision_onnx.exists() or not (has_policy or has_on_policy):
    cloudlog.warning("model_compile: ONNX files not found, cleaning up")
    shutil.rmtree(MODELS_TMP_DIR, ignore_errors=True)
    return

  cloudlog.warning("model_compile: Found pending model, starting compilation...")

  params = Params()
  model_name = params.get("PendingModelName")
  if not model_name:
    cloudlog.warning("model_compile: PendingModelName is empty, cleaning up")
    shutil.rmtree(MODELS_TMP_DIR, ignore_errors=True)
    return

  try:
    openpilot_dir = "/data/openpilot"
    metadata_script = f"{openpilot_dir}/selfdrive/modeld/get_model_metadata.py"
    compile_script = f"{openpilot_dir}/tinygrad_repo/examples/openpilot/compile3.py"

    env = os.environ.copy()
    env["DEV"] = "QCOM"
    env["FLOAT16"] = "1"
    env["NOLOCALS"] = "1"
    env["JIT_BATCH_SIZE"] = "0"
    env["IMAGE"] = "2"

    # on_policy가 있으면 on_policy 사용, 아니면 기존 policy
    model_names = ["driving_vision"]
    if has_on_policy:
      model_names.append("driving_on_policy")
      cloudlog.warning("model_compile: on_policy model detected")
    else:
      model_names.append("driving_policy")

    # off-policy 모델이 있으면 함께 컴파일
    off_policy_onnx = MODELS_TMP_DIR / "driving_off_policy.onnx"
    if off_policy_onnx.exists():
      model_names.append("driving_off_policy")
      cloudlog.warning("model_compile: Off-policy model detected")

    cloudlog.warning(f"model_compile: Will compile {len(model_names)} models: {model_names}")

    for model in model_names:
      onnx_path = str(MODELS_TMP_DIR / f"{model}.onnx")
      pkl_path = str(MODELS_TMP_DIR / f"{model}_tinygrad.pkl")
      meta_path = str(MODELS_TMP_DIR / f"{model}_metadata.pkl")

      cloudlog.warning(f"model_compile: Generating metadata for {model}")
      result = subprocess.run(["python3", metadata_script, onnx_path, meta_path],
                              cwd=openpilot_dir, capture_output=True)
      if result.returncode != 0:
        raise Exception(f"Metadata failed: {result.stderr.decode()}")

      cloudlog.warning(f"model_compile: Compiling {model} with tinygrad")
      result = subprocess.run(["python3", compile_script, onnx_path, pkl_path],
                              cwd=openpilot_dir, env=env, capture_output=True)
      if result.returncode != 0:
        raise Exception(f"Compile failed: {result.stderr.decode()}")

    # Compile warp transform
    cloudlog.warning("model_compile: Compiling warp transform...")
    compile_warp_script = f"{openpilot_dir}/selfdrive/modeld/compile_warp.py"
    result = subprocess.run(["python3", compile_warp_script],
                            cwd=openpilot_dir, env=env, capture_output=True)
    if result.returncode != 0:
      raise Exception(f"Warp compile failed: {result.stderr.decode()}")

    # Copy warp files to model directory
    builtin_models = Path(f"{openpilot_dir}/selfdrive/modeld/models")
    for warp_file in builtin_models.glob("warp_*_tinygrad.pkl"):
      shutil.copy2(warp_file, MODELS_TMP_DIR / warp_file.name)

    # Install: backup → swap → cleanup
    cloudlog.warning("model_compile: Installing model...")

    if MODELS_BACKUP_DIR.exists():
      shutil.rmtree(MODELS_BACKUP_DIR)

    if MODELS_DIR.exists():
      MODELS_DIR.rename(MODELS_BACKUP_DIR)

    MODELS_TMP_DIR.rename(MODELS_DIR)

    if MODELS_BACKUP_DIR.exists():
      shutil.rmtree(MODELS_BACKUP_DIR)

    params.put("DrivingModelName", model_name)
    params.remove("PendingModelName")

    cloudlog.warning(f"model_compile: Successfully installed {model_name}")

  except Exception as e:
    cloudlog.error(f"model_compile: Failed - {e}")
    shutil.rmtree(MODELS_TMP_DIR, ignore_errors=True)
    # 백업에서 기존 모델 복원
    if MODELS_BACKUP_DIR.exists() and not MODELS_DIR.exists():
      MODELS_BACKUP_DIR.rename(MODELS_DIR)
      cloudlog.warning("model_compile: Restored previous model from backup")
    params.remove("PendingModelName")


def main() -> None:
  manager_init()

  # Check for pending model compilation
  compile_pending_model()
  print(f"python ../../opendbc/car/hyundai/values.py > {Params().get_param_path()}/SupportedCars")
  os.system(f"python ../../opendbc/car/hyundai/values.py > {Params().get_param_path()}/SupportedCars")
  os.system(f"python ../../opendbc/car/gm/values.py > {Params().get_param_path()}/SupportedCars_gm")
  os.system(f"python ../../opendbc/car/toyota/values.py > {Params().get_param_path()}/SupportedCars_toyota")
  os.system(f"python ../../opendbc/car/mazda/values.py > {Params().get_param_path()}/SupportedCars_mazda")

  if os.getenv("PREPAREONLY") is not None:
    return

  # SystemExit on sigterm
  signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(1))

  try:
    manager_thread()
  except Exception:
    traceback.print_exc()
    sentry.capture_exception()
  finally:
    manager_cleanup()

  params = Params()
  if params.get_bool("DoUninstall"):
    cloudlog.warning("uninstalling")
    HARDWARE.uninstall()
  elif params.get_bool("DoReboot"):
    cloudlog.warning("reboot")
    HARDWARE.reboot()
  elif params.get_bool("DoShutdown"):
    cloudlog.warning("shutdown")
    HARDWARE.shutdown()


if __name__ == "__main__":
  unblock_stdout()

  try:
    main()
  except KeyboardInterrupt:
    print("got CTRL-C, exiting")
  except Exception:
    add_file_handler(cloudlog)
    cloudlog.exception("Manager failed to start")

    try:
      managed_processes['ui'].stop()
    except Exception:
      pass

    # Show last 3 lines of traceback
    error = traceback.format_exc(-3)
    error = "Manager failed to start\n\n" + error
    with TextWindow(error) as t:
      t.wait_for_exit()

    raise

  # manual exit because we are forked
  sys.exit(0)

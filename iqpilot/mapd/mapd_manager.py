#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import platform
import os
import glob
import shutil
import subprocess
import threading
import time
from datetime import datetime

import cereal.messaging as messaging
from cereal import custom
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper, config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
from openpilot.system.hardware.hw import Paths
from openpilot.iqpilot.mapd import MAPD_PATH, MAPD_BIN_DIR
from openpilot.iqpilot.mapd.mapd_installer import MapdInstallManager

MapdInputType = custom.MapdInputType
_download_thread: threading.Thread | None = None


class _NoopSpinner:
  def update(self, *args, **kwargs) -> None:
    pass

  def close(self, *args, **kwargs) -> None:
    pass


def ensure_mapd_installed() -> None:
  # pfeiferj/mapd v2 ships as a separate download (not committed to the repo), so
  # actually download the pinned VERSION when the on-disk binary differs instead
  # of merely stamping the version param.
  try:
    MapdInstallManager(_NoopSpinner()).check_and_download()
  except Exception:
    cloudlog.exception("mapd: install/download failed")

# PFEIFER - MAPD {{
params = Params()
mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else params
# }} PFEIFER - MAPD


def get_files_for_cleanup() -> list[str]:
  paths = [
    f"{Paths.mapd_root()}/db",
    f"{Paths.mapd_root()}/v*"
  ]
  files_to_remove = []
  for path in paths:
    if os.path.exists(path):
      files = glob.glob(path + '/**', recursive=True)
      files_to_remove.extend(files)
  # check for version and mapd files
  if not os.path.isfile(MAPD_PATH):
    files_to_remove.append(MAPD_PATH)
  return files_to_remove


def cleanup_old_osm_data(files_to_remove: list[str]) -> None:
  for file in files_to_remove:
    # Remove trailing slash if path is file
    if file.endswith('/') and os.path.isfile(file[:-1]):
      file = file[:-1]
    # Try to remove as file or symbolic link first
    if os.path.islink(file) or os.path.isfile(file):
      os.remove(file)
    elif os.path.isdir(file):  # If it's a directory
      shutil.rmtree(file, ignore_errors=False)


def _region_download_paths(nations: list[str], states: list[str] | None = None) -> str:
  # Translate konn3kt's (nations, states) selection into pfeiferj/mapd v2 menu
  # paths: us_state.<ST> for US states, nation.<CC> for nations, comma-joined.
  paths = []
  for s in (states or []):
    code = str(s).strip().upper()
    if code and code != "ALL":
      paths.append(f"us_state.{code}")
  for n in (nations or []):
    code = str(n).strip().upper()
    if code:
      paths.append(f"nation.{code}")
  return ",".join(paths)


def _run_mapd_download(path: str, locations: dict) -> None:
  # mapd v2 downloads are driven by a `download` mapdIn action sent to a RUNNING
  # mapd instance (which fetches offline/{lat}/{lng}.tar.gz tiles). Offroad there
  # is no mapd, so spawn one transiently, send the command, monitor progress via
  # mapdExtendedOut.downloadProgress, then stop it.
  #
  # konn3kt's getOsmStatus()/cancelOsmDownload() are reused unchanged: presence of
  # the OSMDownloadLocations mem-param is the "downloading" flag, OSMDownloadProgress
  # carries total_files/downloaded_files, and konn3kt cancels by removing
  # OSMDownloadLocations (which we detect and forward as a cancelDownload action).
  proc = None
  try:
    mem_params.put("OSMDownloadLocations", locations)  # JSON param: pass the dict, not a string
    proc = subprocess.Popen([MAPD_PATH], cwd=MAPD_BIN_DIR,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pm = messaging.PubMaster(["mapdIn"])
    sm = messaging.SubMaster(["mapdExtendedOut"])
    time.sleep(4.0)  # let mapd start and subscribe to mapdIn

    for _ in range(10):  # repeat briefly to ensure the running mapd receives it
      msg = messaging.new_message("mapdIn")
      msg.mapdIn.type = MapdInputType.download
      msg.mapdIn.str = path
      pm.send("mapdIn", msg)
      time.sleep(0.2)

    started = False
    deadline = time.monotonic() + 3600.0
    while time.monotonic() < deadline:
      sm.update(500)
      dp = sm["mapdExtendedOut"].downloadProgress
      mem_params.put("OSMDownloadProgress", {
        "active": bool(dp.active),
        "total_files": int(dp.totalFiles),
        "downloaded_files": int(dp.downloadedFiles),
      })
      if dp.active:
        started = True
      elif started:
        break  # active -> inactive: download complete
      if not mem_params.get("OSMDownloadLocations"):  # konn3kt requested cancel
        cancel = messaging.new_message("mapdIn")
        cancel.mapdIn.type = MapdInputType.cancelDownload
        pm.send("mapdIn", cancel)
        break
    cloudlog.info(f"mapd: OSM v2 download finished for {path}")
  except Exception:
    cloudlog.exception("mapd: OSM v2 download failed")
  finally:
    try:
      mem_params.remove("OSMDownloadLocations")
    except Exception:
      pass
    if proc is not None:
      proc.terminate()
      try:
        proc.wait(timeout=5)
      except Exception:
        proc.kill()


def request_refresh_osm_location_data(nations: list[str], states: list[str] | None = None) -> None:
  global _download_thread
  params.put("OsmDownloadedDate", str(datetime.now().timestamp()))
  params.put_bool("OsmDbUpdatesCheck", False)

  path = _region_download_paths(nations, states)
  if not path:
    cloudlog.warning("mapd: no region selected for OSM download")
    return
  if _download_thread is not None and _download_thread.is_alive():
    cloudlog.warning("mapd: OSM download already in progress")
    return

  locations = {"nations": nations, "states": states or [], "paths": path}
  cloudlog.info(f"mapd: starting v2 OSM download for {path}")
  _download_thread = threading.Thread(target=_run_mapd_download, args=(path, locations), daemon=True)
  _download_thread.start()


def filter_nations_and_states(nations: list[str], states: list[str] | None = None) -> tuple[list[str], list[str]]:
  """Filters and prepares nation and state data for OSM map download.

  If the nation is 'US' and a specific state is provided, the nation 'US' is removed from the list.
  If the nation is 'US' and the state is 'All', the 'All' is removed from the list.
  The idea behind these filters is that if a specific state in the US is provided,
  there's no need to download map data for the entire US. Conversely,
  if the state is unspecified (i.e., 'All'), we intend to download map data for the whole US,
  and 'All' isn't a valid state name, so it's removed.

  Parameters:
  nations (list): A list of nations for which the map data is to be downloaded.
  states (list, optional): A list of states for which the map data is to be downloaded. Defaults to None.

  Returns:
  tuple: Two lists. The first list is filtered nations and the second list is filtered states.
  """

  if "US" in nations and states and not any(x.lower() == "all" for x in states):
    # If a specific state in the US is provided, remove 'US' from nations
    nations.remove("US")
  elif "US" in nations and states and any(x.lower() == "all" for x in states):
    # If 'All' is provided as a state (case invariant), remove those instances from states
    states = [x for x in states if x.lower() != "all"]
  elif "US" not in nations and states and any(x.lower() == "all" for x in states):
    states.remove("All")
  return nations, states or []


def update_osm_db() -> None:
  if params.get_bool("OsmDbUpdatesCheck"):
    cleanup_old_osm_data(get_files_for_cleanup())
    country = params.get("OsmLocationName", return_default=True)
    state = params.get("OsmStateName", return_default=True)
    filtered_nations, filtered_states = filter_nations_and_states([country], [state])
    request_refresh_osm_location_data(filtered_nations, filtered_states)

  if not mem_params.get("OSMDownloadBounds"):
    mem_params.put("OSMDownloadBounds", "")

  if not mem_params.get("LastGPSPosition"):
    mem_params.put("LastGPSPosition", "{}")


def main_thread():
  ensure_mapd_installed()
  config_realtime_process([0, 1, 2, 3], 5)

  rk = Ratekeeper(1, print_delay_threshold=None)

  # Create folder needed for OSM
  try:
    os.mkdir(Paths.mapd_root())
  except FileExistsError:
    pass
  except PermissionError:
    cloudlog.exception(f"mapd: failed to make {Paths.mapd_root()}")

  while True:
    show_alert = get_files_for_cleanup() and params.get_bool("OsmLocal")
    set_offroad_alert("Offroad_OSMUpdateRequired", show_alert, "This alert will be cleared when new maps are downloaded.")

    update_osm_db()
    rk.keep_time()


def main():
  main_thread()


if __name__ == "__main__":
  main()

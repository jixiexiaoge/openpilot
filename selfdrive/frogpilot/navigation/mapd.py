# PFEIFER - MAPD - Modified by FrogAi for FrogPilot to automatically update
import json
import os
import stat
import subprocess
import time
import urllib.request

VERSION = 'v1'

GITHUB_VERSION_URL = f"https://github.com/FrogAi/FrogPilot-Resources/raw/Versions/mapd_version_{VERSION}.json"
GITLAB_VERSION_URL = f"https://gitlab.com/FrogAi/FrogPilot-Resources/-/raw/Versions/mapd_version_{VERSION}.json"

MAPD_PATH = '/data/media/0/osm/mapd'
VERSION_PATH = '/data/media/0/osm/mapd_version'

def download(current_version):
  urls = [
    f"https://github.com/pfeiferj/openpilot-mapd/releases/download/{current_version}/mapd",
    f"https://gitlab.com/FrogAi/FrogPilot-Resources/-/raw/Mapd/{current_version}"
  ]

  os.makedirs(os.path.dirname(MAPD_PATH), exist_ok=True)

  for url in urls:
    try:
      with urllib.request.urlopen(url, timeout=5) as f:
        with open(MAPD_PATH, 'wb') as output:
          output.write(f.read())
        os.chmod(MAPD_PATH, os.stat(MAPD_PATH).st_mode | stat.S_IEXEC)

        with open(VERSION_PATH, 'w') as version_file:
          version_file.write(current_version)
      print(f"Successfully downloaded mapd from {url}")
      return True
    except Exception as e:
      print(f"Failed to download mapd from {url}: {e}")

  print(f"Failed to download mapd for version {current_version}")
  return False

def get_installed_version():
  try:
    with open(VERSION_PATH, 'r') as version_file:
      return version_file.read().strip()
  except FileNotFoundError:
    return None
  except Exception as e:
    print(f"Error reading installed version: {e}")
    return None

def get_latest_version():
  for url in [GITHUB_VERSION_URL, GITLAB_VERSION_URL]:
    try:
      with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode('utf-8'))['version']
    except Exception as e:
      print(f"Error fetching mapd version from {url}: {e}")
  print("Failed to get the latest mapd version")
  return None

def update_mapd():
  installed_version = get_installed_version()
  latest_version = get_latest_version()

  if latest_version is None:
    print("Could not get the latest mapd version")
    return

  if installed_version != latest_version:
    print("New version available, stopping mapd for update...")
    try:
      subprocess.run(["pkill", "-f", MAPD_PATH], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
      print(f"Error stopping mapd process: {e}")
    if download(latest_version):
      print(f"Updated mapd to version {latest_version}")
    else:
      print("Failed to update mapd")
  else:
    print("Mapd is up to date")

def ensure_mapd_is_running():
  while True:
    try:
      subprocess.run([MAPD_PATH], check=True)
    except Exception as e:
      print(f"Error running mapd process: {e}")
      time.sleep(60)

def main():
  ensure_mapd_is_running()

if __name__ == "__main__":
  main()

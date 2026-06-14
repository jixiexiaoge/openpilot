#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import json
import os

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog


def _car_list_path() -> str:
  candidates = [
    os.path.join(BASEDIR, "opendbc", "iqpilot", "car", "car_list.json"),
    os.path.join(BASEDIR, "opendbc_repo", "opendbc", "iqpilot", "car", "car_list.json"),
    os.path.join(BASEDIR, "iqpilot", "selfdrive", "car", "car_list.json"),  # legacy path
  ]
  for path in candidates:
    if os.path.isfile(path):
      return path
  return ""


def update_car_list_param():
  car_list_path = _car_list_path()
  if not car_list_path:
    cloudlog.warning("Car list file not found in known paths, skipping CarList param update")
    return

  with open(car_list_path) as f:
    current_car_list = json.load(f)

  params = Params()
  if params.get("CarList") != current_car_list:
    params.put("CarList", current_car_list)
    cloudlog.warning("Updated CarList param with latest platform list")
  else:
    cloudlog.warning("CarList param is up to date, no need to update")


if __name__ == "__main__":
  update_car_list_param()

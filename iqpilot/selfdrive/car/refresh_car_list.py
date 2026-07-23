#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot.selfdrive.car.vehicle_catalog import load_catalog


def refresh_car_list_param() -> None:
  platforms = load_catalog()
  if not platforms:
    cloudlog.warning("vehicle catalog not found; leaving CarList param unchanged")
    return

  params = Params()
  if params.get("CarList") == platforms:
    cloudlog.warning("CarList param already current, nothing to write")
    return

  params.put("CarList", platforms)
  cloudlog.warning("CarList param refreshed from vehicle catalog")


if __name__ == "__main__":
  refresh_car_list_param()

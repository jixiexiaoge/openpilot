"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import threading
import traceback

from openpilot.common.realtime import Ratekeeper, config_realtime_process
from openpilot.iqpilot.iq_maps.road_data import debug_road_data
from openpilot.iqpilot.iq_maps.road_data.iq_road_layer import IQRoadLayer

ROAD_LAYER_HZ = 1
ROAD_LAYER_CORES = [0, 1, 2, 3]


def _log_thread_exception(args) -> None:
  debug_road_data(f"IQ maps threading exception:\n{args}")
  traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)


def run() -> None:
  config_realtime_process(ROAD_LAYER_CORES, 5)
  layer = IQRoadLayer()
  rk = Ratekeeper(ROAD_LAYER_HZ, print_delay_threshold=None)
  while True:
    layer.step()
    rk.keep_time()


def main() -> None:
  threading.excepthook = _log_thread_exception
  run()


if __name__ == "__main__":
  main()

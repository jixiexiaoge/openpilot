"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

import os
import time

import numpy as np

import cereal.messaging as messaging
from openpilot.system.manager.process_config import managed_processes

RUN_COUNT = int(os.getenv("N", "5"))
WINDOW_SECONDS = int(os.getenv("TIME", "30"))
WARMUP_MESSAGES = 10


def _collect_execution_samples(sock, duration_s: int) -> np.ndarray:
  samples: list[float] = []
  deadline = time.monotonic() + duration_s
  while time.monotonic() < deadline:
    for message in messaging.drain_sock(sock, wait_for_one=True):
      samples.append(message.modelV2.modelExecutionTime)
  return np.array(samples[WARMUP_MESSAGES:]) * 1000.0


def _single_benchmark_pass(sock) -> np.ndarray:
  os.environ["LOGPRINT"] = "debug"
  managed_processes["modeld"].start()
  time.sleep(5)
  try:
    return _collect_execution_samples(sock, WINDOW_SECONDS)
  finally:
    managed_processes["modeld"].stop()


def _report_run(index: int, values_ms: np.ndarray) -> None:
  print(
    f"run {index}: avg={values_ms.mean():0.2f}ms "
    f"min={values_ms.min():0.2f}ms max={values_ms.max():0.2f}ms"
  )


if __name__ == "__main__":
  subscriber = messaging.sub_sock("modelV2", conflate=False, timeout=1000)
  all_runs = [_single_benchmark_pass(subscriber) for _ in range(RUN_COUNT)]

  print("\n")
  print(f"ran modeld {RUN_COUNT} times for {WINDOW_SECONDS}s each")
  for index, values_ms in enumerate(all_runs, start=1):
    _report_run(index, values_ms)
  print("\n")

#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import logging

from openpilot.iqpilot._proprietary_loader import load_private_module


_ORIGINAL_LOGGER_LOG = logging.Logger._log


def _ble_transport_logger_shim(self, level, msg, args,
                               exc_info=None, extra=None, stack_info=False, stacklevel=1, **kwargs):
  if kwargs:
    suffix = " ".join(f"{key}={value!r}" for key, value in sorted(kwargs.items()))
    msg = f"{msg} {suffix}".strip() if msg is not None else suffix
  return _ORIGINAL_LOGGER_LOG(
    self, level, msg, args,
    exc_info=exc_info, extra=extra, stack_info=stack_info, stacklevel=stacklevel,
  )


logging.Logger._log = _ble_transport_logger_shim

load_private_module(__name__, "iqpilot_private.konn3kt.hephaestus.ble_transportd")

if __name__ == "__main__":
  main()

#!/usr/bin/env python3
"""
Copyright (c) IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.iqpilot._proprietary_loader import load_private_module

load_private_module(__name__, "iqpilot_private.models.manager")

if __name__ == "__main__":
  main()

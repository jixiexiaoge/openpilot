#!/usr/bin/env python3
from openpilot.iqpilot._proprietary_loader import load_private_module

load_private_module(__name__, "iqpilot_private.konn3kt.uploaderd.iquploaderd")

if __name__ == "__main__":
  main()

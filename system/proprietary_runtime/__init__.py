import os
_ROOTFS_PKG = "/usr/libexec/iqpilot/python/openpilot/system/proprietary_runtime"
if os.path.isdir(_ROOTFS_PKG) and _ROOTFS_PKG not in __path__:
  __path__.append(_ROOTFS_PKG)

"""Public, konn3kt-agnostic shim to the private cloud route client.
"""
from __future__ import annotations

UPLOAD_NONE = "none"
UPLOAD_UPLOADING = "uploading"
UPLOAD_UPLOADED = "uploaded"

def _load_cloud():
  # Load the private cloud client through the verified runtime loader (signed-manifest / tamper
  # protection), the same path the hephaestusd daemons use — never a bare sys.path import, which
  # would bypass verification. Absent/failed verification -> cloud features stay off.
  try:
    from openpilot.system.proprietary_runtime._verified_import import import_verified_module
    return import_verified_module("iqpilot_hephaestusd_private",
                                  "iqpilot_private.konn3kt.hephaestus.cloud_routes")
  except Exception:
    return None


_cloud = _load_cloud()


def cloud_available() -> bool:
  return _cloud is not None


def get_dongle_id() -> str | None:
  if _cloud is None:
    return None
  try:
    return _cloud.get_dongle_id()
  except Exception:
    return None


def list_cloud_routes(dongle_id: str) -> list:
  if _cloud is None:
    return []
  try:
    return _cloud.list_cloud_routes(dongle_id)
  except Exception:
    return []


def cloud_route_road_segments(dongle_id: str, fullname: str) -> list:
  if _cloud is None:
    return []
  try:
    return _cloud.cloud_route_road_segments(dongle_id, fullname)
  except Exception:
    return []


def cloud_route_camera_urls(dongle_id: str, fullname: str, camera: str = "road") -> list:
  if _cloud is None:
    return []
  try:
    return _cloud.cloud_route_camera_urls(dongle_id, fullname, camera)
  except Exception:
    return []


def request_mp4_conversion(dongle_id: str, segment_canonical_name: str, camera: str):
  if _cloud is None:
    return None
  try:
    return _cloud.request_mp4_conversion(dongle_id, segment_canonical_name, camera)
  except Exception:
    return None


def get_mp4_conversion(dongle_id: str, segment_canonical_name: str, camera: str):
  if _cloud is None:
    return None
  try:
    return _cloud.get_mp4_conversion(dongle_id, segment_canonical_name, camera)
  except Exception:
    return None


def merge_routes(local_routes: list, cloud_routes: list) -> list:
  if _cloud is not None:
    try:
      return _cloud.merge_routes(local_routes, cloud_routes)
    except Exception:
      pass
  return [_LocalOnly(local) for local in local_routes]


class _LocalOnly:
  def __init__(self, local):
    self.name = local.name
    self.local = local
    self.cloud = None
    self.is_local = True
    self.is_cloud = False
    self.upload_state = UPLOAD_NONE

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openpilot.system.hardware.hw import Paths

_utc_offset_cache: int | None = None


def utc_offset_hours() -> int:
  """Approximate local UTC offset from the device's last GPS longitude (comma devices run in UTC
  with no timezone configured). ~1h imprecise (ignores DST/political borders) but auto and close;
  cached for the session."""
  global _utc_offset_cache
  if _utc_offset_cache is not None:
    return _utc_offset_cache
  offset = 0
  try:
    from openpilot.selfdrive.ui.lib.nav_helpers import current_or_last_gps_position
    lat, lon, _, have_fix = current_or_last_gps_position()
    if have_fix:
      offset = int(round(lon / 15.0))  # solar offset ≈ standard-time zone
      # Crude DST: add an hour in the local warm season (northern spring–autumn, southern inverse).
      month = datetime.now(timezone.utc).month
      northern_dst = 3 <= month <= 10
      if (lat >= 0 and northern_dst) or (lat < 0 and not northern_dst):
        offset += 1
      offset = max(-12, min(14, offset))
  except Exception:
    offset = 0
  _utc_offset_cache = offset
  return offset


def format_local_time(epoch_seconds: float) -> str:
  if epoch_seconds <= 0:
    return "Recorded route"
  dt = datetime.fromtimestamp(epoch_seconds, timezone(timedelta(hours=utc_offset_hours())))
  return f"{dt.strftime('%b')} {dt.day} {dt.strftime('%I:%M %p').lstrip('0').lower()}"

# Dongleless on-device segment directory, e.g. "00000051--3141cf1d76--6".
# The stock tools/lib Route + RE parsers require a 16-hex dongle id + '|' delimiter (cloud naming)
# and reject these, which is why the Routes page was empty. We parse them directly instead.
SEGMENT_DIR_RE = re.compile(r"^(?P<route>[0-9a-f]{8}--[0-9a-z]{10})--(?P<seg>\d+)$")

# Logical camera -> on-disk VIDEO file. Order defines the player's selector order.
# Road uses qcamera.ts (H.264, ~1052x660): small enough to software-decode at hundreds of fps and
# it carries the audio track. Wide/Driver are full-res HEVC (hardware-decoded offroad). The
# streaming decoder handles both containers via ffmpeg's concat demuxer.
CAMERA_FILES: dict[str, str] = {
  "road": "qcamera.ts",
  "wide": "ecamera.hevc",
  "driver": "dcamera.hevc",
}
CAMERA_LABELS: dict[str, str] = {
  "road": "Road Cam",
  "wide": "Wide Cam",
  "driver": "Driver Cam",
}
# The road preview (qcamera.ts) is the only file with an audio track, and the smaller
# cloud-streamable road video. It is not a FrameReader source (TS container).
AUDIO_CAMERA_FILE = "qcamera.ts"
NOMINAL_SEGMENT_SECONDS = 60.0


@dataclass(frozen=True)
class LocalRouteInfo:
  name: str
  label: str
  subtitle: str
  segment_count: int
  cameras: tuple[str, ...]
  modified_at: float
  duration_s: float
  distance_miles: float | None = None


def _scan_segments(root: Path) -> dict[str, dict[int, Path]]:
  """Group dongleless segment dirs under `root` by route id -> {segment_num: dir}."""
  routes: dict[str, dict[int, Path]] = {}
  if not root.exists():
    return routes
  for child in root.iterdir():
    try:
      if not child.is_dir():
        continue
    except OSError:
      continue
    m = SEGMENT_DIR_RE.match(child.name)
    if m is None:
      continue
    routes.setdefault(m.group("route"), {})[int(m.group("seg"))] = child
  return routes


def _cameras_present(seg_dir: Path) -> tuple[str, ...]:
  present = []
  for cam, filename in CAMERA_FILES.items():
    try:
      if (seg_dir / filename).exists():
        present.append(cam)
    except OSError:
      continue
  return tuple(present)


def _format_route_time(ts: float) -> str:
  return format_local_time(ts)


def _format_duration(seconds: float) -> str:
  s = max(0, int(round(seconds)))
  h, rem = divmod(s, 3600)
  m, sec = divmod(rem, 60)
  if h:
    return f"{h}h {m:02d}m"
  return f"{m}:{sec:02d}"


def local_route_camera_paths(route_name: str, camera: str = "road", log_root: str | Path | None = None) -> list[str]:
  """Ordered per-segment file paths for one camera of a local route (for FrameReader)."""
  root = Path(log_root or Paths.log_root())
  segments = _scan_segments(root).get(route_name, {})
  filename = CAMERA_FILES.get(camera, CAMERA_FILES["road"])
  paths: list[str] = []
  for seg_num in sorted(segments):
    path = segments[seg_num] / filename
    try:
      if path.exists():
        paths.append(path.as_posix())
    except OSError:
      continue
  return paths


def local_route_audio_paths(route_name: str, log_root: str | Path | None = None) -> list[str]:
  """Ordered per-segment qcamera.ts paths (the only files with an audio track)."""
  root = Path(log_root or Paths.log_root())
  segments = _scan_segments(root).get(route_name, {})
  paths: list[str] = []
  for seg_num in sorted(segments):
    path = segments[seg_num] / AUDIO_CAMERA_FILE
    try:
      if path.exists():
        paths.append(path.as_posix())
    except OSError:
      continue
  return paths


def local_route_qlog_paths(route_name: str, log_root: str | Path | None = None) -> list[str]:
  """Ordered per-segment qlog paths for a local route."""
  root = Path(log_root or Paths.log_root())
  segments = _scan_segments(root).get(route_name, {})
  paths: list[str] = []
  for seg_num in sorted(segments):
    for name in ("qlog.zst", "qlog"):
      path = segments[seg_num] / name
      try:
        if path.exists():
          paths.append(path.as_posix())
          break
      except OSError:
        continue
  return paths


def compute_route_distance_miles(route_name: str, log_root: str | Path | None = None) -> float:
  """Total driven distance (miles) by integrating carState.vEgo over the route's qlogs.

  Uses vEgo (not GPS) so it still works on cars with broken GPS. Decimated qlog cadence is
  plenty for a distance total. This reads every segment's qlog, so callers should run it off the
  UI thread."""
  from openpilot.tools.lib.logreader import LogReader

  total_m = 0.0
  for qlog_path in local_route_qlog_paths(route_name, log_root):
    last_t: float | None = None
    try:
      for msg in LogReader(qlog_path):
        if msg.which() != "carState":
          continue
        t = msg.logMonoTime * 1e-9
        v = float(msg.carState.vEgo)
        # Guard against segment boundaries / gaps: only integrate contiguous samples.
        if last_t is not None and 0.0 < t - last_t < 1.0:
          total_m += v * (t - last_t)
        last_t = t
    except Exception:
      continue
  return total_m * 0.000621371


def get_local_route(route_name: str, log_root: str | Path | None = None) -> LocalRouteInfo | None:
  root = Path(log_root or Paths.log_root())
  segments = _scan_segments(root).get(route_name)
  if not segments:
    return None
  return _build_info(route_name, segments)


def _build_info(route_name: str, segments: dict[int, Path]) -> LocalRouteInfo:
  seg_nums = sorted(segments)
  mtimes = []
  for seg_num in seg_nums:
    try:
      mtimes.append(segments[seg_num].stat().st_mtime)
    except OSError:
      pass
  modified_at = max(mtimes) if mtimes else 0.0
  started_at = min(mtimes) if mtimes else 0.0

  # Cameras available anywhere in the route (union across segments).
  cameras: list[str] = []
  for cam in CAMERA_FILES:
    if any((segments[s] / CAMERA_FILES[cam]).exists() for s in seg_nums):
      cameras.append(cam)

  segment_count = len(seg_nums)
  duration_s = segment_count * NOMINAL_SEGMENT_SECONDS
  cam_names = ", ".join(CAMERA_LABELS[c] for c in cameras) if cameras else "no cameras"
  subtitle = f"{_format_duration(duration_s)}  ·  {cam_names}"

  return LocalRouteInfo(
    name=route_name,
    label=_format_route_time(started_at),
    subtitle=subtitle,
    segment_count=segment_count,
    cameras=tuple(cameras),
    modified_at=modified_at,
    duration_s=duration_s,
  )


def list_local_routes(log_root: str | Path | None = None, limit: int = 100) -> list[LocalRouteInfo]:
  root = Path(log_root or Paths.log_root())
  routes = _scan_segments(root)
  infos = [_build_info(name, segs) for name, segs in routes.items()]
  infos.sort(key=lambda info: info.modified_at, reverse=True)
  return infos[:limit]

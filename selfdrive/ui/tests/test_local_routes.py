from pathlib import Path

from openpilot.selfdrive.ui.lib.local_routes import list_local_routes


def _touch(path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(b"")


def test_list_local_routes_from_segment_directories(tmp_path):
  route_name = "aaaaaaaaaaaaaaaa|2026-07-03--12-30-00"
  _touch(tmp_path / f"{route_name}--0" / "fcamera.hevc")
  _touch(tmp_path / f"{route_name}--1" / "rlog.zst")

  routes = list_local_routes(tmp_path)

  assert len(routes) == 1
  assert routes[0].name == route_name
  assert routes[0].segment_count == 2
  assert routes[0].camera_count == 1
  assert "Jul 3" in routes[0].label


def test_list_local_routes_from_nested_route_directory(tmp_path):
  route_name = "bbbbbbbbbbbbbbbb|2026-07-03--13-45-00"
  _touch(tmp_path / route_name / "0" / "fcamera.hevc")

  routes = list_local_routes(tmp_path)

  assert len(routes) == 1
  assert routes[0].name == route_name
  assert routes[0].subtitle == "1 segment - road camera"


def test_list_local_routes_ignores_invalid_entries(tmp_path):
  _touch(tmp_path / "not-a-route" / "fcamera.hevc")

  assert list_local_routes(tmp_path) == []

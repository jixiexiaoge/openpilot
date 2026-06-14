from types import SimpleNamespace

from openpilot.selfdrive.ui.iqpilot.onroad.nav_map_utils import (
  build_mapbox_static_url,
  build_mapbox_tile_url,
  choose_nav_camera,
  mercator_world_px,
  mercator_world_px_at_zoom,
  project_nav_point,
  project_nav_polyline,
  tile_world_size,
)


def test_mercator_world_px_changes_with_longitude():
  x1, y1 = mercator_world_px(41.8826, -87.6393, 16.0)
  x2, y2 = mercator_world_px(41.8826, -87.6293, 16.0)

  assert x2 > x1
  assert abs(y2 - y1) < 1.0


def test_project_nav_point_centers_current_position():
  x, y = project_nav_point(41.8826, -87.6393, 41.8826, -87.6393, 16.0, 90.0, 420.0, 420.0)

  assert round(x, 3) == 210.0
  assert round(y, 3) == 210.0


def test_project_nav_polyline_preserves_point_count():
  points = [
    SimpleNamespace(latitude=41.8826, longitude=-87.6422),
    SimpleNamespace(latitude=41.8826, longitude=-87.6393),
    SimpleNamespace(latitude=41.8830, longitude=-87.6366),
  ]

  projected = project_nav_polyline(points, 41.8826, -87.6393, 16.0, 90.0, 420.0, 420.0)

  assert len(projected) == len(points)


def test_choose_nav_camera_looks_ahead_of_vehicle():
  points = [
    SimpleNamespace(latitude=41.8826, longitude=-87.6393),
    SimpleNamespace(latitude=41.8835, longitude=-87.6355),
  ]

  center_lat, center_lon, zoom = choose_nav_camera(41.8826, -87.6393, 90.0, points, 420.0, 420.0, 16.2)

  assert center_lon > -87.6393
  assert 15.0 <= zoom <= 16.8


def test_build_mapbox_static_url_contains_expected_components():
  url = build_mapbox_static_url(41.8826, -87.6393, 16.2, 90.0, 420, 420)

  assert "navigation-day-v1/static/" in url
  assert "-87.639300,41.882600,16.20,90.0,0/420x420@2x" in url


def test_build_mapbox_tile_url_contains_expected_components():
  url = build_mapbox_tile_url(16, 10619, 24322)

  assert "navigation-day-v1/tiles/256/16/10619/24322@2x" in url


def test_world_size_and_world_px_align_at_integer_zoom():
  world_size = tile_world_size(16)
  x, y = mercator_world_px_at_zoom(41.8826, -87.6393, 16)

  assert 0.0 <= x <= world_size
  assert 0.0 <= y <= world_size

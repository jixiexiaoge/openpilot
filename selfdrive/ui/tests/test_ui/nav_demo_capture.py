#!/usr/bin/env python3
import argparse
import os
import pathlib
import subprocess
import shutil
import sys
import time
import importlib

from openpilot.common.params import Params
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.test.helpers import with_processes

TEST_DIR = pathlib.Path(__file__).parent
OUTPUT_DIR = TEST_DIR / "nav_demo_report"
UI_DELAY = float(os.getenv("IQPILOT_NAV_DEMO_UI_DELAY", "0.75"))
VERSION = "0.10.1 / nav-ui-demo / 7864838 / Mar 09"
SCENE_SETTLE_S = float(os.getenv("IQPILOT_NAV_DEMO_SCENE_SETTLE_S", "0.04"))
SEED_REPEATS = int(os.getenv("IQPILOT_NAV_DEMO_SEED_REPEATS", "2"))
SEED_DELAY_S = float(os.getenv("IQPILOT_NAV_DEMO_SEED_DELAY_S", "0.02"))
SEED_REFRESH_EVERY = int(os.getenv("IQPILOT_NAV_DEMO_SEED_REFRESH_EVERY", "24"))
NAV_REPEATS = int(os.getenv("IQPILOT_NAV_DEMO_NAV_REPEATS", "2"))
NAV_DELAY_S = float(os.getenv("IQPILOT_NAV_DEMO_NAV_DELAY_S", "0.02"))
SEED_PUBLISH_DURATION_S = SEED_REPEATS * SEED_DELAY_S
NAV_SCENE_DURATION_S = NAV_REPEATS * NAV_DELAY_S

NAV_SCENES = ()
NAV_TIMELINE = ()
build_ui_pubmaster = None
publish_nav_scene = None
publish_onroad_seed = None
seed_ui_test_params = None


class NavDemoCapture:
  def __init__(self, output_dir: pathlib.Path):
    os.environ["SCALE"] = os.getenv("SCALE", "1")
    os.environ["BIG"] = "1"
    os.environ["RECORD"] = "1"
    os.environ["RECORD_OUTPUT"] = str(output_dir / "nav_demo")
    sys.modules["mouseinfo"] = False
    self.output_dir = output_dir
    self.pm = build_ui_pubmaster()
    self.frames = []
    self._image_lib = None
    self.video_path = self.output_dir / "nav_demo.mp4"

  def _load_image_lib(self):
    if self._image_lib is not None:
      return self._image_lib
    try:
      self._image_lib = importlib.import_module("PIL.Image")
    except ModuleNotFoundError:
      self._image_lib = None
    return self._image_lib

  def setup(self):
    publish_onroad_seed(self.pm)
    time.sleep(UI_DELAY)

  @with_processes(["ui"])
  def run(self):
    self.setup()
    for idx, scene in enumerate(NAV_TIMELINE):
      if idx % SEED_REFRESH_EVERY == 0:
        publish_onroad_seed(self.pm, repeats=SEED_REPEATS, delay=SEED_DELAY_S)
      publish_nav_scene(self.pm, scene, repeats=NAV_REPEATS, delay=NAV_DELAY_S)
      time.sleep(SCENE_SETTLE_S)

  def extract_video_stills(self) -> list[pathlib.Path]:
    if not self.video_path.exists():
      return []

    extracted = []
    current_ts = UI_DELAY
    for idx, scene in enumerate(NAV_TIMELINE):
      if idx % SEED_REFRESH_EVERY == 0:
        current_ts += SEED_PUBLISH_DURATION_S
      capture_ts = current_ts + (NAV_SCENE_DURATION_S * 0.6)
      capture_name = scene.get("capture_name")
      if capture_name:
        output_path = self.output_dir / f"{capture_name}.png"
        subprocess.run(
          [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-ss", f"{capture_ts:.2f}",
            "-i", str(self.video_path),
            "-frames:v", "1",
            str(output_path),
          ],
          check=True,
        )
        extracted.append(output_path)
      current_ts += NAV_SCENE_DURATION_S + SCENE_SETTLE_S
    return extracted

  def write_gif(self) -> pathlib.Path | None:
    if not self.frames:
      for scene in NAV_SCENES:
        image_path = self.output_dir / f"{scene['name']}.png"
        if image_path.exists():
          self.frames.append(self._load_image_lib().open(image_path).copy())

    if not self.frames:
      return None
    if self._load_image_lib() is None:
      return None
    gif_path = self.output_dir / "nav_demo.gif"
    self.frames[0].save(
      gif_path,
      save_all=True,
      append_images=self.frames[1:],
      duration=900,
      loop=0,
    )
    return gif_path


def main():
  parser = argparse.ArgumentParser(description="Run BIG raylib UI with a hard-coded nav route and capture screenshots/GIF.")
  parser.add_argument("--output-dir", type=pathlib.Path, default=OUTPUT_DIR, help="Directory for screenshots and gif.")
  parser.add_argument("--no-gif", action="store_true", help="Skip animated GIF creation.")
  parser.add_argument("--mapbox-token", default="", help="Mapbox token for the demo prefix. Falls back to MAPBOX_TOKEN if omitted.")
  parser.add_argument("--no-mapbox", action="store_true", help="Disable Mapbox for the demo and use only cached/offline tiles.")
  parser.add_argument("--force-local-offline", action="store_true", help="Bypass both live and cached Mapbox so only the local offline provider can render.")
  parser.add_argument("--offline-mbtiles", type=pathlib.Path, default=None, help="Path to a local raster MBTiles file for offline rendering.")
  parser.add_argument("--offline-tile-root", type=pathlib.Path, default=None, help="Path to a local XYZ raster tile directory for offline rendering.")
  parser.add_argument("--fixture", type=pathlib.Path, default=None, help="Route fixture JSON to drive the nav demo.")
  args = parser.parse_args()

  if args.output_dir.exists():
    shutil.rmtree(args.output_dir)
  args.output_dir.mkdir(parents=True)

  mapbox_token = args.mapbox_token
  if not mapbox_token and not args.no_mapbox:
    existing = Params().get("MapboxToken")
    if isinstance(existing, bytes):
      existing = existing.decode("utf-8")
    mapbox_token = existing or ""

  with OpenpilotPrefix():
    if args.fixture is not None:
      os.environ["IQPILOT_NAV_DEMO_FIXTURE"] = str(args.fixture)
    if args.force_local_offline:
      os.environ["IQPILOT_DISABLE_MAPBOX_PROVIDER"] = "1"
      os.environ["IQPILOT_DISABLE_MAPBOX_CACHE"] = "1"
    elif args.no_mapbox:
      os.environ.pop("IQPILOT_DISABLE_MAPBOX_PROVIDER", None)
      os.environ.pop("IQPILOT_DISABLE_MAPBOX_CACHE", None)
    if args.offline_mbtiles is not None:
      os.environ["IQPILOT_OFFLINE_MBTILES"] = str(args.offline_mbtiles)
    if args.offline_tile_root is not None:
      os.environ["IQPILOT_OFFLINE_TILE_ROOT"] = str(args.offline_tile_root)
    global NAV_SCENES, NAV_TIMELINE, build_ui_pubmaster, publish_nav_scene, publish_onroad_seed, seed_ui_test_params
    nav_demo_common = importlib.import_module("openpilot.selfdrive.ui.tests.test_ui.nav_demo_common")
    NAV_SCENES = nav_demo_common.NAV_SCENES
    NAV_TIMELINE = nav_demo_common.NAV_TIMELINE
    build_ui_pubmaster = nav_demo_common.build_ui_pubmaster
    publish_nav_scene = nav_demo_common.publish_nav_scene
    publish_onroad_seed = nav_demo_common.publish_onroad_seed
    seed_ui_test_params = nav_demo_common.seed_ui_test_params
    seed_ui_test_params(Params(), VERSION, mapbox_token=mapbox_token)
    demo = NavDemoCapture(args.output_dir)
    demo.run()
    demo.extract_video_stills()
    gif_path = None if args.no_gif else demo.write_gif()

  print(f"Screenshots written to: {args.output_dir}")
  if demo.video_path.exists():
    print(f"Recorded preview written to: {demo.video_path}")
  if gif_path is not None:
    print(f"Animated preview written to: {gif_path}")


if __name__ == "__main__":
  main()

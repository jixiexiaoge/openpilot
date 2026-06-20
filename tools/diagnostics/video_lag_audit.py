#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
  from PIL import Image, ImageChops, ImageStat
except ModuleNotFoundError:
  Image = None
  ImageChops = None
  ImageStat = None


DEFAULT_PLANNER_ROI = (0.22, 0.54, 0.78, 0.97)


def run(cmd: list[str]) -> str:
  result = subprocess.run(cmd, check=True, capture_output=True, text=True)
  return result.stdout


def ffprobe_video(path: Path) -> dict:
  payload = run([
    "ffprobe",
    "-v", "error",
    "-print_format", "json",
    "-show_streams",
    "-show_format",
    str(path),
  ])
  return json.loads(payload)


def parse_fraction(value: str) -> float:
  if "/" in value:
    num, den = value.split("/", 1)
    return float(num) / float(den)
  return float(value)


def extract_frames(video_path: Path, output_dir: Path) -> list[Path]:
  output_dir.mkdir(parents=True, exist_ok=True)
  run([
    "ffmpeg",
    "-loglevel", "error",
    "-i", str(video_path),
    "-vsync", "0",
    str(output_dir / "frame_%06d.png"),
    "-y",
  ])
  return sorted(output_dir.glob("frame_*.png"))


def file_hash(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def crop_box(width: int, height: int, roi: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
  left = int(width * roi[0])
  top = int(height * roi[1])
  right = int(width * roi[2])
  bottom = int(height * roi[3])
  return left, top, right, bottom


def rms_diff(prev_img, cur_img) -> float:
  diff = ImageChops.difference(prev_img, cur_img)
  return float(ImageStat.Stat(diff).rms[0])


def summarize(values: list[float]) -> dict[str, float]:
  if not values:
    return {"count": 0, "avg": 0.0, "max": 0.0, "min": 0.0}
  return {
    "count": len(values),
    "avg": sum(values) / len(values),
    "max": max(values),
    "min": min(values),
  }


def write_contact_sheet(flagged: list[Path], output_path: Path, *, columns: int = 3) -> None:
  if Image is None or not flagged:
    return

  images = []
  for path in flagged:
    with Image.open(path) as img:
      images.append(img.convert("RGB").copy())

  thumb_w = min(img.width for img in images)
  thumb_h = min(img.height for img in images)
  rows = math.ceil(len(images) / columns)
  sheet = Image.new("RGB", (thumb_w * columns, thumb_h * rows), color=(0, 0, 0))

  for idx, img in enumerate(images):
    thumb = img.resize((thumb_w, thumb_h))
    x = (idx % columns) * thumb_w
    y = (idx // columns) * thumb_h
    sheet.paste(thumb, (x, y))

  sheet.save(output_path)


def audit_video(video_path: Path, output_dir: Path, roi: tuple[float, float, float, float]) -> dict:
  output_dir.mkdir(parents=True, exist_ok=True)
  temp_root = Path(tempfile.mkdtemp(prefix="iqpilot_video_audit_"))
  try:
    frames = extract_frames(video_path, temp_root / "frames")
    probe = ffprobe_video(video_path)
    streams = probe.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    fps = parse_fraction(video_stream.get("avg_frame_rate", "0")) if video_stream.get("avg_frame_rate") else 0.0
    duration = float(probe.get("format", {}).get("duration", 0.0) or 0.0)

    records: list[dict] = []
    duplicate_runs: list[int] = []
    current_duplicate_run = 0
    exact_duplicate_indices: list[int] = []
    low_motion_indices: list[int] = []
    suspicious_paths: list[Path] = []
    full_rms_values: list[float] = []
    planner_rms_values: list[float] = []

    prev_hash = None
    prev_img = None
    prev_planner = None

    for idx, frame_path in enumerate(frames):
      frame_hash = file_hash(frame_path)
      exact_duplicate = prev_hash == frame_hash

      full_rms = 0.0
      planner_rms = 0.0
      if Image is not None:
        with Image.open(frame_path) as img:
          current = img.convert("L")
          planner = current.crop(crop_box(current.width, current.height, roi))
          if prev_img is not None:
            full_rms = rms_diff(prev_img, current)
            planner_rms = rms_diff(prev_planner, planner)
            full_rms_values.append(full_rms)
            planner_rms_values.append(planner_rms)
          prev_img = current.copy()
          prev_planner = planner.copy()

      if exact_duplicate:
        current_duplicate_run += 1
        exact_duplicate_indices.append(idx)
      elif current_duplicate_run:
        duplicate_runs.append(current_duplicate_run)
        current_duplicate_run = 0

      if idx > 0 and (exact_duplicate or planner_rms < 1.2 or full_rms < 1.0):
        low_motion_indices.append(idx)
        suspicious_paths.append(frame_path)

      records.append({
        "frame": idx,
        "exact_duplicate": exact_duplicate,
        "full_rms": round(full_rms, 4),
        "planner_rms": round(planner_rms, 4),
      })
      prev_hash = frame_hash

    if current_duplicate_run:
      duplicate_runs.append(current_duplicate_run)

    csv_path = output_dir / f"{video_path.stem}_frame_metrics.csv"
    with csv_path.open("w", newline="") as f:
      writer = csv.DictWriter(f, fieldnames=["frame", "exact_duplicate", "full_rms", "planner_rms"])
      writer.writeheader()
      writer.writerows(records)

    flagged_dir = output_dir / f"{video_path.stem}_flagged_frames"
    flagged_dir.mkdir(parents=True, exist_ok=True)
    for path in suspicious_paths[:24]:
      shutil.copy2(path, flagged_dir / path.name)

    write_contact_sheet(sorted(flagged_dir.glob("*.png"))[:12], output_dir / f"{video_path.stem}_contact_sheet.png")

    summary = {
      "video": str(video_path),
      "frame_count": len(frames),
      "fps": fps,
      "duration_s": duration,
      "exact_duplicate_frames": len(exact_duplicate_indices),
      "max_duplicate_run": max(duplicate_runs) if duplicate_runs else 0,
      "duplicate_runs": duplicate_runs,
      "low_motion_frames": len(low_motion_indices),
      "full_rms": summarize(full_rms_values),
      "planner_rms": summarize(planner_rms_values),
      "planner_roi": {
        "left": roi[0],
        "top": roi[1],
        "right": roi[2],
        "bottom": roi[3],
      },
      "artifacts": {
        "metrics_csv": str(csv_path),
        "flagged_frames_dir": str(flagged_dir),
        "contact_sheet": str(output_dir / f"{video_path.stem}_contact_sheet.png"),
      },
    }

    summary_path = output_dir / f"{video_path.stem}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary
  finally:
    shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
  parser = argparse.ArgumentParser(description="Audit an MP4 for duplicate/low-motion frame runs.")
  parser.add_argument("video", type=Path, help="Input MP4")
  parser.add_argument("--output-dir", type=Path, default=Path("video_audit"), help="Artifact output directory")
  parser.add_argument(
    "--planner-roi",
    default="0.22,0.54,0.78,0.97",
    help="ROI fractions left,top,right,bottom for planner-focused RMS stats",
  )
  args = parser.parse_args()

  roi = tuple(float(part.strip()) for part in args.planner_roi.split(","))
  if len(roi) != 4:
    raise ValueError("planner-roi must have four comma-separated floats")

  summary = audit_video(args.video, args.output_dir, roi)
  print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
  main()

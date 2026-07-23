"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from __future__ import annotations

import math
import os
import queue
import shutil
import subprocess
import threading
import time

import pyray as rl

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware.hw import Paths

PARAM_KEY = "ScreenRecording"
PARAM_POLL_INTERVAL = 0.5  # seconds between param checks
CAPTURE_FPS = int(os.getenv("SCREEN_RECORD_FPS", "15"))
MAX_DURATION_S = int(os.getenv("SCREEN_RECORD_MAX_S", str(10 * 60)))  # auto-stop safety
MIN_FREE_DISK_BYTES = 2 * 1024**3  # refuse to record with < 2GB free
QUEUE_MAX_FRAMES = 30  # ~2s of frames before we start dropping
MIN_VALID_OUTPUT_BYTES = 8 * 1024
CRF = os.getenv("SCREEN_RECORD_CRF", "28")
MAX_BITRATE = os.getenv("SCREEN_RECORD_MAXRATE", "2M")
# capture at half res above this width (BIG UI 2160 -> 1080), native below (mici 536)
DOWNSCALE_THRESHOLD = 1200
# Skip capture while the UI frame time is above this multiple of target: the readback
# (blocking glReadPixels) and extra present-blit stall the render thread, so back off and
# let the UI recover rather than dragging its framerate down. The recorder self-throttles.
BACKOFF_FRAME_TIME_RATIO = float(os.getenv("SCREEN_RECORD_BACKOFF", "1.35"))


class ScreenRecorder:
  def __init__(self, width: int, height: int, target_fps: int):
    self._width = width
    self._height = height
    scale = 2 if width > DOWNSCALE_THRESHOLD else 1
    # yuv420 needs even dimensions
    self._rec_width = (width // scale) & ~1
    self._rec_height = (height // scale) & ~1
    self._target_fps = max(1, target_fps)
    self._capture_fps = max(1, min(CAPTURE_FPS, target_fps))
    self._frame_interval = max(1, round(target_fps / self._capture_fps))
    self._target_frame_time = 1.0 / self._target_fps

    self._params = Params()
    self._active = False
    self._owns_rt = False
    self._rt: rl.RenderTexture | None = None
    self._small_rt: rl.RenderTexture | None = None

    self._proc: subprocess.Popen | None = None
    self._queue: queue.Queue[bytes | None] | None = None
    self._writer: threading.Thread | None = None
    self._finalizers: list[threading.Thread] = []

    self._frame_idx = 0
    self._dropped = 0
    self._backoff_skips = 0
    self._start_time = 0.0
    self._last_poll = 0.0
    self._out_path = ""
    # after a self-initiated stop, don't restart until the param is observed False
    self._await_param_clear = False
    # adaptive backoff: EMA of the render-loop frame time
    self._last_frame_t = 0.0
    self._frame_time_ema = 0.0
    self._capture_this_frame = False

  @property
  def active(self) -> bool:
    return self._active

  @property
  def render_texture(self) -> rl.RenderTexture | None:
    return self._rt

  def begin_frame(self) -> bool:
    self._capture_this_frame = False
    if not self._active:
      return False

    now = time.monotonic()
    if self._last_frame_t:
      dt = now - self._last_frame_t
      self._frame_time_ema = dt if self._frame_time_ema == 0.0 else 0.85 * self._frame_time_ema + 0.15 * dt
    self._last_frame_t = now

    self._frame_idx += 1
    if self._frame_idx % self._frame_interval != 0:
      return False
    if self._frame_time_ema > self._target_frame_time * BACKOFF_FRAME_TIME_RATIO:
      self._backoff_skips += 1
      if self._backoff_skips % 200 == 1:
        cloudlog.warning(f"screen_recorder: UI busy, backing off capture ({self._backoff_skips} skips)")
      return False

    self._capture_this_frame = True
    return True

  def update(self, app_render_texture: rl.RenderTexture | None) -> None:
    """Called every frame from the render thread. Handles start/stop and safety limits."""
    now = time.monotonic()
    if self._active:
      # encoder died (e.g. broken pipe) or hit the duration cap
      if self._proc is not None and self._proc.poll() is not None:
        cloudlog.error(f"screen_recorder: encoder exited unexpectedly rc={self._proc.returncode}")
        self._stop(clear_param=True)
      elif now - self._start_time > MAX_DURATION_S:
        cloudlog.warning("screen_recorder: max duration reached, auto-stopping")
        self._stop(clear_param=True)

    if now - self._last_poll < PARAM_POLL_INTERVAL:
      return
    self._last_poll = now

    want = self._params.get_bool(PARAM_KEY)
    if self._await_param_clear:
      if want:
        return
      self._await_param_clear = False
    if want and not self._active:
      self._start(app_render_texture)
    elif not want and self._active:
      self._stop(clear_param=False)

  def _start(self, app_render_texture: rl.RenderTexture | None) -> None:
    root = Paths.screen_recordings_root()
    try:
      os.makedirs(root, exist_ok=True)
      if shutil.disk_usage(root).free < MIN_FREE_DISK_BYTES:
        cloudlog.warning("screen_recorder: not enough free disk space, refusing to record")
        self._params.put_bool_nonblocking(PARAM_KEY, False)
        return
    except OSError as e:
      cloudlog.exception(f"screen_recorder: cannot prepare output dir: {e}")
      self._params.put_bool_nonblocking(PARAM_KEY, False)
      return

    if app_render_texture is not None:
      self._rt = app_render_texture
      self._owns_rt = False
    else:
      self._rt = rl.load_render_texture(self._width, self._height)
      rl.set_texture_filter(self._rt.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      self._owns_rt = True
    self._small_rt = rl.load_render_texture(self._rec_width, self._rec_height)

    self._out_path = os.path.join(root, time.strftime("screen_recording_%Y-%m-%d_%H-%M-%S.mp4"))
    args = [
      'ffmpeg', '-v', 'error', '-nostats',
      '-f', 'rawvideo', '-pix_fmt', 'rgba',
      '-s', f'{self._rec_width}x{self._rec_height}',
      '-r', str(self._capture_fps), '-i', 'pipe:0',
      '-vf', 'vflip,format=yuv420p',
      '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
      '-crf', CRF, '-maxrate', MAX_BITRATE, '-bufsize', '4M',
      '-g', str(self._capture_fps * 2),
      '-threads', '2',
      # fragmented mp4: file stays playable even if we die before a clean stop
      '-movflags', '+frag_keyframe+empty_moov+default_base_moof',
      '-y', '-f', 'mp4', self._out_path,
    ]
    try:
      self._proc = subprocess.Popen(args, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    preexec_fn=lambda: os.nice(15))
    except OSError as e:
      cloudlog.exception(f"screen_recorder: failed to start ffmpeg: {e}")
      self._release_textures()
      self._params.put_bool_nonblocking(PARAM_KEY, False)
      return

    self._queue = queue.Queue(maxsize=QUEUE_MAX_FRAMES)
    self._writer = threading.Thread(target=self._writer_thread, args=(self._proc, self._queue), daemon=True)
    self._writer.start()

    self._frame_idx = 0
    self._dropped = 0
    self._backoff_skips = 0
    self._last_frame_t = 0.0
    self._frame_time_ema = 0.0
    self._start_time = time.monotonic()
    self._active = True
    cloudlog.event("screen_recorder: started", path=self._out_path,
                   size=f"{self._rec_width}x{self._rec_height}", fps=self._capture_fps)

  def _stop(self, clear_param: bool) -> None:
    self._active = False
    proc, q, writer = self._proc, self._queue, self._writer
    self._proc, self._queue, self._writer = None, None, None
    self._release_textures()

    if clear_param:
      self._params.put_bool_nonblocking(PARAM_KEY, False)
      self._await_param_clear = True

    # finalize off the render thread; ffmpeg needs a clean stdin close to flush
    out_path = self._out_path
    def _finalize():
      try:
        if q is not None:
          q.put(None)
        if writer is not None:
          writer.join(timeout=10)
        if proc is not None:
          if proc.stdin is not None:
            try:
              proc.stdin.close()
            except OSError:
              pass
          try:
            proc.wait(timeout=15)
          except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
        try:
          if out_path and os.path.getsize(out_path) < MIN_VALID_OUTPUT_BYTES:
            os.remove(out_path)
            cloudlog.warning(f"screen_recorder: discarded truncated output {out_path}")
        except OSError:
          pass
      except Exception:
        cloudlog.exception("screen_recorder: finalize failed")

    t = threading.Thread(target=_finalize, daemon=True)
    t.start()
    self._finalizers = [f for f in self._finalizers if f.is_alive()] + [t]
    cloudlog.event("screen_recorder: stopped", path=self._out_path, dropped=self._dropped)

  def _release_textures(self) -> None:
    # render thread only
    if self._small_rt is not None:
      rl.unload_render_texture(self._small_rt)
      self._small_rt = None
    if self._rt is not None and self._owns_rt:
      rl.unload_render_texture(self._rt)
    self._rt = None
    self._owns_rt = False

  def capture(self, frame_rt: rl.RenderTexture) -> None:
    if not self._capture_this_frame or self._small_rt is None or self._queue is None:
      return
    if self._queue.full():
      self._dropped += 1
      if self._dropped % 100 == 1:
        cloudlog.warning(f"screen_recorder: encoder falling behind, dropped {self._dropped} frames")
      return

    src = rl.Rectangle(0, 0, float(frame_rt.texture.width), -float(frame_rt.texture.height))
    dst = rl.Rectangle(0, 0, float(self._rec_width), float(self._rec_height))
    rl.begin_texture_mode(self._small_rt)
    rl.draw_texture_pro(frame_rt.texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
    rl.end_texture_mode()

    image = rl.load_image_from_texture(self._small_rt.texture)
    try:
      data = bytes(rl.ffi.buffer(image.data, self._rec_width * self._rec_height * 4))
    finally:
      rl.unload_image(image)
    try:
      self._queue.put_nowait(data)
    except queue.Full:
      self._dropped += 1

  def draw_indicator(self, width: int) -> None:
    """Pulsing red REC dot, drawn into the frame so it shows on screen and in the video."""
    big = width > DOWNSCALE_THRESHOLD
    radius = 14 if big else 7
    margin = (28 if big else 14) + radius
    alpha = int(155 + 100 * math.sin(time.monotonic() * 4.0))
    rl.draw_circle(width - margin, margin, float(radius), rl.Color(255, 60, 60, alpha))

  @staticmethod
  def _writer_thread(proc: subprocess.Popen, q: queue.Queue[bytes | None]) -> None:
    while True:
      data = q.get()
      if data is None:
        break
      try:
        proc.stdin.write(data)
      except (BrokenPipeError, OSError):
        break

  def close(self) -> None:
    if self._active:
      self._stop(clear_param=False)
    for t in self._finalizers:
      t.join(timeout=15)

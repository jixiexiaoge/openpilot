from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import numpy as np
import pyray as rl
from collections.abc import Callable
from dataclasses import dataclass

from openpilot.selfdrive.ui.lib.local_routes import local_route_audio_paths
from openpilot.selfdrive.ui.lib import cloud_routes_shim as cloud
from openpilot.selfdrive.ui.ui_state import device

from openpilot.selfdrive.ui.widgets.screen_header import ScreenHeader, HEADER_HEIGHT
from openpilot.selfdrive.ui.lib.local_routes import (
  CAMERA_LABELS,
  compute_route_distance_miles,
  get_local_route,
  local_route_camera_paths,
)
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

MARGIN = 40
SPACING = 25
PLAY_R = 70
SKIP_R = 56
SKIP_OFFSET = PLAY_R + 64 + SKIP_R
SHARE_R = 40
CAM_TAB_H = 66
CAM_TAB_GAP = 14
AUTOHIDE_S = 3.0        # seconds of no touch before the transport + scrubber fade out
STALE_FRAME_TOL = 120  # frames: accept a decoded frame only if within this of the playhead

SCREEN_BG = rl.Color(14, 15, 18, 255)
SCREEN_BORDER = rl.Color(255, 255, 255, 26)
TEAL = rl.Color(16, 185, 169, 255)
GLYPH_DARK = rl.Color(8, 16, 16, 255)
MUTED = rl.Color(160, 160, 165, 255)
TRACK_BG = rl.Color(50, 53, 60, 255)
BTN_BG = rl.Color(38, 40, 46, 255)
SKIP_BG = rl.Color(26, 28, 33, 210)
VIDEO_FPS = 20.0
NOMINAL_SEGMENT_FRAMES = int(VIDEO_FPS * 60)


def _find_bin(name: str) -> str | None:
  """Locate a helper binary robustly — the UI process's PATH may not include /usr/local/bin."""
  found = shutil.which(name)
  if found:
    return found
  for p in (f"/usr/local/bin/{name}", f"/usr/bin/{name}"):
    if os.path.exists(p):
      return p
  return None


def _find_hwdec() -> str | None:
  """The Venus HW HEVC decoder (built only on-device). Absent on PC/open-source -> ffmpeg SW."""
  try:
    from openpilot.common.basedir import BASEDIR
    path = os.path.join(BASEDIR, "system", "loggerd", "encoder", "v4l_decode")
    return path if os.path.exists(path) else None
  except Exception:
    return None


@dataclass
class _DecodedFrame:
  global_frame: int
  frame: np.ndarray


# Cap the read-ahead buffer. Kept modest (~64MB, ~1.5s at 20fps) rather than large: this device's
# offroad memory headroom is thin, and an oversized buffer left playback prone to stalling when a
# periodic background task spiked memory during long sessions.
PREBUFFER_BYTES = 64_000_000
SEEK_AHEAD_FRAMES = 150         # target jumps beyond this restart ffmpeg instead of waiting


class _CloudProxy:
  """Local TLS-terminating proxy for cloud playback: the device ffmpeg has no https/tls protocol,
  so signed konn3kt segment URLs are served to it as http://127.0.0.1:{port}/{index} and this proxy
  streams the upstream https body through (Range passthrough for seeks)."""

  def __init__(self, urls: list[str]):
    import http.server
    import requests

    proxy = self
    self._session = requests.Session()  # TLS/conn reuse across range requests (seek bisection)

    class Handler(http.server.BaseHTTPRequestHandler):
      protocol_version = "HTTP/1.1"

      def log_message(self, *a):
        pass

      def do_GET(self):
        try:
          idx = int(self.path.strip("/").split("?")[0])
          url = proxy._urls[idx]
        except Exception:
          self.send_error(404)
          return
        headers = {}
        rng = self.headers.get("Range")
        if rng:
          headers["Range"] = rng
        try:
          up = proxy._session.get(url, headers=headers, stream=True, timeout=20)
        except Exception:
          self.send_error(502)
          return
        try:
          self.send_response(up.status_code)
          for h in ("Content-Length", "Content-Range", "Accept-Ranges", "Content-Type"):
            if h in up.headers:
              self.send_header(h, up.headers[h])
          self.end_headers()
          for chunk in up.iter_content(chunk_size=65536):
            if chunk:
              self.wfile.write(chunk)
        except Exception:
          pass
        finally:
          up.close()

    self._urls = list(urls)
    self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    self._server.daemon_threads = True
    self.port = self._server.server_address[1]
    threading.Thread(target=self._server.serve_forever, daemon=True).start()

  def local_urls(self) -> list[str]:
    return [f"http://127.0.0.1:{self.port}/{i}" for i in range(len(self._urls))]

  def stop(self) -> None:
    try:
      self._server.shutdown()
      self._server.server_close()
    except Exception:
      pass


class _StreamFrameWorker:
  """Streams decoded frames sequentially from ffmpeg into a prebuffer for smooth playback.

  Handles any source — road qcamera.ts (small, software-decodes at hundreds of fps), wide/driver
  full-res .hevc, or cloud HTTP URLs — through ffmpeg's concat demuxer. One long-lived ffmpeg
  decodes forward from the playhead while a reader thread fills a bounded frame buffer a few seconds
  ahead; small forward moves are served from the buffer, a backward or far-forward seek restarts
  ffmpeg at the new offset. Replaces the old per-frame FrameReader/HTTP-seek workers (4s stalls)."""

  def __init__(self, sources: list[str], status: str | None = None):
    self._proxy: _CloudProxy | None = None
    if sources and sources[0].startswith(("http://", "https://")):
      self._proxy = _CloudProxy(sources)
      sources = self._proxy.local_urls()
    self._sources = list(sources)
    self._ffmpeg = _find_bin("ffmpeg")
    self._ffprobe = _find_bin("ffprobe")
    # Hardware-decode full-res .hevc (wide/driver) via the Venus decoder; road qcam .ts stays SW
    # (already 270fps). Offroad the Venus decoder + GPU are idle.
    self._hwdec = _find_hwdec() if self._sources and self._sources[0].endswith(".hevc") else None
    self.total_frames = max(1, len(self._sources) * NOMINAL_SEGMENT_FRAMES)
    self._dims: tuple[int, int] | None = None
    self._prebuffer = 60
    self._playlist = self._write_playlist()
    self._hw_playlist: str | None = None  # per-seek playlist starting at the target segment (HW path)

    self._cv = threading.Condition()
    self._status_lock = threading.Lock()
    self._buf: dict[int, np.ndarray] = {}
    self._base = 0        # global index of the next frame ffmpeg will emit
    self._run_start = 0   # global index where the current ffmpeg run began
    self._target = 0
    self._need_seek = True
    self._seek_to = 0
    self._stop = False
    self._status = status or tr("Loading video")
    self._thread = threading.Thread(target=self._run, daemon=True)
    self._thread.start()

  def _write_playlist(self, start_idx: int = 0) -> str | None:
    srcs = self._sources[start_idx:]
    if not srcs:
      return None
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="iqroute_")
    with os.fdopen(fd, "w") as f:
      for s in srcs:
        f.write("file '%s'\n" % s.replace("'", "'\\''"))
        # Tell the concat demuxer each segment's duration so a seek can jump straight to the right
        # segment instead of opening every earlier one to measure it (the large-route lag).
        f.write("duration %.3f\n" % (NOMINAL_SEGMENT_FRAMES / VIDEO_FPS))
    return path

  def stop(self) -> None:
    with self._cv:
      self._stop = True
      self._cv.notify_all()
    self._thread.join(timeout=1.5)
    if self._proxy is not None:
      self._proxy.stop()
    for pl in (self._playlist, self._hw_playlist):
      if pl:
        try:
          os.unlink(pl)
        except OSError:
          pass

  def request_frame(self, frame_idx: int) -> None:
    frame_idx = max(0, min(self.total_frames - 1, int(frame_idx)))
    with self._cv:
      self._target = frame_idx
      # Seek (restart ffmpeg) on a backward move or a big forward jump; otherwise let the
      # sequential decode catch up from the buffer.
      if frame_idx < self._run_start or frame_idx > self._base + SEEK_AHEAD_FRAMES:
        self._need_seek = True
        self._seek_to = frame_idx
      self._cv.notify_all()

  def pop_result(self) -> _DecodedFrame | None:
    # Return the newest decoded frame at or before the playhead; if none yet (just after a seek),
    # the earliest buffered frame. Lets slow (full-res) cams display their latest frame instead of
    # stalling waiting for the exact index.
    with self._cv:
      if not self._buf:
        return None
      target = self._target
      le = [k for k in self._buf if k <= target]
      key = max(le) if le else min(self._buf)
      frame = self._buf[key]
    return _DecodedFrame(key, frame)

  def status(self) -> str:
    with self._status_lock:
      return self._status

  def _set_status(self, status: str) -> None:
    with self._status_lock:
      self._status = status

  def _probe_dims(self) -> tuple[int, int] | None:
    if self._dims is not None or self._ffprobe is None or not self._sources:
      return self._dims
    try:
      out = subprocess.run(
        [self._ffprobe, "-v", "quiet", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", self._sources[0]],
        capture_output=True, text=True, timeout=20).stdout.strip()
      # A TS can report the stream twice; take the first non-empty line.
      line = next((ln for ln in out.splitlines() if "x" in ln), "")
      w, h = (int(v) for v in line.split("x")[:2])
      self._dims = (w, h)
    except Exception:
      self._dims = None
    return self._dims

  def _spawn(self, start_frame: int) -> subprocess.Popen:
    start_s = max(0.0, start_frame / VIDEO_FPS)
    if self._hwdec:
      # ffmpeg concats + seeks the raw .hevc (bitstream copy, fast), the Venus decoder turns it
      # into rgb24 at ~30fps (vs ~12fps software). Seeking a raw-hevc concat to 0 needs no -ss.
      import shlex
      # Seek on raw HEVC: INPUT -ss is erratic (no real timestamps) and OUTPUT -ss on the whole
      # route reads every packet up to the target (minutes on long routes). So start the concat at
      # the TARGET SEGMENT (never reads earlier segments) and OUTPUT -ss only the <60s offset within
      # it — fast and frame-accurate. dump_extra re-inserts the parameter sets on every keyframe so
      # a mid-stream start is decodable.
      seg_idx = min(len(self._sources) - 1, int(start_frame // NOMINAL_SEGMENT_FRAMES))
      local_s = max(0.0, (start_frame - seg_idx * NOMINAL_SEGMENT_FRAMES) / VIDEO_FPS)
      if self._hw_playlist:
        try:
          os.unlink(self._hw_playlist)
        except OSError:
          pass
      self._hw_playlist = self._write_playlist(seg_idx)
      ff = [self._ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", self._hw_playlist]
      if local_s > 0.05:
        ff += ["-ss", f"{local_s:.3f}"]
      ff += ["-c:v", "copy", "-bsf:v", "dump_extra", "-f", "hevc", "pipe:1"]
      cmd = " ".join(shlex.quote(a) for a in ff) + " | " + shlex.quote(self._hwdec) + " pipe:0"
      try:
        from openpilot.common.swaglog import cloudlog
        cloudlog.warning(f"video_player: HW decode path ({self._hwdec})")
      except Exception:
        pass
      # New session so we can kill the WHOLE pipe (ffmpeg + v4l_decode) as a group; killing just
      # the shell would orphan them and leave v4l_decode holding /dev/video32 (-> next decode hangs).
      return subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              bufsize=0, start_new_session=True)

    cmd = [self._ffmpeg, "-hide_banner", "-loglevel", "error"]
    playlist = self._playlist
    if self._proxy is not None:
      # concat playlists only open local files by default; allow the proxy's http entries.
      # Seeking over http bisects with many high-latency range requests, so start the playlist at
      # the target segment and only -ss the in-segment remainder (same trick as the HW path).
      cmd += ["-protocol_whitelist", "file,http,tcp"]
      seg_idx = min(len(self._sources) - 1, int(start_frame // NOMINAL_SEGMENT_FRAMES))
      start_s = max(0.0, (start_frame - seg_idx * NOMINAL_SEGMENT_FRAMES) / VIDEO_FPS)
      if seg_idx > 0:
        if self._hw_playlist:
          try:
            os.unlink(self._hw_playlist)
          except OSError:
            pass
        self._hw_playlist = self._write_playlist(seg_idx)
        playlist = self._hw_playlist
    # Seeking a concat of timestamp-less raw .hevc to exactly 0 yields no output; only add -ss for
    # real (non-zero) seeks.
    if start_s > 0.05:
      cmd += ["-ss", f"{start_s:.3f}"]
    cmd += ["-f", "concat", "-safe", "0", "-i", playlist,
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                            start_new_session=True)

  @staticmethod
  def _kill(proc) -> None:
    if proc is None:
      return
    try:
      os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # whole pipe group
    except Exception:
      try:
        proc.kill()
      except Exception:
        pass
    try:
      proc.wait(timeout=1.0)  # reap so it doesn't linger as a zombie
    except Exception:
      pass

  @staticmethod
  def _read_into(pipe, arr) -> bool:
    # Read one frame straight into the numpy buffer — no bytes concat/copy (a ~7MB memcpy/frame
    # otherwise, which halved decode throughput).
    mv = memoryview(arr).cast("B")  # flat byte view so slicing is by bytes, not rows
    n = arr.nbytes
    got = 0
    while got < n:
      r = pipe.readinto(mv[got:])
      if not r:
        return False
      got += r
    return True

  def _run(self) -> None:
    if self._ffmpeg is None or self._playlist is None:
      self._set_status(tr("Unable to load video"))
      return
    dims = self._probe_dims()
    # retry a couple of times: over cloud streaming a single probe can fail transiently
    # (flaky LTE/hotspot), and giving up permanently shows "Unable to load video"
    for _ in range(2):
      if dims is not None or self._stop:
        break
      time.sleep(2.0)
      dims = self._probe_dims()
    if dims is None:
      self._set_status(tr("Unable to load video"))
      return
    w, h = dims
    frame_bytes = w * h * 3
    self._prebuffer = max(8, min(30, PREBUFFER_BYTES // max(1, frame_bytes)))
    proc: subprocess.Popen | None = None
    try:
      while not self._stop:
        with self._cv:
          restart = self._need_seek or proc is None
          if restart:
            self._need_seek = False
            seek_to = self._seek_to
        if restart:
          self._kill(proc)
          proc = None
          with self._cv:
            self._buf.clear()
            self._base = seek_to
            self._run_start = seek_to
          proc = self._spawn(seek_to)

        with self._cv:
          while (not self._stop and not self._need_seek
                 and self._base - self._target > self._prebuffer):
            self._cv.wait(0.1)
          if self._stop or self._need_seek:
            continue

        frame = np.empty((h, w, 3), dtype=np.uint8)
        if not self._read_into(proc.stdout, frame):  # end of the concatenated stream
          self._set_status("")
          with self._cv:
            while not self._stop and not self._need_seek:
              self._cv.wait(0.2)
          continue

        with self._cv:
          if self._need_seek or self._stop:
            continue  # a seek landed mid-read; drop this frame and restart
          self._buf[self._base] = frame
          # Keep the buffer bounded to the most recently decoded frames (they arrive in order).
          over = len(self._buf) - (self._prebuffer + 16)
          if over > 0:
            for k in sorted(self._buf)[:over]:
              del self._buf[k]
          self._base += 1
          self._cv.notify_all()
        self._set_status("")
    finally:
      self._kill(proc)


class _RouteAudioPlayer:
  """Plays a route's audio (from the qcamera.ts segments) synced to the scrubber.

  raylib's audio device won't initialize on the comma, so we decode the qcam AAC track with
  ffmpeg and pipe raw PCM to aplay (ALSA) — the only working output path on device. Multi-segment
  audio is stitched gaplessly with the MPEG-TS `concat:` protocol. Pause/seek tear the pipe down
  and (on resume) respawn ffmpeg at the new offset; frame-exact sync isn't needed for a dashcam."""

  SAMPLE_RATE = 48000
  CHANNELS = 2

  def __init__(self, ts_paths: list[str]):
    self._ts_paths = list(ts_paths)
    self._ffmpeg = _find_bin("ffmpeg")
    self._aplay = _find_bin("aplay")
    self._ff: subprocess.Popen | None = None
    self._ap: subprocess.Popen | None = None
    self._lock = threading.Lock()

  @property
  def available(self) -> bool:
    return bool(self._ts_paths and self._ffmpeg and self._aplay)

  def _kill(self) -> None:
    for proc in (self._ap, self._ff):
      if proc is not None:
        try:
          proc.kill()
        except Exception:
          pass
    self._ff = self._ap = None

  def stop(self) -> None:
    with self._lock:
      self._kill()

  def play_from(self, start_s: float) -> None:
    if not self.available:
      return
    with self._lock:
      self._kill()
      concat = "concat:" + "|".join(self._ts_paths)
      try:
        self._ff = subprocess.Popen(
          [self._ffmpeg, "-v", "quiet", "-ss", f"{max(0.0, start_s):.3f}", "-i", concat,
           "-vn", "-f", "s16le", "-ar", str(self.SAMPLE_RATE), "-ac", str(self.CHANNELS), "-"],
          stdout=subprocess.PIPE)
        self._ap = subprocess.Popen(
          [self._aplay, "-q", "-f", "S16_LE", "-c", str(self.CHANNELS), "-r", str(self.SAMPLE_RATE)],
          stdin=self._ff.stdout)
        if self._ff.stdout is not None:
          self._ff.stdout.close()  # aplay owns the read end of the pipe now
      except Exception:
        self._kill()


class VideoPlayerLayout(Widget):
  """Offroad route video player for local road-camera recordings."""

  def __init__(self):
    super().__init__()
    self._header = self._child(ScreenHeader(tr("Video Player")))
    self._play_icon = gui_app.texture("icons/iq/play.png", 70, 70, keep_aspect_ratio=True)
    self._skip_back_icon = gui_app.texture("icons/iq/rotate-ccw.png", 78, 78, keep_aspect_ratio=True)
    self._skip_fwd_icon = gui_app.texture("icons/iq/rotate-cw.png", 78, 78, keep_aspect_ratio=True)
    self._route: str | None = None
    self._playing = False
    self._progress = 0.0
    self._duration = 1.0

    # Camera selection (Road / Wide / Driver) — only cameras actually recorded are shown.
    self._cameras: tuple[str, ...] = ()
    self._camera: str = "road"
    self._cam_tab_rects: list[tuple[rl.Rectangle, str]] = []

    # Cloud streaming (routes overwritten/deleted on device): road cam only, decoded over HTTP.
    self._is_cloud: bool = False
    self._cloud_fullname: str = ""
    self._dongle: str | None = None

    # Route metadata for the info line (date/time from the header, plus length + miles here).
    self._meta_label: str = ""
    self._distance_miles: float | None = None
    self._miles_thread: threading.Thread | None = None
    self._miles_route: str | None = None

    self._speed = 1.0
    self._speed_rect = rl.Rectangle(0, 0, 0, 0)
    self._play_rect = rl.Rectangle(0, 0, 0, 0)
    self._skip_back_rect = rl.Rectangle(0, 0, 0, 0)
    self._skip_fwd_rect = rl.Rectangle(0, 0, 0, 0)
    self._share_rect = rl.Rectangle(0, 0, 0, 0)
    self._track_x0 = 0.0
    self._track_w = 1.0
    self._track_rect = rl.Rectangle(0, 0, 0, 0)
    self._dragging = False
    self._was_down = False
    self._on_share_cb: Callable[[], None] | None = None
    self._audio: _RouteAudioPlayer | None = None
    self._worker: _StreamFrameWorker | None = None
    self._texture: rl.Texture | None = None
    self._texture_size: tuple[int, int] = (0, 0)
    self._status = ""
    self._last_playback_t = 0.0
    # Auto-hide overlay controls (center transport + scrubber) after a few seconds of no touch.
    self._last_interaction = 0.0
    self._press_revealed = False
    # Loading state for the current camera (fresh full-res HEVC takes a beat to open/index).
    self._loading = False
    # Newest decoded global frame index — used to pace playback to the decoder (so a slow full-res
    # cam plays at its real rate instead of the scrubber racing ahead of the picture).
    self._last_decoded_idx = -1
    self._last_uploaded_idx = -1

  def set_on_back(self, cb: Callable[[], None]) -> None:
    self._header.set_on_back(cb)

  def set_on_share(self, cb: Callable[[], None]) -> None:
    self._on_share_cb = cb

  def set_route(self, route: str | None) -> None:
    self._stop_worker()
    self._stop_audio()
    self._clear_texture()
    self._route = route
    self._playing = False
    self._progress = 0.0
    self._status = ""
    self._last_playback_t = rl.get_time()
    self._cameras = ()
    self._cam_tab_rects = []
    self._distance_miles = None

    if not route:
      self._header.set_title(tr("Video Player"))
      self._meta_label = ""
      return

    info = get_local_route(route)
    self._is_cloud = info is None
    if info is not None:
      self._cameras = info.cameras
      self._header.set_title(info.label)
      self._meta_label = self._fmt(info.duration_s)
      self._duration = max(1.0, info.duration_s)
      self._audio = _RouteAudioPlayer(local_route_audio_paths(route))
      self._start_miles_computation(route)
    else:
      # Not on device — stream the road cam from konn3kt. Reconstruct the cloud fullname
      # (dongle|count--uid) from the canonical route name.
      self._dongle = cloud.get_dongle_id()
      self._cloud_fullname = f"{self._dongle}|{route}" if self._dongle else route
      self._cameras = ("road",)
      self._header.set_title(route)
      self._meta_label = tr("Cloud only")
      self._audio = None  # cloud audio streaming is a follow-up

    self._camera = "road" if "road" in self._cameras else (self._cameras[0] if self._cameras else "road")
    self._load_camera(preserve_progress=False)

  def _stop_audio(self) -> None:
    if self._audio is not None:
      self._audio.stop()

  def _sync_audio(self) -> None:
    """Start/stop audio to match play state + position. Only called at state transitions
    (play/pause, seek, drag end) — never per-frame — since each start respawns ffmpeg."""
    if self._audio is None:
      return
    if self._playing and not self._dragging:
      self._audio.play_from(self._progress * self._duration)
    else:
      self._audio.stop()

  def _load_camera(self, preserve_progress: bool = True) -> None:
    self._stop_worker()
    self._last_decoded_idx = -1
    self._last_uploaded_idx = -1
    if not preserve_progress:
      self._progress = 0.0
    if not self._route:
      return

    if self._is_cloud:
      urls = cloud.cloud_route_camera_urls(self._dongle, self._cloud_fullname, self._camera) if self._dongle else []
      if not urls:
        self._status = tr("Cloud video unavailable")
        return
      self._status = ""
      self._loading = True
      self._worker = _StreamFrameWorker(urls, status=tr("Streaming from cloud"))
      self._duration = max(1.0, self._worker.total_frames / VIDEO_FPS)
      self._request_current_frame()
      return

    camera_paths = local_route_camera_paths(self._route, self._camera)
    if not camera_paths:
      self._status = tr("No video for this camera")
      return

    self._status = ""
    self._loading = True
    self._worker = _StreamFrameWorker(camera_paths)
    self._duration = max(1.0, self._worker.total_frames / VIDEO_FPS)
    self._request_current_frame()

  def _select_camera(self, camera: str) -> None:
    if camera == self._camera or camera not in self._cameras:
      return
    self._camera = camera
    self._clear_texture()
    self._loading = True
    self._load_camera(preserve_progress=True)

  def _start_miles_computation(self, route: str) -> None:
    # Integrating vEgo over the qlogs is slow (reads every segment), so compute off the UI thread.
    self._miles_route = route

    def _worker():
      try:
        miles = compute_route_distance_miles(route)
      except Exception:
        miles = None
      if self._miles_route == route:
        self._distance_miles = miles

    self._miles_thread = threading.Thread(target=_worker, daemon=True)
    self._miles_thread.start()

  def show_event(self):
    super().show_event()
    # Watching a recording is active use — suppress the offroad inactivity timeout that would
    # otherwise blank the screen / bounce back to home mid-playback.
    device.set_override_interactive_timeout(24 * 60 * 60)

  def hide_event(self):
    super().hide_event()
    self._stop_worker()
    self._stop_audio()
    device.set_override_interactive_timeout(None)

  def _stop_worker(self) -> None:
    if self._worker is not None:
      self._worker.stop()
      self._worker = None

  def _clear_texture(self) -> None:
    if self._texture is not None:
      rl.unload_texture(self._texture)
      self._texture = None
    self._texture_size = (0, 0)

  def _request_current_frame(self) -> None:
    if self._worker is None:
      return
    frame_idx = int(round(self._progress * max(0, self._worker.total_frames - 1)))
    self._worker.request_frame(frame_idx)

  def _consume_decoded_frame(self) -> None:
    if self._worker is None:
      return
    result = self._worker.pop_result()
    if result is None:
      return

    # Ignore stale frames from before a seek (the worker briefly still holds the old position's
    # buffer). Accepting them would drag _last_decoded_idx — and the pace clamp — back, which made
    # the scrubber snap to where it was. Only accept frames near the current playhead.
    total = max(1, self._worker.total_frames)
    target_frame = self._progress * (total - 1)
    if abs(result.global_frame - target_frame) > STALE_FRAME_TOL:
      return

    # Don't re-upload the same frame: _render runs at 60fps but frames only change ~15-20x/sec.
    # Uploading a ~7MB texture every render frame was ~400MB/s of wasted GPU bandwidth, starving
    # the decode. Only upload when the frame actually advances.
    if result.global_frame == self._last_uploaded_idx:
      return

    frame = result.frame
    height, width = frame.shape[:2]
    if self._texture is None or self._texture_size != (width, height):
      if self._texture is not None:
        rl.unload_texture(self._texture)
      image = rl.Image(None, width, height, 1, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8)
      self._texture = rl.load_texture_from_image(image)
      rl.set_texture_filter(self._texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      self._texture_size = (width, height)

    rl.update_texture(self._texture, rl.ffi.cast("void *", frame.ctypes.data))
    self._loading = False
    self._last_decoded_idx = result.global_frame
    self._last_uploaded_idx = result.global_frame

  def _advance_playback(self) -> None:
    now = rl.get_time()
    if not self._playing or self._dragging:
      self._last_playback_t = now
      return

    dt = max(0.0, now - self._last_playback_t) * self._speed
    self._last_playback_t = now
    self._progress = min(1.0, self._progress + dt / max(1.0, self._duration))
    # Don't let the playhead outrun the decoder (keeps the picture in step on slow full-res cams).
    if self._worker is not None and self._last_decoded_idx >= 0:
      cap = (self._last_decoded_idx + 12) / max(1, self._worker.total_frames)
      if self._progress > cap:
        self._progress = cap
    if self._progress >= 1.0:
      self._playing = False
      self._stop_audio()
    self._request_current_frame()

  @staticmethod
  def _fmt(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"

  def _controls_visible(self, now: float) -> bool:
    # Transport + scrubber stay up while paused or shortly after the last touch, then fade away.
    return (not self._playing) or (now - self._last_interaction < AUTOHIDE_S)

  def _note_interaction(self) -> None:
    self._last_interaction = rl.get_time()

  @staticmethod
  def _draw_dotted(font, parts: list[str], x: float, y: float, size: int, color) -> None:
    """Draw text segments joined by a small drawn dot (the font atlas lacks the '·' glyph)."""
    cx = x
    for i, part in enumerate(parts):
      if i > 0:
        cx += 10
        rl.draw_circle(int(cx), int(y + size / 2), 3, rl.Color(color.r, color.g, color.b, 150))
        cx += 16
      rl.draw_text_ex(font, part, rl.Vector2(int(cx), int(y)), size, 0, color)
      cx += measure_text_cached(font, part, size).x

  def _meta_parts(self) -> list[str]:
    parts: list[str] = []
    if self._meta_label:
      parts.append(self._meta_label)
    if self._distance_miles is not None and self._distance_miles >= 0.05:
      parts.append(f"{self._distance_miles:.1f} mi")
    elif self._distance_miles is None and self._route and not self._is_cloud:
      parts.append(tr("calculating miles..."))
    return parts

  def _render(self, rect: rl.Rectangle):
    now = rl.get_time()
    # Keep the screen awake the whole time the viewer is on screen — reset every frame because the
    # offroad wakefulness timer only otherwise resets on a physical touch (show_event alone wasn't
    # enough). Restored to the normal timeout in hide_event.
    device.set_override_interactive_timeout(24 * 60 * 60)
    self._advance_playback()
    self._consume_decoded_frame()

    # 1. Full-bleed video (cover the whole surface, crop overflow).
    rl.draw_rectangle_rec(rect, rl.Color(6, 7, 9, 255))
    self._draw_video_cover(rect)

    controls = self._controls_visible(now)

    # 2. Top scrim + header (back / date / share) + metadata + camera tabs. Always visible so the
    #    user can navigate; the scrim keeps text legible over bright footage.
    rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y), int(rect.width), 240,
                                 rl.Color(0, 0, 0, 200), rl.Color(0, 0, 0, 0))
    header_rect = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - 2 * MARGIN, HEADER_HEIGHT)
    self._header.render(header_rect)
    self._render_share(header_rect)
    self._render_speed(header_rect)

    meta_y = header_rect.y + HEADER_HEIGHT + 6
    parts = self._meta_parts()
    if parts:
      self._draw_dotted(gui_app.font(FontWeight.MEDIUM), parts, rect.x + MARGIN + 4, meta_y, 28, MUTED)
    self._render_cam_tabs(rect.x + MARGIN, meta_y + 40)

    # 3. Loading spinner while the (fresh full-res) camera opens.
    if self._texture is None:
      self._draw_center_spinner(rect, now)

    # 4. Center transport (auto-hides) — only once there's video to control.
    cx = rect.x + rect.width / 2
    cy = rect.y + rect.height / 2
    self._skip_back_rect = self._circle_rect(cx - SKIP_OFFSET, cy, SKIP_R)
    self._skip_fwd_rect = self._circle_rect(cx + SKIP_OFFSET, cy, SKIP_R)
    self._play_rect = self._circle_rect(cx, cy, PLAY_R)
    if controls and self._texture is not None:
      self._draw_skip(cx - SKIP_OFFSET, cy, SKIP_R, forward=False)
      self._draw_skip(cx + SKIP_OFFSET, cy, SKIP_R, forward=True)
      self._draw_play(cx, cy)

    # 5. Bottom scrim + scrubber (auto-hides).
    bar_y = rect.y + rect.height - MARGIN - 20
    if controls:
      rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y + rect.height - 200), int(rect.width), 200,
                                   rl.Color(0, 0, 0, 0), rl.Color(0, 0, 0, 210))
      self._render_scrub(rect.x + MARGIN, rect.width - 2 * MARGIN, bar_y)
    else:
      # Keep the hit-track current so a drag can still start, just don't paint it.
      self._track_rect = rl.Rectangle(0, 0, 0, 0)
    self._update_drag()

  def _circle_rect(self, cx, cy, r):
    return rl.Rectangle(cx - r, cy - r, r * 2, r * 2)

  def _draw_video_cover(self, rect: rl.Rectangle) -> None:
    if self._texture is None:
      return
    width, height = self._texture_size
    if width <= 0 or height <= 0:
      return
    # Cover: scale so the frame fills the surface, cropping the overflow instead of letterboxing.
    scale = max(rect.width / width, rect.height / height)
    crop_w = rect.width / scale
    crop_h = rect.height / scale
    src = rl.Rectangle((width - crop_w) / 2, (height - crop_h) / 2, crop_w, crop_h)
    rl.draw_texture_pro(self._texture, src, rect, rl.Vector2(0, 0), 0.0, rl.WHITE)

  def _draw_center_spinner(self, rect: rl.Rectangle, now: float) -> None:
    cx = rect.x + rect.width / 2
    cy = rect.y + rect.height / 2
    a = (now * 280) % 360
    rl.draw_ring(rl.Vector2(cx, cy), 34, 42, 0, 360, 48, rl.Color(255, 255, 255, 35))
    rl.draw_ring(rl.Vector2(cx, cy), 34, 42, a, a + 90, 24, TEAL)
    label = self._status or (self._worker.status() if self._worker is not None else "") \
      or tr("Loading %s") % CAMERA_LABELS.get(self._camera, "")
    if label:
      f = gui_app.font(FontWeight.MEDIUM)
      ts = measure_text_cached(f, label, 30)
      rl.draw_text_ex(f, label, rl.Vector2(int(cx - ts.x / 2), int(cy + 64)), 30, 0, rl.Color(220, 224, 230, 255))

  def _render_cam_tabs(self, x: float, y: float) -> None:
    self._cam_tab_rects = []
    if len(self._cameras) <= 1:
      return
    font = gui_app.font(FontWeight.MEDIUM)
    fs = 28
    pad = 24
    tx = x
    for cam in self._cameras:
      label = CAMERA_LABELS.get(cam, cam)
      tw = measure_text_cached(font, label, fs).x + pad * 2
      tab = rl.Rectangle(tx, y, tw, CAM_TAB_H)
      selected = cam == self._camera
      rl.draw_rectangle_rounded(tab, 0.5, 16, TEAL if selected else rl.Color(30, 32, 38, 220))
      rl.draw_text_ex(font, label, rl.Vector2(int(tx + pad), int(y + (CAM_TAB_H - fs) / 2)), fs, 0,
                      GLYPH_DARK if selected else rl.Color(226, 230, 236, 255))
      self._cam_tab_rects.append((tab, cam))
      tx += tw + CAM_TAB_GAP

  def _draw_play(self, cx, cy):
    rl.draw_circle(int(cx), int(cy), PLAY_R + 4, rl.Color(0, 0, 0, 70))
    rl.draw_circle(int(cx), int(cy), PLAY_R, TEAL)
    if self._playing:
      bar_w, bar_h, gap = 15, 58, 15
      rl.draw_rectangle_rounded(rl.Rectangle(cx - gap / 2 - bar_w, cy - bar_h / 2, bar_w, bar_h), 0.4, 6, GLYPH_DARK)
      rl.draw_rectangle_rounded(rl.Rectangle(cx + gap / 2, cy - bar_h / 2, bar_w, bar_h), 0.4, 6, GLYPH_DARK)
    else:
      rl.draw_texture(self._play_icon, int(cx - self._play_icon.width / 2 + 5), int(cy - self._play_icon.height / 2),
                      GLYPH_DARK)

  def _draw_skip(self, cx, cy, r, forward: bool):
    rl.draw_circle(int(cx), int(cy), r, rl.Color(20, 22, 27, 190))
    icon = self._skip_fwd_icon if forward else self._skip_back_icon
    rl.draw_texture(icon, int(cx - icon.width / 2), int(cy - icon.height / 2), rl.WHITE)
    f = gui_app.font(FontWeight.BOLD)
    ts = measure_text_cached(f, "10", 26)
    rl.draw_text_ex(f, "10", rl.Vector2(cx - ts.x / 2, cy - ts.y / 2 + 2), 26, 0, rl.WHITE)

  def _render_speed(self, header_rect: rl.Rectangle):
    # Speed / fast-forward pill, left of the share button. Tap to cycle 1x -> 2x -> 4x -> 8x.
    cy = header_rect.y + HEADER_HEIGHT / 2
    font = gui_app.font(FontWeight.BOLD)
    label = f"{self._speed:g}x"
    fs = 30
    w = measure_text_cached(font, label, fs).x + 44
    x = header_rect.x + header_rect.width - 2 * SHARE_R - 20 - w
    self._speed_rect = rl.Rectangle(x, cy - 34, w, 68)
    active = self._speed > 1.0
    rl.draw_rectangle_rounded(self._speed_rect, 0.5, 12, TEAL if active else rl.Color(32, 34, 40, 210))
    tw = measure_text_cached(font, label, fs).x
    rl.draw_text_ex(font, label, rl.Vector2(int(x + (w - tw) / 2), int(cy - fs / 2)), fs, 0,
                    GLYPH_DARK if active else rl.WHITE)

  def _render_share(self, header_rect: rl.Rectangle):
    sx = header_rect.x + header_rect.width - SHARE_R
    sy = header_rect.y + HEADER_HEIGHT / 2
    self._share_rect = self._circle_rect(sx, sy, SHARE_R)
    is_pressed = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT) and rl.check_collision_point_rec(rl.get_mouse_position(), self._share_rect)
    rl.draw_circle(int(sx), int(sy), SHARE_R, rl.Color(50, 53, 61, 235) if is_pressed else rl.Color(32, 34, 40, 200))
    nr = 6
    left = rl.Vector2(sx - 13, sy)
    top = rl.Vector2(sx + 13, sy - 14)
    bot = rl.Vector2(sx + 13, sy + 14)
    rl.draw_line_ex(left, top, 3, TEAL)
    rl.draw_line_ex(left, bot, 3, TEAL)
    for p in (left, top, bot):
      rl.draw_circle(int(p.x), int(p.y), nr, TEAL)

  def _render_scrub(self, x, w, bar_y):
    font = gui_app.font(FontWeight.MEDIUM)
    fs = 30
    left = self._fmt(self._progress * self._duration)
    right = "-" + self._fmt((1.0 - self._progress) * self._duration)
    lw = measure_text_cached(font, left, fs)
    rw = measure_text_cached(font, right, fs)

    self._track_x0 = x + lw.x + 24
    track_x1 = x + w - rw.x - 24
    self._track_w = max(1.0, track_x1 - self._track_x0)

    rl.draw_text_ex(font, left, rl.Vector2(x, bar_y - fs / 2), fs, 0, rl.WHITE)
    rl.draw_text_ex(font, right, rl.Vector2(x + w - rw.x, bar_y - fs / 2), fs, 0, rl.Color(200, 204, 210, 255))

    rl.draw_rectangle_rounded(rl.Rectangle(self._track_x0, bar_y - 4, self._track_w, 8), 1.0, 8, rl.Color(255, 255, 255, 60))
    fill = self._track_w * self._progress
    if fill > 0:
      rl.draw_rectangle_rounded(rl.Rectangle(self._track_x0, bar_y - 4, fill, 8), 1.0, 8, TEAL)
    hx = int(self._track_x0 + fill)
    if self._dragging:
      rl.draw_circle(hx, int(bar_y), 22, rl.Color(16, 185, 169, 70))
      rl.draw_circle(hx, int(bar_y), 17, rl.WHITE)
    else:
      rl.draw_circle(hx, int(bar_y), 13, rl.WHITE)
    self._track_rect = rl.Rectangle(self._track_x0 - 20, bar_y - 34, self._track_w + 40, 68)

  def _reset_pace_anchor(self) -> None:
    # After an explicit seek, move the decode-pace anchor to the new spot so _advance_playback
    # doesn't clamp the playhead back to the pre-seek frame (made scrubbing feel stuck).
    if self._worker is not None:
      self._last_decoded_idx = int(self._progress * max(0, self._worker.total_frames - 1))

  def _seek(self, delta_s: float):
    self._progress = min(1.0, max(0.0, self._progress + delta_s / self._duration))
    self._reset_pace_anchor()
    self._request_current_frame()
    self._sync_audio()

  def _update_drag(self):
    down = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)
    mp = rl.get_mouse_position()
    if down and not self._was_down and rl.check_collision_point_rec(mp, self._track_rect):
      self._dragging = True
      self._note_interaction()
      self._stop_audio()
    if not down:
      was_dragging = self._dragging
      self._dragging = False
      if was_dragging:
        # Seek once on release — re-seeking every drag frame just thrashes ffmpeg so nothing decodes.
        self._note_interaction()
        self._reset_pace_anchor()
        self._request_current_frame()
        self._sync_audio()
    if self._dragging:
      # Move the handle live for feedback; the actual seek happens on release.
      self._progress = min(1.0, max(0.0, (mp.x - self._track_x0) / self._track_w))
      self._note_interaction()
    self._was_down = down

  def _handle_mouse_press(self, mouse_pos: MousePos):
    # A tap while the transport is hidden just reveals it; it shouldn't also fire a control.
    self._press_revealed = not self._controls_visible(rl.get_time())
    self._note_interaction()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if self._dragging:
      return
    self._note_interaction()
    # Camera tabs and header controls are always live.
    for tab, cam in self._cam_tab_rects:
      if rl.check_collision_point_rec(mouse_pos, tab):
        self._select_camera(cam)
        return
    if rl.check_collision_point_rec(mouse_pos, self._share_rect):
      if self._on_share_cb is not None:
        self._on_share_cb()
      return
    if rl.check_collision_point_rec(mouse_pos, self._speed_rect):
      speeds = [1.0, 2.0, 4.0, 8.0]
      idx = speeds.index(self._speed) if self._speed in speeds else 0
      self._speed = speeds[(idx + 1) % len(speeds)]
      return
    # If this tap only revealed the hidden transport, don't also trigger it.
    if self._press_revealed:
      return
    if rl.check_collision_point_rec(mouse_pos, self._play_rect):
      self._playing = not self._playing
      self._sync_audio()
    elif rl.check_collision_point_rec(mouse_pos, self._skip_back_rect):
      self._seek(-10)
    elif rl.check_collision_point_rec(mouse_pos, self._skip_fwd_rect):
      self._seek(10)

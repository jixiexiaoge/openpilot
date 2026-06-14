import asyncio
import logging
import struct
import time

import av
from teleoprtc.tracks import TiciVideoStreamTrack

from cereal import messaging
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL, DT_DMON

# Arbitrary 16-byte UUID identifying konn3kt frame-timing SEI messages. When timing
# telemetry is enabled, each frame carries a user_data_unregistered SEI NAL with four
# big-endian doubles (ms): encode duration, IPC/queue delay, host transit, and the
# device wall clock. The client decodes these to compute true glass-to-glass latency.
TIMING_SEI_UUID = bytes([
  0xa5, 0xe0, 0xc4, 0xa4, 0x5b, 0x6e, 0x4e, 0x1e,
  0x9c, 0x7e, 0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc,
])
# Annex-B start code + SEI NAL (type 6) + user_data_unregistered (type 5) + payload size
# (0x30 = 48 bytes = 16 UUID + 32 data). Trailing 0x80 is the RBSP stop bit.
_SEI_PREFIX = b'\x00\x00\x00\x01\x06\x05\x30' + TIMING_SEI_UUID


class LiveStreamVideoStreamTrack(TiciVideoStreamTrack):
  livestream_camera_to_sock_mapping = {
    "driver": "livestreamDriverEncodeData",
    "wideRoad": "livestreamWideRoadEncodeData",
    "road": "livestreamRoadEncodeData",
  }
  main_camera_to_sock_mapping = {
    "driver": "driverEncodeData",
    "wideRoad": "wideRoadEncodeData",
    "road": "roadEncodeData",
  }

  def __init__(self, camera_type: str):
    dt = DT_DMON if camera_type == "driver" else DT_MDL
    super().__init__(camera_type, dt)

    self._params = Params()
    self._camera_type = camera_type
    self._candidate_topics = [
      self.main_camera_to_sock_mapping[camera_type],
      self.livestream_camera_to_sock_mapping[camera_type],
    ]
    # Avoid conflating at the socket level: dropping keyframes can cause the decoder to never start
    # (resulting in a "connected but black" stream in some browsers).
    self._socks = {topic: messaging.sub_sock(topic, conflate=False) for topic in self._candidate_topics}
    self._active_topic = self._preferred_topics()[0]
    self._pts = 0
    # Wall-clock reference for PTS. Timestamping packets by their actual arrival time
    # (rather than frame_number * frame_duration) prevents the client jitter buffer from
    # inflating latency when frames arrive unevenly — frames are played as soon as they land.
    self._t0_ns = time.monotonic_ns()
    self._cached_header: bytes = b""
    self._sent_keyframe = False
    self._frame_count = 0
    self._last_frame_time = 0.0
    self._last_preference_refresh = 0.0
    # Opt-in glass-to-glass latency telemetry (toggled by the client over the data channel).
    self.timing_sei_enabled = False
    self._logger = logging.getLogger("LiveStreamVideoStreamTrack")

  def switch_camera(self, camera_type: str) -> None:
    """Repoint this track at a different camera without renegotiating the peer connection.

    Lets a single video track back the whole Live View — the client flips cameras over the
    data channel and we swap the source here, instead of uplinking every camera at once."""
    if camera_type not in self.livestream_camera_to_sock_mapping:
      self._logger.warning("[%s] ignoring switch to unknown camera %s", self._id, camera_type)
      return
    if camera_type == self._camera_type:
      return
    self._logger.info("[%s] switching camera %s -> %s", self._id, self._camera_type, camera_type)
    self._camera_type = camera_type
    self._candidate_topics = [
      self.main_camera_to_sock_mapping[camera_type],
      self.livestream_camera_to_sock_mapping[camera_type],
    ]
    self._socks = {topic: messaging.sub_sock(topic, conflate=False) for topic in self._candidate_topics}
    self._active_topic = self._preferred_topics()[0]
    # Force a fresh keyframe/header before emitting frames from the new source.
    self._cached_header = b""
    self._sent_keyframe = False
    self._last_preference_refresh = 0.0

  def _preferred_topics(self) -> list[str]:
    # WebRTC currently forces H.264. The dedicated livestream topics are the H.264 feeds,
    # while the main encode topics are the full-resolution HEVC recordings. Prefer the
    # livestream feeds both onroad and offroad, and keep the main topics only as fallback.
    return [
      self.livestream_camera_to_sock_mapping[self._camera_type],
      self.main_camera_to_sock_mapping[self._camera_type],
    ]

  def _reset_decoder_state(self, topic: str) -> None:
    if topic == self._active_topic:
      return
    self._logger.info("[%s] switching video source from %s to %s", self._id, self._active_topic, topic)
    self._active_topic = topic
    self._cached_header = b""
    self._sent_keyframe = False

  def _timing_sei(self, evta, log_mono_time: int) -> bytes:
    """Build a timing SEI NAL from encode metadata, or empty bytes when disabled."""
    if not self.timing_sei_enabled:
      return b""
    idx = evta.idx
    return _SEI_PREFIX + struct.pack(
      '>4d',
      (idx.timestampEof - idx.timestampSof) / 1e6,   # encode duration (ms)
      (log_mono_time - idx.timestampEof) / 1e6,       # IPC/queue delay (ms)
      (time.monotonic_ns() - log_mono_time) / 1e6,    # host transit so far (ms)
      time.time() * 1000,                             # device wall clock (ms)  # noqa: TID251
    ) + b'\x80'

  def _is_keyframe(self, data: bytes) -> bool:
    """Check if H.264 NAL unit contains an IDR keyframe (NAL type 5)."""
    i = 0
    while i < len(data) - 4:
      # Look for Annex B start codes: 0x000001 or 0x00000001
      if data[i:i+3] == b'\x00\x00\x01':
        nal_type = data[i+3] & 0x1f
        if nal_type == 5:  # IDR slice
          return True
        i += 3
      elif data[i:i+4] == b'\x00\x00\x00\x01':
        nal_type = data[i+4] & 0x1f
        if nal_type == 5:  # IDR slice
          return True
        i += 4
      else:
        i += 1
    return False

  async def recv(self):
    while True:
      now = time.monotonic()
      if now - self._last_preference_refresh > 0.5:
        preferred_topics = self._preferred_topics()
        self._last_preference_refresh = now
      else:
        preferred_topics = [self._active_topic, *[t for t in self._candidate_topics if t != self._active_topic]]

      msg = None
      msg_topic = None
      for topic in preferred_topics:
        maybe_msg = messaging.recv_one_or_none(self._socks[topic])
        if maybe_msg is not None:
          msg = maybe_msg
          msg_topic = topic
          break

      if msg is not None and msg_topic is not None:
        self._reset_decoder_state(msg_topic)
        self._last_frame_time = now
        break

      await asyncio.sleep(0.005)

    evta = getattr(msg, msg.which())

    header = bytes(evta.header)
    data = bytes(evta.data)
    self._frame_count += 1

    # Cache SPS/PPS header when it arrives
    if header:
      self._cached_header = header
      self._logger.debug(f"[{self._id}] cached SPS/PPS header ({len(header)} bytes)")

    # CRITICAL: Cannot decode without SPS/PPS. Wait for it.
    if not self._cached_header:
      self._logger.debug(f"[{self._id}] frame {self._frame_count}: no SPS/PPS yet, skipping")
      return await self.recv()

    is_keyframe = self._is_keyframe(data)

    # Wait for first keyframe before sending any frames
    # Browser decoder needs IDR to initialize properly
    if not self._sent_keyframe:
      if not is_keyframe:
        self._logger.debug(f"[{self._id}] frame {self._frame_count}: waiting for keyframe")
        return await self.recv()
      self._sent_keyframe = True
      self._logger.info(f"[{self._id}] first keyframe received, starting stream")

    # Optional timing SEI NAL, inserted before the slice data (and after SPS/PPS on keyframes).
    sei_nal = self._timing_sei(evta, msg.logMonoTime)

    # Prepend SPS/PPS header to keyframes (required by some decoders)
    # For non-keyframes, header is optional but safe to include
    if is_keyframe:
      payload = self._cached_header + sei_nal + data
    else:
      payload = sei_nal + data

    # Wall-clock PTS: stamp by actual arrival time so the decoder plays frames immediately
    # instead of holding them to match an idealized frame#-based schedule.
    self._pts = ((time.monotonic_ns() - self._t0_ns) * self._clock_rate) // 1_000_000_000

    packet = av.Packet(payload)
    packet.time_base = self._time_base
    packet.pts = self._pts
    packet.dts = self._pts
    packet.duration = int(self._dt * self._clock_rate)

    if is_keyframe:
      packet.is_keyframe = True

    self.log_debug("track sending frame %s (keyframe=%s, size=%d)", self._pts, is_keyframe, len(payload))

    return packet

  def codec_preference(self) -> str | None:
    return "H264"

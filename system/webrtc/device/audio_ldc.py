import asyncio
import contextlib
from collections import deque
from fractions import Fraction

import av

from cereal import messaging
from openpilot.selfdrive.ui.soundd import SAMPLE_RATE as SOUND_SAMPLE_RATE
from openpilot.system.webrtc.device.audio import WEBRTC_AUDIO_PTIME, WEBRTC_AUDIO_SERVICE


class AudioInputOpusProducer:
  """Micd PCM -> 48 kHz Opus payloads for libdatachannel's RTP packetizer."""

  def __init__(self) -> None:
    self._sock = messaging.sub_sock("rawAudioData", conflate=False)
    self._pcm = bytearray()
    self._source_rate = 16_000
    self._next_pts = 0
    self._pending: deque[tuple[bytes, int]] = deque()
    self._enabled = True
    self._resampler = av.AudioResampler(format="fltp", layout="mono", rate=48_000)
    self._encoder = av.CodecContext.create("libopus", "w")
    self._encoder.sample_rate = 48_000
    self._encoder.layout = "mono"
    self._encoder.format = "fltp"
    self._encoder.open()

  def enable(self, enabled: bool) -> None:
    self._enabled = enabled

  async def _read_pcm_frame(self) -> av.AudioFrame:
    while True:
      samples = max(1, int(WEBRTC_AUDIO_PTIME * self._source_rate))
      target_bytes = samples * 2
      while len(self._pcm) < target_bytes:
        msg = messaging.recv_one_or_none(self._sock)
        if msg is None:
          await asyncio.sleep(0.002)
          continue
        audio = msg.rawAudioData
        rate = int(audio.sampleRate) or self._source_rate
        if rate != self._source_rate:
          self._source_rate = rate
          self._pcm.clear()
          continue
        self._pcm.extend(bytes(audio.data))

      data = bytes(self._pcm[:target_bytes])
      del self._pcm[:target_bytes]
      frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
      frame.planes[0].update(data)
      frame.sample_rate = self._source_rate
      return frame

  async def recv(self) -> tuple[bytes, int] | None:
    if not self._enabled:
      await asyncio.sleep(WEBRTC_AUDIO_PTIME)
      return None
    while not self._pending:
      source_frame = await self._read_pcm_frame()
      for frame in self._resampler.resample(source_frame):
        frame.pts = self._next_pts
        frame.time_base = Fraction(1, 48_000)
        self._next_pts += frame.samples
        for packet in self._encoder.encode(frame):
          self._pending.append((bytes(packet), int(packet.pts or 0)))
    return self._pending.popleft()


class IncomingOpusCerealProxy:
  """libdatachannel Opus payloads -> soundd-compatible PCM cereal messages."""

  def __init__(self, track) -> None:
    self._loop = asyncio.get_running_loop()
    self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
    self._pm = messaging.PubMaster([WEBRTC_AUDIO_SERVICE])
    self._decoder = av.CodecContext.create("opus", "r")
    self._resampler = av.AudioResampler(format="s16", layout="mono", rate=SOUND_SAMPLE_RATE)
    self._task: asyncio.Task | None = None
    track.on_frame(self._on_frame)

  def _on_frame(self, payload: bytes, _info) -> None:
    def enqueue() -> None:
      if self._queue.full():
        with contextlib.suppress(asyncio.QueueEmpty):
          self._queue.get_nowait()
      self._queue.put_nowait(bytes(payload))
    self._loop.call_soon_threadsafe(enqueue)

  def start(self) -> None:
    if self._task is None:
      self._task = asyncio.create_task(self.run())

  async def stop(self) -> None:
    if self._task is None:
      return
    self._task.cancel()
    try:
      await self._task
    except asyncio.CancelledError:
      pass
    self._task = None

  def _publish(self, frame: av.AudioFrame) -> None:
    data = frame.to_ndarray().tobytes()
    if not data:
      return
    msg = messaging.new_message(WEBRTC_AUDIO_SERVICE, valid=True)
    msg.webrtcAudioData.data = data
    msg.webrtcAudioData.sampleRate = frame.sample_rate
    self._pm.send(WEBRTC_AUDIO_SERVICE, msg)

  async def run(self) -> None:
    while True:
      payload = await self._queue.get()
      try:
        for decoded in self._decoder.decode(av.Packet(payload)):
          for frame in self._resampler.resample(decoded):
            self._publish(frame)
      except Exception:
        # A malformed or stale packet must not end the video/control session.
        continue

import asyncio
import fractions

import aiortc
import av
import numpy as np

from cereal import messaging


WEBRTC_AUDIO_SERVICE = "webrtcAudioData"
WEBRTC_AUDIO_PTIME = 0.020


class AudioInputStreamTrack(aiortc.mediastreams.AudioStreamTrack):
  """Device microphone -> WebRTC, sourced from micd's `rawAudioData` cereal stream.

  micd owns the ALSA capture device, so opening it again via PyAudio fails with a host error
  ('audio in use', PortAudio errno -9999). Instead we consume micd's already-published int16 mono
  PCM and repacketize it into WebRTC audio frames — no device contention, and it works whenever micd
  is running. Reading one message per recv() paces playout to micd's real-time publish rate.
  """
  def __init__(self, rate: int = 16000, channels: int = 1):
    super().__init__()
    self.rate = rate
    self.channels = channels
    # conflate=False: keep audio continuous (don't drop buffered samples) for clean playback.
    self._sock = messaging.sub_sock("rawAudioData", conflate=False)
    self._start: float | None = None
    self.pts = 0
    self.enabled = True
    self._audio_buffer = bytearray()

  def enable(self, enabled: bool) -> None:
    self.enabled = enabled

  async def _fill_audio_buffer(self, target_bytes: int) -> None:
    deadline = asyncio.get_running_loop().time() + WEBRTC_AUDIO_PTIME
    while len(self._audio_buffer) < target_bytes:
      msg = messaging.recv_one_or_none(self._sock)
      if msg is not None:
        audio = msg.rawAudioData
        rate = int(audio.sampleRate) or self.rate
        if rate != self.rate:
          self.rate = rate
          self._audio_buffer.clear()
          self._start = None
          self.pts = 0
        self._audio_buffer.extend(bytes(audio.data))
        continue
      if asyncio.get_running_loop().time() >= deadline:
        break
      await asyncio.sleep(0.005)

  async def _next_audio_data(self) -> tuple[bytes, int]:
    samples = max(1, int(WEBRTC_AUDIO_PTIME * self.rate))
    target_bytes = samples * 2
    await self._fill_audio_buffer(target_bytes)

    if len(self._audio_buffer) >= target_bytes:
      data = bytes(self._audio_buffer[:target_bytes])
      del self._audio_buffer[:target_bytes]
    else:
      data = bytes(self._audio_buffer)
      self._audio_buffer.clear()
      data += bytes(target_bytes - len(data))

    return data, self.rate

  async def _pace(self, pts: int, sample_rate: int) -> None:
    if self._start is None:
      self._start = asyncio.get_running_loop().time()
      return

    wait = self._start + (pts / sample_rate) - asyncio.get_running_loop().time()
    if wait > 0:
      await asyncio.sleep(wait)

  async def recv(self):
    while True:
      if not self.enabled:
        break
      data, sample_rate = await self._next_audio_data()
      if data:
        samples = len(data) // 2
        pts = self.pts
        self.pts += samples
        await self._pace(pts, sample_rate)

        frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(data)
        frame.pts = pts
        frame.sample_rate = sample_rate
        frame.time_base = fractions.Fraction(1, sample_rate)
        return frame

    samples_per_frame = max(1, int(WEBRTC_AUDIO_PTIME * self.rate))
    samples = np.zeros((1, samples_per_frame), dtype=np.int16)
    frame = av.AudioFrame.from_ndarray(samples, format='s16', layout='mono')
    frame.sample_rate = self.rate
    frame.time_base = fractions.Fraction(1, self.rate)
    frame.pts = self.pts
    self.pts += frame.samples
    await self._pace(frame.pts, self.rate)
    return frame

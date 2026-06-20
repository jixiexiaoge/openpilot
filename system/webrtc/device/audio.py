import asyncio
import io

import aiortc
import av
import numpy as np

from cereal import messaging


def _require_pyaudio():
  import pyaudio
  return pyaudio


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
    self.pts = 0

  async def recv(self):
    while True:
      msg = messaging.recv_one_or_none(self._sock)
      if msg is not None:
        break
      await asyncio.sleep(0.005)

    audio = msg.rawAudioData
    rate = int(audio.sampleRate) or self.rate
    samples = np.frombuffer(bytes(audio.data), dtype=np.int16)
    samples = np.expand_dims(samples, axis=0)  # (channels=1, n_samples) for mono s16
    frame = av.AudioFrame.from_ndarray(samples, format='s16', layout='mono')
    frame.rate = rate
    frame.pts = self.pts
    self.pts += frame.samples

    return frame


class AudioOutputSpeaker:
  def __init__(self, audio_format: int | None = None, rate: int = 48000, channels: int = 2, packet_time: float = 0.2, device_index: int | None = None):

    chunk_size = int(packet_time * rate)
    self.pyaudio = _require_pyaudio()
    self.p = self.pyaudio.PyAudio()
    if audio_format is None:
      audio_format = self.pyaudio.paInt16
    self.buffer = io.BytesIO()
    self.channels = channels
    self.stream = self.p.open(format=audio_format,
                              channels=channels,
                              rate=rate,
                              frames_per_buffer=chunk_size,
                              output=True,
                              output_device_index=device_index,
                              stream_callback=self.__pyaudio_callback)
    self.tracks_and_tasks: list[tuple[aiortc.MediaStreamTrack, asyncio.Task | None]] = []

  def __pyaudio_callback(self, in_data, frame_count, time_info, status):
    if self.buffer.getbuffer().nbytes < frame_count * self.channels * 2:
      buff = b'\x00\x00' * frame_count * self.channels
    elif self.buffer.getbuffer().nbytes > 115200:  # 3x the usual read size
      self.buffer.seek(0)
      buff = self.buffer.read(frame_count * self.channels * 4)
      buff = buff[:frame_count * self.channels * 2]
      self.buffer.seek(2)
    else:
      self.buffer.seek(0)
      buff = self.buffer.read(frame_count * self.channels * 2)
      self.buffer.seek(2)
    return (buff, self.pyaudio.paContinue)

  async def __consume(self, track):
    while True:
      try:
        frame = await track.recv()
      except aiortc.MediaStreamError:
        return

      self.buffer.write(bytes(frame.planes[0]))

  def hasTrack(self, track: aiortc.MediaStreamTrack) -> bool:
    return any(t == track for t, _ in self.tracks_and_tasks)

  def addTrack(self, track: aiortc.MediaStreamTrack):
    if not self.hasTrack(track):
      self.tracks_and_tasks.append((track, None))

  def start(self):
    for index, (track, task) in enumerate(self.tracks_and_tasks):
      if task is None:
        self.tracks_and_tasks[index] = (track, asyncio.create_task(self.__consume(track)))

  def stop(self):
    for _, task in self.tracks_and_tasks:
      if task is not None:
        task.cancel()

    self.tracks_and_tasks = []
    self.stream.stop_stream()
    self.stream.close()
    self.p.terminate()

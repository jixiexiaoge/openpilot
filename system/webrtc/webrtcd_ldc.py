import asyncio
import contextlib
import json
import logging
import os
import socket
import uuid
from typing import Any

from openpilot.common.params import Params
from cereal import messaging

from openpilot.system.webrtc.webrtcd import CerealIncomingMessageProxy, CerealOutgoingMessageProxy, CerealProxyRunner, DynamicPubMaster


def _default_route_ip() -> str | None:
  """Use the interface the kernel will actually use for Internet/relay media."""
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    sock.connect(("8.8.8.8", 53))
    return sock.getsockname()[0]
  except OSError:
    return None
  finally:
    sock.close()


class LibdatachannelBitrateController:
  """Loss-driven bitrate control using native RTCP receiver reports."""

  bitrates = [500_000, 1_500_000, int(os.environ.get("STREAM_BITRATE", 5_000_000))]
  label_to_bitrate = {"low": bitrates[0], "med": bitrates[1], "high": bitrates[2]}
  sample_interval = 0.2
  high_loss = 0.10
  sustained_loss = 0.05
  down_samples = 5

  def __init__(self, get_stats, enabled: bool = True):
    self._get_stats = get_stats
    self._enabled = enabled
    self._auto = True
    self._level = 1
    self._counter = 0
    self._up_samples = 5
    self._previous: tuple[Any, ...] | None = None
    self._task: asyncio.Task | None = None
    self.current_bitrate = self.bitrates[self._level]
    self._publish(self.current_bitrate)

  def start(self) -> None:
    if self._task is None:
      self._task = asyncio.create_task(self.run())

  def stop(self) -> None:
    if self._task is not None:
      self._task.cancel()
    self._task = None

  def enable(self, enabled: bool) -> None:
    self._enabled = enabled

  def set_quality(self, quality: str) -> None:
    if quality in self.label_to_bitrate:
      self._auto = False
      self._publish(self.label_to_bitrate[quality])
    elif quality == "auto":
      self._auto = True

  def _publish(self, bitrate: int) -> None:
    self.current_bitrate = int(bitrate)
    Params().put("LivestreamEncoderBitrate", self.current_bitrate)

  def _sample_loss(self) -> float | None:
    report = next(iter(self._get_stats().values()), None)
    if report is None:
      return None
    current = (report.ssrc, report.fraction_lost, report.packets_lost, report.highest_seq_no, report.jitter, report.lsr, report.dlsr)
    if current == self._previous:
      return None
    self._previous = current
    return report.fraction_lost / 256.0

  async def run(self) -> None:
    while True:
      await asyncio.sleep(self.sample_interval)
      if not self._enabled or not self._auto:
        continue
      loss = self._sample_loss()
      if loss is None:
        continue
      if loss >= self.sustained_loss and self._level > 0:
        self._counter += 1
        if loss >= self.high_loss or self._counter >= self.down_samples:
          self._level -= 1
          self._up_samples *= 2
          self._counter = 0
          self._publish(self.bitrates[self._level])
      elif loss <= 0 and self._level < len(self.bitrates) - 1:
        self._counter -= 1
        if -self._counter >= self._up_samples:
          self._level += 1
          self._counter = 0
          self._publish(self.bitrates[self._level])


class StreamSessionLibdatachannel:
  """IQ.Pilot's libdatachannel stream path. It preserves Konn3kt signalling and controls."""

  shared_pub_master = DynamicPubMaster([])

  def __init__(self, sdp: str, cameras: list[str], incoming_services: list[str], outgoing_services: list[str],
               ice_servers: list[dict[str, Any]] | None = None, debug_mode: bool = False, ui_stream: bool = False):
    from openpilot.system.webrtc.device.video_ldc import LiveStreamVideoStreamTrack
    from openpilot.system.webrtc.teleoprtc_ldc.builder import WebRTCAnswerBuilder
    from openpilot.system.webrtc.teleoprtc_ldc.info import parse_info_from_offer

    config = parse_info_from_offer(sdp)
    if len(cameras) != config.n_expected_camera_tracks:
      raise ValueError("Incoming stream has misconfigured number of video tracks")
    if debug_mode:
      raise ValueError("libdatachannel debug tracks are not supported")

    builder = WebRTCAnswerBuilder(sdp, bind_address=_default_route_ip(), ice_servers=ice_servers or [])
    self.video_tracks = [LiveStreamVideoStreamTrack(camera) for camera in cameras]
    for camera, track in zip(cameras, self.video_tracks, strict=True):
      builder.add_video_stream(camera, track)

    # The browser uses a single sendrecv audio m-line. libdatachannel's Python binding
    # currently cannot negotiate that bidirectional track reliably, so this experimental
    # transport deliberately remains video/control-only. The default aiortc path keeps
    # both audio directions until the native duplex path passes the same integration test.
    self.audio_output = None
    self.stream = builder.stream()

    self.identifier = str(uuid.uuid4())
    self.incoming_bridge_services = incoming_services
    self.incoming_bridge = CerealIncomingMessageProxy(self.shared_pub_master) if incoming_services else None
    self.outgoing_bridge = CerealOutgoingMessageProxy(messaging.SubMaster(outgoing_services)) if outgoing_services else None
    self.outgoing_bridge_runner = CerealProxyRunner(self.outgoing_bridge) if self.outgoing_bridge is not None else None
    self.ui_stream_requested = ui_stream
    self.ui_stream_runner: CerealProxyRunner | None = None
    self.audio_input_proxy = None
    self.audio_recv_requested = False
    self.bitrate_controller = LibdatachannelBitrateController(self.stream.get_receiver_report_stats)
    self.run_task: asyncio.Task | None = None
    self._cleanup_lock = asyncio.Lock()
    self._cleanup_done = False
    self.logger = logging.getLogger("webrtcd")

  def start(self) -> None:
    self.run_task = asyncio.create_task(self.run())

  async def get_answer(self):
    return await self.stream.start()

  async def stop_async(self) -> None:
    if self.run_task is not None and not self.run_task.done() and self.run_task is not asyncio.current_task():
      self.run_task.cancel()
      with contextlib.suppress(asyncio.CancelledError):
        await self.run_task
    self.run_task = None
    await self.post_run_cleanup()

  def add_ice_candidate(self, candidate: Any) -> None:
    self.stream.add_ice_candidate(candidate)

  def message_handler(self, message: bytes | str) -> None:
    try:
      payload = json.loads(message)
    except (TypeError, ValueError):
      return
    if not isinstance(payload, dict):
      return
    message_type = payload.get("type")
    if message_type == "timingSei":
      for track in self.video_tracks:
        track.timing_sei_enabled = bool(payload.get("enabled", False))
    elif message_type == "setQuality":
      self.bitrate_controller.set_quality(str(payload.get("quality", "auto")))
    elif message_type == "setAudioEnabled" and self.audio_output is not None:
      self.audio_output.enable(bool(payload.get("enabled", True)))
    elif message_type == "switchCamera":
      for track in self.video_tracks:
        track.switch_camera(str(payload.get("camera", "")))
    elif message_type == "setUiStream":
      self.set_ui_stream(bool(payload.get("enabled", False)))
    elif self.incoming_bridge is not None:
      try:
        self.incoming_bridge.send(message)
      except Exception:
        self.logger.exception("Cereal incoming proxy failure")

  def set_ui_stream(self, enabled: bool) -> None:
    if enabled:
      if self.ui_stream_runner is not None or not self.stream.has_messaging_channel():
        return
      from openpilot.system.webrtc.ui_stream import UIStreamMessageProxy
      proxy = UIStreamMessageProxy(bitrate_getter=lambda: self.bitrate_controller.current_bitrate)
      proxy.add_channel(self.stream.get_messaging_channel())
      self.ui_stream_runner = CerealProxyRunner(proxy)
      self.ui_stream_runner.start()
    elif self.ui_stream_runner is not None:
      self.ui_stream_runner.stop()
      self.ui_stream_runner = None

  async def run(self) -> None:
    try:
      await self.stream.wait_for_connection()
      if self.stream.has_messaging_channel():
        self.stream.set_message_handler(self.message_handler)
        if self.incoming_bridge is not None:
          await self.shared_pub_master.add_services_if_needed(self.incoming_bridge_services)
        if self.outgoing_bridge_runner is not None:
          self.outgoing_bridge_runner.proxy.add_channel(self.stream.get_messaging_channel())
          self.outgoing_bridge_runner.start()
        if self.ui_stream_requested:
          self.set_ui_stream(True)
      if self.audio_recv_requested and self.stream.has_incoming_audio_track():
        from openpilot.system.webrtc.device.audio_ldc import IncomingOpusCerealProxy
        self.audio_input_proxy = IncomingOpusCerealProxy(self.stream.get_incoming_audio_track())
        self.audio_input_proxy.start()
      self.bitrate_controller.start()
      await self.stream.wait_for_disconnection()
    except Exception:
      self.logger.exception("libdatachannel stream session failure")
    finally:
      await self.post_run_cleanup()

  async def post_run_cleanup(self) -> None:
    async with self._cleanup_lock:
      if self._cleanup_done:
        return
      self._cleanup_done = True
      self.bitrate_controller.stop()
      if self.ui_stream_runner is not None:
        self.ui_stream_runner.stop()
        self.ui_stream_runner = None
      if self.outgoing_bridge_runner is not None:
        self.outgoing_bridge_runner.stop()
      if self.audio_input_proxy is not None:
        await self.audio_input_proxy.stop()
      for track in self.video_tracks:
        track.stop()
      await self.stream.stop()

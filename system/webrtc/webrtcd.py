#!/usr/bin/env python3

import argparse
import asyncio
import json
import os
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from openpilot.common.params import Params

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

import capnp
import aiortc.rtcrtpsender
from aiohttp import web
from aiortc.rtp import RTCP_PSFB_APP, RtcpPsfbPacket, unpack_remb_fci
if TYPE_CHECKING:
  from aiortc.rtcdatachannel import RTCDataChannel

from openpilot.system.webrtc.schema import generate_field
from cereal import messaging, log


_handle_rtcp_packet = aiortc.rtcrtpsender.RTCRtpSender._handle_rtcp_packet


async def _handle_rtcp_packet_with_remb(self, packet):
  if isinstance(packet, RtcpPsfbPacket) and packet.fmt == RTCP_PSFB_APP:
    try:
      bitrate, ssrcs = unpack_remb_fci(packet.fci)
      if getattr(self, "_ssrc", None) in ssrcs:
        self._remb_bitrate = bitrate
    except ValueError:
      pass
  return await _handle_rtcp_packet(self, packet)


aiortc.rtcrtpsender.RTCRtpSender._handle_rtcp_packet = _handle_rtcp_packet_with_remb


class CerealOutgoingMessageProxy:
  def __init__(self, sm: messaging.SubMaster):
    self.sm = sm
    self.channels: list[RTCDataChannel] = []

  def add_channel(self, channel: 'RTCDataChannel'):
    self.channels.append(channel)

  def to_json(self, msg_content: Any):
    if isinstance(msg_content, capnp._DynamicStructReader):
      msg_dict = msg_content.to_dict()
    elif isinstance(msg_content, capnp._DynamicListReader):
      msg_dict = [self.to_json(msg) for msg in msg_content]
    elif isinstance(msg_content, bytes):
      msg_dict = msg_content.decode()
    else:
      msg_dict = msg_content

    return msg_dict

  def update(self):
    # this is blocking in async context...
    self.sm.update(0)
    for service, updated in self.sm.updated.items():
      if not updated:
        continue
      msg_dict = self.to_json(self.sm[service])
      mono_time, valid = self.sm.logMonoTime[service], self.sm.valid[service]
      outgoing_msg = {"type": service, "logMonoTime": mono_time, "valid": valid, "data": msg_dict}
      encoded_msg = json.dumps(outgoing_msg).encode()
      for channel in self.channels:
        channel.send(encoded_msg)


class CerealIncomingMessageProxy:
  def __init__(self, pm: messaging.PubMaster):
    self.pm = pm

  def send(self, message: bytes):
    msg_json = json.loads(message)
    msg_type, msg_data = msg_json["type"], msg_json["data"]
    size = None
    if not isinstance(msg_data, dict):
      size = len(msg_data)

    msg = messaging.new_message(msg_type, size=size)
    setattr(msg, msg_type, msg_data)
    self.pm.send(msg_type, msg)


class AsyncTaskRunner:
  def __init__(self):
    self.task: asyncio.Task | None = None
    self.logger = logging.getLogger("webrtcd")

  def start(self):
    if self.task is None:
      self.task = asyncio.create_task(self.run())

  async def stop(self):
    if self.task is None:
      return
    if not self.task.done():
      self.task.cancel()
      try:
        await self.task
      except asyncio.CancelledError:
        pass
    self.task = None


class IncomingAudioCerealProxy(AsyncTaskRunner):
  def __init__(self, track: Any):
    super().__init__()
    from av.audio.resampler import AudioResampler
    from openpilot.selfdrive.ui.soundd import SAMPLE_RATE as SOUND_SAMPLE_RATE
    from openpilot.system.webrtc.device.audio import WEBRTC_AUDIO_SERVICE

    self.track = track
    self.service = WEBRTC_AUDIO_SERVICE
    self.pm = messaging.PubMaster([self.service])
    self.resampler = AudioResampler(format="s16", layout="mono", rate=SOUND_SAMPLE_RATE)

  def _publish(self, frame: Any) -> None:
    data = frame.to_ndarray().tobytes()
    if not data:
      return

    msg = messaging.new_message(self.service, valid=True)
    msg.webrtcAudioData.data = data
    msg.webrtcAudioData.sampleRate = frame.sample_rate
    self.pm.send(self.service, msg)

  async def run(self):
    from aiortc.mediastreams import MediaStreamError

    while True:
      try:
        frame = await self.track.recv()
        for resampled_frame in self.resampler.resample(frame):
          self._publish(resampled_frame)
      except MediaStreamError:
        break
      except Exception:
        self.logger.exception("Incoming audio cereal proxy failure")
        await asyncio.sleep(0.1)


class CerealProxyRunner:
  def __init__(self, proxy: CerealOutgoingMessageProxy):
    self.proxy = proxy
    self.is_running = False
    self.task = None
    self.logger = logging.getLogger("webrtcd")

  def start(self):
    assert self.task is None
    self.task = asyncio.create_task(self.run())

  def stop(self):
    if self.task is None or self.task.done():
      return
    self.task.cancel()
    self.task = None

  async def run(self):
    from aiortc.exceptions import InvalidStateError

    while True:
      try:
        self.proxy.update()
      except InvalidStateError:
        self.logger.warning("Cereal outgoing proxy invalid state (connection closed)")
        break
      except Exception:
        self.logger.exception("Cereal outgoing proxy failure")
      await asyncio.sleep(0.01)


class LivestreamBitrateController:
  """Adaptive bitrate for the livestream encoder using browser REMB feedback."""

  # Match comma's rung choices more closely. A steadier capped stream tends to look better than
  # an occasionally-higher bitrate stream that induces queueing, jitter, and frame pacing swings.
  bitrates = [500_000, 1_500_000, int(os.environ.get("STREAM_BITRATE", 5_000_000))]
  label_to_bitrate = {"low": bitrates[0], "med": bitrates[1], "high": bitrates[-1]}

  sample_interval = 1.0
  lower_factor = 0.9
  probe_after = 10
  settle_samples = 3

  def __init__(self, peer_connection: Any):
    self.pc = peer_connection
    self.params = Params()
    self.task: asyncio.Task | None = None

    # Start conservative and probe UP only when REMB proves headroom. Previously this started at
    # the top rung (5 Mbps); with no REMB feedback (e.g. transport-cc-only receivers, or a flaky
    # uplink that never delivers RTCP), _bandwidth_estimate() returns None and run() hits
    # `if estimate is None: continue` — so the level never moves and the encoder stays pinned at
    # 5 Mbps, flooding a marginal cellular uplink until webrtcd's send buffer balloons and trips the
    # device's lowMemory soft-disable. The med rung is carriable on typical cellular; healthy links
    # with working REMB still probe up to high within ~probe_after seconds.
    self.level = min(1, len(self.bitrates) - 1)
    self.stable = 0
    self.settle = 0
    self._auto = True
    self.current_bitrate = self.bitrates[self.level]
    self._publish(self.bitrates[self.level])

  def start(self):
    if self.task is None:
      self.task = asyncio.create_task(self.run())

  def stop(self):
    if self.task is not None and not self.task.done():
      self.task.cancel()
    self.task = None

  async def run(self):
    while True:
      await asyncio.sleep(self.sample_interval)
      if not self._auto:
        continue
      estimate = self._bandwidth_estimate()
      if estimate is None:
        continue

      if self.settle > 0:
        self.settle -= 1
        continue

      if estimate < self.bitrates[self.level] * self.lower_factor:
        while self.level > 0 and estimate < self.bitrates[self.level] * self.lower_factor:
          self.level -= 1
        self.stable = 0
        self._publish(self.bitrates[self.level])
      elif self.level < len(self.bitrates) - 1:
        self.stable += 1
        if self.stable >= self.probe_after:
          self.level += 1
          self.stable = 0
          self.settle = self.settle_samples
          self._publish(self.bitrates[self.level])
      else:
        self.stable = 0

  def _bandwidth_estimate(self) -> int | None:
    estimate = None
    for sender in self.pc.getSenders():
      bitrate = getattr(sender, "_remb_bitrate", None)
      if bitrate is not None:
        estimate = bitrate if estimate is None else min(estimate, bitrate)
    return estimate

  def set_quality(self, quality: str):
    if quality in self.label_to_bitrate:
      self._auto = False
      self._publish(self.label_to_bitrate[quality])
    elif quality == "auto":
      self._auto = True

  def _publish(self, bitrate: int):
    # Param is registered as INT — must pass a Python int, not str. Passing str throws
    # TypeError in Params.put (type mismatch) and crashes StreamSession.__init__ → HTTP 500.
    self.current_bitrate = int(bitrate)
    self.params.put("LivestreamEncoderBitrate", int(bitrate))


class DynamicPubMaster(messaging.PubMaster):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.lock = asyncio.Lock()

  async def add_services_if_needed(self, services):
    async with self.lock:
      for service in services:
        if service not in self.sock:
          self.sock[service] = messaging.pub_sock(service)


class StreamSession:
  shared_pub_master = DynamicPubMaster([])

  def __init__(self, sdp: str, cameras: list[str], incoming_services: list[str], outgoing_services: list[str],
               ice_servers: list[dict[str, Any]] | None = None, debug_mode: bool = False, ui_stream: bool = False):
    from aiortc.mediastreams import VideoStreamTrack, AudioStreamTrack
    from openpilot.system.webrtc.device.video import LiveStreamVideoStreamTrack
    from openpilot.system.webrtc.device.audio import AudioInputStreamTrack
    from teleoprtc import WebRTCAnswerBuilder
    from teleoprtc.info import parse_info_from_offer

    config = parse_info_from_offer(sdp)
    builder = WebRTCAnswerBuilder(sdp, ice_servers=ice_servers or [])

    assert len(cameras) == config.n_expected_camera_tracks, "Incoming stream has misconfigured number of video tracks"
    self.video_tracks: list[LiveStreamVideoStreamTrack] = []
    for cam in cameras:
      track = LiveStreamVideoStreamTrack(cam) if not debug_mode else VideoStreamTrack()
      if isinstance(track, LiveStreamVideoStreamTrack):
        self.video_tracks.append(track)
      builder.add_video_stream(cam, track)
    # Audio init may fail if openpilot is using the audio subsystem - skip gracefully
    if config.expected_audio_track:
      try:
        self.audio_input_track = AudioInputStreamTrack() if not debug_mode else AudioStreamTrack()
        builder.add_audio_stream(self.audio_input_track)
        self.audio_send_enabled = True
      except Exception as e:
        logging.warning(f"Could not init audio input (audio in use?): {e}")
    if config.incoming_audio_track:
      builder.offer_to_receive_audio_stream()

    self.stream = builder.stream()
    self.identifier = str(uuid.uuid4())

    self.incoming_bridge: CerealIncomingMessageProxy | None = None
    self.incoming_bridge_services = incoming_services
    self.outgoing_bridge: CerealOutgoingMessageProxy | None = None
    self.outgoing_bridge_runner: CerealProxyRunner | None = None
    if len(incoming_services) > 0:
      self.incoming_bridge = CerealIncomingMessageProxy(self.shared_pub_master)
    if len(outgoing_services) > 0:
      self.outgoing_bridge = CerealOutgoingMessageProxy(messaging.SubMaster(outgoing_services))
      self.outgoing_bridge_runner = CerealProxyRunner(self.outgoing_bridge)

    self.ui_stream_requested = ui_stream
    self.ui_stream_runner: CerealProxyRunner | None = None

    self.incoming_audio_proxy: IncomingAudioCerealProxy | None = None
    self.audio_input_track: AudioInputStreamTrack | AudioStreamTrack | None = None
    self.audio_send_enabled = False
    self.audio_recv_requested = bool(config.incoming_audio_track)
    self.audio_send_requested = bool(config.expected_audio_track)
    self.run_task: asyncio.Task | None = None
    # Adaptive bitrate controller for the livestream encoder (no-op in debug mode).
    self.bitrate_controller: LivestreamBitrateController | None = None
    if not debug_mode and len(self.video_tracks) > 0:
      self.bitrate_controller = LivestreamBitrateController(self.stream.peer_connection)
    self.logger = logging.getLogger("webrtcd")
    self.logger.info("New stream session (%s), cameras %s, audio in %s out %s, incoming services %s, outgoing services %s",
                      self.identifier, cameras, config.incoming_audio_track, config.expected_audio_track, incoming_services, outgoing_services)

  def start(self):
    self.run_task = asyncio.create_task(self.run())

  async def stop_async(self):
    if self.run_task is not None and not self.run_task.done():
      self.run_task.cancel()
      try:
        await self.run_task
      except asyncio.CancelledError:
        pass
      except Exception:
        self.logger.exception("Stream session stop task failure")
    self.run_task = None
    await self.post_run_cleanup()

  def stop(self):
    # Backwards-compatible sync wrapper. Prefer `await stop_async()` from async contexts.
    try:
      loop = asyncio.get_running_loop()
      # If we're already in an event loop, schedule async shutdown and return.
      loop.create_task(self.stop_async())
      return
    except RuntimeError:
      pass
    asyncio.run(self.stop_async())

  async def get_answer(self):
    return await self.stream.start()

  async def message_handler(self, message: bytes):
    # Control messages are handled in-process and don't require an incoming cereal bridge.
    try:
      payload = json.loads(message) if isinstance(message, (bytes, str)) else None
    except (ValueError, TypeError):
      payload = None
    if isinstance(payload, dict) and payload.get("type") == "timingSei":
      enabled = bool(payload.get("enabled", False))
      for track in self.video_tracks:
        track.timing_sei_enabled = enabled
      self.logger.info("timing SEI %s", "enabled" if enabled else "disabled")
      return
    if isinstance(payload, dict) and payload.get("type") == "setQuality":
      if self.bitrate_controller is not None:
        quality = str(payload.get("quality", "auto"))
        self.bitrate_controller.set_quality(quality)
        self.logger.info("livestream quality set to %s", quality)
      return
    if isinstance(payload, dict) and payload.get("type") == "setAudioEnabled":
      enabled = bool(payload.get("enabled", True))
      if hasattr(self.audio_input_track, "enable"):
        self.audio_input_track.enable(enabled)
      self.audio_send_enabled = enabled
      self.logger.info("livestream audio send %s", "enabled" if enabled else "disabled")
      return
    if isinstance(payload, dict) and payload.get("type") == "setUiStream":
      enabled = bool(payload.get("enabled", False))
      self.set_ui_stream(enabled)
      self.logger.info("ui stream %s", "enabled" if enabled else "disabled")
      return
    if isinstance(payload, dict) and payload.get("type") == "switchCamera":
      camera = str(payload.get("camera", ""))
      # Single-track model: repoint the (one) video track at the requested camera.
      for track in self.video_tracks:
        track.switch_camera(camera)
      return

    if self.incoming_bridge is None:
      return
    try:
      self.incoming_bridge.send(message)
    except Exception:
      self.logger.exception("Cereal incoming proxy failure")

  def set_ui_stream(self, enabled: bool):
    if enabled:
      if self.ui_stream_runner is not None or not self.stream.has_messaging_channel():
        return
      from openpilot.system.webrtc.ui_stream import UIStreamMessageProxy
      bitrate_getter = None
      if self.bitrate_controller is not None:
        controller = self.bitrate_controller

        def bitrate_getter():
          return controller.current_bitrate
      proxy = UIStreamMessageProxy(bitrate_getter=bitrate_getter)
      proxy.add_channel(self.stream.get_messaging_channel())
      self.ui_stream_runner = CerealProxyRunner(proxy)
      self.ui_stream_runner.start()
    elif self.ui_stream_runner is not None:
      self.ui_stream_runner.stop()
      self.ui_stream_runner = None

  async def add_ice_candidate(self, cand: Any):
    """Add a trickled ICE candidate from the client to the live peer connection."""
    if not isinstance(cand, dict):
      return
    cand_str = cand.get("candidate") or ""
    if not cand_str:
      return  # end-of-candidates marker; aiortc needs no explicit signal
    try:
      from aiortc.sdp import candidate_from_sdp
      sdp_str = cand_str.split(":", 1)[-1] if cand_str.startswith("candidate:") else cand_str
      ice = candidate_from_sdp(sdp_str)
      ice.sdpMid = cand.get("sdpMid")
      ice.sdpMLineIndex = cand.get("sdpMLineIndex")
      await self.stream.peer_connection.addIceCandidate(ice)
    except Exception:
      self.logger.exception("Failed to add ICE candidate")

  async def run(self):
    try:
      await self.stream.wait_for_connection()
      if self.stream.has_messaging_channel():
        # Always install the handler so control messages (e.g. timing SEI toggle) work
        # even when no incoming cereal bridge service was requested.
        self.stream.set_message_handler(self.message_handler)
        if self.incoming_bridge is not None:
          await self.shared_pub_master.add_services_if_needed(self.incoming_bridge_services)
        if self.outgoing_bridge_runner is not None:
          channel = self.stream.get_messaging_channel()
          self.outgoing_bridge_runner.proxy.add_channel(channel)
          self.outgoing_bridge_runner.start()
        if self.ui_stream_requested:
          self.set_ui_stream(True)
      if self.audio_recv_requested and self.stream.has_incoming_audio_track():
        track = self.stream.get_incoming_audio_track(buffered=False)
        self.incoming_audio_proxy = IncomingAudioCerealProxy(track)
        self.incoming_audio_proxy.start()
        self.logger.info("Stream session (%s) incoming audio proxy started", self.identifier)
      else:
        self.logger.info("Stream session (%s) no incoming audio track from client", self.identifier)
      if self.bitrate_controller is not None:
        self.bitrate_controller.start()
      self.logger.info(
        "Stream session (%s) audio state send_requested=%s send_enabled=%s recv_requested=%s recv_active=%s",
        self.identifier,
        self.audio_send_requested,
        self.audio_send_enabled,
        self.audio_recv_requested,
        self.incoming_audio_proxy is not None,
      )
      self.logger.info("Stream session (%s) connected", self.identifier)

      await self.stream.wait_for_disconnection()
      await self.post_run_cleanup()

      self.logger.info("Stream session (%s) ended", self.identifier)
    except Exception:
      self.logger.exception("Stream session failure")

  async def post_run_cleanup(self):
    if self.bitrate_controller is not None:
      self.bitrate_controller.stop()
    await self.stream.stop()
    if self.ui_stream_runner is not None:
      self.ui_stream_runner.stop()
      self.ui_stream_runner = None
    if self.outgoing_bridge is not None:
      self.outgoing_bridge_runner.stop()
    if self.incoming_audio_proxy is not None:
      await self.incoming_audio_proxy.stop()


def _is_retryable_stream_error(e: Exception) -> bool:
  # Transient failures seen during answer generation: SDP/candidate parse issues
  # (typically browser mDNS .local host candidates aiortc can't resolve) and
  # socket-level hiccups while gathering. Anything else is a real error.
  return isinstance(e, (ValueError, OSError))


async def _cleanup_failed_session(session: 'StreamSession | None', logger: logging.Logger) -> None:
  if session is None:
    return
  try:
    await session.stop_async()
  except Exception:
    logger.exception("Failed to clean up failed stream session")


def _strip_mdns_host_candidates(sdp: str) -> tuple[str, int]:
  lines = sdp.split("\r\n")
  kept = [line for line in lines if not (line.startswith("a=candidate:") and ".local" in line)]
  return "\r\n".join(kept), len(lines) - len(kept)


@dataclass
class StreamRequestBody:
  sdp: str
  cameras: list[str]
  bridge_services_in: list[str] = field(default_factory=list)
  bridge_services_out: list[str] = field(default_factory=list)
  iceServers: list[dict[str, Any]] = field(default_factory=list)
  ui_stream: bool = False


def _new_stream_session(offer_sdp: str, body: StreamRequestBody, debug_mode: bool):
  if Params().get_bool("Konn3ktLibdatachannelWebRTC"):
    try:
      from openpilot.system.webrtc.webrtcd_ldc import StreamSessionLibdatachannel
      return StreamSessionLibdatachannel(
        offer_sdp, body.cameras, body.bridge_services_in, body.bridge_services_out, body.iceServers, debug_mode,
        ui_stream=body.ui_stream,
      )
    except Exception:
      logging.getLogger("webrtcd").exception("libdatachannel unavailable; falling back to aiortc")
  return StreamSession(
    offer_sdp, body.cameras, body.bridge_services_in, body.bridge_services_out, body.iceServers, debug_mode,
    ui_stream=body.ui_stream,
  )


async def get_stream(request: 'web.Request'):
  stream_dict, debug_mode = request.app['streams'], request.app['debug']
  logger = logging.getLogger("webrtcd")
  session: StreamSession | None = None
  try:
    raw_body = await request.json()
    body = StreamRequestBody(**raw_body)
    offer_sdp = body.sdp

    # Single active session on the device: tear down any prior session before starting a new
    # one. webrtcd is long-lived (manager-owned), so without this, repeated offers would leak
    # sessions and contend for the same livestream topics.
    for prev in list(stream_dict.values()):
      try:
        await prev.stop_async()
      except Exception:
        logger.exception("Failed to stop previous stream session")
    stream_dict.clear()

    session = _new_stream_session(offer_sdp, body, debug_mode)
    # Creating an answer can occasionally stall (ICE gathering, codec negotiation, etc).
    # Bound it so the HTTP request doesn't hang forever and athena can surface a useful error.
    try:
      answer = await asyncio.wait_for(session.get_answer(), timeout=15.0)
    except Exception as e:
      if not _is_retryable_stream_error(e):
        raise

      logger.warning("Transient stream creation error (%s); retrying once with a fresh session", e)
      await _cleanup_failed_session(session, logger)
      retry_offer_sdp, removed_mdns = _strip_mdns_host_candidates(offer_sdp)
      if removed_mdns > 0:
        logger.info("Retrying with SDP sanitized; removed %d mDNS host ICE candidate(s)", removed_mdns)
      else:
        logger.info("Retrying with fresh session and original SDP (no mDNS host candidates removed)")

      session = _new_stream_session(retry_offer_sdp, body, debug_mode)
      answer = await asyncio.wait_for(session.get_answer(), timeout=15.0)

    session.start()

    stream_dict[session.identifier] = session

    return web.json_response({"sdp": answer.sdp, "type": answer.type})
  except TimeoutError:
    await _cleanup_failed_session(session, logger)
    logger.exception("Timed out generating WebRTC answer")
    return web.json_response({"error": "answer_timeout", "message": "Timed out generating WebRTC answer"}, status=504)
  except Exception as e:
    await _cleanup_failed_session(session, logger)
    logger.exception("Failed to create WebRTC stream session")
    return web.json_response({"error": "stream_create_failed", "message": str(e)}, status=500)


async def add_ice(request: 'web.Request'):
  stream_dict = request.app['streams']
  try:
    body = await request.json()
  except Exception:
    return web.json_response({"error": "bad_request"}, status=400)
  cand = body.get("candidate")
  # Single active session on the device; apply to whatever is live.
  for session in list(stream_dict.values()):
    await session.add_ice_candidate(cand)
  return web.json_response({"ok": True})


async def get_schema(request: 'web.Request'):
  services = request.query["services"].split(",")
  services = [s for s in services if s]
  assert all(s in log.Event.schema.fields and not s.endswith("DEPRECATED") for s in services), "Invalid service name"
  schema_dict = {s: generate_field(log.Event.schema.fields[s]) for s in services}
  return web.json_response(schema_dict)


async def on_shutdown(app: 'web.Application'):
  for session in app['streams'].values():
    await session.stop_async()
  del app['streams']


def webrtcd_thread(host: str, port: int, debug: bool):
  logging.basicConfig(level=logging.CRITICAL, handlers=[logging.StreamHandler()])
  logging_level = logging.DEBUG if debug else logging.INFO
  logging.getLogger("WebRTCStream").setLevel(logging_level)
  logging.getLogger("webrtcd").setLevel(logging_level)
  logging.getLogger("LiveStreamVideoStreamTrack").setLevel(logging_level)

  app = web.Application()

  app['streams'] = dict()
  app['debug'] = debug
  app.on_shutdown.append(on_shutdown)
  app.router.add_post("/stream", get_stream)
  app.router.add_post("/ice", add_ice)
  app.router.add_get("/schema", get_schema)

  web.run_app(app, host=host, port=port)


def main():
  parser = argparse.ArgumentParser(description="WebRTC daemon")
  parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to listen on")
  parser.add_argument("--port", type=int, default=5001, help="Port to listen on")
  parser.add_argument("--debug", action="store_true", help="Enable debug mode")
  args = parser.parse_args()

  webrtcd_thread(args.host, args.port, args.debug)


if __name__=="__main__":
  main()

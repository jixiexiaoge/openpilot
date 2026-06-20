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
from aiohttp import web
if TYPE_CHECKING:
  from aiortc.rtcdatachannel import RTCDataChannel

from openpilot.system.webrtc.schema import generate_field
from cereal import messaging, log


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
  """Adaptive bitrate for the livestream encoder.

  Samples RTCP stats periodically and steps the encoder bitrate up/down via the
  LivestreamEncoderBitrate param (read by encoderd's apply_livestream_bitrate).

  Improves on a loss-only controller: we react to packet loss AND a rising RTT trend
  (early congestion signal on cellular, before loss shows up), so we back off sooner
  and recover smoothly. Manual override via set_quality(high/med/low/auto).
  """
  # Bitrate ladder (bps). Ceiling is generous on a good link; floor keeps it watchable.
  bitrates = [400_000, 1_000_000, 2_500_000, 5_000_000, int(os.environ.get("STREAM_BITRATE", 8_000_000))]
  label_to_bitrate = {"low": bitrates[0], "med": bitrates[2], "high": bitrates[-1]}

  sample_interval = 0.2          # 5 Hz
  high_loss = 0.10               # >=10% loss: drop a level immediately
  med_loss = 0.05                # >=5% loss for down_samples: drop a level
  low_loss = 0.005               # <=0.5% loss for up_samples: raise a level
  rtt_jump_ratio = 1.5           # RTT rising >50% over baseline: treat as congestion
  down_samples = 3               # ~0.6s of sustained loss before stepping down
  up_samples = 5                 # ~1.0s of a clean link before stepping up

  def __init__(self, peer_connection: Any):
    self.pc = peer_connection
    self.params = Params()
    self.task: asyncio.Task | None = None

    self.level = 1               # start mid-low; ramp up as the link proves itself
    self.prev_lost = None
    self.prev_sent = None
    self.rtt_baseline: float | None = None
    self.down_counter = 0
    self.up_counter = 0
    self._auto = True
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
      try:
        loss_rate, rtt = await self._sample()
      except Exception:
        continue
      if loss_rate is None:
        continue

      congested = rtt is not None and self.rtt_baseline is not None and rtt > self.rtt_baseline * self.rtt_jump_ratio

      if loss_rate >= self.high_loss and self.level > 0:
        # hard congestion: drop immediately and reset the up counter
        self._step(-1)
        self.up_counter = 0
      elif (loss_rate >= self.med_loss or congested) and self.level > 0:
        self.down_counter += 1
        self.up_counter = 0
        if self.down_counter >= self.down_samples:
          self._step(-1)
      elif loss_rate <= self.low_loss and not congested and self.level < len(self.bitrates) - 1:
        self.up_counter += 1
        self.down_counter = 0
        if self.up_counter >= self.up_samples:
          self._step(+1)
      else:
        self.down_counter = 0
        self.up_counter = 0

  def _step(self, delta: int):
    new_level = max(0, min(len(self.bitrates) - 1, self.level + delta))
    if new_level == self.level:
      return
    self.level = new_level
    self.down_counter = 0
    self.up_counter = 0
    self._publish(self.bitrates[self.level])

  async def _sample(self):
    report = await self.pc.getStats()
    packets_lost = packets_sent = 0
    rtt = None
    for s in report.values():
      if s.type == "remote-inbound-rtp":
        packets_lost += getattr(s, "packetsLost", 0) or 0
        rtt = getattr(s, "roundTripTime", None)
      elif s.type == "outbound-rtp":
        packets_sent += getattr(s, "packetsSent", 0) or 0

    if rtt is not None:
      self.rtt_baseline = rtt if self.rtt_baseline is None else min(self.rtt_baseline * 1.05, max(self.rtt_baseline * 0.9, rtt))

    if self.prev_lost is None:
      self.prev_lost, self.prev_sent = packets_lost, packets_sent
      return None, rtt
    lost_delta = max(0, packets_lost - self.prev_lost)
    sent_delta = max(0, packets_sent - self.prev_sent)
    self.prev_lost, self.prev_sent = packets_lost, packets_sent
    loss_rate = lost_delta / sent_delta if sent_delta else 0.0
    return loss_rate, rtt

  def set_quality(self, quality: str):
    if quality in self.label_to_bitrate:
      self._auto = False
      self._publish(self.label_to_bitrate[quality])
    elif quality == "auto":
      self._auto = True

  def _publish(self, bitrate: int):
    # Param is registered as INT — must pass a Python int, not str. Passing str throws
    # TypeError in Params.put (type mismatch) and crashes StreamSession.__init__ → HTTP 500.
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
               ice_servers: list[dict[str, Any]] | None = None, debug_mode: bool = False):
    from aiortc.mediastreams import VideoStreamTrack, AudioStreamTrack
    from aiortc.contrib.media import MediaBlackhole
    from openpilot.system.webrtc.device.video import LiveStreamVideoStreamTrack
    from openpilot.system.webrtc.device.audio import AudioInputStreamTrack, AudioOutputSpeaker
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
        builder.add_audio_stream(AudioInputStreamTrack() if not debug_mode else AudioStreamTrack())
      except Exception as e:
        logging.warning(f"Could not init audio input (audio in use?): {e}")
    if config.incoming_audio_track:
      try:
        self.audio_output_cls = AudioOutputSpeaker if not debug_mode else MediaBlackhole
        builder.offer_to_receive_audio_stream()
      except Exception as e:
        logging.warning(f"Could not init audio output: {e}")

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

    self.audio_output: AudioOutputSpeaker | MediaBlackhole | None = None
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
      if self.stream.has_incoming_audio_track():
        track = self.stream.get_incoming_audio_track(buffered=False)
        self.audio_output = self.audio_output_cls()
        self.audio_output.addTrack(track)
        self.audio_output.start()
      if self.bitrate_controller is not None:
        self.bitrate_controller.start()
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
    if self.outgoing_bridge is not None:
      self.outgoing_bridge_runner.stop()
    if self.audio_output:
      self.audio_output.stop()


@dataclass
class StreamRequestBody:
  sdp: str
  cameras: list[str]
  bridge_services_in: list[str] = field(default_factory=list)
  bridge_services_out: list[str] = field(default_factory=list)
  iceServers: list[dict[str, Any]] = field(default_factory=list)


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

    session = StreamSession(offer_sdp, body.cameras, body.bridge_services_in, body.bridge_services_out, body.iceServers, debug_mode)
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

      session = StreamSession(retry_offer_sdp, body.cameras, body.bridge_services_in, body.bridge_services_out, body.iceServers, debug_mode)
      answer = await asyncio.wait_for(session.get_answer(), timeout=15.0)

    session.start()

    stream_dict[session.identifier] = session

    return web.json_response({"sdp": answer.sdp, "type": answer.type})
  except asyncio.TimeoutError:
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

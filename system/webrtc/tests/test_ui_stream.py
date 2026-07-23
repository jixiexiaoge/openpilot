import json
import math

from cereal import log, messaging
from openpilot.system.webrtc.ui_stream import (
  UI_STREAM_SERVICES,
  UIStreamMessageProxy,
  compute_ui_status,
  frame_to_str,
  MAX_BUFFERED_BYTES,
)

OpenpilotState = log.SelfdriveState.OpenpilotState


def make_readers(**overrides):
  readers = {}
  for service in UI_STREAM_SERVICES:
    if service == "onroadEvents":
      msg = messaging.new_message(service, 0)
    else:
      msg = messaging.new_message(service)
    readers[service] = msg
  readers.update(overrides)
  return {s: getattr(m, s) for s, m in readers.items()}


class FakeSubMaster:
  def __init__(self, readers, updated=None, valid=None):
    self.readers = readers
    self.updated = updated or dict.fromkeys(UI_STREAM_SERVICES, True)
    self.valid = valid or dict.fromkeys(UI_STREAM_SERVICES, True)
    self.logMonoTime = dict.fromkeys(UI_STREAM_SERVICES, 42)
    self.update_calls = 0

  def __getitem__(self, service):
    return self.readers[service]

  def update(self, timeout):
    self.update_calls += 1


class FakeChannel:
  def __init__(self, buffered_amount=0):
    self.bufferedAmount = buffered_amount
    self.sent = []

  def send(self, data):
    self.sent.append(data)


def make_proxy(sm, **kwargs):
  return UIStreamMessageProxy(sm=sm, **kwargs)


class TestComputeUiStatus:
  def _msgs(self):
    ss = messaging.new_message("selfdriveState")
    iq = messaging.new_message("iqState")
    ev = messaging.new_message("onroadEvents", 0)
    return ss.selfdriveState, iq.iqState, ev.onroadEvents

  def test_disengaged(self):
    ss, iq, ev = self._msgs()
    assert compute_ui_status(ss, iq, ev) == "disengaged"

  def test_engaged_no_guidance(self):
    ss, iq, ev = self._msgs()
    ss.enabled = True
    assert compute_ui_status(ss, iq, ev) == "engaged"

  def test_pre_enabled_is_override(self):
    ss, iq, ev = self._msgs()
    ss.state = OpenpilotState.preEnabled
    assert compute_ui_status(ss, iq, ev) == "override"

  def test_lat_only(self):
    ss, iq, ev = self._msgs()
    iq.aol.available = True
    iq.aol.enabled = True
    assert compute_ui_status(ss, iq, ev) == "lat_only"

  def test_long_only(self):
    ss, iq, ev = self._msgs()
    ss.enabled = True
    iq.aol.available = True
    assert compute_ui_status(ss, iq, ev) == "long_only"

  def test_both_engaged(self):
    ss, iq, ev = self._msgs()
    ss.enabled = True
    iq.aol.available = True
    iq.aol.enabled = True
    assert compute_ui_status(ss, iq, ev) == "engaged"


class TestUIStreamFrame:
  def test_frame_shape_and_json(self):
    model_msg = messaging.new_message("modelV2")
    model = model_msg.modelV2
    model.position.x = [float(i) for i in range(33)]
    model.position.y = [0.123456] * 33
    model.position.z = [0.0] * 33
    model.init("laneLines", 4)
    for lane in model.laneLines:
      lane.x = [1.0, 2.0]
      lane.y = [0.1, 0.2]
      lane.z = [0.0, 0.0]
    model.laneLineProbs = [0.9, 0.8, 0.7, 0.6]
    model.init("roadEdges", 2)
    for edge in model.roadEdges:
      edge.x = [1.0]
      edge.y = [2.0]
      edge.z = [0.0]
    model.roadEdgeStds = [0.1, 0.2]
    model.acceleration.x = [0.5] * 33

    cs_msg = messaging.new_message("carState")
    cs_msg.carState.vEgo = 12.345
    cs_msg.carState.leftBlinker = True

    readers = make_readers(modelV2=model_msg, carState=cs_msg)
    sm = FakeSubMaster(readers)
    proxy = make_proxy(sm)
    channel = FakeChannel()
    proxy.add_channel(channel)

    proxy.update()

    assert len(channel.sent) == 1
    frame = json.loads(channel.sent[0])
    assert frame["type"] == "uiStream"
    data = frame["data"]
    assert len(data["modelV2"]["position"]["x"]) == 33
    assert data["modelV2"]["position"]["y"][0] == 0.12
    assert len(data["modelV2"]["laneLines"]) == 4
    assert data["carState"]["vEgo"] == 12.35
    assert data["carState"]["leftBlinker"] is True
    assert data["uiStatus"] == "disengaged"
    assert data["selfdriveState"]["alertSize"] == "none"
    assert "hasLongitudinalControl" in data["init"]
    assert "cameraOffset" in data["init"]
    assert "isMetric" in data["init"]

  def test_nan_scrubbed(self):
    model_msg = messaging.new_message("modelV2")
    model_msg.modelV2.position.x = [math.nan, math.inf, 1.0]

    readers = make_readers(modelV2=model_msg)
    sm = FakeSubMaster(readers)
    proxy = make_proxy(sm)
    channel = FakeChannel()
    proxy.add_channel(channel)

    proxy.update()

    raw = channel.sent[0]
    assert "NaN" not in raw and "Infinity" not in raw
    frame = json.loads(raw)
    assert frame["data"]["modelV2"]["position"]["x"] == [0.0, 0.0, 1.0]

  def test_backpressure_drops_frames(self):
    readers = make_readers()
    sm = FakeSubMaster(readers)
    proxy = make_proxy(sm)
    channel = FakeChannel(buffered_amount=MAX_BUFFERED_BYTES + 1)
    proxy.add_channel(channel)

    proxy.update()

    assert channel.sent == []
    assert proxy.dropped_frames == 1

  def test_no_send_without_model_update(self):
    readers = make_readers()
    updated = dict.fromkeys(UI_STREAM_SERVICES, False)
    sm = FakeSubMaster(readers, updated=updated)
    proxy = make_proxy(sm)
    proxy._last_emit_time = float("inf")
    channel = FakeChannel()
    proxy.add_channel(channel)

    proxy.update()

    assert channel.sent == []
    assert sm.update_calls == 1

  def test_heartbeat_without_model_update(self):
    readers = make_readers()
    updated = dict.fromkeys(UI_STREAM_SERVICES, False)
    sm = FakeSubMaster(readers, updated=updated)
    proxy = make_proxy(sm)
    channel = FakeChannel()
    proxy.add_channel(channel)

    proxy.update()

    assert len(channel.sent) == 1
    frame = json.loads(channel.sent[0])
    assert frame["data"]["modelV2"] is None

  def test_low_bandwidth_decimation(self):
    readers = make_readers()
    sm = FakeSubMaster(readers)
    proxy = make_proxy(sm, bitrate_getter=lambda: 500_000)
    channel = FakeChannel()
    proxy.add_channel(channel)

    for _ in range(4):
      proxy.update()

    assert len(channel.sent) == 2

  def test_full_rate_at_high_bitrate(self):
    readers = make_readers()
    sm = FakeSubMaster(readers)
    proxy = make_proxy(sm, bitrate_getter=lambda: 5_000_000)
    channel = FakeChannel()
    proxy.add_channel(channel)

    for _ in range(4):
      proxy.update()

    assert len(channel.sent) == 4

  def test_sticky_status_when_engaged_like(self):
    ss_msg = messaging.new_message("selfdriveState")
    ss_msg.selfdriveState.enabled = True
    iq_msg = messaging.new_message("iqState")
    iq_msg.iqState.aol.available = True
    iq_msg.iqState.aol.enabled = True

    readers = make_readers(selfdriveState=ss_msg, iqState=iq_msg)
    sm = FakeSubMaster(readers)
    proxy = make_proxy(sm)
    channel = FakeChannel()
    proxy.add_channel(channel)
    proxy.update()
    assert json.loads(channel.sent[-1])["data"]["uiStatus"] == "engaged"

    iq_msg.iqState.aol.available = False
    proxy.update()
    assert json.loads(channel.sent[-1])["data"]["uiStatus"] == "engaged"

  def test_frame_size_budget(self):
    model_msg = messaging.new_message("modelV2")
    model = model_msg.modelV2
    model.position.x = [float(i) * 3.03 for i in range(33)]
    model.position.y = [1.234567] * 33
    model.position.z = [0.456789] * 33
    model.init("laneLines", 4)
    for lane in model.laneLines:
      lane.x = [float(i) * 3.03 for i in range(33)]
      lane.y = [1.234567] * 33
      lane.z = [0.456789] * 33
    model.laneLineProbs = [0.9] * 4
    model.init("roadEdges", 2)
    for edge in model.roadEdges:
      edge.x = [float(i) * 3.03 for i in range(33)]
      edge.y = [1.234567] * 33
      edge.z = [0.456789] * 33
    model.acceleration.x = [1.23] * 33

    readers = make_readers(modelV2=model_msg)
    sm = FakeSubMaster(readers)
    proxy = make_proxy(sm)
    frame = proxy._build_frame()
    encoded = frame_to_str(frame)
    assert len(encoded) < 8 * 1024


class TestSessionWiring:
  def test_set_ui_stream_control_message(self):
    import asyncio
    import logging
    from types import SimpleNamespace
    from openpilot.system.webrtc.webrtcd import StreamSession

    session = StreamSession.__new__(StreamSession)
    session.logger = logging.getLogger("webrtcd")
    session.ui_stream_runner = None
    session.bitrate_controller = None
    session.incoming_bridge = None
    channel = FakeChannel()
    session.stream = SimpleNamespace(
      has_messaging_channel=lambda: True,
      get_messaging_channel=lambda: channel,
    )

    async def go():
      await session.message_handler(b'{"type":"setUiStream","enabled":true}')
      assert session.ui_stream_runner is not None
      await asyncio.sleep(0.05)
      await session.message_handler(b'{"type":"setUiStream","enabled":false}')
      assert session.ui_stream_runner is None

    asyncio.run(go())

    assert len(channel.sent) >= 1
    frame = json.loads(channel.sent[0])
    assert frame["type"] == "uiStream"

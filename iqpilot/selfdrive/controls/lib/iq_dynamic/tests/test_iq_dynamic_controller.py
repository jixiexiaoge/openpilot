import pytest

from openpilot.iqpilot.selfdrive.controls.lib.iq_dynamic.engine import IQDynamicController

class MockLeadOne:
  def __init__(self, status=0.0):
    self.status = status

class MockRadarState:
  def __init__(self, status=0.0):
    self.leadOne = MockLeadOne(status=status)

class MockCarState:
  def __init__(self, vEgo=0.0, vCruise=0.0, standstill=False):
    self.vEgo = vEgo
    self.vCruise = vCruise
    self.standstill = standstill

class MockModelData:
  def __init__(self, valid=True, horizon_x=0.0, should_stop=False):
    size = 33 if valid else 10
    self.position = type("Pos", (), {"x": [0.0] * size})()
    self.orientation = type("Ori", (), {"x": [0.0] * size})()
    self.action = type("Action", (), {"shouldStop": should_stop})()
    if valid:
      self.position.x[-1] = horizon_x

class MockSelfDriveState:
  def __init__(self, experimentalMode=False):
    self.experimentalMode = experimentalMode

class MockParams:
  def get_bool(self, name):
    return True

  def get(self, name):
    defaults = {
      "IQDynamicConditionalSpeed": 18.0,
      "IQDynamicConditionalLeadSpeed": 24.0,
      "IQDynamicModelStopTime": 3.0,
    }
    return defaults.get(name)

@pytest.fixture
def default_sm():
  sm = {
    'carState': MockCarState(vEgo=10.0, vCruise=20.0),
    'radarState': MockRadarState(status=1.0),
    'modelV2': MockModelData(valid=True),
    'selfdriveState': MockSelfDriveState(experimentalMode=True),
  }
  return sm

@pytest.fixture
def mock_cp():
  class CP:
    radarUnavailable = False
  return CP()

@pytest.fixture
def mock_mpc():
  class MPC:
    crash_cnt = 0
  return MPC()

def test_initial_mode_is_acc(mock_cp, mock_mpc):
  controller = IQDynamicController(mock_cp, mock_mpc, params=MockParams())
  controller.aeb_c = 0
  assert controller.mode() == "acc"

def test_standstill_triggers_blended(mock_cp, mock_mpc, default_sm):
  controller = IQDynamicController(mock_cp, mock_mpc, params=MockParams())
  controller.aeb_c = 0
  default_sm['carState'].standstill = True
  for _ in range(10):
    controller.update(default_sm)
  assert controller.mode() == "blended"

def test_emergency_blended_on_fcw(mock_cp, mock_mpc, default_sm):
  controller = IQDynamicController(mock_cp, mock_mpc, params=MockParams())
  controller.aeb_c = 1
  for _ in range(2):
    controller.update(default_sm)
  assert controller.mode() == "blended"

def test_radarless_slowdown_triggers_blended(mock_cp, mock_mpc, default_sm):
  mock_cp.radarUnavailable = True
  controller = IQDynamicController(mock_cp, mock_mpc, params=MockParams())
  controller.aeb_c = 0
  default_sm['modelV2'] = MockModelData(valid=True, horizon_x=0.0)
  controller.update(default_sm)

  assert controller.mode() == "blended"


def test_model_stop_triggers_blended(mock_cp, mock_mpc, default_sm):
  controller = IQDynamicController(mock_cp, mock_mpc, params=MockParams())
  controller.aeb_c = 0
  default_sm['radarState'] = MockRadarState(status=0.0)
  default_sm['modelV2'] = MockModelData(valid=True, horizon_x=5.0, should_stop=True)
  controller.update(default_sm)

  assert controller.stop_light_detected
  assert controller.mode() == "blended"

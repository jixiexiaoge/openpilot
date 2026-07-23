from cereal import car
from cereal import messaging
from cereal.messaging import SubMaster, PubMaster
from openpilot.selfdrive.ui.soundd import SELFDRIVE_STATE_TIMEOUT, check_selfdrive_timeout_alert
from openpilot.selfdrive.ui.soundd import get_sound_list

import pytest
import time

AudibleAlert = car.CarControl.HUDControl.AudibleAlert


class TestSoundd:
  @pytest.mark.parametrize("device_type", ["mici", "tici", "tizi"])
  def test_prompt_distracted_sound(self, device_type):
    assert get_sound_list(device_type)[AudibleAlert.promptDistracted][0] == "prompt_distracted.wav"

  def test_check_selfdrive_timeout_alert(self):
    sm = SubMaster(['selfdriveState'])
    pm = PubMaster(['selfdriveState'])

    for _ in range(100):
      cs = messaging.new_message('selfdriveState')
      cs.selfdriveState.enabled = True

      pm.send("selfdriveState", cs)

      time.sleep(0.01)

      sm.update(0)

      assert not check_selfdrive_timeout_alert(sm)

    for _ in range(SELFDRIVE_STATE_TIMEOUT * 110):
      sm.update(0)
      time.sleep(0.01)

    assert check_selfdrive_timeout_alert(sm)

  # TODO: add test with micd for checking that soundd actually outputs sounds

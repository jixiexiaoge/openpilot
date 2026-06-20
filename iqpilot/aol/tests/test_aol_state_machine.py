"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import pytest
from pytest_mock import MockerFixture

from cereal import custom
from openpilot.common.realtime import DT_CTRL
from openpilot.iqpilot.aol.engine import AolStateMachine, SOFT_DISABLE_TIME
from openpilot.selfdrive.selfdrived.events import ET, NormalPermanentAlert, Events
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents, EVENTS_IQ

State = custom.AlwaysOnLateral.AlwaysOnLateralState
EventNameIQ = custom.IQOnroadEvent.EventName

# The event types that maintain the current state
MAINTAIN_STATES = {State.enabled: (None,), State.disabled: (None,), State.softDisabling: (ET.SOFT_DISABLE,),
                   State.paused: (None,), State.overriding: (ET.OVERRIDE_LATERAL,)}
ALL_STATES = (State.schema.enumerants.values())
# The event types checked in DISABLED section of state machine
ENABLE_EVENT_TYPES = (ET.ENABLE, ET.OVERRIDE_LATERAL)


def make_event(event_types):
  event = {}
  for ev in event_types:
    event[ev] = NormalPermanentAlert("alert")
  EVENTS_IQ[0] = event
  return 0


class MockAOL:
  def __init__(self, mocker: MockerFixture):
    self.selfdrive = mocker.MagicMock()
    self.selfdrive.state_machine = mocker.MagicMock()
    self.selfdrive.events = Events()
    self.selfdrive.events_iq = IQEvents()


class TestAOLStateMachine:
  @pytest.fixture(autouse=True)
  def setup_method(self, mocker: MockerFixture):
    self.aol = MockAOL(mocker)
    self.state_machine = AolStateMachine(self.aol)
    self.events = self.aol.selfdrive.events
    self.events_iq = self.aol.selfdrive.events_iq
    self.aol.selfdrive.state_machine.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)

  def clear_events(self):
    self.events.clear()
    self.events_iq.clear()

  def test_immediate_disable(self):
    for state in ALL_STATES:
      for et in MAINTAIN_STATES[state]:
        self.events_iq.add(make_event([et, ET.IMMEDIATE_DISABLE]))
        self.state_machine.state = state
        self.state_machine.update()
        assert State.disabled == self.state_machine.state
        self.clear_events()

  def test_user_disable(self):
    for state in ALL_STATES:
      for et in MAINTAIN_STATES[state]:
        self.events_iq.add(make_event([et, ET.USER_DISABLE]))
        self.state_machine.state = state
        self.state_machine.update()
        assert State.disabled == self.state_machine.state
        self.clear_events()

  def test_user_disable_to_paused(self):
    paused_events = (EventNameIQ.silentLkasDisable, )
    for state in ALL_STATES:
      for et in MAINTAIN_STATES[state]:
        self.events_iq.add(make_event([et, ET.USER_DISABLE]))
        for en in paused_events:
          self.events_iq.add(en)
          self.state_machine.state = state
          self.state_machine.update()
          final_state = State.paused if self.events_iq.has(en) and state != State.disabled else State.disabled
          assert self.state_machine.state == final_state
          self.clear_events()

  def test_soft_disable(self):
    for state in ALL_STATES:
      for et in MAINTAIN_STATES[state]:
        self.events_iq.add(make_event([et, ET.SOFT_DISABLE]))
        self.state_machine.state = state
        self.state_machine.update()
        assert self.state_machine.state == State.disabled if state == State.disabled else State.softDisabling
        self.clear_events()

  def test_soft_disable_timer(self):
    self.state_machine.state = State.enabled
    self.events_iq.add(make_event([ET.SOFT_DISABLE]))
    self.state_machine.update()
    for _ in range(int(SOFT_DISABLE_TIME / DT_CTRL)):
      assert self.state_machine.state == State.softDisabling
      self.aol.selfdrive.state_machine.soft_disable_timer -= 1
      self.state_machine.update()

    assert self.state_machine.state == State.disabled
    self.clear_events()

  def test_no_entry(self):
    for et in ENABLE_EVENT_TYPES:
      self.events_iq.add(make_event([ET.NO_ENTRY, et]))
      self.state_machine.update()
      assert self.state_machine.state == State.disabled
      self.clear_events()

  def test_no_entry_paused(self):
    self.state_machine.state = State.paused
    self.events_iq.add(make_event([ET.NO_ENTRY]))
    self.state_machine.update()
    assert self.state_machine.state == State.paused
    self.clear_events()

  def test_override_lateral(self):
    self.state_machine.state = State.enabled
    self.events_iq.add(make_event([ET.OVERRIDE_LATERAL]))
    self.state_machine.update()
    assert self.state_machine.state == State.overriding
    self.clear_events()

  def test_paused_to_enabled(self):
    self.state_machine.state = State.paused
    self.events_iq.add(make_event([ET.ENABLE]))
    self.state_machine.update()
    assert self.state_machine.state == State.enabled
    self.clear_events()

  def test_maintain_states(self):
    for state in ALL_STATES:
      for et in MAINTAIN_STATES[state]:
        self.state_machine.state = state
        self.events_iq.add(make_event([et]))
        self.state_machine.update()
        assert self.state_machine.state == state
        self.clear_events()

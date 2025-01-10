from cereal import log
from openpilot.selfdrive.selfdrived.events import Events, ET
from openpilot.common.realtime import DT_CTRL

State = log.SelfdriveState.OpenpilotState

SOFT_DISABLE_TIME = 3  # seconds
ACTIVE_STATES = (State.enabled, State.softDisabling, State.overriding)
ENABLED_STATES = (State.preEnabled, *ACTIVE_STATES)

class StateMachine:
  def __init__(self):
    self.current_alert_types = [ET.PERMANENT]
    self.state = State.disabled
    self.soft_disable_timer = 0

  def update(self, events: Events):
    # decrement the soft disable timer at every step, as it's reset on
    # entrance in SOFT_DISABLING state
    self.soft_disable_timer = max(0, self.soft_disable_timer - 1)

    self.current_alert_types = [ET.PERMANENT]

    # ENABLED, SOFT DISABLING, PRE ENABLING, OVERRIDING
    if self.state != State.disabled:
      # user and immediate disable always have priority in a non-disabled state
      if events.contains(ET.USER_DISABLE):
        print("####ET.USER_DISABLE", events.events)
        self.state = State.disabled
        self.current_alert_types.append(ET.USER_DISABLE)

      elif events.contains(ET.IMMEDIATE_DISABLE):
        print("####ET.IMMEDIATE_DISABLE", events.events)
        self.state = State.disabled
        self.current_alert_types.append(ET.IMMEDIATE_DISABLE)

      else:
        # ENABLED
        if self.state == State.enabled:
          if events.contains(ET.SOFT_DISABLE):
            print("#######State.enabled => softDisabling", events.events)
            self.state = State.softDisabling
            self.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)
            self.current_alert_types.append(ET.SOFT_DISABLE)

          elif events.contains(ET.OVERRIDE_LATERAL) or events.contains(ET.OVERRIDE_LONGITUDINAL):
            print("#######State.enabled => overriding")
            self.state = State.overriding
            self.current_alert_types += [ET.OVERRIDE_LATERAL, ET.OVERRIDE_LONGITUDINAL]

        # SOFT DISABLING
        elif self.state == State.softDisabling:
          if not events.contains(ET.SOFT_DISABLE):
            print("#######State.softDisabling => enabled", events.events)
            # no more soft disabling condition, so go back to ENABLED
            self.state = State.enabled

          elif self.soft_disable_timer > 0:
            #print("#######State.softDisabling => timeout => disable")
            self.current_alert_types.append(ET.SOFT_DISABLE)

          elif self.soft_disable_timer <= 0:
            print("#######State.softDisabling => disabled")
            self.state = State.disabled

        # PRE ENABLING
        elif self.state == State.preEnabled:
          if not events.contains(ET.PRE_ENABLE):
            print("#######State.preEnabled => enabled", events.events)
            self.state = State.enabled
          else:
            self.current_alert_types.append(ET.PRE_ENABLE)

        # OVERRIDING
        elif self.state == State.overriding:
          if events.contains(ET.SOFT_DISABLE):
            print("#######State.overriding => softDisabling", events.events)
            self.state = State.softDisabling
            self.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)
            self.current_alert_types.append(ET.SOFT_DISABLE)
          elif not (events.contains(ET.OVERRIDE_LATERAL) or events.contains(ET.OVERRIDE_LONGITUDINAL)):
            print("#######State.overriding => enabled")
            self.state = State.enabled
          else:
            self.current_alert_types += [ET.OVERRIDE_LATERAL, ET.OVERRIDE_LONGITUDINAL]

    # DISABLED
    elif self.state == State.disabled:
      if events.contains(ET.ENABLE):
        print("####ET.ENABLE event....", events.events)
        if events.contains(ET.NO_ENTRY):
          print("######## noEntry", events.events)
          self.current_alert_types.append(ET.NO_ENTRY)

        else:
          if events.contains(ET.PRE_ENABLE):
            print("#######State.disabled => preEnabled", events.events)
            self.state = State.preEnabled
          elif events.contains(ET.OVERRIDE_LATERAL) or events.contains(ET.OVERRIDE_LONGITUDINAL):
            print("#######State.disabled => overriding")
            self.state = State.overriding
          else:
            print("#######State.disabled => enabled")
            self.state = State.enabled
          self.current_alert_types.append(ET.ENABLE)

    # Check if openpilot is engaged and actuators are enabled
    enabled = self.state in ENABLED_STATES
    active = self.state in ACTIVE_STATES
    if active:
      self.current_alert_types.append(ET.WARNING)
    return enabled, active

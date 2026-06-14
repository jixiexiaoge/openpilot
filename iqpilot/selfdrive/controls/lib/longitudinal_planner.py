"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from datetime import datetime

from cereal import messaging, custom
from opendbc.car import structs
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX
from openpilot.iqpilot.selfdrive.controls.lib.iq_dynamic.engine import IQDynamicController
from openpilot.iqpilot.selfdrive.controls.lib.iq_dynamic.imahelper import IQConstants
from openpilot.iqpilot.selfdrive.controls.lib.helpers.e2e_alerts import E2EAlertsHelper
from openpilot.iqpilot.selfdrive.controls.lib.slc_vcruise import SLCVCruise
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents
from openpilot.iqpilot.models.helpers import get_active_bundle

IQDynamicState = custom.IQPlan.IQDynamicControl.IQDynamicControlState
LongitudinalPlanSource = custom.IQPlan.LongitudinalPlanSource
SpeedLimitAssistState = custom.IQPlan.SpeedLimit.AssistState
SpeedLimitSource = custom.IQPlan.SpeedLimit.Source
NavProvider = custom.IQNavState.LongitudinalProvider
NavLongitudinalState = custom.IQNavState.LongitudinalState


class LongitudinalPlannerIQ:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams, mpc):
    self.events_iq = IQEvents()
    self.iq_dynamic = IQDynamicController(CP, mpc)
    self.slc = SLCVCruise()
    self.generation = int(model_bundle.generation) if (model_bundle := get_active_bundle()) else None
    self.source = LongitudinalPlanSource.cruise
    self.e2e_alerts_helper = E2EAlertsHelper()

    self.output_v_target = 0.
    self.output_a_target = 0.
    self.speed_limit_last = 0.
    self.speed_limit_final_last = 0.
    self.speed_limit_source = SpeedLimitSource.none
    self.nav_engaged = False
    self.nav_provider = NavProvider.none
    self.nav_state = NavLongitudinalState.disabled
    self.nav_speed_target = 0.
    self.nav_accel_target = 0.
    self.nav_valid = False
    self.force_stop_timer = 0.0
    self.forcing_stop = False
    self.override_force_stop = False
    self.override_force_stop_timer = 0.0
    self.tracked_model_length = 0.0

  def is_e2e(self, sm: messaging.SubMaster) -> bool:
    experimental_mode = sm['selfdriveState'].experimentalMode
    if not self.iq_dynamic.active():
      return experimental_mode

    return experimental_mode and self.iq_dynamic.mode() == "blended"

  def update_targets(self, sm: messaging.SubMaster, v_ego: float, a_ego: float, v_cruise: float) -> tuple[float, float]:
    CS = sm['carState']
    v_cruise_cluster_kph = min(CS.vCruiseCluster, V_CRUISE_MAX)
    v_cruise_cluster = v_cruise_cluster_kph * CV.KPH_TO_MS
    # SLC should apply whenever IQ.Pilot is engaged, even on stock-longitudinal cars
    # where carControl.longActive stays false.
    slc_apply_enabled = bool(getattr(sm['selfdriveState'], "enabled", False))

    nav_state = sm['iqNavState']
    self.nav_engaged = bool(getattr(nav_state, "longitudinalEngaged", False))
    self.nav_provider = getattr(nav_state, "longitudinalProvider", NavProvider.none)
    self.nav_state = getattr(nav_state, "longitudinalState", NavLongitudinalState.disabled)
    self.nav_speed_target = float(getattr(nav_state, "speedTarget", 0.0))
    self.nav_accel_target = float(getattr(nav_state, "accelTarget", 0.0))
    self.nav_valid = bool(getattr(nav_state, "valid", False) and self.nav_engaged)

    # IQ.Pilot custom Speed Limit Controller
    now = datetime.now()
    if hasattr(sm, "alive"):
      time_validated = sm.alive.get('clocks', False) and getattr(sm['clocks'], 'timeValid', False)
    else:
      clocks = sm.get('clocks', None) if isinstance(sm, dict) else None
      time_validated = bool(getattr(clocks, 'timeValid', False))
    slc_v_cruise = self.slc.update(slc_apply_enabled, now, time_validated, v_cruise, v_ego, sm)
    self.iq_dynamic.set_slc_experimental_mode(self.slc.slc_experimental_mode)
    self.iq_dynamic.update(sm)
    # Prefer confirmed controller output for UI/planner rendering.
    # Fall back to active (policy-resolved) target/source when confirmed is unavailable.
    display_speed_limit = self.slc.slc_target if self.slc.slc_target > 0 else self.slc.slc_active_target
    display_source = self.slc.slc_source if self.slc.slc_source != "None" else self.slc.slc_active_source

    self.speed_limit_last = display_speed_limit if display_speed_limit > 0 else self.speed_limit_last
    self.speed_limit_final_last = display_speed_limit + self.slc.slc_offset if display_speed_limit > 0 else self.speed_limit_final_last
    # Respect user-defined max cruise speed when applying SLC.
    if v_cruise_cluster > 0 and self.speed_limit_final_last > 0:
      self.speed_limit_final_last = min(self.speed_limit_final_last, v_cruise_cluster)
    source_map = {
      "Dashboard": SpeedLimitSource.car,
      "Map Data": SpeedLimitSource.map,
      "Mapbox": SpeedLimitSource.map,
      "None": SpeedLimitSource.none,
    }
    self.speed_limit_source = source_map.get(display_source, SpeedLimitSource.none)

    targets = {
      LongitudinalPlanSource.cruise: (v_cruise, a_ego),
      LongitudinalPlanSource.speedLimitAssist: (slc_v_cruise, a_ego),
    }
    if self.nav_valid:
      targets[LongitudinalPlanSource.nav] = (self.nav_speed_target, self.nav_accel_target)

    self.source = min(targets, key=lambda k: targets[k][0])
    self.output_v_target, self.output_a_target = targets[self.source]
    self.output_v_target = self._apply_force_stop(self.output_v_target, v_ego, sm, slc_apply_enabled)
    return self.output_v_target, self.output_a_target

  def update(self, sm: messaging.SubMaster) -> None:
    self.events_iq.clear()
    for event_name in getattr(self.slc, 'pending_events', []):
      self.events_iq.add(event_name)
    self.e2e_alerts_helper.update(sm, self.events_iq)
    if bool(getattr(sm["iqCarState"], "alcOverrideAlert", False)):
      self.events_iq.add(custom.IQOnroadEvent.EventName.steeringOverrideReengageAlc)

  def _apply_force_stop(self, v_target: float, v_ego: float, sm: messaging.SubMaster, apply_enabled: bool) -> float:
    force_stop = self.iq_dynamic.force_stop_requested() and apply_enabled and self.override_force_stop_timer <= 0.0
    self.force_stop_timer = self.force_stop_timer + DT_MDL if force_stop else 0.0
    force_stop_enabled = self.force_stop_timer >= 1.0

    accel_pressed = bool(getattr(sm["iqCarState"], "accelPressed", False))
    self.override_force_stop |= sm["carState"].gasPressed or accel_pressed
    self.override_force_stop &= force_stop_enabled

    if self.override_force_stop:
      self.override_force_stop_timer = 10.0
    elif self.override_force_stop_timer > 0.0:
      self.override_force_stop_timer = max(0.0, self.override_force_stop_timer - DT_MDL)
    else:
      self.override_force_stop = False

    if force_stop_enabled and not self.override_force_stop:
      self.forcing_stop = True
      self.tracked_model_length = max(self.tracked_model_length - (v_ego * DT_MDL), 0.0)
      if sm["carState"].standstill:
        return 0.0
      return min(self.tracked_model_length / IQConstants.FORCE_STOP_PLANNER_TIME, v_target)

    self.forcing_stop = False
    self.tracked_model_length = max(self.iq_dynamic.model_length, 0.0)
    return v_target

  def _apply_force_stop(self, v_target: float, v_ego: float, sm: messaging.SubMaster, apply_enabled: bool) -> float:
    force_stop = self.iq_dynamic.force_stop_requested() and apply_enabled and self.override_force_stop_timer <= 0.0
    self.force_stop_timer = self.force_stop_timer + DT_MDL if force_stop else 0.0
    force_stop_enabled = self.force_stop_timer >= 1.0
    force_stop_ramp_time = max(float(getattr(self.iq_dynamic, "model_stop_time", IQConstants.FORCE_STOP_PLANNER_TIME)), DT_MDL)

    accel_pressed = bool(getattr(sm["iqCarState"], "accelPressed", False))
    self.override_force_stop |= sm["carState"].gasPressed or accel_pressed
    self.override_force_stop &= force_stop_enabled

    if self.override_force_stop:
      self.override_force_stop_timer = 10.0
    elif self.override_force_stop_timer > 0.0:
      self.override_force_stop_timer = max(0.0, self.override_force_stop_timer - DT_MDL)
    else:
      self.override_force_stop = False

    if force_stop_enabled and not self.override_force_stop:
      self.forcing_stop = True
      self.tracked_model_length = max(self.tracked_model_length - (v_ego * DT_MDL), 0.0)
      if sm["carState"].standstill:
        return 0.0
      return min(self.tracked_model_length / force_stop_ramp_time, v_target)

    self.forcing_stop = False
    self.tracked_model_length = max(
      float(getattr(self.iq_dynamic, "model_length", 0.0)),
      float(getattr(self.iq_dynamic, "minimum_force_stop_length", 0.0)),
      0.0,
    )
    return v_target

  def publish_longitudinal_plan_iq(self, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    def fill_plan(plan_msg) -> None:
      plan_msg.longitudinalPlanSource = self.source
      plan_msg.vTarget = float(self.output_v_target)
      plan_msg.aTarget = float(self.output_a_target)
      plan_msg.events = self.events_iq.to_msg()

      # IQ.Dynamic control state
      iq_dynamic = plan_msg.iqDynamic
      iq_dynamic.state = IQDynamicState.blended if self.iq_dynamic.mode() == 'blended' else IQDynamicState.acc
      iq_dynamic.enabled = self.iq_dynamic.enabled()
      iq_dynamic.active = self.iq_dynamic.active()

      nav_summary = plan_msg.iqNavState.nav
      nav_summary.engaged = self.nav_engaged
      nav_summary.provider = self.nav_provider
      nav_summary.state = self.nav_state
      nav_summary.speedTarget = float(self.nav_speed_target)
      nav_summary.accelTarget = float(self.nav_accel_target)
      nav_summary.valid = self.nav_valid

      # Speed Limit
      speedLimit = plan_msg.speedLimit
      resolver = speedLimit.resolver
      speed_limit = float(self.slc.slc_target if self.slc.slc_target > 0 else self.slc.slc_active_target)
      speed_limit_offset = float(self.slc.slc_offset)
      speed_limit_final = speed_limit + speed_limit_offset if speed_limit > 0 else 0.
      speed_limit_valid = speed_limit > 0.
      speed_limit_last_valid = self.speed_limit_last > 0.

      resolver.speedLimit = speed_limit
      resolver.speedLimitLast = float(self.speed_limit_last)
      resolver.speedLimitFinal = float(speed_limit_final)
      resolver.speedLimitFinalLast = float(self.speed_limit_final_last)
      resolver.speedLimitValid = speed_limit_valid
      resolver.speedLimitLastValid = speed_limit_last_valid
      resolver.speedLimitOffset = speed_limit_offset
      resolver.distToSpeedLimit = 0.
      resolver.source = self.speed_limit_source

      assist = speedLimit.assist
      slc_assist_state = self.slc.assist_state
      assist.enabled = bool(self.slc.slc_target > 0 or self.slc.slc_unconfirmed > 0)
      assist.active = self.source == LongitudinalPlanSource.speedLimitAssist and self.slc.slc_target > 0
      if slc_assist_state is not None:
        assist.state = slc_assist_state
      elif not assist.enabled:
        assist.state = SpeedLimitAssistState.disabled
      elif self.slc.slc_unconfirmed > 0:
        assist.state = SpeedLimitAssistState.preActive
      elif assist.active:
        assist.state = SpeedLimitAssistState.active
      else:
        assist.state = SpeedLimitAssistState.inactive
      assist.vTarget = float(self.output_v_target if assist.active else 255.)
      assist.aTarget = float(self.slc.slc_a_target if assist.active else 0.)

      # E2E Alerts
      e2eAlerts = plan_msg.e2eAlerts
      e2eAlerts.greenLightAlert = self.e2e_alerts_helper.queue_alert
      e2eAlerts.leadDepartAlert = self.e2e_alerts_helper.lead_alert

    valid = sm.all_checks(service_list=['carState', 'controlsState'])

    plan_iq_send = messaging.new_message('iqPlan')
    plan_iq_send.valid = valid
    fill_plan(plan_iq_send.iqPlan)
    pm.send('iqPlan', plan_iq_send)

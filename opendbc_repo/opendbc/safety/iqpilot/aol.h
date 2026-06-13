/*
 * Copyright © IQ.Lvbs, a part of Project Teal Lvbs.
 * All Rights Reserved.
 * Licensed under: https://konn3kt.com/tos
 */

#pragma once

#include "opendbc/safety/iqpilot/aol_declarations.h"

// ===============================
// Global Variables
// ===============================

ButtonState aol_button_press = AOL_BUTTON_UNAVAILABLE;
AOLState m_aol_state;

// state for aol controls_allowed_lat timeout logic
bool heartbeat_engaged_aol = false;  // AOL enabled, passed in heartbeat USB command
uint32_t heartbeat_engaged_aol_mismatches = 0U;  // count of mismatches between heartbeat_engaged_aol and controls_allowed_lat

// ===============================
// State Update Helpers
// ===============================

inline EdgeTransition m_get_edge_transition(const bool current, const bool last) {
  EdgeTransition state;

  if (current && !last) {
    state = AOL_EDGE_RISING;
  } else if (!current && last) {
    state = AOL_EDGE_FALLING;
  } else {
    state = AOL_EDGE_NO_CHANGE;
  }

  return state;
}

inline void m_aol_state_init(void) {
  m_aol_state.is_vehicle_moving = NULL;
  m_aol_state.acc_main.current = NULL;
  m_aol_state.aol_button.current = AOL_BUTTON_UNAVAILABLE;

  m_aol_state.system_enabled = false;
  m_aol_state.disengage_lateral_on_brake = false;
  m_aol_state.pause_lateral_on_brake = false;

  m_aol_state.acc_main.previous = false;
  m_aol_state.acc_main.transition = AOL_EDGE_NO_CHANGE;

  m_aol_state.aol_button.last = AOL_BUTTON_UNAVAILABLE;
  m_aol_state.aol_button.transition = AOL_EDGE_NO_CHANGE;


  m_aol_state.current_disengage.active_reason = AOL_DISENGAGE_REASON_NONE;
  m_aol_state.current_disengage.pending_reasons = AOL_DISENGAGE_REASON_NONE;

  m_aol_state.controls_requested_lat = false;
  m_aol_state.controls_allowed_lat = false;
}

inline void m_update_button_state(ButtonStateTracking *button_state) {
  if (button_state->current != AOL_BUTTON_UNAVAILABLE) {
    button_state->transition = m_get_edge_transition(button_state->current == AOL_BUTTON_PRESSED, button_state->last == AOL_BUTTON_PRESSED);
    button_state->last = button_state->current;
  }
}

inline void m_update_binary_state(BinaryStateTracking *state) {
  state->transition = m_get_edge_transition(state->current, state->previous);
  state->previous = state->current;
}

/**
 * @brief Updates the AOL control state based on current system conditions
 *
 * @return void
 */
inline void m_update_control_state(void) {
  bool allowed = true;

  // Initial control requests from button or ACC transitions
  if ((m_aol_state.acc_main.transition == AOL_EDGE_RISING) ||
      (m_aol_state.aol_button.transition == AOL_EDGE_RISING) ||
      (m_aol_state.op_controls_allowed.transition == AOL_EDGE_RISING)) {
    m_aol_state.controls_requested_lat = true;
  }

  // Primary control blockers - these prevent any further control processing
  if (m_aol_state.acc_main.transition == AOL_EDGE_FALLING) {
    aol_exit_controls(AOL_DISENGAGE_REASON_ACC_MAIN_OFF);
    allowed = false;  // No matter what, no further control processing on this cycle
  }

  if (m_aol_state.aol_steering_disengage.transition == AOL_EDGE_RISING) {
    aol_exit_controls(AOL_DISENGAGE_REASON_STEERING_DISENGAGE);
    allowed = false;  // No matter what, no further control processing on this cycle
  }

  if (m_aol_state.disengage_lateral_on_brake && (m_aol_state.braking.transition == AOL_EDGE_RISING)) {
    aol_exit_controls(AOL_DISENGAGE_REASON_BRAKE);
    allowed = false;
  }

  // Secondary control conditions - only checked if primary conditions don't block further control processing
  if (allowed && m_aol_state.pause_lateral_on_brake) {
    // Brake rising edge immediately blocks controls
    // Brake release might request controls if brake was the ONLY reason for disengagement
    if (m_aol_state.braking.transition == AOL_EDGE_RISING) {
      aol_exit_controls(AOL_DISENGAGE_REASON_BRAKE);
      allowed = false;
    } else if ((m_aol_state.braking.transition == AOL_EDGE_FALLING) &&
               (m_aol_state.current_disengage.active_reason == AOL_DISENGAGE_REASON_BRAKE) &&
               (m_aol_state.current_disengage.pending_reasons == AOL_DISENGAGE_REASON_BRAKE)) {
      m_aol_state.controls_requested_lat = true;
    } else if (m_aol_state.braking.current) {
      allowed = false;
    } else {
    }
  }

  // Process control request if conditions allow
  if (allowed && m_aol_state.controls_requested_lat && !m_aol_state.controls_allowed_lat) {
    m_aol_state.controls_requested_lat = false;
    m_aol_state.controls_allowed_lat = true;
    m_aol_state.current_disengage.active_reason = AOL_DISENGAGE_REASON_NONE;
    m_aol_state.current_disengage.pending_reasons = AOL_DISENGAGE_REASON_NONE;
  }
}

inline void aol_heartbeat_engaged_check(void) {
  if (m_aol_state.controls_allowed_lat && !heartbeat_engaged_aol) {
    heartbeat_engaged_aol_mismatches += 1U;
    if (heartbeat_engaged_aol_mismatches >= 3U) {
      aol_exit_controls(AOL_DISENGAGE_REASON_HEARTBEAT_ENGAGED_MISMATCH);
    }
  } else {
    heartbeat_engaged_aol_mismatches = 0U;
  }
}

// ===============================
// Function Implementations
// ===============================

inline void aol_set_alternative_experience(const int *mode) {
  const bool aol_enabled = (*mode & ALT_EXP_ENABLE_AOL) != 0;
  const bool disengage_lateral_on_brake = (*mode & ALT_EXP_AOL_DISENGAGE_LATERAL_ON_BRAKE) != 0;
  const bool pause_lateral_on_brake = (*mode & ALT_EXP_AOL_PAUSE_LATERAL_ON_BRAKE) != 0;

  aol_set_system_state(aol_enabled, disengage_lateral_on_brake, pause_lateral_on_brake);
}

extern inline void aol_set_system_state(const bool enabled, const bool disengage_lateral_on_brake, const bool pause_lateral_on_brake) {
  m_aol_state_init();
  m_aol_state.system_enabled = enabled;
  m_aol_state.disengage_lateral_on_brake = disengage_lateral_on_brake;
  m_aol_state.pause_lateral_on_brake = pause_lateral_on_brake;
}

inline void aol_exit_controls(const DisengageReason reason) {
  // Always track this as a pending reason
  m_aol_state.current_disengage.pending_reasons |= reason;

  if (m_aol_state.controls_allowed_lat) {
    m_aol_state.current_disengage.active_reason = reason;
    m_aol_state.controls_requested_lat = false;
    m_aol_state.controls_allowed_lat = false;
  }
}

inline bool aol_is_lateral_control_allowed_by_aol(void) {
  return m_aol_state.system_enabled && m_aol_state.controls_allowed_lat;
}

inline void aol_state_update(const bool op_vehicle_moving, const bool op_acc_main, const bool op_allowed, const bool is_braking, const bool _steering_disengage) {
  m_aol_state.is_vehicle_moving = op_vehicle_moving;
  m_aol_state.acc_main.current = op_acc_main;
  m_aol_state.op_controls_allowed.current = op_allowed;
  m_aol_state.aol_button.current = aol_button_press;
  m_aol_state.braking.current = is_braking;
  m_aol_state.aol_steering_disengage.current = _steering_disengage;

  m_update_binary_state(&m_aol_state.acc_main);
  m_update_binary_state(&m_aol_state.op_controls_allowed);
  m_update_binary_state(&m_aol_state.braking);
  m_update_binary_state(&m_aol_state.aol_steering_disengage);
  m_update_button_state(&m_aol_state.aol_button);

  m_update_control_state();
}

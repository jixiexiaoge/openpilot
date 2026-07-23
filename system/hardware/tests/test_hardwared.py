from types import SimpleNamespace

from openpilot.system.hardware.hardwared import (
  ALLOWED_TICI_BRANCHES,
  CAN_STARTUP_RECOVERY_COOLDOWN,
  CAN_STARTUP_RECOVERY_DELAY,
  CAN_STARTUP_RECOVERY_MAX_ATTEMPTS,
  CanStartupRecovery,
  is_supported_tici_branch,
)


def test_beta_pq_allowed_for_tici():
  metadata = SimpleNamespace(channel="beta-pq", channel_type="dev")
  assert "beta-pq" in ALLOWED_TICI_BRANCHES
  assert is_supported_tici_branch(metadata)


def test_tici_channel_type_allowed():
  metadata = SimpleNamespace(channel="random-branch", channel_type="tici")
  assert is_supported_tici_branch(metadata)


def test_unsupported_branch_rejected_for_tici():
  metadata = SimpleNamespace(channel="random-branch", channel_type="dev")
  assert not is_supported_tici_branch(metadata)


def recovery_update(recovery: CanStartupRecovery, now: float, **kwargs) -> bool:
  defaults = {
    "ignition": True,
    "started": True,
    "engaged": False,
    "car_state_alive": True,
    "can_timeout": True,
    "v_ego": 0.,
  }
  return recovery.update(now, **(defaults | kwargs))


def test_can_startup_recovery_requires_persistent_timeout():
  recovery = CanStartupRecovery()
  assert not recovery_update(recovery, 10.)
  assert not recovery_update(recovery, 10. + CAN_STARTUP_RECOVERY_DELAY - 0.1)
  assert recovery_update(recovery, 10. + CAN_STARTUP_RECOVERY_DELAY)


def test_can_startup_recovery_only_when_safe():
  for unsafe_state in (
    {"started": False},
    {"engaged": True},
    {"car_state_alive": False},
    {"can_timeout": False},
    {"v_ego": 0.2},
  ):
    recovery = CanStartupRecovery()
    assert not recovery_update(recovery, 10., **unsafe_state)
    assert not recovery_update(recovery, 10. + CAN_STARTUP_RECOVERY_DELAY, **unsafe_state)


def test_can_startup_recovery_is_bounded_and_resets_next_ignition():
  recovery = CanStartupRecovery()
  now = 10.
  for _ in range(CAN_STARTUP_RECOVERY_MAX_ATTEMPTS):
    assert not recovery_update(recovery, now)
    now += CAN_STARTUP_RECOVERY_DELAY
    assert recovery_update(recovery, now)
    now += CAN_STARTUP_RECOVERY_COOLDOWN

  assert not recovery_update(recovery, now)
  assert not recovery_update(recovery, now + CAN_STARTUP_RECOVERY_DELAY)

  assert not recovery_update(recovery, now + 10., ignition=False)
  assert not recovery_update(recovery, now + 11.)
  assert recovery_update(recovery, now + 11. + CAN_STARTUP_RECOVERY_DELAY)

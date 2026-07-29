from collections import deque

from openpilot.system.ui.lib.scroll_panel2 import weighted_velocity


def test_weighted_velocity_empty():
  assert weighted_velocity(deque()) == 0.0


def test_weighted_velocity_single():
  assert weighted_velocity(deque([120.0])) == 120.0


def test_weighted_velocity_two_samples():
  assert weighted_velocity(deque([100.0, 200.0])) == 130.0


def test_weighted_velocity_three_samples_biases_older():
  velocity = weighted_velocity(deque([300.0, 180.0, 20.0]))
  assert velocity == 244.0

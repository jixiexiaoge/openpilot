#!/usr/bin/env python3
import argparse
import os
import signal
import socket
import struct
import threading
import time

import numpy as np
from inputs import UnpluggedError, get_gamepad

from cereal import messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.system.hardware import HARDWARE
from openpilot.tools.lib.kbhit import KBHit

REMOTE_PORT_DEFAULT = 8765
REMOTE_TIMEOUT_S = 0.25
REMOTE_PUBLISH_HZ = 30
LOCAL_PUBLISH_HZ = 100


class Keyboard:
  def __init__(self):
    self.kb = KBHit()
    self.axis_increment = 0.05  # 5% of full actuation each key press
    self.axes_map = {'w': 'gb', 's': 'gb',
                     'a': 'steer', 'd': 'steer'}
    self.axes_values = {'gb': 0., 'steer': 0.}
    self.axes_order = ['gb', 'steer']
    self.cancel = False
    self.idle_sleep_s = 0.0

  def update(self):
    key = self.kb.getch().lower()
    self.cancel = False
    if key == 'r':
      self.axes_values = dict.fromkeys(self.axes_values, 0.)
    elif key == 'c':
      self.cancel = True
    elif key in self.axes_map:
      axis = self.axes_map[key]
      incr = self.axis_increment if key in ['w', 'a'] else -self.axis_increment
      self.axes_values[axis] = float(np.clip(self.axes_values[axis] + incr, -1, 1))
    else:
      return False
    return True

  def get_buttons(self):
    return [False, self.cancel]


class Joystick:
  def __init__(self):
    # This class supports a PlayStation 5 DualSense controller on the comma 3X
    # Using both analog sticks: left stick Y for gas/brake, right stick X for steering
    self.cancel_button = 'BTN_NORTH'  # BTN_NORTH=X/triangle
    if HARDWARE.get_device_type() == 'pc':
      accel_axis = 'ABS_Y'      # Left stick Y-axis
      steer_axis = 'ABS_RX'     # Right stick X-axis
      self.flip_map = {}         # No flipping needed
    else:
      accel_axis = 'ABS_Y'      # Left stick Y-axis
      steer_axis = 'ABS_Z'      # Right stick X-axis
      self.flip_map = {}         # No flipping needed

    self.min_axis_value = {accel_axis: 0., steer_axis: 0.}
    self.max_axis_value = {accel_axis: 255., steer_axis: 255.}
    self.axes_values = {accel_axis: 0., steer_axis: 0.}
    self.axes_order = [accel_axis, steer_axis]
    self.cancel = False
    self.idle_sleep_s = 0.0

  def update(self):
    try:
      joystick_event = get_gamepad()[0]
    except (OSError, UnpluggedError):
      self.axes_values = dict.fromkeys(self.axes_values, 0.)
      return False

    event = (joystick_event.code, joystick_event.state)

    # flip left trigger to negative accel
    if event[0] in self.flip_map:
      event = (self.flip_map[event[0]], -event[1])

    if event[0] == self.cancel_button:
      if event[1] == 1:
        self.cancel = True
      elif event[1] == 0:   # state 0 is falling edge
        self.cancel = False
    elif event[0] in self.axes_values:
      self.max_axis_value[event[0]] = max(event[1], self.max_axis_value[event[0]])
      self.min_axis_value[event[0]] = min(event[1], self.min_axis_value[event[0]])

      norm = -float(np.interp(event[1], [self.min_axis_value[event[0]], self.max_axis_value[event[0]]], [-1., 1.]))
      norm = norm if abs(norm) > 0.03 else 0.  # center can be noisy, deadzone of 3%
      self.axes_values[event[0]] = norm
    else:
      return False
    return True

  def get_buttons(self):
    return [False, self.cancel]


class RemoteJoystick:
  def __init__(self, host: str, port: int):
    self.addr = (host, port)
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.socket.bind(self.addr)
    self.socket.settimeout(0.1)

    self.axes_values = {'gb': 0.0, 'steer': 0.0}
    self.axes_order = ['gb', 'steer']
    self.buttons = [False, False]
    self.last_update = 0.0
    self.authenticated = False
    self.client_addr = None
    self.idle_sleep_s = 0.01

  def _clamp(self, value: float) -> float:
    return float(np.clip(value, -1.0, 1.0))

  def _handle_timeout(self, now: float) -> None:
    if self.authenticated and (now - self.last_update) > REMOTE_TIMEOUT_S:
      self.axes_values = {'gb': 0.0, 'steer': 0.0}
      self.buttons = [False, False]

  def _send_auth_ok(self, addr) -> None:
    try:
      self.socket.sendto(bytes([1]), addr)
    except OSError:
      pass

  def update(self):
    now = time.monotonic()
    try:
      data, addr = self.socket.recvfrom(64)
    except socket.timeout:
      self._handle_timeout(now)
      return False
    except OSError:
      return False

    if not data:
      return False

    msg_type = data[0]
    if msg_type == 0:
      self.client_addr = addr
      self.authenticated = True
      self._send_auth_ok(addr)
      return True

    if msg_type == 2:
      try:
        payload = data[1:].decode("utf-8", errors="strict").strip()
        steer_s, accel_s, engage_s, disengage_s = payload.split(",", 3)
        steer = float(steer_s)
        accel = float(accel_s)
        engage = engage_s == "1"
        disengage = disengage_s == "1"
      except (UnicodeDecodeError, ValueError):
        return False

      self.axes_values['steer'] = self._clamp(steer)
      self.axes_values['gb'] = self._clamp(accel)
      self.buttons = [engage, disengage]
      self.last_update = now
      return True

    if msg_type != 1 or len(data) < 9:
      return False

    steer, accel = struct.unpack_from("<ff", data, 1)
    engage = bool(data[9]) if len(data) > 9 else False
    disengage = bool(data[10]) if len(data) > 10 else False

    self.axes_values['steer'] = self._clamp(steer)
    self.axes_values['gb'] = self._clamp(accel)
    self.buttons = [engage, disengage]
    self.last_update = now
    return True

  def get_buttons(self):
    return self.buttons


def send_thread(joystick, show_values: bool):
  pm = messaging.PubMaster(['testJoystick'])

  publish_hz = REMOTE_PUBLISH_HZ if isinstance(joystick, RemoteJoystick) else LOCAL_PUBLISH_HZ
  rk = Ratekeeper(publish_hz, print_delay_threshold=None)

  while True:
    if show_values and rk.frame % 20 == 0:
      print('\n' + ', '.join(f'{name}: {round(v, 3)}' for name, v in joystick.axes_values.items()))

    joystick_msg = messaging.new_message('testJoystick')
    joystick_msg.valid = True
    joystick_msg.testJoystick.axes = [joystick.axes_values[ax] for ax in joystick.axes_order]
    joystick_msg.testJoystick.buttons = joystick.get_buttons()

    pm.send('testJoystick', joystick_msg)

    rk.keep_time()


def joystick_control_thread(joystick, show_values: bool):
  Params().put_bool('JoystickDebugMode', True)
  try:
    threading.Thread(target=send_thread, args=(joystick, show_values), daemon=True).start()
    while True:
      updated = joystick.update()
      if not updated and joystick.idle_sleep_s > 0:
        time.sleep(joystick.idle_sleep_s)
  finally:
    Params().put_bool('JoystickDebugMode', False)


def main():
  joystick_control_thread(Joystick(), True)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Publishes events from your joystick to control your car.\n' +
                                               'openpilot must be offroad before starting joystick_control. This tool supports ' +
                                               'a PlayStation 5 DualSense controller on the comma 3X.',
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('--keyboard', action='store_true', help='Use your keyboard instead of a joystick')
  parser.add_argument('--remote', action='store_true', help='Listen for UDP joystick input')
  parser.add_argument('--listen', type=int, default=REMOTE_PORT_DEFAULT, help='UDP port for remote joystick input')
  parser.add_argument('--listen-address', default='0.0.0.0', help='UDP address to bind for remote input')
  args = parser.parse_args()

  if not Params().get_bool("IsOffroad") and "ZMQ" not in os.environ:
    print("The car must be off before running joystick_control.")
    exit()

  if args.remote and args.keyboard:
    print("Choose only one input mode.")
    exit()

  print()
  if args.remote:
    print(f'Listening for remote joystick on {args.listen_address}:{args.listen}')
  elif args.keyboard:
    print('Gas/brake control: `W` and `S` keys')
    print('Steering control: `A` and `D` keys')
    print('Buttons')
    print('- `R`: Resets axes')
    print('- `C`: Cancel cruise control')
  else:
    print('Using joystick, make sure to run cereal/messaging/bridge on your device if running over the network!')
    print('If not running on a comma device, the mapping may need to be adjusted.')

  def handle_exit(signum, _frame):
    Params().put_bool('JoystickDebugMode', False)
    raise SystemExit

  signal.signal(signal.SIGINT, handle_exit)
  signal.signal(signal.SIGTERM, handle_exit)

  if args.remote:
    joystick = RemoteJoystick(args.listen_address, int(args.listen))
    joystick_control_thread(joystick, False)
  else:
    joystick = Keyboard() if args.keyboard else Joystick()
    joystick_control_thread(joystick, True)

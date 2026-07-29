from iqdbc.safety.tests.libsafety import libsafety_py


def packet(addr: int, bus: int, length: int, updates: dict[int, int] | None = None):
  data = bytearray(length)
  for index, value in (updates or {}).items():
    data[index] = value
  return libsafety_py.make_CANPacket(addr, bus, data)


def classic_steer(torque: int, request: bool = True):
  value = torque + 1024
  word = (value << 16) | (int(request) << 27)
  return packet(0x340, 0, 8, {i: (word >> (8 * i)) & 0xFF for i in range(4)})


def canfd_steer(addr: int, length: int, torque: int, request: bool = True):
  value = torque + 1024
  return packet(addr, 0, length, {
    5: (value & 0x7F) << 1,
    6: ((value >> 7) & 0xF) | (int(request) << 4),
  })


def classic_accel(accel: int, *, aeb_decel: int = 0, aeb_request: bool = False):
  value = accel + 1023
  return packet(0x421, 0, 8, {
    2: aeb_decel,
    3: value & 0xFF,
    4: ((value >> 8) & 0x7) | ((value & 0x7) << 5),
    5: (value >> 3) & 0xFF,
    6: int(aeb_request) << 6,
  })


def canfd_accel(accel: int, *, acc_mode: int = 0, bus: int = 0):
  value = accel + 1023
  return packet(0x1A0, bus, 32, {
    8: (acc_mode & 0x7) << 4,
    16: value & 0xFF,
    17: ((value >> 8) & 0x7) | ((value & 0xF) << 4),
    18: (value >> 4) & 0xFF,
  })


TESTER_PRESENT = bytes.fromhex("023e800000000000")

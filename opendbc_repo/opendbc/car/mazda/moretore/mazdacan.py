from openpilot.selfdrive.car.mazda.values import Buttons, MazdaFlags
from openpilot.common.numpy_fast import clip

def create_steering_control(packer, CP, frame, apply_steer, lkas):
  msgs = []
  if CP.flags & MazdaFlags.GEN1:
    if not CP.flags & MazdaFlags.NO_FSC:
      tmp = apply_steer + 2048

      lo = tmp & 0xFF
      hi = tmp >> 8

      # copy values from camera
      b1 = int(lkas["BIT_1"])
      er1 = int(lkas["ERR_BIT_1"])
      lnv = 0
      ldw = 0
      er2 = int(lkas["ERR_BIT_2"])

      # Some older models do have these, newer models don't.
      # Either way, they all work just fine if set to zero.
      steering_angle = 0
      b2 = 0

      tmp = steering_angle + 2048
      ahi = tmp >> 10
      amd = (tmp & 0x3FF) >> 2
      amd = (amd >> 4) | (( amd & 0xF) << 4)
      alo = (tmp & 0x3) << 2

      ctr = frame % 16
      # bytes:     [    1  ] [ 2 ] [             3               ]  [           4         ]
      csum = 249 - ctr - hi - lo - (lnv << 3) - er1 - (ldw << 7) - ( er2 << 4) - (b1 << 5)

      # bytes      [ 5 ] [ 6 ] [    7   ]
      csum = csum - ahi - amd - alo - b2

      if ahi == 1:
        csum = csum + 15

      if csum < 0:
        if csum < -256:
          csum = csum + 512
        else:
          csum = csum + 256

      csum = csum % 256
      values = {
        "LKAS_REQUEST": apply_steer,
        "CTR": ctr,
        "ERR_BIT_1": er1,
        "LINE_NOT_VISIBLE" : lnv,
        "LDW": ldw,
        "BIT_1": b1,
        "ERR_BIT_2": er2,
        "STEERING_ANGLE": steering_angle,
        "ANGLE_ENABLED": b2,
        "CHKSUM": csum
      }
      msgs.append(packer.make_can_msg("CAM_LKAS", 0, values))

    if CP.flags & MazdaFlags.TORQUE_INTERCEPTOR:
      values = {
          "LKAS_REQUEST"     : apply_steer,
          "CHKSUM"           : apply_steer,
          "KEY"              : 3294744160
      }
      msgs.append(packer.make_can_msg("CAM_LKAS2", 1, values))

  elif CP.flags & MazdaFlags.GEN2:
    bus = 1
    sig_name = "EPS_LKAS"
    values = {
      "LKAS_REQUEST": apply_steer,
      "STEER_FEEL": 12000,
    }
    msgs.append(packer.make_can_msg(sig_name, bus, values))

  return msgs

def create_ti_steering_control(packer, CP, apply_steer):

  key = 3294744160
  chksum = apply_steer

  if CP.flags & MazdaFlags.GEN1:
    values = {
        "LKAS_REQUEST"     : apply_steer,
        "CHKSUM"           : chksum,
        "KEY"              : key
     }
  # TODO
  # 1. Add new CAR values for MDARS Mazdas so that we can change the rate of the message. This will take some work.
  # 2. Listen for reply's on both CAN buses if not MDARS version of
  # Mazda (2021+ or m3 2019+) and warn the user if there is a bad connection
  # but do not cause disengagment

  # Write to both buses for *future* redundancy, but we only check bus 1 for a response in carstate and safey_mazda.h for now.
  # if (frame % 2 == 0):
  #  commands.append(packer.make_can_msg("CAM_LKAS2", 0, values))

  return packer.make_can_msg("CAM_LKAS2", 1, values)

def create_alert_command(packer, cam_msg: dict, ldw: bool, steer_required: bool):
  values = {s: cam_msg[s] for s in [
    "LINE_VISIBLE",
    "LINE_NOT_VISIBLE",
    "LANE_LINES",
    "BIT1",
    "BIT2",
    "BIT3",
    "NO_ERR_BIT",
    "S1",
    "S1_HBEAM",
  ]}
  values.update({
    # TODO: what's the difference between all these? do we need to send all?
    "HANDS_WARN_3_BITS": 0b111 if steer_required else 0,
    "HANDS_ON_STEER_WARN": steer_required,
    "HANDS_ON_STEER_WARN_2": steer_required,

    # TODO: right lane works, left doesn't
    # TODO: need to do something about L/R
    "LDW_WARN_LL": 0,
    "LDW_WARN_RL": 0,
  })
  return packer.make_can_msg("CAM_LANEINFO", 0, values)


def create_button_cmd(packer, CP, counter, button):

  can = int(button == Buttons.CANCEL)
  res = int(button == Buttons.RESUME)

  if CP.flags & MazdaFlags.GEN1:
    values = {
      "CAN_OFF": can,
      "CAN_OFF_INV": (can + 1) % 2,

      "SET_P": 0,
      "SET_P_INV": 1,

      "RES": res,
      "RES_INV": (res + 1) % 2,

      "SET_M": 0,
      "SET_M_INV": 1,

      "DISTANCE_LESS": 0,
      "DISTANCE_LESS_INV": 1,

      "DISTANCE_MORE": 0,
      "DISTANCE_MORE_INV": 1,

      "MODE_X": 0,
      "MODE_X_INV": 1,

      "MODE_Y": 0,
      "MODE_Y_INV": 1,

      "BIT1": 1,
      "BIT2": 1,
      "BIT3": 1,
      "CTR": (counter + 1) % 16,
    }

    return packer.make_can_msg("CRZ_BTNS", 0, values)

STATIC_DATA_21B = [0x01FFE000, 0x00000000]
STATIC_DATA_361 = [0xFFF7FEFE, 0x1FC]
STATIC_DATA_362 = [0xFFF7FEFE, 0x1FC]
STATIC_DATA_363 = [0xFFF7FEFE, 0x1FC0000]
STATIC_DATA_364 = [0xFFF7FEFE, 0x1FC0000]
STATIC_DATA_365 = [0xFFF7FE7F, 0xFBFF3FC]
STATIC_DATA_366 = [0xFFF7FE7F, 0xFBFF3FC]
static_data_list = [STATIC_DATA_361, STATIC_DATA_362, STATIC_DATA_363, STATIC_DATA_364, STATIC_DATA_365, STATIC_DATA_366]

# GEN1 radar interceptor
def create_radar_command(packer, frame, active, CS, hold):
  #accel = 0
  ret = []
  crz_ctrl = CS.crz_cntr
  crz_info = CS.crz_info

  # if CC.longActive: # this is set true in longcontrol.py
  #   accel = CC.actuators.accel * 1150
  #   accel = accel if accel < 1000 else 1000
  # else:
  #   accel = int(crz_info["ACCEL_CMD"])

  crz_info["ACC_ACTIVE"] = active
  crz_info["ACC_SET_ALLOWED"] = int(bool(int(CS.cp.vl["GEAR"]["GEAR"]) & 4)) # we can set ACC_SET_ALLOWED bit when in drive. Allows crz to be set from 1kmh.
  crz_info["CRZ_ENDED"] = 0 # this should keep acc on down to 5km/h on my 2018 M3
  #crz_info["ACCEL_CMD"] = accel
  crz_info["STOPPING_MAYBE"] = hold
  crz_info["STOPPING_MAYBE2"] = hold

  crz_ctrl["CRZ_ACTIVE"] = active
  crz_ctrl["ACC_ACTIVE_2"] = active
  crz_ctrl["DISABLE_TIMER_1"] = 0
  crz_ctrl["DISABLE_TIMER_2"] = 0

  ret.append(packer.make_can_msg("CRZ_INFO", 0, crz_info))
  ret.append(packer.make_can_msg("CRZ_CTRL", 0, crz_ctrl))
  # convert steering angle to radar units and clip to range
  steer_angle = (CS.out.steeringAngleDeg *-17.4) + 2048

  if (frame % 10 == 0):
    for i, addr in enumerate(range(361,367)):
      addr_name = f"RADAR_{addr}"
      msg = CS.cp_cam.vl[addr_name]
      values = {
        "MSGS_1" : static_data_list[i][0],
        "MSGS_2" : static_data_list[i][1],
        "CTR"    : int(msg["CTR"]) #frame % 16
      }
      if addr == 361:
        values.update({
          "INVERSE_SPEED" : int(CS.out.vEgo * -4.4),
          "BIT" : 1,
        })
      if addr == 362:
        values.update({
          "CLIPPED_STEER_ANGLE" : int(clip(steer_angle, 0, 4092)),
        })
      ret.append(packer.make_can_msg(addr_name, 0, values))

  return ret

# GEN2 new mazdas
def create_acc_cmd(self, packer, values, hold, resume):
  msg_name = "ACC"
  bus = 2

  if (values["ACC_ENABLED"]):
    values["HOLD"] = hold
    values["RESUME"] = resume
  else:
    pass

  return packer.make_can_msg(msg_name, bus, values)



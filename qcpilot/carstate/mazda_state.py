from opendbc.car.structs import QcMazdaStateT, QcMazdaState
from opendbc.can.parser import CANParser

qcMazdaState: QcMazdaStateT = QcMazdaState()
stateUpdated: bool = False


def reset_mazda_state():
  global qcMazdaState
  global stateUpdated
  qcMazdaState = QcMazdaState()
  stateUpdated = False


def update_mazda_state(cp: CANParser):
  global qcMazdaState
  global stateUpdated
  stateUpdated = True

  # CRZ = KD + KL
  # KD = ACC
  # True if ACC is ready, but not work. speed is three dots
  qcMazdaState.isCruiseAvailable = cp.vl["CRZ_CTRL"]["CRZ_AVAILABLE"] == 1
  qcMazdaState.isCruiseActive = cp.vl["CRZ_CTRL"]["CRZ_ACTIVE"] == 1
  qcMazdaState.isAccActive = cp.vl["CRZ_CTRL"]["ACC_ACTIVE"] == 1

  qcMazdaState.isLkasBlocked = cp.vl["STEER_RATE"]["LKAS_BLOCK"] == 1

  # print(f"publish message: {qcMazdaState.isCruiseAvailable}")


def get_mazda_state():
  global qcMazdaState
  global stateUpdated

  return qcMazdaState if stateUpdated else None

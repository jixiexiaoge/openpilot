from opendbc.car.toyota.values import ToyotaFlags
from opendbc.can.parser import CANParser

ANGLE_DIFF_THRESHOLD = 4.0
THRESHOLD_COUNT = 10

class ZSS:

  def __init__(self, flags: int):
    self.enabled = flags & ToyotaFlags.ZSS.value
    # self._alka_enabled = flags & ToyotaFlags.ALKA.value

    self._offset_compute_once = True
    # self._alka_active_prev = False
    self._cruise_active_prev = False
    self._offset = 0.
    self._threshold_count = 0
    self._zss_value = 0.
    self._print_allow = True

  def set_values(self, cp: CANParser):
    self._zss_value = cp.vl["SECONDARY_STEER_ANGLE"]["ZORRO_STEER"]

  def get_enabled(self):
    return self.enabled

  def get_steering_angle_deg(self, cruise_active, stock_steering_angle_deg):
    # off, fall back to stock
    if not self.enabled:
      return stock_steering_angle_deg

    # when lka control is off, use stock
    # alka_active = self._is_alka_active(main_on)
    if not cruise_active: # and not alka_active:
      return stock_steering_angle_deg

    # lka just activated
    # if not self._offset_compute_once and ((alka_active and not self._alka_active_prev) or (cruise_active and not self._cruise_active_prev)):
    if not self._offset_compute_once and (cruise_active and not self._cruise_active_prev):
      self._threshold_count = 0
      self._offset_compute_once = True
      self._print_allow = True

    # self._alka_active_prev = alka_active
    self._cruise_active_prev = cruise_active

    # compute offset when required
    if self._offset_compute_once:
      self._offset_compute_once = not self._compute_offset(stock_steering_angle_deg)

    # error checking
    if self._threshold_count >= THRESHOLD_COUNT:
      if self._print_allow:
        print("ZSS: Too many large diff, fallback to stock.")
        self._print_allow = False
      return stock_steering_angle_deg

    if self._offset_compute_once:
      print("ZSS: Compute offset required, fallback to stock.")
      return stock_steering_angle_deg

    zss_steering_angle_deg = self._zss_value - self._offset
    angle_diff = abs(stock_steering_angle_deg - zss_steering_angle_deg)
    if angle_diff > ANGLE_DIFF_THRESHOLD:
      print(f"ZSS: Diff too large ({angle_diff}), fallback to stock. ")
      # if self._is_alka_active(main_on) or cruise_active:
      if cruise_active:
        self._threshold_count += 1
      return stock_steering_angle_deg

    return zss_steering_angle_deg

  # def _is_alka_active(self, main_on):
  #   return self._alka_enabled and main_on != 0

  def _compute_offset(self, steering_angle_deg):
    if abs(steering_angle_deg) > 1e-3 and abs(self._zss_value) > 1e-3:
      self._offset = self._zss_value - steering_angle_deg
      print(f"ZSS: offset computed: {self._offset}")
      return True
    return False

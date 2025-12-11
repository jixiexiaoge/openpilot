#!/usr/bin/env python3

class Tuning:

  LAT_SIGLIN_TABLE = [4.867, 1.09, 0.243] #仅siglin模式有效

  STEERING_ANGLE_OFFSET = 0

  #Angle mode only, seal
  ANGLE_SPEED_MAX = 600 # deg
  ANGLE_SPEED_BP =   [0., 5.  , 15.]  # m/s
  ANGLE_SPEED_UP =   [5., .8  , .15]  # deg/s
  ANGLE_SPEED_DOWN = [5., 3.5 , 0.4]  # deg/s
  LKAS_MAX_TORQUE = 2.4               # Nm
  STEER_THRESHOLD = 1.0               # Nm
  MAX_STEER_ANGLE = 1310              # deg

  # modified stock long control 原车long控制的速度平滑百分比设定, 例如下面40米以内，则加速率是原来的70%，减速率是原来的100%
  K_ACCEL_BP       = [40,  50,  60,  70,  80]  # meters BP是离前车距离

  K_ACCEL_POS_4BAR = [0.8, 0.7, 0.7, 0.7, 0.7] # acceleration 加速的百分比
  K_ACCEL_NEG_4BAR = [1.0, 0.8, 0.7, 0.7, 0.7] # deceleration 减速的百分比

  K_ACCEL_POS_3BAR = [0.8, 0.7, 0.7, 0.7, 0.7] # acceleration 加速的百分比
  K_ACCEL_NEG_3BAR = [1.0, 0.9, 0.8, 0.7, 0.7] # deceleration 减速的百分比

  K_ACCEL_POS_2BAR = [0.8, 0.8, 0.7, 0.7, 0.7] # acceleration 加速的百分比
  K_ACCEL_NEG_2BAR = [1.0, 1.0, 0.9, 0.8, 0.7] # deceleration 减速的百分比

  K_ACCEL_POS_1BAR = [1.0, 1.0, 1.0, 0.9, 0.8] # acceleration 加速的百分比
  K_ACCEL_NEG_1BAR = [1.1, 1.1, 1.1, 1.0, 0.9] # deceleration 减速的百分比

  # 人为扭动方向盘的阈值，大于这个值才认为方向盘被故意扭动了，变道辅助涉及它
  STEER_PRESSED_THRESHOLD = 56

  # 禁用EPS故障检查, 某些车有EPS固件比较奇怪报错的话，则可以设为True
  DISABLE_EPS_WARNING = False
  DISABLE_EPS_TEMPORARY_FAULT = False
  DISABLE_EPS_PERMANENT_FAULT = False

  DISABLE_PARKBRAKE = False
import json
import time
import threading
import socket
import fcntl
import struct
import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.common.params import Params
from openpilot.system.hardware import PC

BLINKER_NONE = 0
BLINKER_LEFT = 1
BLINKER_RIGHT = 2
BLINKER_BOTH = 3

lock = threading.Lock()


class RadarSpeedEstimator:
  def __init__(self,
               max_points=10,
               max_acc=4.0,            # m/s²，用于距离跳变过滤 & dv/dt 限制
               smooth_alpha=0.7):      # EMA α 值（越大越平滑，0.6~0.8）
    self.max_points = max_points
    self.points = []                  # (t_ms, dist_mm)
    self.last_output_speed = None     # mm/ms
    self.max_acc = max_acc
    self.smooth_alpha = smooth_alpha  # EMA 平滑比例
    self.last_smooth_speed = None     # 平滑后的速度

  def reset(self):
    self.points.clear()
    self.last_output_speed = None
    self.last_smooth_speed = None

  def update(self, t_ms, dist_mm, has_target):
    """
    t_ms: ESP32 ms 时间戳（整数）
    dist_mm: 当前距离（毫米）
    has_target: 是否有目标
    返回速度单位：mm/ms（可以 *1000 变成 m/s）
    """

    # ───────────────────────────────
    # ① 无目标 → 直接清空
    # ───────────────────────────────
    if not has_target:
      self.reset()
      return None

    # ───────────────────────────────
    # ② 跳变过滤（按最大加速度 4 m/s²）
    # ───────────────────────────────
    if self.points:
      last_t, last_d = self.points[-1]
      dt_ms = t_ms - last_t
      if dt_ms <= 0:
        return None

      dt_s = dt_ms / 1000.0

      # 最大可能的物理距离变化：0.5 * a * t^2
      max_jump_mm = 0.5 * self.max_acc * dt_s * dt_s * 1000.0  # m→mm

      if abs(dist_mm - last_d) > max_jump_mm:
        # 说明目标切换了：重置窗口
        self.reset()
        self.points.append((t_ms, dist_mm))
        return None

    # ───────────────────────────────
    # ③ 正常加入点
    # ───────────────────────────────
    self.points.append((t_ms, dist_mm))
    if len(self.points) > self.max_points:
      self.points.pop(0)

    if len(self.points) < 3:
      return None

    # ───────────────────────────────
    # ④ 线性回归速度（基础速度）
    # ───────────────────────────────
    t0 = self.points[0][0]
    xs = [(t - t0) for (t, d) in self.points]  # ms
    ys = [d for (t, d) in self.points]         # mm

    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
      return None

    slope = (n * sum_xy - sum_x * sum_y) / denom  # mm/ms
    raw_speed = slope

    # ───────────────────────────────
    # ⑤ dv/dt 限制（速度连续性约束）
    # ───────────────────────────────
    if self.last_output_speed is not None:
      # 当前帧与上一帧的时间差
      dt_ms = self.points[-1][0] - self.points[-2][0]
      if dt_ms > 0:
        dt_s = dt_ms / 1000.0
        # dv/dt 最大允许变化（单位：mm/ms）
        max_dv_mm_ms = (self.max_acc * dt_s) / 1000.0

        if abs(raw_speed - self.last_output_speed) > max_dv_mm_ms:
          # 超过物理限制 → 不可信 → 用上一帧的
          raw_speed = self.last_output_speed

    self.last_output_speed = raw_speed

    # ───────────────────────────────
    # ⑥ EMA 平滑（最终输出）
    # ───────────────────────────────
    if self.last_smooth_speed is None:
      smooth = raw_speed
    else:
      α = self.smooth_alpha
      smooth = α * self.last_smooth_speed + (1 - α) * raw_speed

    self.last_smooth_speed = smooth
    return smooth

class SharedData:
  def __init__(self):
    #=============共享数据（来自amap_navi）=============
    #盲区信号
    self.left_blind = False #摄像头盲区信号
    self.right_blind = False
    self.lidar_lblind = False #雷达盲区信号
    self.lidar_rblind = False
    self.lf_drel = {} #雷达左前车距离
    self.lb_drel = {} #雷达左后车距离
    self.rf_drel = {} #雷达右前车距离
    self.rb_drel = {} #雷达右后车距离
    self.lf_xrel = {} #雷达左前车距离
    self.lb_xrel = {} #雷达左后车距离
    self.rf_xrel = {} #雷达右前车距离
    self.rb_xrel = {} #雷达右后车距离
    self.lidar_l = False
    self.lidar_r = False
    self.camera_l = False
    self.camera_r = False
    self.lf_vrel = None #雷达左前车相对速度
    self.lb_vrel = None #雷达左后车相对速度
    self.rf_vrel = None #雷达右前车相对速度
    self.rb_vrel = None #雷达右后车相对速度

    #客户端控制命令
    self.cmd_index = -1
    self.remote_cmd = ""
    self.remote_arg = ""

    self.ext_blinker = BLINKER_NONE # 外挂控制器转向灯状态
    self.ext_state = 0  # 外挂控制器的数量

    #=============共享数据（desire_helper）=============
    self.leftFrontBlind = None
    self.rightFrontBlind = None

    # =============共享数据（carrotMan）=============
    self.roadcate = None
    self.lat_a = None
    self.max_curve = None

    # =============共享数据（carState）=============
    self.carState = False
    self.v_ego_kph = None
    self.v_cruise_kph = None
    self.vEgo = None
    self.aEgo = None
    self.steer_angle = None
    self.gas_press = None
    self.break_press = None
    self.engaged = None
    self.left_blindspot = None
    self.right_blindspot = None

    self.showDebugLog = 0

def f1(x):
  return round(float(x), 1)

class AmapNaviServ:
  def __init__(self):
    self.shared_data = SharedData() #new
    self.params = Params()
    #self.sm = messaging.SubMaster(['carState', 'modelV2', 'selfdriveState', 'radarState', 'carrotMan'])
    self.sm = messaging.SubMaster(['modelV2', 'selfdriveState', 'radarState', 'carrotMan'])

    self.broadcast_ip = self.navi_get_broadcast_address() #广播地址
    self.broadcast_port = 4210 #广播端口
    self.listen_port = 4211 #监听地址
    self.local_ip_address = "0.0.0.0" #本地ip地址

    self.clients = {}  # 保存多个客户端
    self.clients_copy = {}
    self.active_clients = {}

    now = time.time()
    self.blinker_alive = False
    self.blinker_time = now
    self.lead_left_right = False

    self.leftFrontTarget = RadarSpeedEstimator(max_points=10)
    self.leftBehindTarget = RadarSpeedEstimator(max_points=10)
    self.rightFrontTarget = RadarSpeedEstimator(max_points=10)
    self.rightBehindTarget = RadarSpeedEstimator(max_points=10)

    threading.Thread(target=self.navi_broadcast_info).start()
    threading.Thread(target=self.navi_comm_thread).start()

  def left_blindspot(self):
    return self.shared_data.left_blind or self.shared_data.lidar_lblind
  def right_blindspot(self):
    return self.shared_data.right_blind or self.shared_data.lidar_rblind

  def _capnp_list_to_list(self, capnp_list, max_items=None):
    """将capnp列表转换为Python列表"""
    if capnp_list is None:
      return []
    try:
      result = [float(x) for x in capnp_list]
      if max_items is not None:
          return result[:max_items]
      return result
    except (TypeError, AttributeError):
      return []

  def update_navi_carstate(self, sm):
    if sm.alive['carState']:  # and self.sm.updated['carState']:
      self.shared_data.carState = True
      carState = sm['carState']
      if hasattr(carState, 'vEgoCluster'):
        self.shared_data.v_ego_kph = int(carState.vEgoCluster * 3.6 + 0.5)
      if hasattr(carState, 'vCruise'):
        self.shared_data.v_cruise_kph = carState.vCruise
      if hasattr(carState, 'vEgo'):
        self.shared_data.vEgo = int(carState.vEgo * 3.6)
      if hasattr(carState, 'aEgo'):
        self.shared_data.aEgo = round(carState.aEgo, 1)
      if hasattr(carState, 'steeringAngleDeg'):
        self.shared_data.steer_angle = round(carState.steeringAngleDeg, 1)
      if hasattr(carState, 'gasPressed'):
        self.shared_data.gas_press = carState.gasPressed
      if hasattr(carState, 'brakePressed'):
        self.shared_data.break_press = carState.brakePressed
      if hasattr(carState, 'cruiseState'):
        self.shared_data.engaged = carState.cruiseState.enabled
      # 盲区检测
      if hasattr(carState, 'leftBlindspot'):
        self.shared_data.left_blindspot = int(carState.leftBlindspot)
      if hasattr(carState, 'rightBlindspot'):
        self.shared_data.right_blindspot = int(carState.rightBlindspot)

  def navi_comm_thread(self):
    while True:
      try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
          sock.settimeout(10)  # 超时10秒
          sock.bind(('0.0.0.0', self.listen_port))
          print("#########navi_comm_thread: UDP thread started...")

          while True:
            try:
              try:
                data, remote_addr = sock.recvfrom(4096)

                if not data:
                  raise ConnectionError("No data received")

                ip, port = remote_addr
                # 修改: 保存多个客户端地址及最后活跃时间
                if not hasattr(self, "clients"):
                  self.clients = {}  # {ip: last_seen_time}

                now = time.time()

                left_blind = None
                right_blind = None
                lidar_lblind = None
                lidar_rblind = None

                lf_drel = None
                lb_drel = None
                rf_drel = None
                rb_drel = None
                lf_xrel = None
                lb_xrel = None
                rf_xrel = None
                rb_xrel = None

                lf_drel_alive = False
                lb_drel_alive = False
                rf_drel_alive = False
                rb_drel_alive = False
                lf_xrel_alive = False
                lb_xrel_alive = False
                rf_xrel_alive = False
                rb_xrel_alive = False

                camera_data = False
                lidar_data = False

                try:
                  json_obj = json.loads(data.decode())

                  #转向灯模块
                  if "blinker" in json_obj:
                    self.shared_data.ext_blinker = json_obj.get("blinker")
                    if self.shared_data.ext_blinker in ["left", "stockleft"]:
                      self.shared_data.ext_blinker = BLINKER_LEFT
                    elif self.shared_data.ext_blinker in ["right", "stockright"]:
                      self.shared_data.ext_blinker = BLINKER_RIGHT
                    else:
                      self.shared_data.ext_blinker = BLINKER_NONE
                    self.blinker_alive = True
                    self.blinker_time = time.time()

                  #客户端命令
                  if "index" in json_obj:
                    self.shared_data.cmd_index = int(json_obj.get("index"))
                  if "cmd" in json_obj:
                    self.shared_data.remote_cmd = json_obj.get("cmd")
                    self.shared_data.remote_arg = json_obj.get("arg")
                    print(f"Command: index={self.shared_data.cmd_index}, cmd={self.shared_data.remote_cmd},arg={self.shared_data.remote_arg}")

                  #响应类型
                  if "resp" in json_obj:
                    resp = json_obj.get("resp")
                    #摄像头盲区信号
                    if resp == "cam_blind":
                      camera_data = True
                      if "left_blind" in json_obj:
                        left_blind = json_obj.get("left_blind")
                        #l_blindspot_alive = True
                      if "right_blind" in json_obj:
                        right_blind = json_obj.get("right_blind")
                        #r_blindspot_alive = True

                    #雷达盲区信号和距离
                    if resp == "blindspot":
                      lidar_data = True
                      #雷达编号，0号为主雷达
                      lidar_id = int(json_obj.get("lidar_id", 0))
                      dist_timems = int(json_obj["dist_time"]) if "dist_time" in json_obj else None
                      #盲区
                      if "lidar_lblind" in json_obj:
                        lidar_lblind = json_obj.get("lidar_lblind")
                        #lidar_lblind_alive = True
                      if "lidar_rblind" in json_obj:
                        lidar_rblind = json_obj.get("lidar_rblind")
                        #lidar_rblind_alive = True
                      #距离
                      if "lf_drel" in json_obj:
                        lf_drel = int(json_obj.get("lf_drel"))
                        lf_drel_alive = True
                        #计算速度
                        if 0 == lidar_id and dist_timems is not None:
                          self.shared_data.lf_vrel = self.leftFrontTarget.update(dist_timems, lf_drel, True)
                      else:
                        if 0 == lidar_id and dist_timems is not None:
                          self.leftFrontTarget.update(dist_timems if dist_timems is not None else 0, lf_drel, False)
                      if "lb_drel" in json_obj:
                        lb_drel = int(json_obj.get("lb_drel"))
                        lb_drel_alive = True
                        #计算速度
                        if 0 == lidar_id and dist_timems is not None:
                          self.shared_data.lb_vrel = self.leftBehindTarget.update(dist_timems, lb_drel, True)
                      else:
                        if 0 == lidar_id and dist_timems is not None:
                          self.leftBehindTarget.update(dist_timems if dist_timems is not None else 0, lb_drel, False)
                      if "rf_drel" in json_obj:
                        rf_drel = int(json_obj.get("rf_drel"))
                        rf_drel_alive = True
                        #计算速度
                        if 0 == lidar_id and dist_timems is not None:
                          self.shared_data.rf_vrel = self.rightFrontTarget.update(dist_timems, rf_drel, True)
                      else:
                        if 0 == lidar_id and dist_timems is not None:
                          self.rightFrontTarget.update(dist_timems if dist_timems is not None else 0, rf_drel, False)
                      if "rb_drel" in json_obj:
                        rb_drel = int(json_obj.get("rb_drel"))
                        rb_drel_alive = True
                        #计算速度
                        if 0 == lidar_id and dist_timems is not None:
                          self.shared_data.rb_vrel = self.rightBehindTarget.update(dist_timems, rb_drel, True)
                      else:
                        if 0 == lidar_id and dist_timems is not None:
                          self.rightBehindTarget.update(dist_timems if dist_timems is not None else 0, rb_drel, False)

                      if "lf_xrel" in json_obj:
                        lf_xrel = int(json_obj.get("lf_xrel"))
                        lf_xrel_alive = True
                      if "lb_xrel" in json_obj:
                        lb_xrel = int(json_obj.get("lb_xrel"))
                        lb_xrel_alive = True
                      if "rf_xrel" in json_obj:
                        rf_xrel = int(json_obj.get("rf_xrel"))
                        rf_xrel_alive = True
                      if "rb_xrel" in json_obj:
                        rb_xrel = int(json_obj.get("rb_xrel"))
                        rb_xrel_alive = True

                  #更新客户端信息
                  old_info = self.clients.get(ip, {})

                  #检测盲区状态是否超时
                  l_blindspot_time = old_info.get("l_blindspot_time", now)
                  r_blindspot_time = old_info.get("r_blindspot_time", now)
                  lidar_lblind_time = old_info.get("lidar_lblind_time", now)
                  lidar_rblind_time = old_info.get("lidar_rblind_time", now)

                  if (now - l_blindspot_time) > 10 and left_blind is not None:
                    left_blind = False
                  if (now - r_blindspot_time) > 10 and right_blind is not None:
                    right_blind = False
                  if (now - lidar_lblind_time) > 10 and lidar_lblind is not None:
                    lidar_lblind = False
                  if (now - lidar_rblind_time) > 10 and lidar_rblind is not None:
                    lidar_rblind = False

                  #上次的距离数据时间
                  lf_drel_time = old_info.get("lf_drel_time", now)
                  lb_drel_time = old_info.get("lb_drel_time", now)
                  rf_drel_time = old_info.get("rf_drel_time", now)
                  rb_drel_time = old_info.get("rb_drel_time", now)
                  lf_xrel_time = old_info.get("lf_xrel_time", now)
                  lb_xrel_time = old_info.get("lb_xrel_time", now)
                  rf_xrel_time = old_info.get("rf_xrel_time", now)
                  rb_xrel_time = old_info.get("rb_xrel_time", now)
                  #若本次通讯无数据，加载上次的数据
                  if not lidar_data:
                    if lf_drel is None:
                      lf_drel = old_info.get("lf_drel", None)
                    if lb_drel is None:
                      lb_drel = old_info.get("lb_drel", None)
                    if rf_drel is None:
                      rf_drel = old_info.get("rf_drel", None)
                    if rb_drel is None:
                      rb_drel = old_info.get("rb_drel", None)
                    if lf_xrel is None:
                      lf_xrel = old_info.get("lf_xrel", None)
                    if lb_xrel is None:
                      lb_xrel = old_info.get("lb_xrel", None)
                    if rf_xrel is None:
                      rf_xrel = old_info.get("rf_xrel", None)
                    if rb_xrel is None:
                      rb_xrel = old_info.get("rb_xrel", None)
                  #检测距离数据是否超时
                  if (now - lf_drel_time) > 10 and lf_drel is not None:
                    lf_drel = None
                  if (now - lb_drel_time) > 10 and lb_drel is not None:
                    lb_drel = None
                  if (now - rf_drel_time) > 10 and rf_drel is not None:
                    rf_drel = None
                  if (now - rb_drel_time) > 10 and rb_drel is not None:
                    rb_drel = None
                  if (now - lf_xrel_time) > 10 and lf_xrel is not None:
                    lf_xrel = None
                  if (now - lb_xrel_time) > 10 and lb_xrel is not None:
                    lb_xrel = None
                  if (now - rf_xrel_time) > 10 and rf_xrel is not None:
                    rf_xrel = None
                  if (now - rb_xrel_time) > 10 and rb_xrel is not None:
                    rb_xrel = None

                  with lock:
                    self.clients[ip] = {
                      "last_seen": time.time(),
                      "device": json_obj.get("device", old_info.get("device", "")),
                      "detect_side":json_obj.get("detect_side", old_info.get("detect_side", 0)),
                      #盲区状态更新
                      "lidar_lblind": lidar_lblind if lidar_lblind is not None else old_info.get("lidar_lblind", False),
                      "lidar_rblind": lidar_rblind if lidar_rblind is not None else old_info.get("lidar_rblind", False),
                      "left_blind": left_blind if left_blind is not None else old_info.get("left_blind", False),
                      "right_blind": right_blind if right_blind is not None else old_info.get("right_blind", False),
                      #f雷达盲区更新时间
                      "lidar_lblind_time": now if lidar_lblind is not None else old_info.get("lidar_lblind_time", now),
                      "lidar_rblind_time": now if lidar_rblind is not None else old_info.get("lidar_rblind_time", now),
                      "l_blindspot_time": now if left_blind is not None else old_info.get("l_blindspot_time", now),
                      "r_blindspot_time": now if right_blind is not None else old_info.get("r_blindspot_time", now),
                      #雷达距离
                      "lf_drel": lf_drel,
                      "lb_drel": lb_drel,
                      "rf_drel": rf_drel,
                      "rb_drel": rb_drel,
                      "lf_xrel": lf_xrel,
                      "lb_xrel": lb_xrel,
                      "rf_xrel": rf_xrel,
                      "rb_xrel": rb_xrel,
                      # 雷达距离更新时间
                      "lf_drel_time": now if lf_drel_alive else old_info.get("lf_drel_time", now),
                      "lb_drel_time": now if lb_drel_alive else old_info.get("lb_drel_time", now),
                      "rf_drel_time": now if rf_drel_alive else old_info.get("rf_drel_time", now),
                      "rb_drel_time": now if rb_drel_alive else old_info.get("rb_drel_time", now),
                      "lf_xrel_time": now if lf_xrel_alive else old_info.get("lf_xrel_time", now),
                      "lb_xrel_time": now if lb_xrel_alive else old_info.get("lb_xrel_time", now),
                      "rf_xrel_time": now if rf_xrel_alive else old_info.get("rf_xrel_time", now),
                      "rb_xrel_time": now if rb_xrel_alive else old_info.get("rb_xrel_time", now),
                    }

                  if (self.shared_data.showDebugLog & 32) > 0:
                    print(f"receive: {json_obj}")
                except Exception as e:
                  self.shared_data.ext_blinker = BLINKER_NONE
                  if (self.shared_data.showDebugLog & 32) > 0:
                    print(f"navi_comm_thread: json error...: {e}")
                    print(data)
              except TimeoutError:
                if (self.shared_data.showDebugLog & 32) > 0:
                  print("Waiting for data (timeout)...")
              except Exception as e:
                if (self.shared_data.showDebugLog & 32) > 0:
                  print(f"navi_comm_thread: error...: {e}")
                break

              # 修改: 清理超过 10 秒未活跃的客户端
              now = time.time()
              with lock:
                self.clients = {ip: info for ip, info in self.clients.items() if now - info["last_seen"] < 10}

              #超过10秒后重启转向灯和盲区状态
              if self.blinker_alive and (now - self.blinker_time) > 10:
                self.shared_data.ext_blinker = BLINKER_NONE
                self.blinker_alive = False

              with lock:
                if self.clients:
                  self.shared_data.ext_state = len(self.clients)
                else:
                  self.shared_data.ext_state = 0
                  self.shared_data.ext_blinker = BLINKER_NONE

              self.shared_data.ext_blinker = self.shared_data.ext_blinker

            except Exception as e:
              print(f"navi_comm_thread: recv error...: {e}")
              break

          time.sleep(1)
      except Exception as e:
        print(f"Network error, retrying...: {e}")
        time.sleep(2)

  def navi_broadcast_info(self):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    frame = 0
    rk = Ratekeeper(10, print_delay_threshold=None)
    broadcast_cnt = 0

    while True:
      try:
        self.sm.update(0)
        # 修改: 获取当前活跃客户端
        #active_clients = list(getattr(self, "clients", {}).keys())
        with lock:
          self.clients_copy = getattr(self, "clients", {}).copy()
          self.active_clients = list(self.clients_copy.keys())

        if frame % 20 == 0 or self.active_clients:
          try:
            if not PC:
              ip_address = socket.gethostbyname(socket.gethostname())
            else:
              ip_address = self.navi_get_local_ip()
            if ip_address != self.local_ip_address:
              self.local_ip_address = ip_address
              self.clients_copy = {}
              with lock:
                self.clients = {}  # 修改: 本地 IP 变化时清空客户端

            lidar_l = False
            lidar_r = False
            camera_l = False
            camera_r = False
            lidar_lblind = False
            lidar_rblind = False
            left_blind = False
            right_blind = False
            now = time.time()

            #消息
            navi_msg = None
            navi_dat = None
            lidar_msg = None
            lidar_dat = None

            blinker_msg = self.make_blinker_message()
            blinker_dat = blinker_msg.encode('utf-8')

            broadcast_msg = self.make_broadcast_message()
            broadcast_dat = broadcast_msg.encode('utf-8')

            if self.active_clients:
              if self.clients_copy:
                #遍历前清空旧数据
                for field in [ "lb_drel", "rf_drel", "rb_drel","lf_xrel", "lb_xrel", "rf_xrel", "rb_xrel",]:
                  getattr(self.shared_data, field).clear()

                # 遍历所有客户端的盲区状态和更新时间
                left_lidar_id = 0
                right_lidar_id = 0
                for ip, info in self.clients_copy.items():
                  try:
                    device_type = info.get("device", None)
                    detect_side = info.get("detect_side", None)
                    if device_type == "lidar" or device_type == "camera":  # 雷达模块
                      #获取盲区状态
                      if info.get("lidar_lblind", False):
                        lidar_lblind = True
                      if info.get("lidar_rblind", False):
                        lidar_rblind = True
                      if info.get("left_blind", False):
                        left_blind = True
                      if info.get("right_blind", False):
                        right_blind = True
                      #获取雷达距离数据
                      if (detect_side & 0x01) > 0:
                        self.shared_data.lf_drel[left_lidar_id] = info.get("lf_drel", None)
                        self.shared_data.lb_drel[left_lidar_id] = info.get("lb_drel", None)
                        self.shared_data.lf_xrel[left_lidar_id] = info.get("lf_xrel", None)
                        self.shared_data.lb_xrel[left_lidar_id] = info.get("lb_xrel", None)
                        left_lidar_id += 1

                      if (detect_side & 0x02) > 0:
                        self.shared_data.rf_drel[right_lidar_id] = info.get("rf_drel", None)
                        self.shared_data.rb_drel[right_lidar_id] = info.get("rb_drel", None)
                        self.shared_data.rf_xrel[right_lidar_id] = info.get("rf_xrel", None)
                        self.shared_data.rb_xrel[right_lidar_id] = info.get("rb_xrel", None)
                        right_lidar_id += 1

                  except Exception as e:
                    if (self.shared_data.showDebugLog & 32) > 0:
                      print(f"sendto {ip} failed: {e}")

                #更新盲区状态
                self.shared_data.lidar_lblind = lidar_lblind
                self.shared_data.lidar_rblind = lidar_rblind
                self.shared_data.left_blind = left_blind
                self.shared_data.right_blind = right_blind

                # 向所有客户端发送数据
                for ip, info in self.clients_copy.items():
                  try:
                    device_type = info.get("device", None)
                    detect_side = info.get("detect_side", None)

                    # 根据 device_type 做判断
                    if device_type == "overtake" or device_type == "navi": #超车或导航
                      if navi_msg is None:
                        navi_msg = self.make_navi_message()
                        navi_dat = navi_msg.encode('utf-8')
                      if navi_dat is not None:
                        sock.sendto(navi_dat, (ip, self.broadcast_port))
                        if (self.shared_data.showDebugLog & 32) > 0:
                          print(f"sendto {ip} (overtake): {navi_dat}")
                    elif device_type == "lidar" or device_type == "camera": #雷达模块
                      if device_type == "lidar":
                        if (detect_side & 1) > 0:
                          lidar_l = True
                        if (detect_side & 2) > 0:
                          lidar_r = True
                      if device_type == "camera":
                        if (detect_side & 1) > 0:
                          camera_l = True
                        if (detect_side & 2) > 0:
                          camera_r = True

                      if lidar_msg is None:
                        lidar_msg = self.make_lidar_message()
                        lidar_dat = lidar_msg.encode('utf-8')
                      if lidar_dat is not None:
                        sock.sendto(lidar_dat, (ip, self.broadcast_port))
                        if (self.shared_data.showDebugLog & 32) > 0:
                          print(f"sendto {ip} (lidar): {lidar_dat}")
                    else: #其他
                      sock.sendto(blinker_dat, (ip, self.broadcast_port))
                      if (self.shared_data.showDebugLog & 32) > 0:
                        print(f"sendto {ip} (blinker): {blinker_dat}")
                  except Exception as e:
                    if (self.shared_data.showDebugLog & 32) > 0:
                      print(f"sendto {ip} failed: {e}")

            self.shared_data.lidar_l = lidar_l
            self.shared_data.lidar_r = lidar_r
            self.shared_data.camera_l = camera_l
            self.shared_data.camera_r = camera_r

            #每2秒广播一次自己的ip和端口
            if frame % 20 == 0:
              if self.broadcast_ip is not None and broadcast_dat is not None:
                self.broadcast_ip = self.navi_get_broadcast_address()
                sock.sendto(broadcast_dat, (self.broadcast_ip, self.broadcast_port))
                broadcast_cnt += 1
                if (self.shared_data.showDebugLog & 32) > 0:
                  print(f"broadcasting: {self.broadcast_ip}:{self.broadcast_port},{broadcast_msg}")

          except Exception as e:
            if (self.shared_data.showDebugLog & 32) > 0:
              print(f"##### navi_broadcast_error...: {e}")
            #traceback.print_exc()

        rk.keep_time()
        frame += 1
      except Exception as e:
        if (self.shared_data.showDebugLog & 32) > 0:
          print(f"navi_broadcast_info error...: {e}")
        #traceback.print_exc()
        time.sleep(1)

  def make_navi_message(self):
    msg = {}
    msg['ip'] = self.local_ip_address
    msg['port'] = self.listen_port
    isOnroad = self.params.get_bool("IsOnroad")
    msg['IsOnroad'] = isOnroad

    if isOnroad:
      #车辆状态
      if self.shared_data.carState:
        if self.shared_data.v_cruise_kph is not None:
          #msg["cruise_speed"] = self.shared_data.v_cruise_kph  # 巡航速度
          msg['v_cruise_kph'] = self.shared_data.v_cruise_kph  # 巡航速度
        if self.shared_data.v_ego_kph is not None:
          msg['v_ego_kph'] = self.shared_data.v_ego_kph  # 当前速度
        if self.shared_data.vEgo is not None:
          msg["vego"] = self.shared_data.vEgo
        if self.shared_data.aEgo is not None:
          msg["aego"] = self.shared_data.aEgo
        if self.shared_data.steer_angle is not None:
          msg["steer_angle"] = self.shared_data.steer_angle
        if self.shared_data.gas_press is not None:
          msg["gas_press"] = self.shared_data.gas_press
        if self.shared_data.break_press is not None:
          msg["break_press"] = self.shared_data.break_press
        if self.shared_data.engaged is not None:
          msg["engaged"] = self.shared_data.engaged
        # 盲区检测
        if self.shared_data.left_blindspot is not None:
          msg["left_blindspot"] = self.shared_data.left_blindspot
        if self.shared_data.right_blindspot is not None:
          msg["right_blindspot"] = self.shared_data.right_blindspot

      # 雷达数据
      if self.sm.alive['radarState']:# and self.sm.updated['radarState']:
        radar_state = self.sm['radarState']
        # 当前车道前车
        if hasattr(radar_state, 'leadOne') and radar_state.leadOne and hasattr(radar_state.leadOne,'status') and radar_state.leadOne.status:
          msg["lead1"] = True
          if hasattr(radar_state.leadOne, 'dRel'):
            msg["drel"] = int(radar_state.leadOne.dRel)
          if hasattr(radar_state.leadOne, 'vLead'):
            msg["vlead"] = int(radar_state.leadOne.vLead * 3.6)
          if hasattr(radar_state.leadOne, 'vRel'):
            msg["vrel"] = int(radar_state.leadOne.vRel * 3.6)
          if hasattr(radar_state.leadOne, 'aRel'):
            msg["lead_accel"] = radar_state.leadOne.aRel
        else:
          msg["lead1"] = False
        # 左侧前车
        if hasattr(radar_state, 'leadLeft') and radar_state.leadLeft and hasattr(radar_state.leadLeft,'status') and radar_state.leadLeft.status:
          self.lead_left_right = True
          msg["l_lead"] = True
          if hasattr(radar_state.leadLeft, 'dRel'):
            msg["l_drel"] = int(radar_state.leadLeft.dRel)
          if hasattr(radar_state.leadLeft, 'vLead'):
            msg["l_vlead"] = int(radar_state.leadLeft.vLead * 3.6)
          if hasattr(radar_state.leadLeft, 'vRel'):
            msg["l_vrel"] = int(radar_state.leadLeft.vRel * 3.6)
        else:
          msg["l_lead"] = False
        # 右侧前车
        if hasattr(radar_state, 'leadRight') and radar_state.leadRight and hasattr(radar_state.leadRight,'status') and radar_state.leadRight.status:
          self.lead_left_right = True
          msg["r_lead"] = True
          if hasattr(radar_state.leadRight, 'dRel'):
            msg["r_drel"] = int(radar_state.leadRight.dRel)
          if hasattr(radar_state.leadRight, 'vLead'):
            msg["r_vlead"] = int(radar_state.leadRight.vLead * 3.6)
          if hasattr(radar_state.leadRight, 'vRel'):
            msg["r_vrel"] = int(radar_state.leadRight.vRel * 3.6)
        else:
          msg["r_lead"] = False

      #前方激光雷达速度
      if self.shared_data.lf_vrel is not None:
        msg["lf_vrel"] = int(self.shared_data.lf_vrel * 3.6)
      if self.shared_data.rf_vrel is not None:
        msg["rf_vrel"] = int(self.shared_data.rf_vrel * 3.6)
      #后方激光雷达速度
      if self.shared_data.lb_vrel is not None:
        msg["lb_vrel"] = int(self.shared_data.lb_vrel * 3.6)
      if self.shared_data.rb_vrel is not None:
        msg["rb_vrel"] = int(self.shared_data.rb_vrel * 3.6)

      #前雷达盲区信号
      if self.shared_data.leftFrontBlind is not None:
        msg['l_front_blind'] = self.shared_data.leftFrontBlind
      if self.shared_data.rightFrontBlind is not None:
        msg['r_front_blind'] = self.shared_data.rightFrontBlind

      #雷达和摄像头盲区
      msg['lidar_lblind'] = self.left_blindspot()
      msg['lidar_rblind'] = self.right_blindspot()

      #雷达距离数据
      fields = ["lf_drel", "lb_drel", "rf_drel", "rb_drel", "lf_xrel", "lb_xrel", "rf_xrel", "rb_xrel"]
      # 找出所有 field 的所有 lidar_id
      all_lidar_ids = set()
      for f in fields:
        all_lidar_ids.update(getattr(self.shared_data, f).keys())
      # 按索引顺序遍历
      for idx in sorted(all_lidar_ids):
        for field in fields:
          d = getattr(self.shared_data, field)
          if idx in d and d[idx] is not None:
            key = field if idx == 0 else f"{field}{idx}"
            msg[key] = d[idx]

      #雷达或摄像头是否存在标志
      msg['lidar_l'] = self.shared_data.lidar_l
      msg['lidar_r'] = self.shared_data.lidar_r
      msg['camera_l'] = self.shared_data.camera_l
      msg['camera_r'] = self.shared_data.camera_r

      #来自共享数据
      if self.shared_data.roadcate is not None:
        msg['roadcate'] = self.shared_data.roadcate
      if self.shared_data.lat_a is not None:
        msg['lat_a'] = self.shared_data.lat_a
      if self.shared_data.max_curve is not None:
        msg['max_curve'] = self.shared_data.max_curve

      # carrotMan数据
      if self.sm.alive['carrotMan']:
        carrotMan = self.sm['carrotMan']
        msg["desire_speed"] = int(carrotMan.desiredSpeed)  # 期望速度
        msg['atc_type'] = carrotMan.atcType
        msg['road_name'] = carrotMan.szPosRoadName

    # 来自模型的消息
    if self.sm.alive['modelV2']:
      modelV2 = self.sm['modelV2']
      meta = modelV2.meta

      if hasattr(meta, 'blinker'):
        msg['blinker'] = meta.blinker
      if isOnroad:
        msg['l_lane_width'] = round(meta.laneWidthLeft, 1)
        msg['r_lane_width'] = round(meta.laneWidthRight, 1)
        msg['l_edge_dist'] = round(meta.distanceToRoadEdgeLeft, 1)
        msg['r_edge_dist'] = round(meta.distanceToRoadEdgeRight, 1)
        msg['atc_state'] = meta.laneChangeState.raw

        if self.shared_data.max_curve is None and hasattr(modelV2, 'orientationRate') and len(modelV2.orientationRate.z) > 0:
          orientation_rate_z = self._capnp_list_to_list(modelV2.orientationRate.z)
          if orientation_rate_z:
            # 找到最大方向变化率（表示最大曲率点）
            max_index = max(range(len(orientation_rate_z)), key=lambda i: abs(orientation_rate_z[i]))
            max_orientation_rate = orientation_rate_z[max_index]
            #curvature_value = float(max_orientation_rate)
            #curvature_direction = 1 if max_orientation_rate > 0 else -1
            msg['max_curve'] = f1(max_orientation_rate)

        # 如果字段存在才赋值
        if self.shared_data.leftFrontBlind is None and hasattr(meta, 'leftFrontBlind'):
          msg['l_front_blind'] = meta.leftFrontBlind
        if self.shared_data.rightFrontBlind is None and hasattr(meta, 'rightFrontBlind'):
          msg['r_front_blind'] = meta.rightFrontBlind

    #来自selfdriveState消息
    if self.sm.alive['selfdriveState']:
      selfdrive = self.sm['selfdriveState']
      msg['active'] = True if selfdrive.active else False

      # 若 engaged 不存在或为 False，且 active 为 True，则设置 engaged = True
      if selfdrive.active and not msg.get('engaged', False):
        msg['engaged'] = True

    return json.dumps(msg)

  def make_lidar_message(self):
    msg = {}
    msg['ip'] = self.local_ip_address
    msg['port'] = self.listen_port
    isOnroad = self.params.get_bool("IsOnroad")
    msg['IsOnroad'] = isOnroad

    if isOnroad:
      if self.shared_data.carState:
        if self.shared_data.v_cruise_kph is not None:
          msg['v_cruise_kph'] = self.shared_data.v_cruise_kph  # 巡航速度
        if self.shared_data.v_ego_kph is not None:
          msg['v_ego_kph'] = self.shared_data.v_ego_kph  # 当前速度

      if self.sm.alive['selfdriveState']:
        selfdrive = self.sm['selfdriveState']
        msg['active'] = True if selfdrive.active else False

      if self.sm.alive['carrotMan']:
        carrotMan = self.sm['carrotMan']
        msg['atc_type'] = carrotMan.atcType
        msg['road_name'] = carrotMan.szPosRoadName

    return json.dumps(msg)

  def make_blinker_message(self):
    msg = {}
    msg['ip'] = self.local_ip_address
    msg['port'] = self.listen_port

    # 来自模型的消息
    if self.sm.alive['modelV2']:
      meta = self.sm['modelV2'].meta
      if hasattr(meta, 'blinker'):
        msg['blinker'] = meta.blinker

    #来自selfdriveState消息
    if self.sm.alive['selfdriveState']:
      selfdrive = self.sm['selfdriveState']
      msg['active'] = True if selfdrive.active else False

    return json.dumps(msg)

  def make_broadcast_message(self):
    msg = {}
    msg['ip'] = self.local_ip_address
    msg['port'] = self.listen_port

    return json.dumps(msg)

  def navi_get_broadcast_address(self):
    # 修改为支持PC的多接口检测
    if PC:
        interfaces = ['wlan0', 'eth0', 'enp0s3', 'br0']  # 常见PC接口
        for iface in interfaces:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    ip = fcntl.ioctl(
                        s.fileno(),
                        0x8919,  # SIOCGIFBRDADDR
                        struct.pack('256s', iface.encode('utf-8')[:15])
                    )[20:24]
                    return socket.inet_ntoa(ip)
            except Exception:
                continue
        return "255.255.255.255"  # 回退地址
    else:
      iface = b'wlan0'
    try:
      with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        ip = fcntl.ioctl(
          s.fileno(),
          0x8919,
          struct.pack('256s', iface)
        )[20:24]
        return socket.inet_ntoa(ip)
    except (OSError, Exception):
      return None

  def navi_get_local_ip(self):
      try:
          # 외부 서버와의 연결을 통해 로컬 IP 확인
          with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
              s.connect(("8.8.8.8", 80))  # Google DNS로 연결 시도
              return s.getsockname()[0]
      except Exception as e:
          return f"Error: {e}"

def main():
  amap_navi = AmapNaviServ()
  #amap_navi.navi_comm_thread()

if __name__ == "__main__":
  main()

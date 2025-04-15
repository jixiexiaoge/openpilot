#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import socket
import struct
import fcntl
import threading
import argparse

# 添加openpilot根目录到Python路径
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

# 导入必要的模块
try:
    from cereal import log, messaging
    from common.params import Params
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保您在openpilot目录下运行此程序")
    sys.exit(1)

class CarStateBroadcast:
    def __init__(self, broadcast_port=8088, broadcast_interval=0.2):
        self.broadcast_port = broadcast_port  # UDP广播端口
        self.broadcast_interval = broadcast_interval  # 广播间隔(秒)
        self.broadcast_count = 0  # 广播计数器

        # 初始化共享内存消息
        self.sm = messaging.SubMaster(['carState', 'controlsState', 'deviceState', 'carParams', 'lateralPlan'])
        self.params = Params()
        self.params_memory = Params("/dev/shm/params")  # 用于获取NetworkAddress等共享内存参数

        # 获取设备信息（只需获取一次）
        self.dongle_id = self.params.get("DongleId", encoding='utf-8')
        self.device_serial = self.params.get("HardwareSerial", encoding='utf-8')
        self.network_ip = self.params_memory.get("NetworkAddress", encoding='utf-8')

        # 获取IP地址
        self.ip_address = self.get_local_ip()
        self.broadcast_ip = self.get_broadcast_address()

        # 创建UDP套接字
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # 是否运行标志
        self.is_running = True

        # 初始化空的车辆状态数据
        self.car_state_data = {}

        #print(f"车辆状态广播服务已初始化. 广播地址: {self.broadcast_ip}:{self.broadcast_port}, 间隔: {self.broadcast_interval}秒")

    def get_broadcast_address(self):
        """获取广播地址"""
        try:
            # 尝试使用wlan0接口
            iface = b'wlan0'
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                try:
                    ip = fcntl.ioctl(
                        s.fileno(),
                        0x8919,  # SIOCGIFADDR
                        struct.pack('256s', iface)
                    )[20:24]
                    return socket.inet_ntoa(ip)
                except:
                    # 如果wlan0失败，尝试使用eth0
                    iface = b'eth0'
                    ip = fcntl.ioctl(
                        s.fileno(),
                        0x8919,  # SIOCGIFADDR
                        struct.pack('256s', iface)
                    )[20:24]
                    return socket.inet_ntoa(ip)
        except:
            # 如果获取接口IP失败，使用通用广播地址
            return '255.255.255.255'

    def get_local_ip(self):
        """获取本地IP地址"""
        try:
            # 连接到外部服务器来确定本地IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            print(f"获取本地IP错误: {e}")
            return "127.0.0.1"

    def update_car_state(self):
        """更新车辆状态数据"""
        self.sm.update(0)  # 非阻塞更新

        if not self.sm.updated['carState'] and not self.sm.updated['controlsState']:
            return  # 如果没有更新，直接返回

        # 检查openpilot状态
        is_onroad = self.params.get_bool("IsOnroad")
        is_active = False
        if self.sm.valid['controlsState']:
            try:
                controls_state = self.sm['controlsState']
                if hasattr(controls_state, 'enabled'):
                    is_active = controls_state.enabled
                elif hasattr(controls_state, 'state'):
                    is_active = controls_state.state > 0
                elif hasattr(controls_state, 'longActive') or hasattr(controls_state, 'latActive'):
                    is_active = getattr(controls_state, 'longActive', False) or getattr(controls_state, 'latActive', False)
            except Exception as e:
                print(f"检查controlsState出错: {e}")

        # 设备状态
        started = False
        if self.sm.valid['deviceState']:
            device_state = self.sm['deviceState']
            if hasattr(device_state, 'started'):
                started = device_state.started

        # 获取车道线信息
        lane_info = ""
        if self.sm.valid['lateralPlan']:
            lat_plan = self.sm['lateralPlan']
            if hasattr(lat_plan, 'latDebugText'):
                lane_info = lat_plan.latDebugText
            elif hasattr(lat_plan, 'laneWidth'):
                lane_info = f"车道宽度: {lat_plan.laneWidth:.2f}m"

        # 判断openpilot状态
        openpilot_status = "ONROAD" if (is_onroad or is_active or started) else "OFFROAD"

        # 如果carState有效，提取详细数据
        if self.sm.valid['carState']:
            CS = self.sm['carState']
            is_car_started = CS.vEgo > 0.1

            # 获取车型信息
            car_name = self.params.get("CarName", encoding='utf8')
            car_fingerprint = self.sm['carParams'].carFingerprint if self.sm.valid['carParams'] else "未知"

            # 获取LogCarrot信息
            log_carrot = CS.logCarrot if hasattr(CS, "logCarrot") else ""

            # 创建状态数据
            self.car_state_data = {
                # 设备信息（静态）
                "dongle_id": self.dongle_id,
                "device_serial": self.device_serial,
                "network_ip": self.network_ip,

                # 广播信息
                "broadcast_count": self.broadcast_count,
                "broadcast_interval": self.broadcast_interval,

                # 基本信息
                "device_ip": self.ip_address,
                "broadcast_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),

                # 系统状态
                "openpilot_status": openpilot_status,
                "active": is_active,
                "onroad": is_onroad,
                "started": started,
                "lane_info": lane_info,
                "log_carrot": log_carrot,

                # 车辆基本信息
                "car_name": car_name,
                "car_fingerprint": car_fingerprint,
                "v_ego": round(CS.vEgo * 3.6, 1),  # km/h
                "a_ego": round(CS.aEgo, 2),        # m/s²
                "steering_angle": round(CS.steeringAngleDeg, 1),  # 度
                "steering_torque": round(CS.steeringTorque, 1),

                # 巡航状态
                "cruise_enabled": CS.cruiseState.enabled,
                "cruise_speed": round(CS.cruiseState.speed * 3.6, 1) if CS.cruiseState.speed > 0 else 0,
                "cruise_available": CS.cruiseState.available,

                # 踏板状态
                "gas": round(CS.gas * 100, 1) if hasattr(CS, "gas") else 0,
                "brake_pressed": CS.brakePressed,

                # 车辆状态
                "door_open": CS.doorOpen if hasattr(CS, "doorOpen") else False,
                "seatbelt_unlatched": CS.seatbeltUnlatched if hasattr(CS, "seatbeltUnlatched") else False,
                "left_blinker": CS.leftBlinker if hasattr(CS, "leftBlinker") else False,
                "right_blinker": CS.rightBlinker if hasattr(CS, "rightBlinker") else False,
                "running_status": "行驶中" if is_car_started else "停止"
            }

            # 添加所有可用的carState属性
            for attr in dir(CS):
                if not attr.startswith('_') and attr not in self.car_state_data:
                    try:
                        value = getattr(CS, attr)
                        # 尝试转换为基本类型
                        if hasattr(value, 'is_valid') or hasattr(value, '_fields'):
                            # 这是一个复杂结构体，跳过
                            continue

                        # 处理基本类型
                        if isinstance(value, (int, float, bool, str)):
                            self.car_state_data[attr] = value
                        # 处理枚举类型
                        elif hasattr(value, 'value'):
                            self.car_state_data[attr] = value.value
                    except:
                        pass  # 忽略无法转换的属性

    def broadcast_thread(self):
        """广播线程函数"""
        #print("开始广播车辆状态数据...")

        while self.is_running:
            try:
                # 更新车辆状态
                self.update_car_state()

                # 如果有数据，进行广播
                if self.car_state_data:
                    # 更新广播计数
                    self.broadcast_count += 1
                    self.car_state_data["broadcast_count"] = self.broadcast_count

                    # 转换为JSON格式
                    json_data = json.dumps(self.car_state_data)

                    # 发送广播
                    self.sock.sendto(json_data.encode('utf-8'), (self.broadcast_ip, self.broadcast_port))

                    # 打印调试信息
                    if time.time() % 100 < 1:  # 每10秒只打印一次，减少日志输出
                        print(f"广播数据: {self.broadcast_ip}:{self.broadcast_port}, 数据大小: {len(json_data)}字节, 频率: {1/self.broadcast_interval:.2f}包/秒")

            except Exception as e:
                print(f"广播出错: {e}")
                import traceback
                traceback.print_exc()

            # 按指定间隔等待
            time.sleep(self.broadcast_interval)

    def start(self):
        """启动广播服务"""
        # 创建并启动广播线程
        self.broadcast_thread = threading.Thread(target=self.broadcast_thread)
        self.broadcast_thread.daemon = True
        self.broadcast_thread.start()

        # 保持主线程运行
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("正在关闭广播服务...")
            self.is_running = False
            self.sock.close()
            print("广播服务已关闭")

def main():
    """
    模块主入口函数，供进程管理器调用
    """
    print("正在启动车辆状态UDP广播服务...")

    # 解析命令行参数（如果通过命令行启动）
    try:
        parser = argparse.ArgumentParser(description='车辆状态UDP广播服务')
        parser.add_argument('-p', '--port', type=int, default=8088, help='广播端口号 (默认: 8088)')
        parser.add_argument('-i', '--interval', type=float, default=0.2, help='广播间隔(秒) (默认: 0.2)')
        args, unknown = parser.parse_known_args()

        port = args.port
        interval = args.interval
    except:
        # 如果解析失败（例如通过进程管理器启动），使用默认值
        port = 8088
        interval = 0.2

    print(f"初始化广播服务 - 端口: {port}, 广播间隔: {interval}秒")

    # 创建并启动广播服务
    broadcaster = CarStateBroadcast(broadcast_port=port, broadcast_interval=interval)
    broadcaster.start()

# 主函数
if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='车辆状态UDP广播服务')
    parser.add_argument('-p', '--port', type=int, default=8088, help='广播端口号 (默认: 8088)')
    parser.add_argument('-i', '--interval', type=float, default=1.0, help='广播间隔(秒) (默认: 1.0)')
    args = parser.parse_args()

    print("启动车辆状态UDP广播服务")
    #print(f"广播端口: {args.port}, 广播间隔: {args.interval}秒")

    broadcaster = CarStateBroadcast(broadcast_port=args.port, broadcast_interval=args.interval)
    broadcaster.start()
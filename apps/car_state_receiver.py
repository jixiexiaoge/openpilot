#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import socket
import threading

class CarStateReceiver:
    def __init__(self):
        self.udp_port = 8088  # 监听的UDP端口
        self.buffer_size = 4096  # 接收缓冲区大小
        self.discovered_devices = {}  # 已发现的设备列表
        self.last_received_time = {}  # 最后一次接收数据的时间
        self.timeout = 10  # 超时时间（秒）

        # 创建UDP套接字
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', self.udp_port))  # 绑定到所有网络接口

        # 运行标志
        self.is_running = True

        print(f"车辆状态接收服务已启动，监听端口: {self.udp_port}")

    def clean_timeout_devices(self):
        """清除超时的设备"""
        current_time = time.time()
        for ip in list(self.last_received_time.keys()):
            if current_time - self.last_received_time[ip] > self.timeout:
                print(f"设备 {ip} 已超时，从列表中移除")
                if ip in self.discovered_devices:
                    del self.discovered_devices[ip]
                del self.last_received_time[ip]

    def receiver_thread(self):
        """接收线程函数"""
        print("开始接收车辆状态数据...")

        while self.is_running:
            try:
                # 接收数据
                data, addr = self.sock.recvfrom(self.buffer_size)
                sender_ip = addr[0]

                # 解析JSON数据
                json_data = json.loads(data.decode('utf-8'))

                # 更新设备列表
                self.discovered_devices[sender_ip] = json_data
                self.last_received_time[sender_ip] = time.time()

                # 打印接收到的数据（首次接收或每30秒一次）
                if sender_ip not in self.last_received_time or time.time() % 30 < 1:
                    print(f"已接收来自 {sender_ip} 的车辆状态数据")

            except json.JSONDecodeError:
                print(f"收到无效JSON数据: {data[:100]}...")
            except Exception as e:
                print(f"接收数据出错: {e}")

            # 清除超时设备
            self.clean_timeout_devices()

    def display_thread(self):
        """显示线程函数，定期在控制台更新显示车辆状态"""
        while self.is_running:
            try:
                os.system('cls' if os.name == 'nt' else 'clear')  # 清屏

                print("\033[1m" + "=== 车辆状态监控器 ===" + "\033[0m")
                print(f"当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"已发现 {len(self.discovered_devices)} 个设备\n")

                if not self.discovered_devices:
                    print("等待发现车辆...")

                for ip, data in sorted(self.discovered_devices.items()):
                    # 计算最后更新时间
                    last_update_seconds = int(time.time() - self.last_received_time[ip])

                    # 打印设备信息
                    print("\033[1m" + f"设备 IP: {ip} (最后更新: {last_update_seconds}秒前)" + "\033[0m")
                    print(f"车辆: {data.get('car_name', '未知')} ({data.get('car_fingerprint', '未知')})")

                    # 系统状态
                    status = data.get('openpilot_status', 'UNKNOWN')
                    status_color = "\033[92m" if status == "ONROAD" else "\033[91m"  # 绿色或红色
                    print(f"系统状态: {status_color}{status}\033[0m")

                    # 车辆基本信息
                    print(f"速度: {data.get('v_ego', 0)} km/h, 加速度: {data.get('a_ego', 0)} m/s²")
                    print(f"方向盘角度: {data.get('steering_angle', 0)}°, 转矩: {data.get('steering_torque', 0)}")

                    # 巡航状态
                    cruise_status = "开启" if data.get('cruise_enabled', False) else "关闭"
                    cruise_speed = data.get('cruise_speed', 0)
                    print(f"巡航状态: {cruise_status}, 设定速度: {cruise_speed} km/h")

                    # 踏板状态
                    gas = data.get('gas', 0)
                    brake = "已踩下" if data.get('brake_pressed', False) else "未踩下"
                    print(f"油门: {gas}%, 刹车: {brake}")

                    # 车辆状态
                    door = "开启" if data.get('door_open', False) else "关闭"
                    seatbelt = "未系" if data.get('seatbelt_unlatched', False) else "已系"
                    print(f"车门: {door}, 安全带: {seatbelt}")

                    # 转向灯状态
                    blinker = "左转" if data.get('left_blinker', False) else (
                        "右转" if data.get('right_blinker', False) else "关闭")
                    print(f"转向灯: {blinker}")

                    # 运行状态
                    print(f"运行状态: {data.get('running_status', '未知')}")

                    print("-" * 50)

            except Exception as e:
                print(f"显示数据出错: {e}")

            # 每秒更新一次显示
            time.sleep(1)

    def start(self):
        """启动接收服务"""
        # 创建并启动接收线程
        self.receiver_thread = threading.Thread(target=self.receiver_thread)
        self.receiver_thread.daemon = True
        self.receiver_thread.start()

        # 创建并启动显示线程
        self.display_thread = threading.Thread(target=self.display_thread)
        self.display_thread.daemon = True
        self.display_thread.start()

        # 保持主线程运行
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("正在关闭接收服务...")
            self.is_running = False
            self.sock.close()
            print("接收服务已关闭")

# 主函数
if __name__ == "__main__":
    print("启动车辆状态UDP接收服务")
    receiver = CarStateReceiver()
    receiver.start()
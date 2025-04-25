#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox, font, scrolledtext
from datetime import datetime

class CarStateReceiverGUI:
    def __init__(self, root):
        self.root = root
        self.udp_port = 8088  # 监听的UDP端口
        self.buffer_size = 4096  # 接收缓冲区大小
        self.discovered_devices = {}  # 已发现的设备列表
        self.last_received_time = {}  # 最后一次接收数据的时间
        self.timeout = 10  # 超时时间（秒）

        # 数据推送频率统计
        self.packet_count = 0
        self.last_packet_count = 0
        self.last_frequency_update = time.time()
        self.current_frequency = 0
        self.frequency_history = []  # 用于存储历史频率数据
        self.max_history_length = 60  # 存储最多60个数据点（约1分钟）

        # 运行标志
        self.is_running = True

        # 设置窗口
        self.root.title("车辆状态监控器")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)
        self.setup_ui()

        # 创建UDP套接字
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('', self.udp_port))

            # 开始监听线程
            self.receiver_thread = threading.Thread(target=self.receiver_thread)
            self.receiver_thread.daemon = True
            self.receiver_thread.start()

            # 定时更新UI
            self.update_ui()

            self.log_message(f"车辆状态接收服务已启动，监听端口: {self.udp_port}")
        except Exception as e:
            messagebox.showerror("启动错误", f"无法启动UDP监听: {e}")
            self.log_message(f"启动失败: {e}")

    def setup_ui(self):
        """设置用户界面"""
        # 创建菜单栏
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="退出", command=self.on_close)
        menubar.add_cascade(label="文件", menu=file_menu)
        self.root.config(menu=menubar)

        # 主框架
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 顶部状态栏
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(status_frame, text="监听状态: ").pack(side=tk.LEFT)
        self.status_label = ttk.Label(status_frame, text="正在监听", foreground="green")
        self.status_label.pack(side=tk.LEFT)

        ttk.Label(status_frame, text="  发现设备: ").pack(side=tk.LEFT)
        self.device_count_label = ttk.Label(status_frame, text="0")
        self.device_count_label.pack(side=tk.LEFT)

        ttk.Label(status_frame, text="  数据频率: ").pack(side=tk.LEFT)
        self.frequency_label = ttk.Label(status_frame, text="0 包/秒")
        self.frequency_label.pack(side=tk.LEFT)

        ttk.Label(status_frame, text="  当前时间: ").pack(side=tk.LEFT)
        self.time_label = ttk.Label(status_frame, text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.time_label.pack(side=tk.LEFT)

        # 设备选择栏
        device_frame = ttk.Frame(main_frame)
        device_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(device_frame, text="选择设备: ").pack(side=tk.LEFT)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(device_frame, textvariable=self.device_var, state="readonly")
        self.device_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.device_combo.bind("<<ComboboxSelected>>", self.update_car_info)

        # 主窗口 - 使用Notebook (TabControl)创建标签页
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 标签页1: 预设数据视图
        preset_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(preset_frame, text="预设视图")

        # 车辆信息区域
        info_frame = ttk.LabelFrame(preset_frame, text="车辆状态信息", padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True)

        # 创建两列布局
        left_frame = ttk.Frame(info_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_frame = ttk.Frame(info_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 系统状态区域
        system_frame = ttk.LabelFrame(left_frame, text="系统状态", padding=10)
        system_frame.pack(fill=tk.X, pady=5)

        self.create_info_field(system_frame, "设备 IP:", "device_ip")
        self.create_info_field(system_frame, "设备 ID:", "dongle_id")
        self.create_info_field(system_frame, "序列号:", "device_serial")
        self.create_info_field(system_frame, "车型:", "car_name")
        self.create_info_field(system_frame, "指纹:", "car_fingerprint")
        self.create_status_field(system_frame, "系统状态:", "openpilot_status")
        self.create_info_field(system_frame, "最后更新:", "last_update")
        self.create_info_field(system_frame, "推送频率:", "push_frequency", "包/秒")

        # 车辆基本信息区域
        basic_frame = ttk.LabelFrame(left_frame, text="基本信息", padding=10)
        basic_frame.pack(fill=tk.X, pady=5)

        self.create_info_field(basic_frame, "速度:", "v_ego", "km/h")
        self.create_info_field(basic_frame, "加速度:", "a_ego", "m/s²")
        self.create_info_field(basic_frame, "建议车速:", "apply_speed", "km/h")
        self.create_info_field(basic_frame, "建议来源:", "apply_source", "")
        self.create_info_field(basic_frame, "方向盘角度:", "steering_angle", "°")
        self.create_info_field(basic_frame, "方向盘转矩:", "steering_torque", "")

        # 曲率数据区域
        curvature_frame = ttk.LabelFrame(right_frame, text="曲率数据", padding=10)
        curvature_frame.pack(fill=tk.X, pady=5)

        self.create_info_field(curvature_frame, "控制器曲率:", "actuator_curvature")
        self.create_info_field(curvature_frame, "模型曲率:", "model_curvature")
        self.create_info_field(curvature_frame, "当前曲率:", "current_curvature")
        self.create_info_field(curvature_frame, "曲率变化:", "curvature_change")
        self.create_info_field(curvature_frame, "速度控制:", "speed_from_pcm")

        # UI文本信息区域
        ui_text_frame = ttk.LabelFrame(left_frame, text="UI显示文本", padding=10)
        ui_text_frame.pack(fill=tk.X, pady=5)

        self.create_info_field(ui_text_frame, "顶部文本:", "top_text")
        self.create_info_field(ui_text_frame, "底部文本:", "bottom_text")

        # 交通信号灯区域
        traffic_frame = ttk.LabelFrame(left_frame, text="交通信号", padding=10)
        traffic_frame.pack(fill=tk.X, pady=5)

        self.create_traffic_signal_field(traffic_frame, "信号状态:", "traffic_state_text")

        # 巡航状态区域
        cruise_frame = ttk.LabelFrame(right_frame, text="巡航状态", padding=10)
        cruise_frame.pack(fill=tk.X, pady=5)

        self.create_info_field(cruise_frame, "巡航状态:", "cruise_enabled")
        self.create_info_field(cruise_frame, "设定速度:", "cruise_speed", "km/h")
        self.create_info_field(cruise_frame, "巡航可用:", "cruise_available")

        # 车辆状态区域
        vehicle_frame = ttk.LabelFrame(right_frame, text="车辆状态", padding=10)
        vehicle_frame.pack(fill=tk.X, pady=5)

        self.create_info_field(vehicle_frame, "油门:", "gas", "%")
        self.create_info_field(vehicle_frame, "刹车:", "brake_pressed")
        self.create_info_field(vehicle_frame, "车门:", "door_open")
        self.create_info_field(vehicle_frame, "安全带:", "seatbelt_unlatched")
        self.create_info_field(vehicle_frame, "转向灯:", "blinker")
        self.create_info_field(vehicle_frame, "运行状态:", "running_status")

        # 前车信息区域
        lead_frame = ttk.LabelFrame(right_frame, text="前车信息", padding=10)
        lead_frame.pack(fill=tk.X, pady=5)

        self.create_info_field(lead_frame, "前车检测:", "lead_detected")
        self.create_info_field(lead_frame, "前车速度:", "lead_speed", "km/h")
        self.create_info_field(lead_frame, "前车距离:", "lead_distance", "m")
        self.create_info_field(lead_frame, "跟车间距:", "pcm_cruise_gap", "档")
        self.create_info_field(lead_frame, "发动机转速:", "engine_rpm", "RPM")

        # 标签页2: 所有数据视图
        all_data_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(all_data_frame, text="所有数据")

        # 创建树状视图显示所有数据
        self.tree_frame = ttk.Frame(all_data_frame)
        self.tree_frame.pack(fill=tk.BOTH, expand=True)

        # 创建搜索框
        search_frame = ttk.Frame(self.tree_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(search_frame, text="搜索参数:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<KeyRelease>", self.filter_tree_view)

        ttk.Button(search_frame, text="清除", command=self.clear_search).pack(side=tk.LEFT, padx=(5, 0))

        # 创建TreeView
        self.tree = ttk.Treeview(self.tree_frame, columns=('key', 'value', 'type'), show='headings')
        self.tree.heading('key', text='参数名')
        self.tree.heading('value', text='参数值')
        self.tree.heading('type', text='数据类型')
        self.tree.column('key', width=200, anchor='w')
        self.tree.column('value', width=300, anchor='w')
        self.tree.column('type', width=100, anchor='w')

        # 添加滚动条
        tree_scrollbar = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)

        # 排列树状视图和滚动条
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 标签页3: 原始数据视图
        raw_data_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(raw_data_frame, text="原始JSON")

        # 创建JSON查看器
        self.json_text = scrolledtext.ScrolledText(raw_data_frame, wrap=tk.WORD, font=('Courier New', 10))
        self.json_text.pack(fill=tk.BOTH, expand=True)

        # 标签页4: 频率监控
        frequency_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(frequency_frame, text="频率监控")

        # 频率监控信息
        freq_info_frame = ttk.Frame(frequency_frame)
        freq_info_frame.pack(fill=tk.X, pady=5)

        ttk.Label(freq_info_frame, text="当前频率:").pack(side=tk.LEFT, padx=(0, 5))
        self.freq_current_label = ttk.Label(freq_info_frame, text="0 包/秒")
        self.freq_current_label.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(freq_info_frame, text="平均频率:").pack(side=tk.LEFT, padx=(0, 5))
        self.freq_average_label = ttk.Label(freq_info_frame, text="0 包/秒")
        self.freq_average_label.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(freq_info_frame, text="最大频率:").pack(side=tk.LEFT, padx=(0, 5))
        self.freq_max_label = ttk.Label(freq_info_frame, text="0 包/秒")
        self.freq_max_label.pack(side=tk.LEFT)

        # 频率历史记录框
        freq_history_frame = ttk.LabelFrame(frequency_frame, text="频率历史记录 (最近1分钟)")
        freq_history_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.freq_history_text = scrolledtext.ScrolledText(freq_history_frame, wrap=tk.WORD, height=10)
        self.freq_history_text.pack(fill=tk.BOTH, expand=True)
        self.freq_history_text.config(state=tk.DISABLED)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="消息日志", padding=10, height=150)
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 5))

        self.log_text = scrolledtext.ScrolledText(log_frame, height=6, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

        # 状态栏
        self.statusbar = ttk.Label(main_frame, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.statusbar.pack(fill=tk.X)

        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_info_field(self, parent, label_text, key, unit=""):
        """创建信息字段"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)

        ttk.Label(frame, text=label_text, width=12).pack(side=tk.LEFT)
        var = tk.StringVar(value="--")
        setattr(self, f"{key}_var", var)
        ttk.Label(frame, textvariable=var).pack(side=tk.LEFT)

        if unit:
            ttk.Label(frame, text=unit).pack(side=tk.LEFT)

    def create_traffic_signal_field(self, parent, label_text, key):
        """创建交通信号灯字段（带颜色）"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)

        ttk.Label(frame, text=label_text, width=12).pack(side=tk.LEFT)
        var = tk.StringVar(value="--")
        label = ttk.Label(frame, textvariable=var, foreground="black")
        label.pack(side=tk.LEFT)

        setattr(self, f"{key}_var", var)
        setattr(self, f"{key}_label", label)

    def create_status_field(self, parent, label_text, key):
        """创建状态字段（带颜色）"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)

        ttk.Label(frame, text=label_text, width=12).pack(side=tk.LEFT)
        var = tk.StringVar(value="--")
        label = ttk.Label(frame, textvariable=var, foreground="black")
        label.pack(side=tk.LEFT)

        setattr(self, f"{key}_var", var)
        setattr(self, f"{key}_label", label)

    def log_message(self, message):
        """向日志区域添加消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def update_frequency(self):
        """更新数据频率计算"""
        current_time = time.time()
        elapsed_time = current_time - self.last_frequency_update

        if elapsed_time >= 1.0:  # 每秒更新一次
            # 计算频率 (包/秒)
            current_freq = round((self.packet_count - self.last_packet_count) / elapsed_time, 2)
            self.current_frequency = current_freq
            self.last_packet_count = self.packet_count
            self.last_frequency_update = current_time

            # 更新频率历史
            self.frequency_history.append((datetime.now(), current_freq))
            if len(self.frequency_history) > self.max_history_length:
                self.frequency_history.pop(0)

            # 计算平均和最大频率
            avg_freq = round(sum(freq for _, freq in self.frequency_history) / len(self.frequency_history), 2)
            max_freq = round(max(freq for _, freq in self.frequency_history), 2) if self.frequency_history else 0

            # 更新频率监控标签
            self.freq_current_label.config(text=f"{current_freq} 包/秒")
            self.freq_average_label.config(text=f"{avg_freq} 包/秒")
            self.freq_max_label.config(text=f"{max_freq} 包/秒")

            # 更新频率历史记录文本
            self.update_frequency_history()

            # 更新顶部频率显示
            self.frequency_label.config(text=f"{current_freq} 包/秒")

    def update_frequency_history(self):
        """更新频率历史记录文本框"""
        self.freq_history_text.config(state=tk.NORMAL)
        self.freq_history_text.delete(1.0, tk.END)

        for timestamp, freq in self.frequency_history:
            time_str = timestamp.strftime("%H:%M:%S")
            self.freq_history_text.insert(tk.END, f"{time_str}: {freq} 包/秒\n")

        self.freq_history_text.see(tk.END)
        self.freq_history_text.config(state=tk.DISABLED)

    def filter_tree_view(self, event=None):
        """根据搜索框内容过滤树视图"""
        search_text = self.search_var.get().lower()

        # 获取当前选择的设备数据
        selected_ip = self.device_var.get()
        if not selected_ip or selected_ip not in self.discovered_devices:
            return

        data = self.discovered_devices[selected_ip]

        # 清空树视图
        self.tree.delete(*self.tree.get_children())

        # 重新填充树视图
        for key, value in sorted(data.items()):
            if search_text in key.lower() or (isinstance(value, str) and search_text in str(value).lower()):
                # 格式化数据，让布尔值显示为中文
                formatted_value = value
                if isinstance(value, bool):
                    formatted_value = "是" if value else "否"

                # 获取数据类型
                type_name = type(value).__name__
                self.tree.insert('', 'end', values=(key, formatted_value, type_name))

    def clear_search(self):
        """清空搜索框并重置树视图"""
        self.search_var.set("")
        self.filter_tree_view()

    def update_ui(self):
        """定时更新UI"""
        try:
            # 更新时间
            self.time_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            # 更新数据推送频率
            self.update_frequency()

            # 更新设备数量
            self.device_count_label.config(text=str(len(self.discovered_devices)))

            # 清除超时设备
            self.clean_timeout_devices()

            # 更新设备下拉列表
            current_selection = self.device_var.get()
            device_list = list(self.discovered_devices.keys())
            self.device_combo['values'] = device_list

            # 保持选择
            if current_selection and current_selection in device_list:
                self.device_var.set(current_selection)
            elif device_list and not current_selection:
                self.device_var.set(device_list[0])
                self.update_car_info(None)
            elif not device_list:
                self.device_var.set("")
                self.clear_car_info()

            # 如果当前有选择，更新车辆信息
            if self.device_var.get():
                self.update_car_info(None)

        except Exception as e:
            self.log_message(f"UI更新错误: {e}")

        # 每100毫秒更新一次
        self.root.after(100, self.update_ui)

    def update_car_info(self, event):
        """更新车辆信息显示"""
        selected_ip = self.device_var.get()
        if not selected_ip or selected_ip not in self.discovered_devices:
            self.clear_car_info()
            return

        data = self.discovered_devices[selected_ip]

        # 更新基本字段 (预设视图)
        self.device_ip_var.set(selected_ip)
        self.dongle_id_var.set(data.get('dongle_id', '未知'))
        self.device_serial_var.set(data.get('device_serial', '未知'))
        self.car_name_var.set(data.get('car_name', '未知'))
        self.car_fingerprint_var.set(data.get('car_fingerprint', '未知'))

        # 计算最后更新时间
        seconds_ago = int(time.time() - self.last_received_time.get(selected_ip, 0))
        self.last_update_var.set(f"{seconds_ago}秒前")

        # 更新推送频率
        self.push_frequency_var.set(str(self.current_frequency))

        # 更新系统状态（带颜色）
        status = data.get('openpilot_status', 'UNKNOWN')
        self.openpilot_status_var.set(status)
        if status == "ONROAD":
            self.openpilot_status_label.config(foreground="green")
        else:
            self.openpilot_status_label.config(foreground="red")

        # 更新车辆数据
        self.v_ego_var.set(str(data.get('v_ego', 0)))
        self.a_ego_var.set(str(data.get('a_ego', 0)))
        self.apply_speed_var.set(str(data.get('apply_speed', 0)))
        self.apply_source_var.set(data.get('apply_source', '未知'))
        self.steering_angle_var.set(str(data.get('steering_angle', 0)))
        self.steering_torque_var.set(str(data.get('steering_torque', 0)))

        # 更新UI文本信息
        self.top_text_var.set(data.get('top_text', '识别信息'))
        self.bottom_text_var.set(data.get('bottom_text', '车道信息'))

        # 更新交通信号信息
        traffic_state_text = data.get('traffic_state_text', '无信号')
        self.traffic_state_text_var.set(traffic_state_text)

        # 根据交通信号状态设置颜色
        traffic_state = data.get('traffic_state', 0)
        if traffic_state == 1:  # 红灯
            self.traffic_state_text_label.config(foreground="red")
        elif traffic_state == 2:  # 绿灯
            self.traffic_state_text_label.config(foreground="green")
        else:  # 无信号
            self.traffic_state_text_label.config(foreground="black")

        # 更新巡航状态
        cruise_enabled = data.get('cruise_enabled', False)
        self.cruise_enabled_var.set("开启" if cruise_enabled else "关闭")
        self.cruise_speed_var.set(str(data.get('cruise_speed', 0)))
        self.cruise_available_var.set("可用" if data.get('cruise_available', False) else "不可用")

        # 更新车辆状态
        self.gas_var.set(str(data.get('gas', 0)))
        self.brake_pressed_var.set("已踩下" if data.get('brake_pressed', False) else "未踩下")
        self.door_open_var.set("开启" if data.get('door_open', False) else "关闭")
        self.seatbelt_unlatched_var.set("未系" if data.get('seatbelt_unlatched', False) else "已系")

        # 更新转向灯状态
        blinker = "左转" if data.get('left_blinker', False) else (
            "右转" if data.get('right_blinker', False) else "关闭")
        self.blinker_var.set(blinker)

        # 更新运行状态
        self.running_status_var.set(data.get('running_status', '未知'))

        # 更新前车信息
        lead_info = data.get('lead_info', {})
        self.lead_detected_var.set("已检测" if lead_info.get('detected', False) else "未检测")
        self.lead_speed_var.set(str(round(lead_info.get('speed', 0), 1)))
        self.lead_distance_var.set(str(round(lead_info.get('distance', 0), 1)))

        # 更新跟车间距和发动机转速
        self.pcm_cruise_gap_var.set(str(data.get('pcm_cruise_gap', 0)))
        self.engine_rpm_var.set(str(data.get('engine_rpm', 0)))

        # 更新曲率数据
        self.actuator_curvature_var.set(str(data.get('actuator_curvature', 0)))
        self.model_curvature_var.set(str(data.get('model_curvature', 0)))
        self.current_curvature_var.set(str(data.get('current_curvature', 0)))
        self.curvature_change_var.set(str(data.get('curvature_change', 0)))

        # 更新速度控制状态
        speed_from_pcm = data.get('speed_from_pcm', 1)
        speed_status = {
            0: "减速",
            1: "正常",
            2: "弯道"
        }.get(speed_from_pcm, "未知")
        self.speed_from_pcm_var.set(speed_status)

        # 更新树状视图（所有数据）
        self.filter_tree_view()  # 使用搜索过滤功能更新树视图

        # 更新原始JSON视图
        formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
        self.json_text.delete('1.0', tk.END)
        self.json_text.insert(tk.END, formatted_json)

    def clear_car_info(self):
        """清除车辆信息显示"""
        for attr in dir(self):
            if attr.endswith('_var') and attr not in ['device_var', 'search_var']:
                getattr(self, attr).set("--")

        # 清除树状视图
        self.tree.delete(*self.tree.get_children())

        # 清除JSON文本
        self.json_text.delete('1.0', tk.END)

        # 清除频率历史记录
        self.freq_history_text.config(state=tk.NORMAL)
        self.freq_history_text.delete(1.0, tk.END)
        self.freq_history_text.config(state=tk.DISABLED)

    def clean_timeout_devices(self):
        """清除超时的设备"""
        current_time = time.time()
        for ip in list(self.last_received_time.keys()):
            if current_time - self.last_received_time[ip] > self.timeout:
                if ip in self.discovered_devices:
                    self.log_message(f"设备 {ip} 已超时，从列表中移除")
                    del self.discovered_devices[ip]
                del self.last_received_time[ip]

    def receiver_thread(self):
        """接收线程函数"""
        self.log_message("开始接收车辆状态数据...")

        while self.is_running:
            try:
                # 接收数据
                data, addr = self.sock.recvfrom(self.buffer_size)
                sender_ip = addr[0]

                # 解析JSON数据
                json_data = json.loads(data.decode('utf-8'))

                # 是否是新设备
                is_new = sender_ip not in self.discovered_devices

                # 更新设备列表
                self.discovered_devices[sender_ip] = json_data
                self.last_received_time[sender_ip] = time.time()

                # 更新数据包计数
                self.packet_count += 1

                # 首次发现新设备时记录日志
                if is_new:
                    self.log_message(f"发现新设备: {sender_ip} ({json_data.get('car_name', '未知')})")

            except json.JSONDecodeError as e:
                self.log_message(f"收到无效JSON数据: {e}")
            except Exception as e:
                if self.is_running:  # 只在运行时记录错误
                    self.log_message(f"接收数据出错: {e}")

    def on_close(self):
        """关闭应用程序"""
        self.is_running = False
        try:
            self.sock.close()
        except:
            pass
        self.root.destroy()

# 主函数
if __name__ == "__main__":
    root = tk.Tk()
    app = CarStateReceiverGUI(root)
    root.mainloop()
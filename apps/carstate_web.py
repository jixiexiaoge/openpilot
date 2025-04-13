#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import threading
from flask import Flask, render_template, jsonify

# 添加openpilot根目录到Python路径
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

# 导入必要的模块
try:
    from cereal import log, messaging
    from opendbc.can.parser import CANParser
    from opendbc.car import Bus
    from opendbc_repo.opendbc.car.mazda.values import DBC, MazdaFlags
    from opendbc_repo.opendbc.car.values import PLATFORMS
    from common.params import Params
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保您在openpilot目录下运行此程序")
    sys.exit(1)

# 创建Flask应用
app = Flask(__name__)
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
app.config['JSON_AS_ASCII'] = False

# 全局变量保存最新的车辆状态数据
car_state_data = {
    # 系统状态
    "openpilot状态": "OFFROAD",
    "数据状态": "等待数据...",
    "连接状态": "等待连接...",
    "最后有效数据时间": "无数据",
    "自动驾驶": "未激活",

    # 基本车辆信息
    "车速": 0,
    "加速度": 0,
    "方向盘角度": 0,
    "方向盘转矩": 0,
    "方向盘速率": 0,

    # 踏板状态
    "油门踏板": 0,
    "刹车踏板": "未踩下",
    "刹车压力": 0,

    # 巡航控制
    "巡航系统": "关闭",
    "巡航速度": 0,
    "巡航状态": "不可用",
    "巡航跟车距离": 0,

    # 变速箱
    "档位": "未知",
    "档位步数": 0,

    # 车轮速度
    "左前轮速度": 0,
    "右前轮速度": 0,
    "左后轮速度": 0,
    "右后轮速度": 0,

    # 安全系统
    "安全带状态": "未知",
    "车门状态": "未知",
    "刹车灯": "未知",

    # 其他状态
    "转向灯": "关闭",
    "远光灯": "关闭",
    "左盲区监测": "未知",
    "右盲区监测": "未知",

    # 高级功能
    "车型": "未知",
    "车型指纹": "未知",
    "发动机转速": 0,

    # 可选信息
    "车外温度": "未知",
    "燃油续航": "未知",
    "总里程": "未知",
    "瞬时油耗": "未知",

    # 安全系统状态
    "ESP状态": "未知",
    "ABS状态": "未知",
    "牵引力控制": "未知",
    "碰撞警告": "未知",

    # 车辆规格
    "车重": "未知",
    "轴距": "未知",
    "转向比": "未知",

    # 时间戳
    "更新时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    "运行状态": "停止"
}
last_update_time = 0
car_state_lock = threading.Lock()
openpilot_status = "OFFROAD"  # 初始状态为OFFROAD
can_data_available = False    # 标记是否成功获取到CAN数据
last_valid_data_time = 0      # 上次成功获取数据的时间

# 线程函数：定期更新车辆状态数据
def update_car_state_thread():
    global car_state_data, last_update_time, openpilot_status, can_data_available, last_valid_data_time

    try:
        # 初始化参数对象
        params = Params()

        # 初始化消息管理器，订阅carState、controlsState和deviceState
        sm = messaging.SubMaster(['carState', 'carParams', 'controlsState', 'deviceState'])

        # 获取车型信息
        car_name = params.get("CarName", encoding='utf8')
        if car_name in PLATFORMS:
            platform = PLATFORMS[car_name]
            car_fingerprint = platform.config.platform_str
            car_specs = platform.config.specs
        else:
            car_name = "未知车型"
            car_fingerprint = "未知指纹"
            car_specs = None

        print(f"已识别车辆: {car_name}, 指纹: {car_fingerprint}")

        while True:
            try:
                # 更新消息
                sm.update()

                # 检查openpilot状态
                # 1. 首先从params中读取IsOnroad参数
                is_onroad = params.get_bool("IsOnroad")

                # 2. 检查controlsState，但不尝试访问active字段
                is_active = False
                is_enabled = False
                if sm.updated['controlsState'] and sm.valid['controlsState']:
                    controls_state = sm['controlsState']
                    # 使用available代替active作为判断依据
                    # 或者检查enabled字段（如果存在）
                    try:
                        if hasattr(controls_state, 'enabled'):
                            is_enabled = controls_state.enabled
                        # 检查其他可能的状态字段
                        if hasattr(controls_state, 'state'):
                            is_active = controls_state.state > 0
                        elif hasattr(controls_state, 'longActive') or hasattr(controls_state, 'latActive'):
                            is_active = getattr(controls_state, 'longActive', False) or getattr(controls_state, 'latActive', False)
                    except Exception as e:
                        print(f"检查controlsState时出错: {e}")

                # 3. 设备状态
                started = False
                if sm.updated['deviceState'] and sm.valid['deviceState']:
                    device_state = sm['deviceState']
                    if hasattr(device_state, 'started'):
                        started = device_state.started

                # 综合判断openpilot状态
                if is_onroad or is_active or is_enabled or started:
                    openpilot_status = "ONROAD"
                    can_data_available = True
                    last_valid_data_time = time.time()
                else:
                    openpilot_status = "OFFROAD"
                    # 当处于OFFROAD状态时，也可能有CAN数据
                    # 进一步检查车辆数据的有效性

                    # 获取车辆状态
                    if sm.updated['carState'] and sm.valid['carState']:
                        CS = sm['carState']
                        # 检查是否有基本的车辆数据
                        data_valid = (CS.wheelSpeeds.fl > 0.01 or
                                    CS.wheelSpeeds.fr > 0.01 or
                                    CS.wheelSpeeds.rl > 0.01 or
                                    CS.wheelSpeeds.rr > 0.01 or
                                    abs(CS.steeringAngleDeg) > 0.1 or
                                    CS.vEgo > 0.1 or
                                    CS.gas > 0.01 or
                                    CS.brakePressed)

                        if data_valid:
                            can_data_available = True
                            last_valid_data_time = time.time()
                    else:
                        # 如果没有carState更新或数据无效，可能没连接CAN或系统未启动
                        can_data_available = False

                # 检查是否过期 - 如果10秒内没有有效数据，则认为连接断开
                if time.time() - last_valid_data_time > 10:
                    can_data_available = False

                # 获取车辆状态
                if sm.updated['carState'] and sm.valid['carState']:
                    CS = sm['carState']

                    # 基本状态判断
                    is_car_started = CS.vEgo > 0.1
                    is_car_engaged = CS.cruiseState.enabled

                    # 准备数据
                    data = {
                        # 系统状态
                        "openpilot状态": openpilot_status,
                        "数据状态": "正常" if can_data_available else "未检测到车辆数据",
                        "连接状态": "已连接" if can_data_available else "未连接",
                        "最后有效数据时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_valid_data_time)) if last_valid_data_time > 0 else "无数据",
                        "自动驾驶": "激活" if is_active else "未激活",

                        # 基本车辆信息
                        "车速": round(CS.vEgo * 3.6, 1),  # 转换为km/h并保留1位小数
                        "加速度": round(CS.aEgo, 2),
                        "方向盘角度": round(CS.steeringAngleDeg, 1),
                        "方向盘转矩": round(CS.steeringTorque, 1),
                        "方向盘速率": round(CS.steeringRateDeg, 1),
                        "发动机转速": CS.engineRpm if hasattr(CS, "engineRpm") else 0,  # 添加发动机转速

                        # 踏板状态
                        "油门踏板": round(CS.gas * 100, 1) if hasattr(CS, "gas") else 0,
                        "刹车踏板": "已踩下" if CS.brakePressed else "未踩下",
                        "刹车压力": CS.brake if hasattr(CS, "brake") else 0,  # 直接显示原始值，不做百分比转换

                        # 巡航控制
                        "巡航系统": "开启" if CS.cruiseState.enabled else "关闭",
                        "巡航速度": round(CS.cruiseState.speed * 3.6, 1) if CS.cruiseState.speed > 0 else 0,
                        "巡航状态": "可用" if CS.cruiseState.available else "不可用",
                        "巡航跟车距离": CS.pcmCruiseGap if hasattr(CS, "pcmCruiseGap") else 0,  # 添加巡航跟车距离

                        # 变速箱
                        "档位": str(CS.gearShifter) if hasattr(CS, "gearShifter") else "未知",
                        "档位步数": CS.gearStep if hasattr(CS, "gearStep") else 0,

                        # 车轮速度
                        "左前轮速度": round(CS.wheelSpeeds.fl * 3.6, 1),
                        "右前轮速度": round(CS.wheelSpeeds.fr * 3.6, 1),
                        "左后轮速度": round(CS.wheelSpeeds.rl * 3.6, 1),
                        "右后轮速度": round(CS.wheelSpeeds.rr * 3.6, 1),

                        # 安全系统
                        "安全带状态": "未系" if CS.seatbeltUnlatched else "已系",
                        "车门状态": "开启" if CS.doorOpen else "关闭",
                        "刹车灯": "亮起" if hasattr(CS, "brakeLights") and CS.brakeLights else "熄灭",

                        # 其他状态
                        "转向灯": "左转" if CS.leftBlinker else ("右转" if CS.rightBlinker else "关闭"),
                        "远光灯": "开启" if CS.genericToggle else "关闭",
                        "左盲区监测": "有车" if CS.leftBlindspot else "无车",
                        "右盲区监测": "有车" if CS.rightBlindspot else "无车",

                        # 高级功能
                        "车型": car_name,
                        "车型指纹": car_fingerprint,
                        "发动机转速": CS.engineRPM if hasattr(CS, "engineRPM") and CS.engineRPM > 0 else 0,

                        # 可选信息
                        "车外温度": f"{CS.outsideTemp:.1f}°C" if hasattr(CS, "outsideTemp") else "未知",
                        "燃油续航": f"{CS.fuelGauge:.1f}km" if hasattr(CS, "fuelGauge") else "未知",
                        "总里程": f"{CS.odometer:.1f}km" if hasattr(CS, "odometer") else "未知",
                        "瞬时油耗": f"{CS.instantFuelConsumption:.1f}L/100km" if hasattr(CS, "instantFuelConsumption") else "未知",

                        # 安全系统状态
                        "ESP状态": "已禁用" if hasattr(CS, "espDisabled") and CS.espDisabled else "正常",
                        "ABS状态": "激活" if hasattr(CS, "absActive") and CS.absActive else "正常",
                        "牵引力控制": "激活" if hasattr(CS, "tcsActive") and CS.tcsActive else "正常",
                        "碰撞警告": "警告" if hasattr(CS, "collisionWarning") and CS.collisionWarning else "正常",

                        # 车辆规格(如果有)
                        "车重": f"{car_specs.mass:.0f} kg" if car_specs and hasattr(car_specs, "mass") else "未知",
                        "轴距": f"{car_specs.wheelbase:.3f} m" if car_specs and hasattr(car_specs, "wheelbase") else "未知",
                        "转向比": f"{car_specs.steerRatio:.1f}" if car_specs and hasattr(car_specs, "steerRatio") else "未知",

                        # 时间戳
                        "更新时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        "运行状态": "行驶中" if is_car_started else "停止"
                    }

                    # 更新全局数据
                    with car_state_lock:
                        car_state_data = data
                        last_update_time = time.time()
                else:
                    # 如果没有车辆状态更新，仅更新系统状态
                    with car_state_lock:
                        # 只更新关键状态字段
                        car_state_data["openpilot状态"] = openpilot_status
                        car_state_data["数据状态"] = "正常" if can_data_available else "未检测到车辆数据"
                        car_state_data["连接状态"] = "已连接" if can_data_available else "未连接"
                        car_state_data["最后有效数据时间"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_valid_data_time)) if last_valid_data_time > 0 else "无数据"
                        car_state_data["更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                        car_state_data["自动驾驶"] = "激活" if is_active else "未激活"

            except Exception as e:
                print(f"更新车辆状态时出错: {e}")
                can_data_available = False

            # 每秒更新一次
            time.sleep(1)
    except Exception as e:
        print(f"初始化车辆状态监控时出错: {e}")
        import traceback
        traceback.print_exc()

# 启动后台线程
def start_background_thread():
    thread = threading.Thread(target=update_car_state_thread, daemon=True)
    thread.start()
    print("后台数据更新线程已启动")

# 主页路由
@app.route('/')
def index():
    # 在渲染初始模板时就传入基本数据
    return render_template('index.html', initial_data=json.dumps(car_state_data))

# API路由获取最新车辆状态
@app.route('/api/car_state')
def get_car_state():
    with car_state_lock:
        data = car_state_data.copy()

    # 确保返回成功，并打印日志以便调试
    print(f"API请求: 返回{len(data)}个数据项")
    return jsonify(data)

# 创建模板目录
def create_templates():
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(templates_dir, exist_ok=True)

    # 创建index.html
    index_html = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>车辆状态监控</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f4f4f4;
            color: #333;
        }
        .container {
            max-width: 100%;
            padding: 10px;
        }
        h1 {
            color: #2c3e50;
            font-size: 24px;
            margin-bottom: 20px;
            text-align: center;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 10px;
        }
        .status-card {
            background-color: #fff;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .status-card h3 {
            margin: 0 0 10px 0;
            font-size: 16px;
            color: #7f8c8d;
        }
        .status-value {
            font-size: 20px;
            font-weight: bold;
            color: #2980b9;
        }
        .status-unit {
            font-size: 14px;
            color: #95a5a6;
        }
        .update-time {
            text-align: center;
            margin-top: 20px;
            color: #7f8c8d;
            font-size: 14px;
        }
        .section-title {
            margin: 20px 0 10px 0;
            padding: 5px 10px;
            background-color: #34495e;
            color: white;
            border-radius: 4px;
            font-size: 18px;
        }

        /* 特殊状态颜色 */
        .status-normal { color: #27ae60; }
        .status-warning { color: #f39c12; }
        .status-danger { color: #e74c3c; }

        /* 数据连接警告 */
        .data-status-alert {
            background-color: #e74c3c;
            color: white;
            text-align: center;
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
            font-weight: bold;
            display: none;
        }

        /* openpilot状态标签 */
        .status-offroad {
            background-color: #e74c3c;
            color: white;
            padding: 5px 10px;
            border-radius: 4px;
            display: inline-block;
        }

        .status-onroad {
            background-color: #27ae60;
            color: white;
            padding: 5px 10px;
            border-radius: 4px;
            display: inline-block;
        }

        /* 加载指示器 */
        .loading {
            text-align: center;
            margin: 20px 0;
            display: none;
        }

        .loading-spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #3498db;
            border-radius: 50%;
            width: 30px;
            height: 30px;
            animation: spin 2s linear infinite;
            margin: 0 auto;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* 响应式调整 */
        @media (max-width: 600px) {
            .status-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .status-card {
                padding: 10px;
            }
            h1 {
                font-size: 20px;
            }
            .status-value {
                font-size: 18px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>车辆状态实时监控</h1>

        <!-- 数据连接状态警告 -->
        <div id="data-status-alert" class="data-status-alert">
            未检测到车辆CAN数据，请确保：
            <ul style="text-align: left; margin: 5px 20px;">
                <li>车辆已启动</li>
                <li>openpilot已正常运行</li>
                <li>CAN总线连接正常</li>
            </ul>
        </div>

        <!-- 加载指示器 -->
        <div id="loading" class="loading">
            <div class="loading-spinner"></div>
            <p>正在加载数据...</p>
        </div>

        <div class="section-title">系统状态</div>
        <div class="status-grid" id="system-status">
            <!-- 动态填充 -->
        </div>

        <div class="section-title">基本信息</div>
        <div class="status-grid" id="basic-info">
            <!-- 动态填充 -->
        </div>

        <div class="section-title">驾驶操作</div>
        <div class="status-grid" id="driving-controls">
            <!-- 动态填充 -->
        </div>

        <div class="section-title">巡航系统</div>
        <div class="status-grid" id="cruise-info">
            <!-- 动态填充 -->
        </div>

        <div class="section-title">安全系统</div>
        <div class="status-grid" id="safety-info">
            <!-- 动态填充 -->
        </div>

        <div class="section-title">车辆状态</div>
        <div class="status-grid" id="vehicle-status">
            <!-- 动态填充 -->
        </div>

        <div class="section-title">车辆规格</div>
        <div class="status-grid" id="vehicle-specs">
            <!-- 动态填充 -->
        </div>

        <div class="update-time" id="update-time">最后更新时间: 加载中...</div>
    </div>

    <script>
        // 获取初始数据
        let initialData = {{ initial_data|safe }};

        // 数据映射
        const dataConfig = {
            'system-status': [
                {key: 'openpilot状态', unit: '', custom: true},
                {key: '数据状态', unit: ''},
                {key: '连接状态', unit: ''},
                {key: '最后有效数据时间', unit: ''},
                {key: '自动驾驶', unit: ''}
            ],
            'basic-info': [
                {key: '车速', unit: 'km/h'},
                {key: '加速度', unit: 'm/s²'},
                {key: '发动机转速', unit: 'RPM'},
                {key: '总里程', unit: ''},
                {key: '车型', unit: ''},
                {key: '运行状态', unit: ''}
            ],
            'driving-controls': [
                {key: '方向盘角度', unit: '°'},
                {key: '方向盘转矩', unit: 'Nm'},
                {key: '方向盘速率', unit: '°/s'},
                {key: '油门踏板', unit: '%'},
                {key: '刹车踏板', unit: ''},
                {key: '刹车压力', unit: ''},
                {key: '档位', unit: ''},
                {key: '档位步数', unit: ''}
            ],
            'cruise-info': [
                {key: '巡航系统', unit: ''},
                {key: '巡航速度', unit: 'km/h'},
                {key: '巡航状态', unit: ''},
                {key: '巡航跟车距离', unit: '档位'}
            ],
            'safety-info': [
                {key: '安全带状态', unit: ''},
                {key: '车门状态', unit: ''},
                {key: '刹车灯', unit: ''},
                {key: 'ESP状态', unit: ''},
                {key: 'ABS状态', unit: ''},
                {key: '牵引力控制', unit: ''},
                {key: '碰撞警告', unit: ''},
                {key: '左盲区监测', unit: ''},
                {key: '右盲区监测', unit: ''}
            ],
            'vehicle-status': [
                {key: '左前轮速度', unit: 'km/h'},
                {key: '右前轮速度', unit: 'km/h'},
                {key: '左后轮速度', unit: 'km/h'},
                {key: '右后轮速度', unit: 'km/h'},
                {key: '转向灯', unit: ''},
                {key: '远光灯', unit: ''},
                {key: '车外温度', unit: ''},
                {key: '燃油续航', unit: ''},
                {key: '瞬时油耗', unit: ''}
            ],
            'vehicle-specs': [
                {key: '车型指纹', unit: ''},
                {key: '车重', unit: ''},
                {key: '轴距', unit: ''},
                {key: '转向比', unit: ''}
            ]
        };

        // 设置状态类
        function getStatusClass(key, value) {
            if (key === '数据状态' && value !== '正常') {
                return 'status-danger';
            }
            if (key === '连接状态' && value !== '已连接') {
                return 'status-danger';
            }
            if (key === '车速') {
                return parseInt(value) > 120 ? 'status-danger' : (parseInt(value) > 80 ? 'status-warning' : 'status-normal');
            }
            if (key === '前车距离') {
                return parseFloat(value) < 20 ? 'status-danger' : (parseFloat(value) < 40 ? 'status-warning' : 'status-normal');
            }
            if (key === '碰撞时间') {
                return parseFloat(value) < 1.5 ? 'status-danger' : (parseFloat(value) < 3 ? 'status-warning' : 'status-normal');
            }
            if (key === 'ESP状态' && value !== '正常') {
                return 'status-warning';
            }
            if (key === 'ABS状态' && value !== '正常') {
                return 'status-warning';
            }
            if (key === '碰撞警告' && value !== '正常') {
                return 'status-danger';
            }
            // 其他状态颜色映射
            return 'status-normal';
        }

        // 更新状态卡片
        function updateStatusCards(data) {
            console.log("收到数据更新:", data);

            // 隐藏加载指示器
            document.getElementById('loading').style.display = 'none';

            // 检查CAN数据状态并显示警告
            const dataStatusAlert = document.getElementById('data-status-alert');
            if (data['数据状态'] === '未检测到车辆数据') {
                dataStatusAlert.style.display = 'block';
            } else {
                dataStatusAlert.style.display = 'none';
            }

            // 更新各部分数据
            for (const [sectionId, items] of Object.entries(dataConfig)) {
                const section = document.getElementById(sectionId);
                section.innerHTML = '';

                items.forEach(item => {
                    // 即使数据不存在也创建一个默认卡片
                    const card = document.createElement('div');
                    card.className = 'status-card';

                    const title = document.createElement('h3');
                    title.textContent = item.key;
                    card.appendChild(title);

                    if (item.custom && item.key === 'openpilot状态') {
                        // 特殊处理openpilot状态
                        const valueSpan = document.createElement('span');
                        const status = data[item.key] || 'OFFROAD';
                        valueSpan.className = status === 'ONROAD' ? 'status-onroad' : 'status-offroad';
                        valueSpan.textContent = status;
                        card.appendChild(valueSpan);
                    } else {
                        const valueSpan = document.createElement('span');
                        const value = data[item.key] !== undefined ? data[item.key] : (typeof item.unit === 'number' ? 0 : '未知');
                        valueSpan.className = `status-value ${getStatusClass(item.key, value)}`;
                        valueSpan.textContent = value;

                        const unitSpan = document.createElement('span');
                        unitSpan.className = 'status-unit';
                        unitSpan.textContent = ' ' + item.unit;

                        card.appendChild(valueSpan);
                        card.appendChild(unitSpan);
                    }

                    section.appendChild(card);
                });
            }

            // 更新时间
            document.getElementById('update-time').textContent = `最后更新时间: ${data['更新时间'] || '未更新'}`;
        }

        // 立即显示初始数据
        updateStatusCards(initialData);

        // 定期获取数据
        function fetchData() {
            console.log("正在获取最新数据...");

            // 显示加载指示器，但延迟显示，避免闪烁
            const loadingTimeout = setTimeout(() => {
                document.getElementById('loading').style.display = 'block';
            }, 500);

            fetch('/api/car_state')
                .then(response => {
                    console.log("API响应状态:", response.status);
                    if (!response.ok) {
                        throw new Error(`HTTP错误 ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    // 清除加载超时
                    clearTimeout(loadingTimeout);

                    console.log("获取到数据，包含", Object.keys(data).length, "个项目");
                    // 确保data是一个有效的对象
                    if (data && typeof data === 'object') {
                        updateStatusCards(data);
                    } else {
                        throw new Error('收到无效数据');
                    }
                })
                .catch(error => {
                    // 清除加载超时
                    clearTimeout(loadingTimeout);

                    console.error('获取数据失败:', error);
                    document.getElementById('data-status-alert').style.display = 'block';
                    document.getElementById('data-status-alert').innerHTML = `
                        数据获取失败，请检查网络连接<br>
                        错误: ${error}
                    `;
                })
                .finally(() => {
                    // 每秒刷新一次
                    setTimeout(fetchData, 1000);
                });
        }

        // 页面加载后开始获取数据
        document.addEventListener('DOMContentLoaded', () => {
            // 显示初始数据
            console.log("初始化数据:", initialData);
            updateStatusCards(initialData);

            // 开始定期获取数据
            setTimeout(fetchData, 1000);
        });
    </script>
</body>
</html>
    '''

    with open(os.path.join(templates_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_html)

    print(f"创建模板目录: {templates_dir}")

# 主函数
if __name__ == '__main__':
    # 确保模板目录存在
    create_templates()

    # 启动后台线程 - 在Flask应用启动前手动启动线程
    start_background_thread()

    # 启动Flask应用
    host = '0.0.0.0'  # 监听所有网络接口
    port = 8080       # 使用8080端口

    print(f"启动车辆状态监控Web服务，访问地址: http://<设备IP>:{port}/")
    app.run(host=host, port=port, debug=False, threaded=True)
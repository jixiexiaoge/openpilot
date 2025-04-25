#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import socket
import threading
from flask import Flask, render_template, jsonify
from datetime import datetime

# 创建Flask应用
app = Flask(__name__)
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
app.config['JSON_AS_ASCII'] = False

# 全局变量
car_state_data = {}  # 存储最新的车辆状态数据
discovered_devices = {}  # 已发现的设备列表
last_received_time = {}  # 最后一次接收数据的时间
data_lock = threading.Lock()  # 数据锁
udp_port = 8088  # UDP监听端口
timeout = 10  # 设备超时时间（秒）

def create_udp_socket():
    """创建UDP套接字"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', udp_port))
    return sock

def clean_timeout_devices():
    """清理超时设备"""
    current_time = time.time()
    with data_lock:
        for ip in list(last_received_time.keys()):
            if current_time - last_received_time[ip] > timeout:
                if ip in discovered_devices:
                    print(f"设备 {ip} 已超时，从列表中移除")
                    del discovered_devices[ip]
                del last_received_time[ip]

def udp_receiver_thread():
    """UDP接收线程"""
    print(f"启动UDP接收线程，监听端口: {udp_port}")
    sock = create_udp_socket()

    while True:
        try:
            # 接收数据
            data, addr = sock.recvfrom(4096)
            sender_ip = addr[0]

            try:
                # 解析JSON数据
                json_data = json.loads(data.decode('utf-8'))

                # 更新设备列表
                with data_lock:
                    discovered_devices[sender_ip] = json_data
                    last_received_time[sender_ip] = time.time()

                # 清理超时设备
                clean_timeout_devices()

            except json.JSONDecodeError as e:
                print(f"收到无效JSON数据: {e}")
            except Exception as e:
                print(f"处理数据时出错: {e}")

        except Exception as e:
            print(f"接收UDP数据时出错: {e}")
            time.sleep(1)  # 出错时等待一秒再继续

def create_templates():
    """创建模板目录和文件"""
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
        .device-selector {
            margin: 20px auto;
            text-align: center;
        }
        select {
            padding: 8px;
            font-size: 16px;
            border-radius: 4px;
            border: 1px solid #bdc3c7;
            width: 80%;
            max-width: 400px;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 10px;
            margin: 20px 0;
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
        .section-title {
            margin: 20px 0 10px 0;
            padding: 5px 10px;
            background-color: #34495e;
            color: white;
            border-radius: 4px;
            font-size: 18px;
        }
        .status-normal { color: #27ae60; }
        .status-warning { color: #f39c12; }
        .status-danger { color: #e74c3c; }
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
        .update-time {
            text-align: center;
            margin-top: 20px;
            color: #7f8c8d;
            font-size: 14px;
        }
        .no-data {
            text-align: center;
            padding: 20px;
            color: #e74c3c;
            font-size: 18px;
            background-color: #ffd7d7;
            border-radius: 4px;
            margin: 20px 0;
        }
        .ui-text-card {
            background-color: #fff;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 15px;
        }
        .ui-text-title {
            font-size: 16px;
            color: #7f8c8d;
            margin-bottom: 5px;
        }
        .ui-text-content {
            font-size: 18px;
            font-weight: bold;
            color: #2980b9;
            padding: 8px;
            background-color: #f8f9fa;
            border-radius: 4px;
            border-left: 4px solid #3498db;
        }
        .traffic-signal {
            display: flex;
            justify-content: space-between;
            margin-bottom: 15px;
            align-items: center;
        }
        .traffic-text {
            font-size: 18px;
            font-weight: bold;
            flex: 1;
        }
        .traffic-status {
            font-size: 20px;
            font-weight: bold;
            padding: 8px 15px;
            border-radius: 20px;
            color: white;
            text-align: center;
            min-width: 80px;
        }
        .traffic-none {
            background-color: #95a5a6;
        }
        .traffic-red {
            background-color: #e74c3c;
        }
        .traffic-green {
            background-color: #27ae60;
        }
        @media (max-width: 600px) {
            .status-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .status-card {
                padding: 10px;
            }
            .status-value {
                font-size: 16px;
            }
            h1 {
                font-size: 20px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>车辆状态实时监控</h1>

        <div class="device-selector">
            <select id="deviceSelect" onchange="updateSelectedDevice()">
                <option value="">选择设备...</option>
            </select>
        </div>

        <div id="noDataAlert" class="no-data" style="display: none;">
            未检测到任何设备，请确保：
            <ul style="text-align: left; margin: 10px 20px;">
                <li>车辆状态广播服务正在运行</li>
                <li>设备在同一局域网内</li>
                <li>UDP端口8088未被占用</li>
            </ul>
        </div>

        <div id="deviceData" style="display: none;">
            <div class="section-title">系统状态</div>
            <div class="status-grid" id="systemStatus"></div>

            <div class="section-title">交通信号</div>
            <div class="traffic-signal">
                <span class="traffic-text">信号状态:</span>
                <span class="traffic-status traffic-none" id="trafficSignal">无信号</span>
            </div>

            <div class="section-title">UI显示文本</div>
            <div id="uiTextInfo">
                <div class="ui-text-card">
                    <div class="ui-text-title">顶部文本:</div>
                    <div class="ui-text-content" id="topText">识别信息</div>
                </div>
                <div class="ui-text-card">
                    <div class="ui-text-title">底部文本:</div>
                    <div class="ui-text-content" id="bottomText">车道信息</div>
                </div>
            </div>

            <div class="section-title">基本信息</div>
            <div class="status-grid" id="basicInfo"></div>

            <div class="section-title">前车信息</div>
            <div class="status-grid" id="leadInfo"></div>

            <div class="section-title">巡航状态</div>
            <div class="status-grid" id="cruiseInfo"></div>

            <div class="section-title">车辆状态</div>
            <div class="status-grid" id="vehicleStatus"></div>

            <div class="section-title">其他数据</div>
            <div class="status-grid" id="otherData"></div>

            <div class="section-title">曲率数据</div>
            <div class="status-grid" id="curvatureInfo"></div>
        </div>

        <div class="update-time" id="updateTime">最后更新: 等待数据...</div>
    </div>

    <script>
        let currentDevice = '';
        const dataConfig = {
            'systemStatus': [
                {key: 'openpilot_status', label: 'openpilot状态', unit: ''},
                {key: 'active', label: '自动驾驶', unit: ''},
                {key: 'started', label: '系统状态', unit: ''},
                {key: 'onroad', label: '行驶状态', unit: ''},
                {key: 'apply_speed', label: '建议车速', unit: 'km/h'},
                {key: 'apply_source', label: '建议来源', unit: ''}
            ],
            'basicInfo': [
                {key: 'v_ego', label: '车速', unit: 'km/h'},
                {key: 'a_ego', label: '加速度', unit: 'm/s²'},
                {key: 'apply_speed', label: '建议车速', unit: 'km/h'},
                {key: 'apply_source', label: '建议来源', unit: ''},
                {key: 'engine_rpm', label: '发动机转速', unit: 'RPM'},
                {key: 'steering_angle', label: '方向盘角度', unit: '°'},
                {key: 'steering_torque', label: '方向盘转矩', unit: 'Nm'}
            ],
            'leadInfo': [
                {key: 'lead_info.detected', label: '前车检测', unit: ''},
                {key: 'lead_info.speed', label: '前车速度', unit: 'km/h'},
                {key: 'lead_info.distance', label: '前车距离', unit: 'm'},
                {key: 'pcm_cruise_gap', label: '跟车间距', unit: '档'}
            ],
            'cruiseInfo': [
                {key: 'cruise_enabled', label: '巡航状态', unit: ''},
                {key: 'cruise_speed', label: '巡航速度', unit: 'km/h'},
                {key: 'cruise_available', label: '巡航可用', unit: ''}
            ],
            'vehicleStatus': [
                {key: 'gas', label: '油门', unit: '%'},
                {key: 'brake_pressed', label: '刹车', unit: ''},
                {key: 'door_open', label: '车门', unit: ''},
                {key: 'seatbelt_unlatched', label: '安全带', unit: ''},
                {key: 'left_blinker', label: '左转向', unit: ''},
                {key: 'right_blinker', label: '右转向', unit: ''}
            ],
            'curvatureInfo': [
                {key: 'actuator_curvature', label: '控制器曲率', unit: ''},
                {key: 'model_curvature', label: '模型曲率', unit: ''},
                {key: 'current_curvature', label: '当前曲率', unit: ''},
                {key: 'curvature_change', label: '曲率变化', unit: ''},
                {key: 'speed_from_pcm', label: '速度控制', unit: ''}
            ]
        };

        const excludedKeys = [
            'openpilot_status', 'active', 'started', 'onroad',
            'v_ego', 'a_ego', 'engine_rpm', 'steering_angle', 'steering_torque',
            'lead_info', 'pcm_cruise_gap',
            'cruise_enabled', 'cruise_speed', 'cruise_available',
            'gas', 'brake_pressed', 'door_open', 'seatbelt_unlatched',
            'left_blinker', 'right_blinker',
            'top_text', 'bottom_text', 'traffic_state', 'traffic_state_text',
            'actuator_curvature', 'model_curvature', 'current_curvature', 'curvature_change', 'speed_from_pcm'
        ];

        function getNestedValue(obj, path) {
            return path.split('.').reduce((acc, part) => acc && acc[part], obj);
        }

        function formatSpeedFromPCM(value) {
            const status = {
                0: "减速",
                1: "正常",
                2: "弯道"
            };
            return status[value] || "未知";
        }

        function formatValue(key, value) {
            if (value === undefined || value === null) return '--';
            if (key === 'speed_from_pcm') {
                return formatSpeedFromPCM(value);
            }
            if (typeof value === 'boolean') {
                return value ? '是' : '否';
            }
            if (typeof value === 'number') {
                return value.toFixed(1);
            }
            return value;
        }

        function updateSelectedDevice() {
            currentDevice = document.getElementById('deviceSelect').value;
            if (currentDevice) {
                document.getElementById('deviceData').style.display = 'block';
                fetchData();
            } else {
                document.getElementById('deviceData').style.display = 'none';
            }
        }

        function updateDeviceList(devices) {
            const select = document.getElementById('deviceSelect');
            const currentValue = select.value;
            const deviceIps = Object.keys(devices);

            // 清除现有选项
            while (select.options.length > 1) {
                select.remove(1);
            }

            // 添加新选项
            deviceIps.forEach(ip => {
                const option = new Option(ip, ip);
                select.add(option);
            });

            // 如果当前选中的设备还在列表中，保持选中
            if (deviceIps.includes(currentValue)) {
                select.value = currentValue;
            } else if (deviceIps.length > 0 && !currentValue) {
                // 如果没有选中的设备但有可用设备，选择第一个
                select.value = deviceIps[0];
                currentDevice = deviceIps[0];
                document.getElementById('deviceData').style.display = 'block';
            }

            // 显示/隐藏无数据提示
            document.getElementById('noDataAlert').style.display =
                deviceIps.length === 0 ? 'block' : 'none';
        }

        function updateStatusSection(sectionId, data) {
            const section = document.getElementById(sectionId);
            section.innerHTML = '';

            dataConfig[sectionId].forEach(item => {
                const value = getNestedValue(data, item.key);
                const formattedValue = formatValue(item.key, value);

                const card = document.createElement('div');
                card.className = 'status-card';

                const title = document.createElement('h3');
                title.textContent = item.label;
                card.appendChild(title);

                const valueSpan = document.createElement('span');
                valueSpan.className = 'status-value';
                valueSpan.textContent = formattedValue;

                if (item.unit) {
                    const unitSpan = document.createElement('span');
                    unitSpan.className = 'status-unit';
                    unitSpan.textContent = ' ' + item.unit;
                    card.appendChild(valueSpan);
                    card.appendChild(unitSpan);
                } else {
                    card.appendChild(valueSpan);
                }

                section.appendChild(card);
            });
        }

        function updateDisplay(data) {
            if (!data || !currentDevice || !data[currentDevice]) return;

            const deviceData = data[currentDevice];

            // 更新各个部分
            Object.keys(dataConfig).forEach(section => {
                updateStatusSection(section, deviceData);
            });

            // 更新其他所有数据
            const otherDataSection = document.getElementById('otherData');
            otherDataSection.innerHTML = '';

            Object.entries(deviceData).forEach(([key, value]) => {
                // 跳过已经在其他部分显示的数据
                if (excludedKeys.includes(key) || key.includes('.')) return;

                const card = document.createElement('div');
                card.className = 'status-card';

                const title = document.createElement('h3');
                // 将下划线替换为空格，并将首字母大写
                title.textContent = key.replace(/_/g, ' ')
                    .replace(/\b\w/g, l => l.toUpperCase());
                card.appendChild(title);

                const valueSpan = document.createElement('span');
                valueSpan.className = 'status-value';
                valueSpan.textContent = formatValue(key, value);
                card.appendChild(valueSpan);

                otherDataSection.appendChild(card);
            });

            // 更新UI文本字段
            document.getElementById('topText').textContent = deviceData.top_text || '识别信息';
            document.getElementById('bottomText').textContent = deviceData.bottom_text || '车道信息';

            // 更新交通信号灯状态
            const trafficSignal = document.getElementById('trafficSignal');
            const trafficState = deviceData.traffic_state || 0;
            const trafficText = deviceData.traffic_state_text || '无信号';

            trafficSignal.textContent = trafficText;

            // 移除旧的类
            trafficSignal.classList.remove('traffic-none', 'traffic-red', 'traffic-green');

            // 添加对应的类
            if (trafficState === 1) {
                trafficSignal.classList.add('traffic-red');
            } else if (trafficState === 2) {
                trafficSignal.classList.add('traffic-green');
            } else {
                trafficSignal.classList.add('traffic-none');
            }

            // 更新时间戳
            document.getElementById('updateTime').textContent =
                '最后更新: ' + new Date().toLocaleString();
        }

        function fetchData() {
            fetch('/api/car_state')
                .then(response => response.json())
                .then(data => {
                    updateDeviceList(data);
                    updateDisplay(data);
                })
                .catch(error => console.error('获取数据失败:', error))
                .finally(() => {
                    setTimeout(fetchData, 1000);
                });
        }

        // 页面加载后开始获取数据
        document.addEventListener('DOMContentLoaded', fetchData);
    </script>
</body>
</html>
    '''

    with open(os.path.join(templates_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_html)

@app.route('/')
def index():
    """主页路由"""
    return render_template('index.html')

@app.route('/api/car_state')
def get_car_state():
    """API路由获取最新车辆状态"""
    with data_lock:
        return jsonify(discovered_devices)

def main():
    """主函数"""
    # 创建模板目录
    create_templates()

    # 启动UDP接收线程
    receiver_thread = threading.Thread(target=udp_receiver_thread, daemon=True)
    receiver_thread.start()

    # 获取本机IP地址
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    # 启动Flask应用
    print(f"启动Web服务，访问地址: http://{local_ip}:8080/")
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)

if __name__ == '__main__':
    main()
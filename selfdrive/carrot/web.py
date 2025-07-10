#!/usr/bin/env python3
"""
车辆监控网页应用
接收UDP广播的车辆数据并在网页上实时显示
兼容大多数Python环境

修改说明：
- 更新dataConfig以匹配基于mazda carstate.py修改后的数据结构
- 支持新增的字段如 Gear Step, Standstill, Steering Pressed等
- 移除了不适用于mazda的字段（如安全系统的详细状态）
- 增加了系统状态监控面板
"""

import json
import socket
import threading
import time
from datetime import datetime
from flask import Flask, render_template_string, jsonify
from flask_socketio import SocketIO, emit


class VehicleDataReceiver:
    def __init__(self):
        self.latest_data = None
        self.last_update_time = None
        self.is_running = True

        # UDP接收配置
        self.listen_port = 8080

        # 启动UDP接收线程
        self.receiver_thread = threading.Thread(target=self.receive_udp_data)
        self.receiver_thread.daemon = True
        self.receiver_thread.start()

    def receive_udp_data(self):
        """接收UDP广播数据"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind(('', self.listen_port))
            print(f"开始监听端口 {self.listen_port} 的UDP广播...")

            while self.is_running:
                try:
                    data, addr = sock.recvfrom(65536)  # 64KB缓冲区

                    # 解析JSON数据
                    json_data = json.loads(data.decode('utf-8'))
                    self.latest_data = json_data
                    self.last_update_time = datetime.now()

                    print(f"收到来自 {addr} 的数据: 状态={json_data.get('status', 'unknown')}")

                except json.JSONDecodeError as e:
                    print(f"JSON解析错误: {e}")
                except Exception as e:
                    print(f"接收数据时出错: {e}")

        except Exception as e:
            print(f"UDP接收器启动失败: {e}")
        finally:
            sock.close()

    def get_latest_data(self):
        """获取最新数据"""
        return self.latest_data, self.last_update_time

    def stop(self):
        """停止接收"""
        self.is_running = False


# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = 'vehicle_monitor_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# 创建数据接收器
data_receiver = VehicleDataReceiver()

# HTML模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>车辆实时监控</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            color: white;
            background: rgba(255, 255, 255, 0.1);
            padding: 20px;
            border-radius: 12px;
            backdrop-filter: blur(10px);
        }
        .header h1 {
            margin: 0 0 10px 0;
            font-size: 2.5em;
        }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        .status-online { background-color: #4CAF50; }
        .status-offline { background-color: #f44336; }
        .status-warning { background-color: #ff9800; }

        .main-dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .card {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            transition: transform 0.2s ease;
        }
        .card:hover {
            transform: translateY(-2px);
        }
        .card h3 {
            margin: 0 0 20px 0;
            color: #2c3e50;
            font-size: 1.3em;
            font-weight: 600;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
            display: flex;
            align-items: center;
        }
        .card-icon {
            margin-right: 10px;
            font-size: 1.2em;
        }
        .data-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid rgba(0, 0, 0, 0.05);
            transition: all 0.3s ease;
        }
        .data-item:last-child {
            border-bottom: none;
        }
        .data-item.updated {
            background-color: #e3f2fd;
            border-radius: 6px;
            padding: 12px;
            margin: 2px 0;
        }
        .data-label {
            font-weight: 500;
            color: #555;
            font-size: 0.95em;
        }
        .data-value {
            font-weight: 600;
            color: #2c3e50;
            font-size: 1em;
        }
        .speed-highlight {
            font-size: 1.8em;
            color: #3498db;
            font-weight: bold;
        }
        .status-value {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 500;
            text-transform: uppercase;
        }
                 .status-enabled { background-color: #d4edda; color: #155724; }
         .status-disabled { background-color: #f8d7da; color: #721c24; }
         .status-active { background-color: #d1ecf1; color: #0c5460; }
         .status-normal { background-color: #e2e3e5; color: #383d41; }
         .status-warning { background-color: #fff3cd; color: #856404; }

        .timestamp {
            text-align: center;
            color: rgba(255, 255, 255, 0.8);
            font-size: 0.9em;
            margin-top: 20px;
            padding: 10px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 8px;
        }
        .error-message {
            background: linear-gradient(45deg, #ff6b6b, #ff8e8e);
            color: white;
            padding: 20px;
            border-radius: 12px;
            margin: 20px 0;
            text-align: center;
            font-weight: 500;
        }
        .no-data {
            text-align: center;
            color: rgba(255, 255, 255, 0.8);
            padding: 60px;
            font-size: 1.2em;
        }
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255, 255, 255, 0.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s ease-in-out infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚗 车辆实时监控系统</h1>
            <div id="connection-status">
                <span class="status-indicator status-offline"></span>
                <span id="status-text">等待连接...</span>
            </div>
        </div>

        <div id="vehicle-data">
            <div class="no-data">
                <div class="loading"></div>
                <p>等待车辆数据...</p>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let isInitialized = false;
        let previousData = null;

        // 数据结构配置 - 匹配 mazda carstate.py 的数据结构
        const dataConfig = {
            "Basic Information": {
                title: '� 基本信息',
                fields: {
                    "Car Model": '车辆型号',
                    "Fingerprint": '车辆指纹',
                    "Weight": '车重',
                    "Wheelbase": '轴距',
                    "Steering Ratio": '转向比'
                }
            },
            "Vehicle Status": {
                title: '🚗 车辆状态',
                fields: {
                    "Running Status": '运行状态',
                    "Cruise System": '巡航系统',
                    "Current Speed": '当前速度',
                    "Engine RPM": '发动机转速',
                    "Gear Position": '挡位',
                    "Gear Step": '变速箱档位'
                }
            },
            "Cruise Information": {
                title: '🎯 巡航信息',
                fields: {
                    "Cruise Status": '巡航状态',
                    "Adaptive Cruise": '自适应巡航',
                    "Set Speed": '设定速度',
                    "Following Distance": '跟车距离',
                    "Standstill": '静止状态'
                }
            },
            "Wheel Speeds": {
                title: '🛞 车轮速度',
                fields: {
                    "Front Left": '前左',
                    "Front Right": '前右',
                    "Rear Left": '后左',
                    "Rear Right": '后右'
                }
            },
            "Steering System": {
                title: '🎯 转向系统',
                fields: {
                    "Steering Angle": '转向角度',
                    "Steering Torque": '转向扭矩',
                    "Steering Rate": '转向速率',
                    "Steering Pressed": '方向盘被握持',
                    "Steering EPS Torque": 'EPS扭矩'
                }
            },
            "Pedal Status": {
                title: '🦶 踏板状态',
                fields: {
                    "Gas Position": '油门位置',
                    "Brake Pressure": '刹车压力',
                    "Gas Pedal": '油门踏板',
                    "Brake Pedal": '刹车踏板'
                }
            },
            "Door Status": {
                title: '🚪 车门状态',
                fields: {
                    "Any Door Open": '车门开启',
                    "Seatbelt": '安全带'
                }
            },
            "Light Status": {
                title: '💡 灯光状态',
                fields: {
                    "Left Turn Signal": '左转向灯',
                    "Right Turn Signal": '右转向灯',
                    "High Beam": '远光灯'
                }
            },
            "Blind Spot Monitor": {
                title: '👁️ 盲点监控',
                fields: {
                    "Left Side": '左侧检测',
                    "Right Side": '右侧检测'
                }
            },
            "System Status": {
                title: '⚠️ 系统状态',
                fields: {
                    "Low Speed Alert": '低速警告',
                    "Steer Fault Temporary": '转向临时故障',
                    "Steer Fault Permanent": '转向永久故障'
                }
            },
            "selfdrive_status": {
                title: '🤖 自驾状态',
                fields: {
                    "active": '自驾激活',
                    "state": '自驾状态'
                }
            },
            "device_status": {
                title: '📱 设备状态',
                fields: {
                    "network_type": '网络类型',
                    "memory_usage_percent": '内存使用率',
                    "free_space_percent": '剩余空间',
                    "thermal_status": '温度状态',
                    "cpu_temp_c": 'CPU温度',
                    "max_temp_c": '最高温度'
                }
            }
        };

        socket.on('connect', function() {
            document.getElementById('status-text').textContent = '已连接';
            document.querySelector('.status-indicator').className = 'status-indicator status-online';
        });

        socket.on('disconnect', function() {
            document.getElementById('status-text').textContent = '连接断开';
            document.querySelector('.status-indicator').className = 'status-indicator status-offline';
        });

        socket.on('vehicle_data', function(data) {
            updateVehicleData(data);
        });

        function updateVehicleData(data) {
            const container = document.getElementById('vehicle-data');

            if (!data) {
                container.innerHTML = '<div class="no-data">暂无车辆数据</div>';
                return;
            }

            if (data.status === 'error') {
                container.innerHTML = `<div class="error-message">❌ 错误: ${data.error_message}</div>`;
                return;
            }

            // 首次初始化或需要重建结构
            if (!isInitialized) {
                buildInitialLayout(data);
                isInitialized = true;
            } else {
                // 仅更新数据值
                updateDataValues(data);
            }

            // 更新时间戳
            updateTimestamp(data.timestamp);
            previousData = data;
        }

                function buildInitialLayout(data) {
            const container = document.getElementById('vehicle-data');
            let html = '<div class="main-dashboard">';

            // 遍历配置，构建卡片
            Object.entries(dataConfig).forEach(([sectionKey, config]) => {
                if (data[sectionKey]) {
                    const sectionId = sectionKey.replace(/\s+/g, '-').toLowerCase();
                    html += `<div class="card" id="card-${sectionId}">`;
                    html += `<h3><span class="card-icon">${config.title.split(' ')[0]}</span>${config.title.substring(2)}</h3>`;

                    Object.entries(config.fields).forEach(([fieldKey, fieldLabel]) => {
                        const value = data[sectionKey][fieldKey];
                        const displayValue = formatValue(fieldKey, value);
                        const fieldId = fieldKey.replace(/\s+/g, '-').toLowerCase();

                        html += `<div class="data-item" id="item-${sectionId}-${fieldId}">`;
                        html += `<span class="data-label">${fieldLabel}:</span>`;
                        html += `<span class="data-value" id="value-${sectionId}-${fieldId}">${displayValue}</span>`;
                        html += `</div>`;
                    });

                    html += '</div>';
                }
            });

            html += '</div>';
            container.innerHTML = html;
        }

                function updateDataValues(data) {
            Object.entries(dataConfig).forEach(([sectionKey, config]) => {
                if (data[sectionKey]) {
                    const sectionId = sectionKey.replace(/\s+/g, '-').toLowerCase();
                    Object.entries(config.fields).forEach(([fieldKey, fieldLabel]) => {
                        const newValue = data[sectionKey][fieldKey];
                        const fieldId = fieldKey.replace(/\s+/g, '-').toLowerCase();
                        const element = document.getElementById(`value-${sectionId}-${fieldId}`);
                        const itemElement = document.getElementById(`item-${sectionId}-${fieldId}`);

                        if (element) {
                            const oldValue = previousData && previousData[sectionKey] ? previousData[sectionKey][fieldKey] : null;
                            const displayValue = formatValue(fieldKey, newValue);

                            if (oldValue !== newValue) {
                                element.innerHTML = displayValue;

                                // 添加更新动画
                                if (itemElement) {
                                    itemElement.classList.add('updated');
                                    setTimeout(() => {
                                        itemElement.classList.remove('updated');
                                    }, 1000);
                                }
                            }
                        }
                    });
                }
            });
        }

        function formatValue(fieldKey, value) {
            if (value === null || value === undefined || value === "Unknown") {
                return '未知';
            }

            // 速度高亮显示
            if (fieldKey.includes('Speed') && typeof value === 'string' && value.includes('km/h')) {
                const speedMatch = value.match(/(\d+\.?\d*)/);
                if (speedMatch) {
                    const speed = speedMatch[1];
                    return `<span class="speed-highlight">${speed}</span> km/h`;
                }
            }

            // 转速高亮显示
            if (fieldKey.includes('RPM') && typeof value === 'string' && value.includes('RPM')) {
                const rpmMatch = value.match(/(\d+)/);
                if (rpmMatch) {
                    const rpm = rpmMatch[1];
                    return `<span class="speed-highlight">${rpm}</span> RPM`;
                }
            }

            // 挡位显示格式化
            if (fieldKey === 'Gear Position') {
                if (value === 'Unknown' || !value) {
                    return '未知';
                }
                let gearText = value;
                if (value.toString().toLowerCase().includes('park')) gearText = 'P档';
                else if (value.toString().toLowerCase().includes('reverse')) gearText = 'R档';
                else if (value.toString().toLowerCase().includes('neutral')) gearText = 'N档';
                else if (value.toString().toLowerCase().includes('drive')) gearText = 'D档';
                else if (value.toString().match(/^\d+$/)) gearText = `${value}档`;
                return `<span class="status-value status-normal">${gearText}</span>`;
            }

            // 跟车距离格式化
            if (fieldKey === 'Following Distance') {
                if (value === 'Unknown' || !value || value === '0') {
                    return '未设置';
                }
                return `<span class="status-value status-normal">${value}档</span>`;
            }

            // 刹车压力特殊格式化 (原始值 0-255)
            if (fieldKey === 'Brake Pressure') {
                if (value === 'Unknown' || !value || value === '0' || value === '0.0') {
                    return '无压力';
                }
                const numValue = parseFloat(value);
                if (!isNaN(numValue)) {
                    const percentage = ((numValue / 255) * 100).toFixed(1);
                    return `${numValue} <span style="color: #666; font-size: 0.9em;">(${percentage}%)</span>`;
                }
                return value;
            }

            // 状态值格式化
            if (fieldKey.includes('Status') || fieldKey.includes('System')) {
                let className = 'status-normal';
                if (value === 'On' || value === 'Enabled' || value === 'Active') {
                    className = 'status-enabled';
                } else if (value === 'Off' || value === 'Disabled' || value === 'Normal') {
                    className = 'status-disabled';
                } else if (value === 'Warning') {
                    className = 'status-warning';
                }
                return `<span class="status-value ${className}">${value}</span>`;
            }

            // 踏板状态格式化
            if (fieldKey.includes('Pedal')) {
                const className = value === 'Pressed' ? 'status-enabled' : 'status-disabled';
                return `<span class="status-value ${className}">${value}</span>`;
            }

            // 车门状态格式化
            if (fieldKey.includes('Door') || fieldKey === 'Trunk' || fieldKey === 'Hood' || fieldKey === 'Seatbelt') {
                const className = value === 'Open' || value === 'Unbuckled' ? 'status-warning' : 'status-normal';
                return `<span class="status-value ${className}">${value}</span>`;
            }

            // 灯光状态格式化
            if (fieldKey.includes('Turn Signal') || fieldKey.includes('Beam')) {
                const className = value === 'On' ? 'status-enabled' : 'status-disabled';
                return `<span class="status-value ${className}">${value}</span>`;
            }

            // 盲点监控格式化
            if (fieldKey.includes('Side')) {
                const className = value === 'Vehicle Detected' ? 'status-warning' : 'status-normal';
                return `<span class="status-value ${className}">${value}</span>`;
            }

            // 变道检测格式化
            if (fieldKey === 'Lane Departure') {
                const className = value === 'Yes' ? 'status-warning' : 'status-normal';
                return `<span class="status-value ${className}">${value}</span>`;
            }

            // 布尔值格式化 (for device status)
            if (typeof value === 'boolean') {
                const className = value ? 'status-enabled' : 'status-disabled';
                const text = value ? '是' : '否';
                return `<span class="status-value ${className}">${text}</span>`;
            }

            return value;
        }

        function updateTimestamp(timestamp) {
            let timestampElement = document.getElementById('timestamp');
            if (!timestampElement) {
                timestampElement = document.createElement('div');
                timestampElement.id = 'timestamp';
                timestampElement.className = 'timestamp';
                document.querySelector('.container').appendChild(timestampElement);
            }

            if (timestamp) {
                const date = new Date(timestamp);
                timestampElement.textContent = `最后更新: ${date.toLocaleString('zh-CN')}`;
            }
        }

        // 定期请求数据（作为WebSocket的备用）
        setInterval(function() {
            fetch('/api/vehicle_data')
                .then(response => response.json())
                .then(result => {
                    if (result.data) {
                        updateVehicleData(result.data);
                    }
                })
                .catch(error => console.error('Error fetching data:', error));
        }, 2000);

        // 初始化时立即请求一次数据
        setTimeout(() => {
            fetch('/api/vehicle_data')
                .then(response => response.json())
                .then(result => {
                    if (result.data) {
                        updateVehicleData(result.data);
                    }
                })
                .catch(error => console.error('Error fetching initial data:', error));
        }, 500);
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    """主页"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/vehicle_data')
def api_vehicle_data():
    """API接口：获取车辆数据"""
    data, last_update = data_receiver.get_latest_data()

    response = {
        'data': data,
        'last_update': last_update.isoformat() if last_update else None,
        'is_online': last_update and (datetime.now() - last_update).seconds < 5 if last_update else False
    }

    return jsonify(response)


@socketio.on('connect')
def handle_connect():
    """WebSocket连接"""
    print('客户端已连接')
    # 发送最新数据
    data, _ = data_receiver.get_latest_data()
    if data:
        emit('vehicle_data', data)


@socketio.on('disconnect')
def handle_disconnect():
    """WebSocket断开连接"""
    print('客户端已断开连接')


def broadcast_data():
    """定期广播数据到所有连接的客户端"""
    while True:
        data, last_update = data_receiver.get_latest_data()
        if data and last_update:
            socketio.emit('vehicle_data', data)
        time.sleep(1)


def main():
    """主函数"""
    try:
        # 启动数据广播线程
        broadcast_thread = threading.Thread(target=broadcast_data)
        broadcast_thread.daemon = True
        broadcast_thread.start()

        print("车辆监控网页应用启动...")
        print("访问 http://localhost:5000 查看车辆数据")

        # 启动Flask应用
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)

    except KeyboardInterrupt:
        print("收到停止信号...")
        data_receiver.stop()
    except Exception as e:
        print(f"应用启动失败: {e}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
小鸽数据接收Web界面
接收7701端口的UDP广播数据并通过Web页面实时显示
"""

import json
import socket
import struct
import time
import threading
import zlib
from datetime import datetime
from typing import Optional, Dict, Any
from flask import Flask, Response, render_template_string

app = Flask(__name__)

# 全局数据存储
data_cache: Dict[str, Any] = {}
stats = {
    'packet_count': 0,
    'lost_packets': 0,
    'last_sequence': -1,
    'last_update_time': time.time(),
}

# 全局接收器实例（避免重复创建）
# 注意：这个实例会在类定义后初始化，所以先声明为None
global_receiver = None

# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Xiaoge Data Receiver</title>
    <style>
        body {
            font-family: monospace;
            margin: 10px;
            background: #f5f5f5;
        }
        h1 { color: #333; }
        .section {
            background: white;
            margin: 10px 0;
            padding: 10px;
            border: 1px solid #ddd;
        }
        .section h2 {
            margin-top: 0;
            color: #555;
            border-bottom: 1px solid #eee;
            padding-bottom: 5px;
        }
        .data-row {
            padding: 3px 0;
        }
        .label { font-weight: bold; }
        .value { color: #0066cc; }
        .status { color: #666; }
    </style>
</head>
<body>
    <h1>Xiaoge Data Receiver - Real-time Display</h1>

    <div class="section">
        <h2>Packet Info</h2>
        <div id="packet-info">Waiting for data...</div>
    </div>

    <div class="section">
        <h2>Statistics</h2>
        <div id="statistics">-</div>
    </div>

    <div class="section">
        <h2>Vehicle State</h2>
        <div id="car-state">-</div>
    </div>

    <div class="section">
        <h2>Lead Vehicles (Fused)</h2>
        <div id="lead-vehicles">-</div>
    </div>

    <div class="section">
        <h2>Lane Information</h2>
        <div id="lane-info">-</div>
    </div>

    <div class="section">
        <h2>Meta Information</h2>
        <div id="meta-info">-</div>
    </div>

    <div class="section">
        <h2>Curvature Information</h2>
        <div id="curvature">-</div>
    </div>

    <div class="section">
        <h2>System State</h2>
        <div id="system-state">-</div>
    </div>

    <div class="section">
        <h2>Longitudinal Plan</h2>
        <div id="longitudinal-plan">-</div>
    </div>

    <div class="section">
        <h2>Carrot Navigation & Speed Limit</h2>
        <div id="carrot-man">-</div>
    </div>

    <!-- 盲区数据已包含在Vehicle State中，无需单独显示 -->

    <script>
        const eventSource = new EventSource('/stream');

        eventSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            updateDisplay(data);
        };

        eventSource.onerror = function(event) {
            console.error('SSE error:', event);
        };

        function updateDisplay(data) {
            // Packet Info
            const packetInfo = data.packet_info || {};
            document.getElementById('packet-info').innerHTML =
                `<div class="data-row"><span class="label">Sequence:</span> <span class="value">${packetInfo.sequence || '-'}</span></div>
                 <div class="data-row"><span class="label">Timestamp:</span> <span class="value">${packetInfo.timestamp || '-'}</span></div>
                 <div class="data-row"><span class="label">Version:</span> <span class="value">${packetInfo.version || '-'}</span></div>`;

            // Statistics
            const stats = data.statistics || {};
            document.getElementById('statistics').innerHTML =
                `<div class="data-row"><span class="label">Packets Received:</span> <span class="value">${stats.packet_count || 0}</span></div>
                 <div class="data-row"><span class="label">Lost Packets:</span> <span class="value">${stats.lost_packets || 0}</span></div>
                 <div class="data-row"><span class="label">Loss Rate:</span> <span class="value">${(stats.loss_rate || 0).toFixed(1)}%</span></div>
                 <div class="data-row"><span class="label">Receive Rate:</span> <span class="value">${(stats.receive_rate || 0).toFixed(1)} Hz</span></div>`;

            // Vehicle State
            const carState = data.car_state || {};
            document.getElementById('car-state').innerHTML = formatObject(carState);

            // Lead Vehicles (merged from ModelV2 and RadarState)
            const leadVehicles = data.lead_vehicles || {};
            document.getElementById('lead-vehicles').innerHTML = formatObject(leadVehicles);

            // Lane Info (merged with lane line types)
            const laneInfo = data.lane_info || {};
            document.getElementById('lane-info').innerHTML = formatObject(laneInfo);

            // Meta Info
            const metaInfo = data.meta_info || {};
            document.getElementById('meta-info').innerHTML = formatObject(metaInfo);

            // Curvature
            const curvature = data.curvature || {};
            document.getElementById('curvature').innerHTML = formatObject(curvature);

            // System State
            const systemState = data.system_state || {};
            document.getElementById('system-state').innerHTML = formatObject(systemState);

            // Longitudinal Plan
            const longPlan = data.longitudinal_plan || {};
            document.getElementById('longitudinal-plan').innerHTML = formatObject(longPlan);

            // Carrot Man
            const carrotMan = data.carrot_man || {};
            document.getElementById('carrot-man').innerHTML = formatObject(carrotMan);

            // 盲区数据已包含在car_state中，无需单独显示
        }

        function formatObject(obj, indent = 0) {
            if (obj === null || obj === undefined) return '-';
            if (typeof obj !== 'object') return String(obj);

            let html = '';
            for (const [key, value] of Object.entries(obj)) {
                if (value === null || value === undefined) continue;
                const indentStyle = 'padding-left: ' + (indent * 20) + 'px';
                if (typeof value === 'object' && !Array.isArray(value)) {
                    html += `<div class="data-row" style="${indentStyle}"><span class="label">${key}:</span></div>`;
                    html += formatObject(value, indent + 1);
                } else {
                    const displayValue = Array.isArray(value) ? `[${value.length} items]` : value;
                    html += `<div class="data-row" style="${indentStyle}"><span class="label">${key}:</span> <span class="value">${displayValue}</span></div>`;
                }
            }
            return html || '-';
        }
    </script>
</body>
</html>
'''


# 初始化全局接收器实例
def init_global_receiver():
    """初始化全局接收器实例"""
    global global_receiver
    if global_receiver is None:
        global_receiver = XiaogeDataReceiver()


class XiaogeDataReceiver:
    def __init__(self, udp_port=7701):
        self.udp_port = udp_port
        self.udp_socket = None
        self.running = False

    def setup_socket(self):
        """设置UDP接收socket"""
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.bind(('0.0.0.0', self.udp_port))
        self.udp_socket.settimeout(0.1)
        print(f"Listening on UDP port {self.udp_port}...")

    def parse_packet(self, packet: bytes) -> Optional[Dict[str, Any]]:
        """解析数据包"""
        try:
            if len(packet) < 8:
                return None

            checksum, data_len = struct.unpack('!II', packet[:8])
            if len(packet) < 8 + data_len:
                return None

            data_bytes = packet[8:8+data_len]
            calculated_checksum = zlib.crc32(data_bytes) & 0xffffffff
            if calculated_checksum != checksum:
                return None

            data = json.loads(data_bytes.decode('utf-8'))
            return data
        except Exception:
            return None

    def format_data_for_web(self, packet_data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化数据用于Web显示"""
        data = packet_data.get('data', packet_data)

        # 计算统计信息
        current_time = time.time()
        elapsed = current_time - stats['last_update_time'] if stats['last_update_time'] > 0 else 0
        rate = stats['packet_count'] / elapsed if elapsed > 0 else 0

        result = {
            'packet_info': {
                'sequence': packet_data.get('sequence', -1),
                'timestamp': datetime.fromtimestamp(packet_data.get('timestamp', 0)).strftime('%H:%M:%S.%f')[:-3] if packet_data.get('timestamp', 0) > 0 else 'N/A',
                'version': packet_data.get('version', 'N/A'),
            },
            'statistics': {
                'packet_count': stats['packet_count'],
                'lost_packets': stats['lost_packets'],
                'loss_rate': (stats['lost_packets'] / max(stats['packet_count'], 1)) * 100,
                'receive_rate': rate,
            },
            'car_state': self.format_car_state(data.get('carState', {})),
            'lead_vehicles': self.format_lead_vehicles(
                data.get('modelV2', {}),
                data.get('radarState', {})
            ),
            'lane_info': self.format_lane_info(
                data.get('modelV2', {}),
                data.get('carState', {})
            ),
            'meta_info': self.format_meta_info(data.get('modelV2', {}).get('meta', {})),
            'curvature': self.format_curvature(data.get('modelV2', {}).get('curvature', {})),
            'system_state': self.format_system_state(data.get('systemState', {})),
            'longitudinal_plan': self.format_longitudinal_plan(data.get('longitudinalPlan', {})),
            'carrot_man': self.format_carrot_man(data.get('carrotMan', {})),
            # 盲区数据已包含在car_state中，无需单独显示
        }
        return result

    def format_car_state(self, carState: Dict[str, Any]) -> Dict[str, Any]:
        """格式化本车状态"""
        if not carState:
            return {}
        return {
            'Speed (vEgo)': f"{(carState.get('vEgo', 0) * 3.6):.1f} km/h",
            'Acceleration': f"{carState.get('aEgo', 0):.2f} m/s²",
            'Steering Angle': f"{carState.get('steeringAngleDeg', 0):.1f}°",
            'Left Blinker': 'ON' if carState.get('leftBlinker') else 'OFF',
            'Right Blinker': 'ON' if carState.get('rightBlinker') else 'OFF',
            'Brake': 'PRESSED' if carState.get('brakePressed') else 'Released',
            'Standstill': 'YES' if carState.get('standstill') else 'NO',
            'Left Lane Distance': f"{carState.get('leftLatDist', 0):.2f} m",
            'Right Lane Distance': f"{carState.get('rightLatDist', 0):.2f} m",
            'Left Blindspot': 'YES' if carState.get('leftBlindspot') else 'NO',  # 左盲区
            'Right Blindspot': 'YES' if carState.get('rightBlindspot') else 'NO',  # 右盲区
            # 移除 Cruise Speed - 使用 Longitudinal Plan 中的 Cruise Target 代替
            # 移除 Lane Line Type - 合并到 Lane Information 中显示
        }

    def format_lead_vehicles(self, modelV2: Dict[str, Any], radarState: Dict[str, Any]) -> Dict[str, Any]:
        """格式化前车信息（合并 ModelV2 和 RadarState，避免重复）"""
        result = {}

        # 主前车（融合后的最终结果，优先显示 RadarState）
        if 'leadOne' in radarState:
            lead = radarState['leadOne']
            if lead.get('status'):
                lead_info = {
                    'Distance': f"{lead.get('dRel', 0):.1f} m",
                    'Relative Speed': f"{(lead.get('vRel', 0) * 3.6):.1f} km/h",
                    'Lead Speed': f"{(lead.get('vLead', 0) * 3.6):.1f} km/h",
                }
                # 添加 ModelV2 的加速度和置信度（作为补充信息）
                if 'lead0' in modelV2:
                    lead0 = modelV2['lead0']
                    if lead0.get('prob', 0) >= 0.1:
                        lead_info['Acceleration'] = f"{lead0.get('a', 0):.2f} m/s²"
                        lead_info['Vision Confidence'] = f"{(lead0.get('prob', 0) * 100):.1f}%"
                result['Lead One (Front)'] = lead_info

        # 第二前车
        if 'leadTwo' in radarState:
            lead = radarState['leadTwo']
            if lead.get('status'):
                lead_info = {
                    'Distance': f"{lead.get('dRel', 0):.1f} m",
                }
                # 添加 ModelV2 的速度和置信度（作为补充信息）
                if 'lead1' in modelV2:
                    lead1 = modelV2['lead1']
                    if lead1.get('prob', 0) >= 0.1:
                        lead_info['Speed'] = f"{(lead1.get('v', 0) * 3.6):.1f} km/h"
                        lead_info['Vision Confidence'] = f"{(lead1.get('prob', 0) * 100):.1f}%"
                result['Lead Two (Second Front)'] = lead_info

        # 左侧车道前车
        if 'leadLeft' in radarState:
            lead = radarState['leadLeft']
            if lead.get('status'):
                result['Lead Left'] = {
                    'Distance': f"{lead.get('dRel', 0):.1f} m",
                    'Relative Speed': f"{(lead.get('vRel', 0) * 3.6):.1f} km/h",
                }

        # 右侧车道前车
        if 'leadRight' in radarState:
            lead = radarState['leadRight']
            if lead.get('status'):
                result['Lead Right'] = {
                    'Distance': f"{lead.get('dRel', 0):.1f} m",
                    'Relative Speed': f"{(lead.get('vRel', 0) * 3.6):.1f} km/h",
                }

        return result

    def format_lane_info(self, modelV2: Dict[str, Any], carState: Dict[str, Any]) -> Dict[str, Any]:
        """格式化车道线信息（合并车道线类型和置信度）"""
        result = {}
        probs = modelV2.get('laneLineProbs', [0, 0])

        # 车道线类型映射
        lane_line_types = {
            0: "DASHED",  # 虚线
            1: "SOLID",   # 实线
            2: "UNKNOWN",
        }

        left_type = carState.get('leftLaneLine', -1)
        right_type = carState.get('rightLaneLine', -1)

        # 合并显示车道线类型和置信度
        result['Left Lane'] = {
            'Type': lane_line_types.get(left_type, f'UNKNOWN({left_type})'),
            'Confidence': f"{(probs[0] * 100):.1f}%" if len(probs) > 0 else "0%",
        }
        result['Right Lane'] = {
            'Type': lane_line_types.get(right_type, f'UNKNOWN({right_type})'),
            'Confidence': f"{(probs[1] * 100):.1f}%" if len(probs) > 1 else "0%",
        }

        # 移除以下字段（已优化移除）:
        # - laneLineLeft/Right 坐标数组
        # - velocity (模型速度估计)
        # - position (路径规划轨迹)
        # - roadEdges (路边线)

        return result

    def format_meta_info(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """格式化元数据（包含车道宽度和到路边缘距离）"""
        if not meta:
            return {}

        lane_change_states = {0: "OFF", 1: "PRE", 2: "STARTING", 3: "FINISHING"}
        lane_change_directions = {0: "NONE", 1: "LEFT", 2: "RIGHT"}

        return {
            'Lane Width Left': f"{meta.get('laneWidthLeft', 0):.2f} m",
            'Lane Width Right': f"{meta.get('laneWidthRight', 0):.2f} m",
            'Distance to Road Edge Left': f"{meta.get('distanceToRoadEdgeLeft', 0):.2f} m",
            'Distance to Road Edge Right': f"{meta.get('distanceToRoadEdgeRight', 0):.2f} m",
            'Lane Change State': lane_change_states.get(meta.get('laneChangeState', 0), "UNKNOWN"),
            'Lane Change Direction': lane_change_directions.get(meta.get('laneChangeDirection', 0), "UNKNOWN"),
        }

    def format_curvature(self, curvature: Dict[str, Any]) -> Dict[str, Any]:
        """格式化曲率信息"""
        if not curvature:
            return {}

        direction_map = {-1: "RIGHT", 0: "STRAIGHT", 1: "LEFT"}
        direction = direction_map.get(curvature.get('direction', 0), "UNKNOWN")
        max_rate = curvature.get('maxOrientationRate', 0.0)

        return {
            'Max Orientation Rate': f"{max_rate:.4f} rad/s",
            'Direction': direction,
            'Curvature Level': self._get_curvature_level(abs(max_rate)),
        }

    def _get_curvature_level(self, abs_rate: float) -> str:
        """根据方向变化率判断弯道程度

        Args:
            abs_rate: 方向变化率的绝对值 (rad/s)

        Returns:
            弯道程度描述: STRAIGHT, GENTLE_CURVE, MODERATE_CURVE, SHARP_CURVE
        """
        if abs_rate < 0.02:  # 优化：阈值从0.01提高到0.02，更准确地判断直路
            return "STRAIGHT"
        elif abs_rate < 0.05:
            return "GENTLE_CURVE"
        elif abs_rate < 0.1:
            return "MODERATE_CURVE"
        else:
            return "SHARP_CURVE"

    def format_system_state(self, systemState: Dict[str, Any]) -> Dict[str, Any]:
        """格式化系统状态"""
        if not systemState:
            return {}

        long_control_states = {0: "OFF", 1: "PID", 2: "STOPPING", 3: "STARTING"}
        long_control_state = systemState.get('longControlState', 0)

        return {
            'System Enabled': 'YES' if systemState.get('enabled') else 'NO',
            'System Active': 'YES' if systemState.get('active') else 'NO',
            'Long Control State': long_control_states.get(long_control_state, f'UNKNOWN({long_control_state})'),
        }

    def format_longitudinal_plan(self, lp: Dict[str, Any]) -> Dict[str, Any]:
        """格式化纵向规划"""
        if not lp:
            return {}

        x_states = {0: "OFF", 1: "CRUISE", 2: "FOLLOWING", 3: "STOPPING"}
        traffic_states = {0: "NONE", 1: "SLOWING", 2: "STOPPED"}

        x_state_val = lp.get('xState', 0)
        traffic_state_val = lp.get('trafficState', 0)

        return {
            'X State': x_states.get(x_state_val, f'UNKNOWN({x_state_val})'),
            'Traffic State': traffic_states.get(traffic_state_val, f'UNKNOWN({traffic_state_val})'),
            'Cruise Target': f"{(lp.get('cruiseTarget', 0) * 3.6):.1f} km/h",
            'Has Lead': 'YES' if lp.get('hasLead', False) else 'NO',
        }

    def format_carrot_man(self, cm: Dict[str, Any]) -> Dict[str, Any]:
        """格式化Carrot数据"""
        if not cm:
            return {}

        speed_limit_types = {0: "NONE", 1: "STATIC", 2: "DYNAMIC"}
        speed_limit_type_val = cm.get('xSpdType', 0)

        # 道路类型映射
        roadcate_map = {
            0: "UNKNOWN",
            1: "HIGHWAY",  # 高速
            2: "EXPRESSWAY",  # 快速路
            3: "CITY",  # 城市道路
        }
        roadcate_val = cm.get('roadcate', 0)
        roadcate_str = roadcate_map.get(roadcate_val, f'UNKNOWN({roadcate_val})')

        return {
            'Road Limit Speed': f"{cm.get('nRoadLimitSpeed', 0)} km/h",
            'Desired Speed': f"{cm.get('desiredSpeed', 0)} km/h",
            'Speed Limit Distance': f"{cm.get('xSpdDist', 0)} m",
            'Speed Limit': f"{cm.get('xSpdLimit', 0)} km/h",
            'Speed Limit Type': speed_limit_types.get(speed_limit_type_val, f'UNKNOWN({speed_limit_type_val})'),
            'Road Category': roadcate_str,  # 添加道路类型显示
        }

    # 移除 format_blindspot() - 盲区数据已包含在car_state中

    def udp_listener_thread(self):
        """UDP监听线程"""
        self.setup_socket()
        self.running = True

        while self.running:
            try:
                packet, addr = self.udp_socket.recvfrom(4096)
                packet_data = self.parse_packet(packet)

                if packet_data is None:
                    continue

                # 更新统计信息
                stats['packet_count'] += 1
                sequence = packet_data.get('sequence', -1)

                if stats['last_sequence'] >= 0:
                    lost = sequence - stats['last_sequence'] - 1
                    if lost > 0:
                        stats['lost_packets'] += lost

                stats['last_sequence'] = sequence
                stats['last_update_time'] = time.time()

                # 更新数据缓存
                global data_cache
                data_cache = packet_data

            except socket.timeout:
                continue
            except Exception as e:
                print(f"UDP listener error: {e}")
                time.sleep(0.1)

        if self.udp_socket:
            self.udp_socket.close()


# Flask路由
@app.route('/')
def index():
    """主页"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/stream')
def stream():
    """SSE流"""
    def generate():
        last_data = None
        global global_receiver
        while True:
            global data_cache
            if data_cache and data_cache != last_data:
                # 使用全局接收器实例，避免重复创建
                formatted_data = global_receiver.format_data_for_web(data_cache)
                yield f"data: {json.dumps(formatted_data)}\n\n"
                last_data = data_cache
            time.sleep(0.05)  # 20Hz更新频率

    return Response(generate(), mimetype='text/event-stream')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Xiaoge Data Receiver Web Tool')
    parser.add_argument('--udp-port', type=int, default=7701, help='UDP port to listen on (default: 7701)')
    parser.add_argument('--web-port', type=int, default=8080, help='Web server port (default: 8080)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Web server host (default: 0.0.0.0)')
    args = parser.parse_args()

    # 初始化全局接收器实例
    init_global_receiver()

    # 启动UDP监听线程（使用全局接收器实例）
    global global_receiver
    global_receiver.udp_port = args.udp_port
    udp_thread = threading.Thread(target=global_receiver.udp_listener_thread, daemon=True)
    udp_thread.start()

    print(f"Web server starting on http://{args.host}:{args.web_port}")
    print(f"UDP listener started on port {args.udp_port}")
    print("Press Ctrl+C to exit")

    # 启动Flask服务器
    app.run(host=args.host, port=args.web_port, threaded=True, debug=False)


if __name__ == "__main__":
    main()

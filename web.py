#!/usr/bin/env python3
"""
openpilot modelV2 车辆检测数据实时展示 - 无过滤版本
通过Flask在端口8899显示所有检测到的车辆信息
"""

import json
import threading
import time
from typing import Dict, Any, List
from flask import Flask, render_template_string, jsonify

import cereal.messaging as messaging
import numpy as np
from openpilot.common.realtime import Ratekeeper


class VehicleDetectionDisplay:
    """车辆检测数据展示类 - 显示所有检测目标"""

    # 常量定义（移除所有限制）
    RADAR_TO_CAMERA = 1.52  # 雷达相对于相机中心的偏移（米）
    LANE_PROB_THRESHOLD = 0.0  # 移除车道内概率阈值限制
    CONFIDENCE_BASE_THRESHOLD = 0.0  # 移除基础置信度阈值限制
    CONFIDENCE_DISTANCE_THRESHOLD = 999.0  # 移除距离阈值限制
    CONFIDENCE_DISTANCE_BOOST = 0.0  # 移除距离置信度提升
    CONFIDENCE_VELOCITY_DIFF_THRESHOLD = 999.0  # 移除速度差异阈值限制
    CONFIDENCE_VELOCITY_BOOST = 0.0  # 移除速度置信度提升
    DEFAULT_LANE_HALF_WIDTH = 1.75  # 默认车道半宽
    MIN_LANE_HALF_WIDTH = 0.1  # 最小车道半宽阈值

    def __init__(self):
        # 数据存储
        self.current_data = {
            'center_vehicles': [],
            'left_vehicles': [],
            'right_vehicles': [],
            'all_detections': [],  # 所有原始检测数据
            'timestamp': 0,
            'frame_id': 0
        }
        self.data_lock = threading.Lock()

        # 订阅openpilot消息
        self.sm = messaging.SubMaster(['modelV2', 'carState'], poll='modelV2')

        # 车道线数据缓存
        self._lane_cache = {
            'lane_xs': None,
            'left_ys': None,
            'right_ys': None,
            'position_x': None,
            'position_y': None,
            'position_valid': False,
            'cache_valid': False
        }

    def _update_lane_cache(self, modelV2):
        """更新车道线数据缓存"""
        try:
            if not hasattr(modelV2, 'laneLines') or len(modelV2.laneLines) < 3:
                self._lane_cache['cache_valid'] = False
                return

            if len(modelV2.laneLines) <= 2:
                self._lane_cache['cache_valid'] = False
                return

            # 提取车道线数据
            lane_xs = [float(x) for x in modelV2.laneLines[1].x]
            left_ys = [float(y) for y in modelV2.laneLines[1].y]
            right_ys = [float(y) for y in modelV2.laneLines[2].y]

            if not (len(lane_xs) == len(left_ys) == len(right_ys)):
                self._lane_cache['cache_valid'] = False
                return

            if len(lane_xs) < 2 or not all(lane_xs[i] < lane_xs[i+1] for i in range(len(lane_xs)-1)):
                self._lane_cache['cache_valid'] = False
                return

            self._lane_cache['lane_xs'] = lane_xs
            self._lane_cache['left_ys'] = left_ys
            self._lane_cache['right_ys'] = right_ys

            # 更新规划路径数据
            if hasattr(modelV2, 'position') and len(modelV2.position.x) > 0:
                position_x = [float(x) for x in modelV2.position.x]
                position_y = [float(y) for y in modelV2.position.y]

                if len(position_x) == len(position_y) and len(position_x) >= 2:
                    if all(position_x[i] < position_x[i+1] for i in range(len(position_x)-1)):
                        self._lane_cache['position_x'] = position_x
                        self._lane_cache['position_y'] = position_y
                        self._lane_cache['position_valid'] = True
                    else:
                        self._lane_cache['position_x'] = None
                        self._lane_cache['position_y'] = None
                        self._lane_cache['position_valid'] = False
                else:
                    self._lane_cache['position_x'] = None
                    self._lane_cache['position_y'] = None
                    self._lane_cache['position_valid'] = False
            else:
                self._lane_cache['position_x'] = None
                self._lane_cache['position_y'] = None
                self._lane_cache['position_valid'] = False

            self._lane_cache['cache_valid'] = (
                len(self._lane_cache['lane_xs']) > 0 and
                len(self._lane_cache['left_ys']) > 0 and
                len(self._lane_cache['right_ys']) > 0
            )
        except (IndexError, AttributeError, ValueError):
            self._lane_cache['cache_valid'] = False

    def _calculate_dpath(self, dRel: float, yRel: float, yvRel: float = 0.0, vLead: float = 0.0) -> tuple:
        """计算车辆相对于规划路径的横向偏移和车道内概率"""
        if not self._lane_cache['cache_valid']:
            return 0.0, 0.0, 0.0

        try:
            lane_xs = self._lane_cache['lane_xs']
            left_ys = self._lane_cache['left_ys']
            right_ys = self._lane_cache['right_ys']

            def d_path_interp(dRel_val: float, yRel_val: float) -> tuple:
                """内部函数：计算指定距离处的 dPath 和 in_lane_prob"""
                left_lane_y = np.interp(dRel_val, lane_xs, left_ys)
                right_lane_y = np.interp(dRel_val, lane_xs, right_ys)
                center_y = (left_lane_y + right_lane_y) / 2.0
                lane_half_width = abs(right_lane_y - left_lane_y) / 2.0
                if lane_half_width < self.MIN_LANE_HALF_WIDTH:
                    lane_half_width = self.DEFAULT_LANE_HALF_WIDTH
                dist_from_center = yRel_val - center_y
                in_lane_prob = max(0.0, 1.0 - (abs(dist_from_center) / lane_half_width))

                if self._lane_cache.get('position_valid', False):
                    path_y = np.interp(dRel_val, self._lane_cache['position_x'], self._lane_cache['position_y'])
                    dPath = yRel_val - path_y
                else:
                    dPath = dist_from_center

                return dPath, in_lane_prob

            # 计算当前时刻的值
            dPath, in_lane_prob = d_path_interp(dRel, yRel)

            # 计算未来时刻的值
            future_dRel = dRel + vLead * 0.5  # RADAR_LAT_FACTOR
            future_yRel = yRel + yvRel * 0.5
            _, in_lane_prob_future = d_path_interp(future_dRel, future_yRel)

            return float(dPath), float(in_lane_prob), float(in_lane_prob_future)

        except (IndexError, ValueError, TypeError):
            return 0.0, 0.0, 0.0

    def collect_vehicle_data(self) -> Dict[str, Any]:
        """收集车辆检测数据 - 显示所有检测目标"""
        if not self.sm.alive['modelV2']:
            return {}

        modelV2 = self.sm['modelV2']
        v_ego = 0.0

        # 获取自车速度
        if self.sm.alive['carState']:
            v_ego = float(self.sm['carState'].vEgo)
        elif hasattr(modelV2, 'velocity') and len(modelV2.velocity.x) > 0:
            v_ego = float(modelV2.velocity.x[0])

        # 更新车道线缓存
        self._update_lane_cache(modelV2)

        # 分类车辆
        left_vehicles = []
        right_vehicles = []
        center_vehicles = []
        all_detections = []  # 所有原始检测数据

        # 遍历所有检测目标 - 移除所有过滤条件
        for i, lead in enumerate(modelV2.leadsV3):
            lead_prob = float(lead.prob)

            # 提取车辆数据
            x = float(lead.x[0]) if len(lead.x) > 0 else 0.0
            y = float(lead.y[0]) if len(lead.y) > 0 else 0.0
            v = float(lead.v[0]) if len(lead.v) > 0 else 0.0
            a = float(lead.a[0]) if len(lead.a) > 0 else 0.0

            v_rel = v - v_ego
            dRel = x - self.RADAR_TO_CAMERA
            yRel = -y
            yvRel = 0.0
            vLead = v_ego + v_rel

            # 计算路径偏移和车道内概率
            dPath, in_lane_prob, in_lane_prob_future = self._calculate_dpath(dRel, yRel, yvRel, vLead)

            # 生成更稳定的车辆ID
            vehicle_id = f"V{i}_{hash(f'{x:.1f}_{y:.1f}_{lead_prob:.3f}') % 1000}"

            vehicle_data = {
                'id': vehicle_id,
                'raw_id': i,  # 保留原始数组索引
                'x': round(x, 2),
                'y': round(y, 2),
                'dRel': round(dRel, 2),
                'yRel': round(yRel, 2),
                'v': round(v, 2),
                'vLead': round(vLead, 2),
                'a': round(a, 2),
                'vRel': round(v_rel, 2),
                'dPath': round(dPath, 2),
                'inLaneProb': round(in_lane_prob, 3),
                'inLaneProbFuture': round(in_lane_prob_future, 3),
                'prob': round(lead_prob, 3),
                'stopped': abs(v) < 0.1,  # 标记停止车辆
            }

            # 添加到所有检测列表
            all_detections.append(vehicle_data.copy())

            # 根据位置分类车辆 - 移除概率阈值限制
            if in_lane_prob > 0.05:  # 极低阈值，基本不过滤
                center_vehicles.append(vehicle_data)
            elif yRel < 0:
                left_vehicles.append(vehicle_data)
            else:
                right_vehicles.append(vehicle_data)

        return {
            'center_vehicles': center_vehicles,
            'left_vehicles': left_vehicles,
            'right_vehicles': right_vehicles,
            'all_detections': all_detections,
            'timestamp': time.time(),
            'frame_id': modelV2.frameId
        }

    def update_loop(self):
        """数据更新循环"""
        rk = Ratekeeper(20, print_delay_threshold=None)

        print("Vehicle detection data collector started (No Filter Mode)")

        while True:
            try:
                # 更新消息
                self.sm.update(0)

                # 收集数据
                data = self.collect_vehicle_data()

                # 更新共享数据
                with self.data_lock:
                    self.current_data = data

                rk.keep_time()

            except Exception as e:
                print(f"Error in update loop: {e}")
                time.sleep(0.1)


# Flask应用
app = Flask(__name__)
display = VehicleDetectionDisplay()

# 完整的HTML模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>openpilot 车辆检测数据 - 无过滤模式</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }
        .container { max-width: 1400px; margin: 0 auto; }
        .header { background: #333; color: white; padding: 10px; text-align: center; }
        .lane-section { margin: 10px 0; padding: 15px; background: white; border-radius: 5px; }
        .lane-title { font-size: 18px; font-weight: bold; margin-bottom: 10px; }
        .current-lane { border-left: 5px solid #4CAF50; }
        .left-lane { border-left: 5px solid #2196F3; }
        .right-lane { border-left: 5px solid #FF9800; }
        .all-detections { border-left: 5px solid #9C27B0; }
        .vehicle { margin: 5px 0; padding: 8px; background: #f9f9f9; border-radius: 3px; font-family: monospace; font-size: 12px; }
        .vehicle.stopped { background: #ffebee; border-left: 3px solid #f44336; }
        .no-vehicle { color: #666; font-style: italic; }
        .info { margin: 10px 0; padding: 10px; background: #e3f2fd; border-radius: 5px; }
        .stats { display: flex; gap: 20px; margin: 10px 0; flex-wrap: wrap; }
        .stat-item { background: #f5f5f5; padding: 8px; border-radius: 3px; text-align: center; min-width: 120px; }
    </style>
    <script>
        function updateData() {
            fetch('/api/data')
                .then(response => response.json())
                .then(data => {
                    updateLane('center', data.center_vehicles);
                    updateLane('left', data.left_vehicles);
                    updateLane('right', data.right_vehicles);
                    updateLane('all', data.all_detections);

                    // 更新信息
                    document.getElementById('timestamp').textContent = new Date(data.timestamp * 1000).toLocaleTimeString();
                    document.getElementById('frame_id').textContent = data.frame_id;

                    // 更新统计
                    document.getElementById('total_count').textContent = data.all_detections.length;
                    document.getElementById('stopped_count').textContent = data.all_detections.filter(v => v.stopped).length;
                })
                .catch(error => console.error('Error:', error));
        }

        function updateLane(lane, vehicles) {
            const container = document.getElementById(lane + '-vehicles');
            if (vehicles.length === 0) {
                container.innerHTML = '<div class="no-vehicle">无检测到的车辆</div>';
            } else {
                container.innerHTML = vehicles.map(v => `
                    <div class="vehicle ${v.stopped ? 'stopped' : ''}">
                        ${v.stopped ? '🛑 ' : ''}ID:${v.id} (raw:${v.raw_id}) |
                        距离:${v.x}m | 横向:${v.y}m | 速度:${v.v}m/s |
                        相对速度:${v.vRel}m/s | 置信度:${v.prob} | 车道概率:${v.inLaneProb}
                    </div>
                `).join('');
            }
        }

        // 自动更新
        setInterval(updateData, 100);
        updateData();
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>openpilot 视觉模型车辆检测数据 - 无过滤模式</h1>
            <p>显示所有检测到的车辆，移除置信度和距离限制</p>
        </div>

        <div class="info">
            <strong>更新时间:</strong> <span id="timestamp">--</span> |
            <strong>帧ID:</strong> <span id="frame_id">--</span> |
            <strong>刷新频率:</strong> 10Hz
        </div>

        <div class="stats">
            <div class="stat-item">
                <strong>总检测数:</strong> <span id="total_count">0</span>
            </div>
            <div class="stat-item">
                <strong>停止车辆:</strong> <span id="stopped_count">0</span>
            </div>
            <div class="stat-item">
                <strong>当前车道:</strong> {{ center_count }} 辆
            </div>
            <div class="stat-item">
                <strong>左车道:</strong> {{ left_count }} 辆
            </div>
            <div class="stat-item">
                <strong>右车道:</strong> {{ right_count }} 辆
            </div>
        </div>

        <div class="lane-section all-detections">
            <div class="lane-title">🟣 所有检测目标 ({{ total_count }} 辆)</div>
            <div id="all-vehicles">
                <div class="no-vehicle">加载中...</div>
            </div>
        </div>

        <div class="lane-section current-lane">
            <div class="lane-title">🟢 当前车道 ({{ center_count }} 辆)</div>
            <div id="center-vehicles">
                <div class="no-vehicle">加载中...</div>
            </div>
        </div>

        <div class="lane-section left-lane">
            <div class="lane-title">🔵 左车道 ({{ left_count }} 辆)</div>
            <div id="left-vehicles">
                <div class="no-vehicle">加载中...</div>
            </div>
        </div>

        <div class="lane-section right-lane">
            <div class="lane-title">🟠 右车道 ({{ right_count }} 辆)</div>
            <div id="right-vehicles">
                <div class="no-vehicle">加载中...</div>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    with display.data_lock:
        center_count = len(display.current_data.get('center_vehicles', []))
        left_count = len(display.current_data.get('left_vehicles', []))
        right_count = len(display.current_data.get('right_vehicles', []))
        total_count = len(display.current_data.get('all_detections', []))

    return render_template_string(
        HTML_TEMPLATE,
        center_count=center_count,
        left_count=left_count,
        right_count=right_count,
        total_count=total_count
    )

@app.route('/api/data')
def get_data():
    with display.data_lock:
        return jsonify(display.current_data)

if __name__ == '__main__':
    # 启动数据更新线程
    update_thread = threading.Thread(target=display.update_loop, daemon=True)
    update_thread.start()

    # 启动Flask应用
    print("Starting Flask server on http://0.0.0.0:8899")
    app.run(host='0.0.0.0', port=8899, debug=False)

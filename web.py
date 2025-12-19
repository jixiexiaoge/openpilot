
#!/usr/bin/env python3
"""
openpilot modelV2 车辆检测数据实时展示
通过Flask在端口8899显示车辆检测信息
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
    """车辆检测数据展示类"""

    # 常量定义（参考 radard.py）
    RADAR_TO_CAMERA = 1.52  # 雷达相对于相机中心的偏移（米）
    LANE_PROB_THRESHOLD = 0.1  # 车道内概率阈值
    CONFIDENCE_BASE_THRESHOLD = 0.5  # 基础置信度阈值
    CONFIDENCE_DISTANCE_THRESHOLD = 50.0  # 距离阈值（米）
    CONFIDENCE_DISTANCE_BOOST = 0.7  # 距离超过阈值时的置信度提升
    CONFIDENCE_VELOCITY_DIFF_THRESHOLD = 10.0  # 速度差异阈值（m/s）
    CONFIDENCE_VELOCITY_BOOST = 0.6  # 速度差异超过阈值时的置信度提升
    SIDE_VEHICLE_MIN_DISTANCE = 5.0  # 侧方车辆最小距离（米）
    SIDE_VEHICLE_MAX_DPATH = 3.5  # 侧方车辆最大路径偏移（米）
    DEFAULT_LANE_HALF_WIDTH = 1.75  # 默认车道半宽
    MIN_LANE_HALF_WIDTH = 0.1  # 最小车道半宽阈值

    def __init__(self):
        # 数据存储
        self.current_data = {
            'center_vehicles': [],
            'left_vehicles': [],
            'right_vehicles': [],
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
        """收集车辆检测数据"""
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

        # 遍历所有检测目标
        for i, lead in enumerate(modelV2.leadsV3):
            lead_prob = float(lead.prob)

            # 动态置信度过滤
            x = float(lead.x[0]) if len(lead.x) > 0 else 0.0
            v = float(lead.v[0]) if len(lead.v) > 0 else 0.0

            min_prob = self.CONFIDENCE_BASE_THRESHOLD
            if x > self.CONFIDENCE_DISTANCE_THRESHOLD:
                min_prob = max(min_prob, self.CONFIDENCE_DISTANCE_BOOST)
            if abs(v - v_ego) > self.CONFIDENCE_VELOCITY_DIFF_THRESHOLD:
                min_prob = max(min_prob, self.CONFIDENCE_VELOCITY_BOOST)

            if lead_prob < min_prob:
                continue

            # 提取车辆数据
            y = float(lead.y[0]) if len(lead.y) > 0 else 0.0
            a = float(lead.a[0]) if len(lead.a) > 0 else 0.0
            v_rel = v - v_ego
            dRel = x - self.RADAR_TO_CAMERA
            yRel = -y
            yvRel = 0.0
            vLead = v_ego + v_rel

            # 计算路径偏移和车道内概率
            dPath, in_lane_prob, in_lane_prob_future = self._calculate_dpath(dRel, yRel, yvRel, vLead)

            vehicle_data = {
                'id': i,
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
            }

            # 根据位置分类车辆
            if in_lane_prob > self.LANE_PROB_THRESHOLD:
                center_vehicles.append(vehicle_data)
            elif yRel < 0:
                left_vehicles.append(vehicle_data)
            else:
                right_vehicles.append(vehicle_data)

        return {
            'center_vehicles': center_vehicles,
            'left_vehicles': left_vehicles,
            'right_vehicles': right_vehicles,
            'timestamp': time.time(),
            'frame_id': modelV2.frameId
        }

    def update_loop(self):
        """数据更新循环"""
        rk = Ratekeeper(20, print_delay_threshold=None)

        print("Vehicle detection data collector started")

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

# HTML模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>openpilot 车辆检测数据</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background: #333; color: white; padding: 10px; text-align: center; }
        .lane-section { margin: 10px 0; padding: 15px; background: white; border-radius: 5px; }
        .lane-title { font-size: 18px; font-weight: bold; margin-bottom: 10px; }
        .current-lane { border-left: 5px solid #4CAF50; }
        .left-lane { border-left: 5px solid #2196F3; }
        .right-lane { border-left: 5px solid #FF9800; }
        .vehicle { margin: 5px 0; padding: 8px; background: #f9f9f9; border-radius: 3px; font-family: monospace; }
        .no-vehicle { color: #666; font-style: italic; }
        .info { margin: 10px 0; padding: 10px; background: #e3f2fd; border-radius: 5px; }
    </style>
    <script>
        function updateData() {
            fetch('/api/data')
                .then(response => response.json())
                .then(data => {
                    updateLane('center', data.center_vehicles);
                    updateLane('left', data.left_vehicles);
                    updateLane('right', data.right_vehicles);

                    // 更新信息
                    document.getElementById('timestamp').textContent = new Date(data.timestamp * 1000).toLocaleTimeString();
                    document.getElementById('frame_id').textContent = data.frame_id;
                })
                .catch(error => console.error('Error:', error));
        }

        function updateLane(lane, vehicles) {
            const container = document.getElementById(lane + '-vehicles');
            if (vehicles.length === 0) {
                container.innerHTML = '<div class="no-vehicle">无检测到的车辆</div>';
            } else {
                container.innerHTML = vehicles.map(v => `
                    <div class="vehicle">
                        ID:${v.id} | 距离:${v.x}m | 横向:${v.y}m | 速度:${v.v}m/s |
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
            <h1>openpilot 视觉模型车辆检测数据</h1>
        </div>

        <div class="info">
            <strong>更新时间:</strong> <span id="timestamp">--</span> |
            <strong>帧ID:</strong> <span id="frame_id">--</span> |
            <strong>刷新频率:</strong> 10Hz
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
    """主页面"""
    # 获取当前车辆数量
    with display.data_lock:
        center_count = len(display.current_data.get('center_vehicles', []))
        left_count = len(display.current_data.get('left_vehicles', []))
        right_count = len(display.current_data.get('right_vehicles', []))

    return render_template_string(
        HTML_TEMPLATE,
        center_count=center_count,
        left_count=left_count,
        right_count=right_count
    )

@app.route('/api/data')
def get_data():
    """API接口获取最新数据"""
    with display.data_lock:
        return jsonify(display.current_data)


def main():
    """主函数"""
    # 启动数据收集线程
    collector_thread = threading.Thread(target=display.update_loop, daemon=True)
    collector_thread.start()

    # 等待数据初始化
    time.sleep(1)

    # 启动Flask服务
    print("Starting Flask server on port 8899...")
    print("Access http://localhost:8899 to view vehicle detection data")
    app.run(host='0.0.0.0', port=8899, debug=False, threaded=True)


if __name__ == "__main__":
    main()
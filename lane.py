#!/usr/bin/env python3
import time
import numpy as np
from collections import deque
import threading
from flask import Flask, jsonify, render_template_string

from msgq.visionipc.visionipc_pyx import VisionIpcClient, VisionStreamType
import cereal.messaging as messaging
from openpilot.common.transformations.camera import get_view_frame_from_calib_frame, DEVICE_CAMERAS
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

# ==============================================================================
# 全局数据共享 (用于 Web 展示)
# ==============================================================================
latest_data = {
    'speed': 0.0,
    'left_type': '未知',
    'right_type': '未知',
    'left_rel_std': 0.0,
    'right_rel_std': 0.0,
    'left_confidence': 0.0,
    'right_confidence': 0.0,
    'last_update': 0
}

# ==============================================================================
# Web 界面 (Stateless Flask)
# ==============================================================================
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>CPlink Lane Monitor</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; }
        .container { background: #1e293b; padding: 2.5rem; border-radius: 1.5rem; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); width: 90%; max-width: 600px; border: 1px solid #334155; }
        h1 { color: #38bdf8; text-align: center; margin-bottom: 2.5rem; font-weight: 700; letter-spacing: -0.025em; }
        .stat { display: flex; justify-content: space-between; margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 1px solid #334155; align-items: center; }
        .label { color: #94a3b8; font-size: 1rem; font-weight: 500; }
        .value { font-weight: 700; font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 1.5rem; }
        .type-solid { color: #ef4444; text-shadow: 0 0 10px rgba(239, 68, 68, 0.3); }
        .type-dashed { color: #10b981; text-shadow: 0 0 10px rgba(16, 185, 129, 0.3); }
        .type-unknown { color: #64748b; }
        .speed { color: #38bdf8; font-size: 2.5rem; }
        .unit { font-size: 1rem; color: #64748b; margin-left: 0.5rem; font-weight: 400; }
        .footer { text-align: center; font-size: 0.875rem; color: #475569; margin-top: 2rem; font-weight: 500; }
    </style>
</head>
<body>
    <div class="container">
        <h1>车道线性能监控</h1>
        <div class="stat">
            <span class="label">实时车速</span>
            <span class="value speed"><span id="speed">0.0</span><span class="unit">km/h</span></span>
        </div>
        <div class="stat">
            <span class="label">左侧线路</span>
            <span class="value" id="left_type">检测中...</span>
        </div>
        <div class="stat">
            <span class="label">左侧方差</span>
            <span class="value" id="left_std">0.0000</span>
        </div>
        <div class="stat">
            <span class="label">右侧线路</span>
            <span class="value" id="right_type">检测中...</span>
        </div>
        <div class="stat">
            <span class="label">右侧方差</span>
            <span class="value" id="right_std">0.0000</span>
        </div>
        <div class="footer">
            最后心跳: <span id="timestamp">--:--:--</span>
        </div>
    </div>
    <script>
        function update() {
            fetch('/data')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('speed').innerText = data.speed.toFixed(1);

                    const updateLine = (id, typeId, typeStr, stdId, stdVal) => {
                        const el = document.getElementById(typeId);
                        el.innerText = typeStr;
                        el.className = 'value ' + (typeStr === '实线' ? 'type-solid' : (typeStr === '虚线' ? 'type-dashed' : 'type-unknown'));
                        document.getElementById(stdId).innerText = stdVal.toFixed(4);
                    };

                    updateLine('left', 'left_type', data.left_type, 'left_std', data.left_rel_std);
                    updateLine('right', 'right_type', data.right_type, 'right_std', data.right_rel_std);

                    document.getElementById('timestamp').innerText = new Date(data.last_update * 1000).toLocaleTimeString();
                })
                .catch(e => console.error("Monitor failed:", e));
        }
        setInterval(update, 500);
        update();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data():
    return jsonify(latest_data)

def start_flask():
    cloudlog.info("Starting Flask on port 8888")
    app.run(host='0.0.0.0', port=8888, debug=False, use_reloader=False)

# ==============================================================================
# 车道线类型检测器类
# ==============================================================================

class LaneLineDetector:
    """中国道路标准优化版检测器"""

    FULL_RES_WIDTH = 1928

    def __init__(self):
        self.params = Params()
        self.intrinsics = None
        self.w, self.h = None, None
        self.update_params()

    def update_params(self):
        self.lookahead_start = 6.0
        self.lookahead_end = 45.0  # 覆盖 39 米长距离
        self.num_points = 100      # 增加采样密度 (约 0.4m 一个点)
        self.prob_threshold = 0.3

        # 针对中国道路的相对方差阈值
        self.rel_std_solid_max = 0.08
        self.rel_std_dash_min = 0.12

    def init_camera(self, sm, vipc_client):
        if self.intrinsics is not None: return True
        if not sm.updated['roadCameraState']: return False
        try:
            # 简化内参获取，实际生产中应从 DEVICE_CAMERAS 获取
            self.w, self.h = vipc_client.width, vipc_client.height
            scale = self.w / self.FULL_RES_WIDTH
            # 这里使用标准 C3 相机内参作为 fallback
            self.intrinsics = np.array([
                [910 * scale, 0, 960 * scale],
                [0, 910 * scale, 540 * scale],
                [0, 0, 1]
            ])
            return True
        except Exception: return False

    def analyze_vocal_continuity(self, pixel_values, v_ego):
        """
        视觉连贯性检查 (考虑中国虚线 6m 线 + 9m 空)
        """
        if len(pixel_values) < 30: return -1, 0.0

        std = np.std(pixel_values)
        mean = np.mean(pixel_values)
        rel_std = std / max(mean, 1.0)

        # 1. 基础波动判断
        if rel_std < self.rel_std_solid_max:
            return 1, rel_std  # 极其平稳 -> 实线

        # 2. 局部对比度检查 (虚线会有明显的周期性明暗)
        # 计算 15 米周期内的梯度
        # 在 100 个点覆盖 39 米的情况下，15 米约 38 个点
        window = 38
        if len(pixel_values) >= window:
            diffs = np.abs(np.diff(pixel_values))
            significant_jumps = np.sum(diffs > (mean * 0.4)) # 显著亮度跳变

            # 虚线在 40 米内通常由于视角和采样，会有 3-6 次显著边缘
            if significant_jumps >= 3 and rel_std > self.rel_std_dash_min:
                return 0, rel_std # 判定为虚线

        # 3. 兜底判断
        if rel_std > self.rel_std_dash_min * 1.5:
            return 0, rel_std

        return -1, rel_std

    def update(self, sm, yuv_buf):
        global latest_data
        result = {'left': -1, 'right': -1, 'left_rel_std': 0.0, 'right_rel_std': 0.0}

        if not sm.updated.get('modelV2') or not sm.updated.get('liveCalibration'):
            return result

        v_ego = sm['carState'].vEgo if sm.updated.get('carState') else 0.0
        latest_data['speed'] = v_ego * 3.6

        model = sm['modelV2']
        calib = sm['liveCalibration']

        try:
            imgff = np.frombuffer(yuv_buf.data, dtype=np.uint8).reshape((-1, yuv_buf.stride))
            y_data = imgff[:self.h, :self.w]
            extrinsic = get_view_frame_from_calib_frame(calib.rpyCalib[0], 0.0, 0.0, 0.0)
        except Exception: return result

        for i, line_idx in enumerate([1, 2]):
            line = model.laneLines[line_idx]
            if model.laneLineProbs[line_idx] < self.prob_threshold: continue

            xs, ys, zs = np.array(line.x), np.array(line.y), np.array(line.z)
            sample_xs = np.linspace(self.lookahead_start, self.lookahead_end, self.num_points)
            sample_ys = np.interp(sample_xs, xs, ys)
            sample_zs = np.interp(sample_xs, xs, zs)

            pixels = []
            for k in range(self.num_points):
                p = extrinsic.dot(np.array([sample_xs[k], sample_ys[k], sample_zs[k], 1.0]))
                if p[2] <= 1.0: continue
                u = int(p[0] / p[2] * self.intrinsics[0, 0] + self.intrinsics[0, 2])
                v = int(p[1] / p[2] * self.intrinsics[1, 1] + self.intrinsics[1, 2])
                if 0 <= u < self.w and 0 <= v < self.h:
                    pixels.append(int(y_data[v, u]))

            res_type, res_std = self.analyze_vocal_continuity(pixels, v_ego)

            side = 'left' if i == 0 else 'right'
            result[side] = res_type
            result[f'{side}_rel_std'] = res_std

            latest_data[f'{side}_type'] = ['虚线', '实线', '不确定'][res_type if res_type >= 0 else 2]
            latest_data[f'{side}_rel_std'] = res_std

        latest_data['last_update'] = time.time()
        return result

def main():
    threading.Thread(target=start_flask, daemon=True).start()

    detector = LaneLineDetector()
    sm = messaging.SubMaster(['modelV2', 'liveCalibration', 'roadCameraState', 'carState'])
    vipc_client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_ROAD, True)

    while not vipc_client.connect(False): time.sleep(0.1)

    while True:
        sm.update(0)
        if detector.init_camera(sm, vipc_client): break
        time.sleep(0.1)

    while True:
        sm.update(0)
        yuv_buf = vipc_client.recv()
        if yuv_buf is not None:
            detector.update(sm, yuv_buf)

if __name__ == "__main__":
    main()
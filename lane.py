#!/usr/bin/env python3
import time
import numpy as np
from collections import deque, Counter
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

latest_config = {
    'lookahead_start': 3.0,
    'lookahead_end': 40.0,
    'num_points': 120,
    'prob_threshold': 0.4,
    'rel_std_solid_max': 0.06,
    'rel_std_dash_min': 0.15,
    'jump_threshold_factor': 0.5,
    'window_points': 25
}
config_lock = threading.Lock()

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
        .panel { margin-top: 2rem; padding-top: 1.5rem; border-top: 1px solid #334155; }
        .row { display: flex; align-items: center; justify-content: space-between; margin: 0.75rem 0; }
        .row label { color: #94a3b8; font-size: 0.95rem; width: 50%; }
        .row input[type="range"] { width: 40%; }
        .row .val { width: 10%; text-align: right; color: #38bdf8; font-family: 'JetBrains Mono', 'Fira Code', monospace; }
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
        <div class="panel">
            <div class="row">
                <label>概率阈值</label>
                <input id="prob_threshold" type="range" min="0" max="1" step="0.01" value="0.3">
                <span class="val" id="prob_threshold_val">0.30</span>
            </div>
            <div class="row">
                <label>实线相对方差最大值</label>
                <input id="rel_std_solid_max" type="range" min="0.02" max="0.20" step="0.01" value="0.08">
                <span class="val" id="rel_std_solid_max_val">0.08</span>
            </div>
            <div class="row">
                <label>虚线相对方差最小值</label>
                <input id="rel_std_dash_min" type="range" min="0.05" max="0.50" step="0.01" value="0.12">
                <span class="val" id="rel_std_dash_min_val">0.12</span>
            </div>
            <div class="row">
                <label>采样起点 (米)</label>
                <input id="lookahead_start" type="range" min="2" max="10" step="0.5" value="6.0">
                <span class="val" id="lookahead_start_val">6.0</span>
            </div>
            <div class="row">
                <label>采样终点 (米)</label>
                <input id="lookahead_end" type="range" min="20" max="60" step="0.5" value="45.0">
                <span class="val" id="lookahead_end_val">45.0</span>
            </div>
            <div class="row">
                <label>采样点数量</label>
                <input id="num_points" type="range" min="20" max="200" step="1" value="100">
                <span class="val" id="num_points_val">100</span>
            </div>
            <div class="row">
                <label>亮度跳变因子</label>
                <input id="jump_threshold_factor" type="range" min="0.1" max="1.0" step="0.05" value="0.4">
                <span class="val" id="jump_threshold_factor_val">0.40</span>
            </div>
            <div class="row">
                <label>虚线周期窗口点数</label>
                <input id="window_points" type="range" min="10" max="80" step="1" value="38">
                <span class="val" id="window_points_val">38</span>
            </div>
        </div>
        <div class="footer">
            最后心跳: <span id="timestamp">--:--:--</span>
        </div>
    </div>
    <script>
        const ids = ["prob_threshold","rel_std_solid_max","rel_std_dash_min","lookahead_start","lookahead_end","num_points","jump_threshold_factor","window_points"];
        function setVal(id, val) {
            document.getElementById(id).value = val;
            document.getElementById(id + "_val").innerText = (typeof val === 'number') ? (id.includes("num_points") || id.includes("window_points") ? Math.round(val) : Number(val).toFixed(id.includes("lookahead") ? 1 : 2)) : val;
        }
        function bindSliders() {
            ids.forEach(id => {
                const el = document.getElementById(id);
                el.oninput = () => {
                    const v = el.type === 'range' ? parseFloat(el.value) : el.value;
                    setVal(id, v);
                    const payload = {};
                    payload[id] = (id === 'num_points' || id === 'window_points') ? Math.round(v) : v;
                    fetch('/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
                };
            });
        }
        function loadConfig() {
            fetch('/config').then(r=>r.json()).then(cfg=>{
                ids.forEach(id => setVal(id, cfg[id]));
            });
        }
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
            fetch('/config')
                .then(r=>r.json())
                .then(cfg=>{
                    ids.forEach(id => setVal(id, cfg[id]));
                })
                .catch(e => console.error("Config failed:", e));
        }
        bindSliders();
        loadConfig();
        setInterval(update, 1000);
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

@app.route('/config', methods=['GET'])
def get_config():
    with config_lock:
        return jsonify(latest_config)

@app.route('/config', methods=['POST'])
def set_config():
    from flask import request
    data = request.get_json(force=True) or {}
    allowed = set(latest_config.keys())
    with config_lock:
        for k, v in data.items():
            if k in allowed:
                latest_config[k] = float(v) if k not in ('num_points', 'window_points') else int(v)
    return jsonify({'ok': True, 'config': latest_config})

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
        self.history = {'left': deque(maxlen=5), 'right': deque(maxlen=5)}
        self.update_params()

    def update_params(self):
        with config_lock:
            cfg = dict(latest_config)
        self.lookahead_start = cfg['lookahead_start']
        self.lookahead_end = cfg['lookahead_end']
        self.num_points = int(cfg['num_points'])
        self.prob_threshold = cfg['prob_threshold']
        self.rel_std_solid_max = cfg['rel_std_solid_max']
        self.rel_std_dash_min = cfg['rel_std_dash_min']
        self.jump_threshold_factor = cfg['jump_threshold_factor']
        self.window_points = int(cfg['window_points'])

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

    def smooth_result(self, side, current_type):
        """使用历史帧平滑结果"""
        self.history[side].append(current_type)

        if len(self.history[side]) < 3:
            return current_type

        # 投票机制：取最近5帧的众数
        counts = Counter(self.history[side])
        most_common = counts.most_common(1)[0][0]

        return most_common

    def analyze_lane_continuity(self, pixel_values, v_ego):
        """改进的虚线检测 - 添加周期性分析

        理论依据:
        1. 信号处理(Signal Processing): 使用自相关(Autocorrelation)检测亮度信号的周期性
        2. 统计学(Statistics): 使用相对标准差(Relative STD)区分实线(低波动)和虚线(高波动)
        """
        if len(pixel_values) < 30:
            return -1, 0.0

        # 基础统计
        pixels = np.array(pixel_values, dtype=np.float32)
        std = np.std(pixels)
        mean = np.mean(pixels)
        rel_std = std / max(mean, 1.0)

        # 1. 明确的实线判断 - 方差极低且稳定
        if rel_std < self.rel_std_solid_max:
            return 1, rel_std

        # 2. 归一化信号用于周期性分析
        normalized = (pixels - mean) / max(std, 1.0)

        # 3. 自相关分析检测周期性
        def detect_periodicity(signal, min_period=5, max_period=None):
            """使用自相关检测周期性"""
            if max_period is None:
                max_period = len(signal) // 3

            autocorr_scores = []
            for lag in range(min_period, min(max_period, len(signal)//2)):
                corr = np.corrcoef(signal[:-lag], signal[lag:])[0, 1]
                if not np.isnan(corr):
                    autocorr_scores.append((lag, corr))

            if not autocorr_scores:
                return False, 0

            # 找到最强的周期性（正相关峰值）
            max_corr = max(autocorr_scores, key=lambda x: x[1])
            return max_corr[1] > 0.3, max_corr[0]  # 相关系数 > 0.3 认为有周期性

        has_period, period = detect_periodicity(normalized)

        # 4. 改进的跳变分析 - 检测虚线段数
        diffs = np.abs(np.diff(pixels))
        jump_thresh = self.jump_threshold_factor * max(mean, 1.0)
        significant_jumps = diffs > jump_thresh

        # 统计虚线段数（连续跳变算一段）
        dash_segments = 0
        in_segment = False
        for is_jump in significant_jumps:
            if is_jump and not in_segment:
                dash_segments += 1
                in_segment = True
            elif not is_jump:
                in_segment = False

        # 5. 综合判断虚线
        # 条件：高方差 + 周期性 + 足够的虚线段数（至少2-3段）
        max_possible_segments = (len(pixels) // period * 1.5) if period > 0 else 999

        is_dashed = (
            rel_std > self.rel_std_dash_min and
            has_period and
            dash_segments >= 2 and
            dash_segments <= max_possible_segments
        )

        if is_dashed:
            return 0, rel_std

        # 6. 备选判断 - 基于跳变但要求更严格
        if dash_segments >= 4 and rel_std > self.rel_std_dash_min * 1.2:
            return 0, rel_std

        # 7. 不确定情况
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

        self.update_params()

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

                # 添加边界检查和插值采样
                if 1 <= u < self.w-1 and 1 <= v < self.h-1:
                    # 使用双线性插值提高采样质量 (5点均值)
                    pixel_val = (
                        int(y_data[v, u]) * 0.5 +
                        int(y_data[v-1, u]) * 0.125 +
                        int(y_data[v+1, u]) * 0.125 +
                        int(y_data[v, u-1]) * 0.125 +
                        int(y_data[v, u+1]) * 0.125
                    )
                    pixels.append(pixel_val)

            res_type, res_std = self.analyze_lane_continuity(pixels, v_ego)

            side = 'left' if i == 0 else 'right'
            # 平滑结果
            res_type = self.smooth_result(side, res_type)
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

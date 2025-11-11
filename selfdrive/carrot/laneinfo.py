#!/usr/bin/env python3
"""
马自达车道线信息实时监控Web服务
端口: 8888
功能: 实时显示马自达车道线融合信息和模型数据
"""

import json
import time
import threading
from datetime import datetime
from flask import Flask, render_template_string, jsonify, Response
import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.common.params import Params

# ============ Flask应用初始化 ============
app = Flask(__name__)
app.config['SECRET_KEY'] = 'mazda_lane_info_secret_key'

# ============ 全局变量 ============
current_lane_data = {
    'timestamp': 0,
    'mazda_fusion': {
        'fusion_enabled': False,
        'left_lane_line': -1,
        'right_lane_line': -1,
        'mazda_lane_status': 0,
        'fusion_debug': ''
    },
    'model_data': {
        'lane_lines': {
            '0': {'x': [], 'y': [], 'z': [], 't': []},
            '1': {'x': [], 'y': [], 'z': [], 't': []},
            '2': {'x': [], 'y': [], 'z': [], 't': []},
            '3': {'x': [], 'y': [], 'z': [], 't': []}
        },
        'lane_line_probs': [0.0, 0.0, 0.0, 0.0],
        'lane_line_stds': [0.0, 0.0, 0.0, 0.0],
        'road_edges': {
            'left': {'x': [], 'y': [], 'z': [], 't': []},
            'right': {'x': [], 'y': [], 'z': [], 't': []}
        },
        'road_edge_stds': [0.0, 0.0],
        'desire_state': {
            'lane_change_left': 0.0,
            'lane_change_right': 0.0
        }
    },
    'car_state': {
        'leftLaneLine': -1,
        'rightLaneLine': -1,
        'vEgo': 0.0,
        'steeringAngleDeg': 0.0
    },
    'system_status': {
        'active': False,
        'last_update': '',
        'error_count': 0
    }
}

# HTML模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>马自达车道线信息监控</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 15px;
            backdrop-filter: blur(10px);
        }
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            background: linear-gradient(45deg, #00d4ff, #0099ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-left: 10px;
            animation: pulse 2s infinite;
        }
        .status-active { background-color: #00ff00; }
        .status-inactive { background-color: #ff4444; }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        .dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .card {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 15px;
            padding: 20px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            transition: transform 0.3s, box-shadow 0.3s;
        }
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }
        .card-title {
            font-size: 1.3em;
            font-weight: 600;
            margin-bottom: 15px;
            color: #00d4ff;
            border-bottom: 2px solid #00d4ff;
            padding-bottom: 10px;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            padding: 8px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
        }
        .info-label {
            font-weight: 500;
            color: #a0a0a0;
        }
        .info-value {
            font-weight: 600;
            color: #fff;
        }
        .fusion-active {
            background: rgba(0, 255, 0, 0.1);
            border: 1px solid rgba(0, 255, 0, 0.3);
        }
        .fusion-inactive {
            background: rgba(255, 68, 68, 0.1);
            border: 1px solid rgba(255, 68, 68, 0.3);
        }
        .lane-line-type {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.9em;
            font-weight: 600;
        }
        .lane-solid { background: #00ff00; color: #000; }
        .lane-dashed { background: #ffff00; color: #000; }
        .lane-none { background: #ff4444; color: #fff; }
        .chart-container {
            margin-top: 20px;
            height: 300px;
            position: relative;
        }
        .refresh-info {
            text-align: center;
            margin-top: 20px;
            font-size: 0.9em;
            color: #a0a0a0;
        }
        .debug-info {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 10px;
            margin-top: 10px;
            font-family: monospace;
            font-size: 0.85em;
            max-height: 100px;
            overflow-y: auto;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚗 马自达车道线信息监控</h1>
            <div>
                <span id="status-text">系统状态</span>
                <span id="status-indicator" class="status-indicator status-inactive"></span>
            </div>
            <div class="refresh-info">
                最后更新: <span id="last-update">--</span> |
                自动刷新间隔: 1秒
            </div>
        </div>

        <div class="dashboard">
            <!-- 马自达融合信息 -->
            <div class="card">
                <div class="card-title">🔄 马自达融合信息 (CAN+视觉)</div>
                <div class="info-row">
                    <span class="info-label">融合状态:</span>
                    <span class="info-value" id="fusion-status">
                        <span id="fusion-enabled">未启用</span>
                    </span>
                </div>
                <div class="info-row">
                    <span class="info-label">马自达车道线状态 (CAN):</span>
                    <span class="info-value" id="mazda-lane-status">--</span>
                </div>
                <div class="info-row">
                    <span class="info-label">融合后左车道线:</span>
                    <span class="info-value" id="fusion-left-lane">
                        <span class="lane-line-type lane-none">无</span>
                    </span>
                </div>
                <div class="info-row">
                    <span class="info-label">融合后右车道线:</span>
                    <span class="info-value" id="fusion-right-lane">
                        <span class="lane-line-type lane-none">无</span>
                    </span>
                </div>
                <div class="debug-info" id="fusion-debug">
                    等待数据...
                </div>
            </div>

            <!-- 车辆状态 -->
            <div class="card">
                <div class="card-title">🚗 车辆状态 (CarState)</div>
                <div class="info-row">
                    <span class="info-label">左车道线 (CS):</span>
                    <span class="info-value" id="car-left-lane">
                        <span class="lane-line-type lane-none">无</span>
                    </span>
                </div>
                <div class="info-row">
                    <span class="info-label">右车道线 (CS):</span>
                    <span class="info-value" id="car-right-lane">
                        <span class="lane-line-type lane-none">无</span>
                    </span>
                </div>
                <div class="info-row">
                    <span class="info-label">车速 (CAN):</span>
                    <span class="info-value" id="vehicle-speed">0 km/h</span>
                </div>
                <div class="info-row">
                    <span class="info-label">转向角度 (CAN):</span>
                    <span class="info-value" id="steering-angle">0.0°</span>
                </div>
            </div>

            <!-- 模型车道线概率 -->
            <div class="card">
                <div class="card-title">📊 模型车道线概率 (视觉模型)</div>
                <div class="info-row">
                    <span class="info-label">最左侧车道线 (视觉):</span>
                    <span class="info-value" id="prob-0">0.00</span>
                </div>
                <div class="info-row">
                    <span class="info-label">左侧车道线 (视觉):</span>
                    <span class="info-value" id="prob-1">0.00</span>
                </div>
                <div class="info-row">
                    <span class="info-label">右侧车道线 (视觉):</span>
                    <span class="info-value" id="prob-2">0.00</span>
                </div>
                <div class="info-row">
                    <span class="info-label">最右侧车道线 (视觉):</span>
                    <span class="info-value" id="prob-3">0.00</span>
                </div>
                <div class="chart-container">
                    <canvas id="probChart"></canvas>
                </div>
            </div>

            <!-- 变道意图 -->
            <div class="card">
                <div class="card-title">🔀 变道意图 (视觉模型)</div>
                <div class="info-row">
                    <span class="info-label">左变道概率 (视觉):</span>
                    <span class="info-value" id="desire-left">0.00</span>
                </div>
                <div class="info-row">
                    <span class="info-label">右变道概率 (视觉):</span>
                    <span class="info-value" id="desire-right">0.00</span>
                </div>
                <div class="info-row">
                    <span class="info-label">车道保持概率 (视觉):</span>
                    <span class="info-value" id="desire-keep">0.00</span>
                </div>
            </div>
        </div>

        <!-- 车道线可视化 -->
        <div class="card">
            <div class="card-title">📈 车道线可视化</div>
            <div class="chart-container" style="height: 400px;">
                <canvas id="laneChart"></canvas>
            </div>
        </div>
    </div>

    <script>
        // 全局变量
        let probChart, laneChart;

        // 初始化图表
        function initCharts() {
            // 概率图表
            const probCtx = document.getElementById('probChart').getContext('2d');
            probChart = new Chart(probCtx, {
                type: 'bar',
                data: {
                    labels: ['最左侧(视觉)', '左侧(视觉)', '右侧(视觉)', '最右侧(视觉)'],
                    datasets: [{
                        label: '车道线概率',
                        data: [0, 0, 0, 0],
                        backgroundColor: [
                            'rgba(255, 99, 132, 0.8)',
                            'rgba(54, 162, 235, 0.8)',
                            'rgba(255, 206, 86, 0.8)',
                            'rgba(75, 192, 192, 0.8)'
                        ],
                        borderColor: [
                            'rgba(255, 99, 132, 1)',
                            'rgba(54, 162, 235, 1)',
                            'rgba(255, 206, 86, 1)',
                            'rgba(75, 192, 192, 1)'
                        ],
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 1.0,
                            ticks: { color: '#fff' },
                            grid: { color: 'rgba(255, 255, 255, 0.1)' }
                        },
                        x: {
                            ticks: { color: '#fff' },
                            grid: { color: 'rgba(255, 255, 255, 0.1)' }
                        }
                    },
                    plugins: {
                        legend: { labels: { color: '#fff' } }
                    }
                }
            });

            // 车道线可视化图表
            const laneCtx = document.getElementById('laneChart').getContext('2d');
            laneChart = new Chart(laneCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: '最左侧车道线 (视觉)',
                            data: [],
                            borderColor: 'rgba(255, 99, 132, 0.8)',
                            backgroundColor: 'rgba(255, 99, 132, 0.2)',
                            borderWidth: 2,
                            tension: 0.4
                        },
                        {
                            label: '左侧车道线 (视觉)',
                            data: [],
                            borderColor: 'rgba(54, 162, 235, 0.8)',
                            backgroundColor: 'rgba(54, 162, 235, 0.2)',
                            borderWidth: 3,
                            tension: 0.4
                        },
                        {
                            label: '右侧车道线 (视觉)',
                            data: [],
                            borderColor: 'rgba(255, 206, 86, 0.8)',
                            backgroundColor: 'rgba(255, 206, 86, 0.2)',
                            borderWidth: 3,
                            tension: 0.4
                        },
                        {
                            label: '最右侧车道线 (视觉)',
                            data: [],
                            borderColor: 'rgba(75, 192, 192, 0.8)',
                            backgroundColor: 'rgba(75, 192, 192, 0.2)',
                            borderWidth: 2,
                            tension: 0.4
                        },
                        {
                            label: '左道路边缘 (视觉)',
                            data: [],
                            borderColor: 'rgba(255, 255, 255, 0.5)',
                            borderWidth: 1,
                            borderDash: [5, 5]
                        },
                        {
                            label: '右道路边缘 (视觉)',
                            data: [],
                            borderColor: 'rgba(255, 255, 255, 0.5)',
                            borderWidth: 1,
                            borderDash: [5, 5]
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            title: { display: true, text: '纵向距离 (米)', color: '#fff' },
                            ticks: { color: '#fff' },
                            grid: { color: 'rgba(255, 255, 255, 0.1)' }
                        },
                        y: {
                            title: { display: true, text: '横向偏移 (米)', color: '#fff' },
                            ticks: { color: '#fff' },
                            grid: { color: 'rgba(255, 255, 255, 0.1)' }
                        }
                    },
                    plugins: {
                        legend: { labels: { color: '#fff' } }
                    }
                }
            });
        }

        // 更新车道线类型显示
        function updateLaneType(elementId, laneType) {
            const element = document.getElementById(elementId);
            let className = 'lane-line-type ';
            let text = '';

            if (laneType === -1) {
                className += 'lane-none';
                text = '无';
            } else if (laneType === 0) {
                className += 'lane-dashed';
                text = '虚线';
            } else if (laneType === 10) {
                className += 'lane-dashed';
                text = '虚线';
            } else if (laneType === 11) {
                className += 'lane-solid';
                text = '实线';
            } else {
                className += 'lane-none';
                text = `类型${laneType}`;
            }

            element.innerHTML = `<span class="${className}">${text}</span>`;
        }

        // 更新界面数据
        function updateUI(data) {
            // 更新系统状态
            const statusIndicator = document.getElementById('status-indicator');
            const statusText = document.getElementById('status-text');

            if (data.system_status.active) {
                statusIndicator.className = 'status-indicator status-active';
                statusText.textContent = '系统运行中';
            } else {
                statusIndicator.className = 'status-indicator status-inactive';
                statusText.textContent = '系统未激活';
            }

            // 更新最后更新时间
            document.getElementById('last-update').textContent = data.system_status.last_update;

            // 更新马自达融合信息
            const mazdaFusion = data.mazda_fusion;
            const fusionEnabled = document.getElementById('fusion-enabled');
            const fusionStatus = document.getElementById('fusion-status');

            if (mazdaFusion.fusion_enabled) {
                fusionEnabled.textContent = '已启用';
                fusionStatus.className = 'info-value fusion-active';
            } else {
                fusionEnabled.textContent = '未启用';
                fusionStatus.className = 'info-value fusion-inactive';
            }

            // 更新马自达车道线状态
            const mazdaLaneStatusText = {
                0: '无车道线',
                1: '未知',
                2: '双车道线',
                3: '仅左车道线',
                4: '仅右车道线'
            };
            document.getElementById('mazda-lane-status').textContent =
                mazdaLaneStatusText[mazdaFusion.mazda_lane_status] || `状态${mazdaFusion.mazda_lane_status}`;

            // 更新融合后车道线
            updateLaneType('fusion-left-lane', mazdaFusion.left_lane_line);
            updateLaneType('fusion-right-lane', mazdaFusion.right_lane_line);

            // 更新调试信息
            document.getElementById('fusion-debug').textContent = mazdaFusion.fusion_debug || '无调试信息';

            // 更新车辆状态
            const carState = data.car_state;
            updateLaneType('car-left-lane', carState.leftLaneLine);
            updateLaneType('car-right-lane', carState.rightLaneLine);
            document.getElementById('vehicle-speed').textContent = `${(carState.vEgo * 3.6).toFixed(1)} km/h`;
            document.getElementById('steering-angle').textContent = `${carState.steeringAngleDeg.toFixed(1)}°`;

            // 更新模型概率
            const modelData = data.model_data;
            const probs = modelData.lane_line_probs;
            for (let i = 0; i < 4; i++) {
                document.getElementById(`prob-${i}`).textContent = probs[i].toFixed(2);
            }
            probChart.data.datasets[0].data = probs;
            probChart.update('none');

            // 更新变道意图
            const desireLeft = modelData.desire_state.lane_change_left;
            const desireRight = modelData.desire_state.lane_change_right;
            document.getElementById('desire-left').textContent = desireLeft.toFixed(2);
            document.getElementById('desire-right').textContent = desireRight.toFixed(2);

            const keepProbability = Math.max(0, 1 - desireLeft - desireRight);
            document.getElementById('desire-keep').textContent = keepProbability.toFixed(2);

            // 更新车道线可视化
            updateLaneVisualization(modelData);
        }

        // 更新车道线可视化
        function updateLaneVisualization(modelData) {
            const laneLines = modelData.lane_lines;
            const roadEdges = modelData.road_edges;

            // 准备数据
            const distances = [];
            const datasets = [];

            // 使用左车道线作为X轴参考
            if (laneLines['1'].x && laneLines['1'].x.length > 0) {
                distances.push(...laneLines['1'].x);

                // 车道线数据
                for (let i = 0; i < 4; i++) {
                    const laneKey = i.toString();
                    if (laneLines[laneKey].x && laneLines[laneKey].y) {
                        datasets.push({
                            label: ['最左侧车道线 (视觉)', '左侧车道线 (视觉)', '右侧车道线 (视觉)', '最右侧车道线 (视觉)'][i],
                            data: laneLines[laneKey].x.map((x, idx) => ({
                                x: x,
                                y: laneLines[laneKey].y[idx]
                            })),
                            borderColor: ['rgba(255, 99, 132, 0.8)', 'rgba(54, 162, 235, 0.8)',
                                        'rgba(255, 206, 86, 0.8)', 'rgba(75, 192, 192, 0.8)'][i],
                            backgroundColor: ['rgba(255, 99, 132, 0.2)', 'rgba(54, 162, 235, 0.2)',
                                            'rgba(255, 206, 86, 0.2)', 'rgba(75, 192, 192, 0.2)'][i],
                            borderWidth: i === 1 || i === 2 ? 3 : 2,
                            tension: 0.4,
                            pointRadius: 0
                        });
                    }
                }

                // 道路边缘数据
                if (roadEdges.left.x && roadEdges.left.y) {
                    datasets.push({
                        label: '左道路边缘 (视觉)',
                        data: roadEdges.left.x.map((x, idx) => ({
                            x: x,
                            y: roadEdges.left.y[idx]
                        })),
                        borderColor: 'rgba(255, 255, 255, 0.5)',
                        borderWidth: 1,
                        borderDash: [5, 5],
                        tension: 0.4,
                        pointRadius: 0
                    });
                }

                if (roadEdges.right.x && roadEdges.right.y) {
                    datasets.push({
                        label: '右道路边缘 (视觉)',
                        data: roadEdges.right.x.map((x, idx) => ({
                            x: x,
                            y: roadEdges.right.y[idx]
                        })),
                        borderColor: 'rgba(255, 255, 255, 0.5)',
                        borderWidth: 1,
                        borderDash: [5, 5],
                        tension: 0.4,
                        pointRadius: 0
                    });
                }

                // 更新图表
                laneChart.data.labels = distances;
                laneChart.data.datasets = datasets;
                laneChart.update('none');
            }
        }

        // 获取数据
        async function fetchData() {
            try {
                const response = await fetch('/api/lane_data');
                const data = await response.json();
                updateUI(data);
            } catch (error) {
                console.error('获取数据失败:', error);
            }
        }

        // 初始化
        document.addEventListener('DOMContentLoaded', function() {
            initCharts();
            fetchData();
            // 每秒自动刷新
            setInterval(fetchData, 1000);
        });
    </script>
</body>
</html>
"""

# ============ 数据更新线程 ============
def lane_data_updater():
    """车道线数据更新线程"""
    global current_lane_data

    try:
        # 初始化消息订阅
        sm = messaging.SubMaster(['carState', 'modelV2'])
        rk = Ratekeeper(10.0)  # 10Hz更新频率

        error_count = 0

        while True:
            # 更新数据
            sm.update()

            if sm.updated['carState'] or sm.updated['modelV2']:
                try:
                    # 获取CarState数据
                    if sm.valid['carState']:
                        cs = sm['carState']
                        current_lane_data['car_state'].update({
                            'leftLaneLine': cs.leftLaneLine,
                            'rightLaneLine': cs.rightLaneLine,
                            'vEgo': cs.vEgo,
                            'steeringAngleDeg': cs.steeringAngleDeg
                        })

                        # 检查是否为马自达车型且支持融合
                        if hasattr(cs, 'camLaneInfo'):
                            current_lane_data['mazda_fusion']['mazda_lane_status'] = cs.camLaneInfo.get("LANE_LINES", 0)

                        # 尝试获取马自达融合结果（如果有）
                        if hasattr(cs, 'getMazdaFusionResult'):
                            try:
                                fusion_result = cs.getMazdaFusionResult()
                                current_lane_data['mazda_fusion'].update({
                                    'fusion_enabled': fusion_result.get('enabled', False),
                                    'left_lane_line': fusion_result.get('left_lane', -1),
                                    'right_lane_line': fusion_result.get('right_lane', -1)
                                })
                            except:
                                pass

                    # 获取Model数据
                    if sm.valid['modelV2']:
                        md = sm['modelV2']

                        # 车道线数据
                        if hasattr(md, 'laneLines') and len(md.laneLines) >= 4:
                            for i, lane_line in enumerate(md.laneLines):
                                lane_key = str(i)
                                if hasattr(lane_line, 'x') and hasattr(lane_line, 'y'):
                                    current_lane_data['model_data']['lane_lines'][lane_key] = {
                                        'x': list(lane_line.x),
                                        'y': list(lane_line.y),
                                        'z': list(lane_line.z) if hasattr(lane_line, 'z') else [],
                                        't': list(lane_line.t) if hasattr(lane_line, 't') else []
                                    }

                        # 车道线概率
                        if hasattr(md, 'laneLineProbs') and len(md.laneLineProbs) >= 4:
                            current_lane_data['model_data']['lane_line_probs'] = [
                                float(md.laneLineProbs[i]) for i in range(4)
                            ]

                        # 车道线标准差
                        if hasattr(md, 'laneLineStds') and len(md.laneLineStds) >= 4:
                            current_lane_data['model_data']['lane_line_stds'] = [
                                float(md.laneLineStds[i]) for i in range(4)
                            ]

                        # 道路边缘
                        if hasattr(md, 'roadEdges') and len(md.roadEdges) >= 2:
                            current_lane_data['model_data']['road_edges'] = {
                                'left': {
                                    'x': list(md.roadEdges[0].x) if hasattr(md.roadEdges[0], 'x') else [],
                                    'y': list(md.roadEdges[0].y) if hasattr(md.roadEdges[0], 'y') else [],
                                    'z': list(md.roadEdges[0].z) if hasattr(md.roadEdges[0], 'z') else [],
                                    't': list(md.roadEdges[0].t) if hasattr(md.roadEdges[0], 't') else []
                                },
                                'right': {
                                    'x': list(md.roadEdges[1].x) if hasattr(md.roadEdges[1], 'x') else [],
                                    'y': list(md.roadEdges[1].y) if hasattr(md.roadEdges[1], 'y') else [],
                                    'z': list(md.roadEdges[1].z) if hasattr(md.roadEdges[1], 'z') else [],
                                    't': list(md.roadEdges[1].t) if hasattr(md.roadEdges[1], 't') else []
                                }
                            }

                        # 道路边缘标准差
                        if hasattr(md, 'roadEdgeStds') and len(md.roadEdgeStds) >= 2:
                            current_lane_data['model_data']['road_edge_stds'] = [
                                float(md.roadEdgeStds[0]),
                                float(md.roadEdgeStds[1])
                            ]

                        # 变道意图
                        if hasattr(md, 'meta') and hasattr(md.meta, 'desireState') and len(md.meta.desireState) >= 5:
                            current_lane_data['model_data']['desire_state'] = {
                                'lane_change_left': float(md.meta.desireState[3]),
                                'lane_change_right': float(md.meta.desireState[4])
                            }

                    # 更新时间戳和状态
                    current_lane_data['timestamp'] = time.time()
                    current_lane_data['system_status'].update({
                        'active': True,
                        'last_update': datetime.now().strftime('%H:%M:%S'),
                        'error_count': error_count
                    })

                    # 生成融合调试信息
                    fusion_info = current_lane_data['mazda_fusion']
                    model_probs = current_lane_data['model_data']['lane_line_probs']
                    fusion_info['fusion_debug'] = (
                        f"马自达状态: {fusion_info['mazda_lane_status']} | "
                        f"融合状态: {'启用' if fusion_info['fusion_enabled'] else '禁用'} | "
                        f"模型概率(左/右): {model_probs[1]:.2f}/{model_probs[2]:.2f} | "
                        f"融合结果: {fusion_info['left_lane_line']}/{fusion_info['right_lane_line']}"
                    )

                    error_count = 0  # 重置错误计数

                except Exception as e:
                    error_count += 1
                    print(f"数据处理错误: {e}")
                    current_lane_data['system_status']['error_count'] = error_count

                    if error_count > 10:
                        current_lane_data['system_status']['active'] = False

            rk.keep_time()

    except Exception as e:
        print(f"车道线数据更新线程错误: {e}")
        current_lane_data['system_status']['active'] = False
        time.sleep(1)

# ============ Flask路由 ============
@app.route('/')
def index():
    """主页面"""
    return HTML_TEMPLATE

@app.route('/api/lane_data')
def get_lane_data():
    """获取车道线数据的API接口"""
    # 添加响应头防止缓存
    response = jsonify(current_lane_data)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/status')
def get_status():
    """获取系统状态"""
    return jsonify({
        'status': 'ok',
        'timestamp': current_lane_data['timestamp'],
        'active': current_lane_data['system_status']['active'],
        'last_update': current_lane_data['system_status']['last_update'],
        'error_count': current_lane_data['system_status']['error_count']
    })

# ============ 启动服务器 ============
def main():
    """主函数"""
    print("🚗 启动马自达车道线信息监控服务...")
    print("📊 Web界面: http://localhost:8888")
    print("🔄 数据更新频率: 10Hz")
    print("⏹️  按 Ctrl+C 停止服务")

    # 启动数据更新线程
    updater_thread = threading.Thread(target=lane_data_updater, daemon=True)
    updater_thread.start()

    # 启动Flask服务器
    try:
        app.run(host='0.0.0.0', port=8888, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n⏹️  服务已停止")
    except Exception as e:
        print(f"❌ 服务器启动失败: {e}")

if __name__ == '__main__':
    main()
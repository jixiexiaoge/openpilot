#!/usr/bin/env python3
"""
Web界面模块 - 优化版
负责HTTP服务器和Web界面处理
"""

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

class WebInterface:
    """Web界面处理器"""
    
    def __init__(self, controller):
        self.controller = controller
        self.web_server = None

    def create_web_handler(self):
        """创建Web处理器"""
        controller = self.controller

        class OvertakeHTTPHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                """处理GET请求"""
                if self.path == '/':
                    self.send_html_response()
                elif self.path == '/status':
                    self.send_json_status()
                else:
                    pass

            def do_POST(self):
                """处理POST请求"""
                try:
                    content_length = int(self.headers.get('Content-Length', 0))
                    post_data = self.rfile.read(content_length).decode('utf-8')
                    data = json.loads(post_data) if post_data else {}

                    if self.path == '/control':
                        self.handle_control(data)
                    elif self.path == '/overtake':
                        self.handle_overtake(data)
                    elif self.path == '/config':
                        self.handle_config(data)
                    elif self.path == '/params':
                        self.handle_params(data)
                    else:
                        self.send_error(404, "接口未找到")
                except Exception as e:
                    self.send_error(400, "请求解析错误")

            def handle_control(self, data):
                """处理控制命令"""
                cmd_type = data.get('type', '')
                value = data.get('value', '')
                if cmd_type == 'SPEED':
                    controller.change_speed(value)
                self.send_json_response({'status': 'success', 'command': f'{cmd_type}: {value}'})

            def handle_overtake(self, data):
                """处理超车命令 - 修复状态显示"""
                if 'manual' in data:
                    # 修复：手动操作时短暂显示状态
                    controller.control_state['overtakeState'] = f"准备手动{data['manual']}变道"
                    controller.control_state['overtakeReason'] = "执行用户手动变道指令"
                    controller.manual_overtake(data['manual'])
                    self.send_json_response({'status': 'success', 'action': f'manual_{data["manual"]}'})
                elif 'cancel' in data:
                    controller.control_state['overtakeState'] = "取消超车"
                    controller.control_state['overtakeReason'] = "用户取消超车操作"
                    controller.cancel_overtake()
                    self.send_json_response({'status': 'success', 'action': 'cancel'})
                elif 'auto' in data:
                    new_auto = bool(data['auto'])
                    old_auto = controller.config['autoOvertakeEnabled']
                    controller.config['autoOvertakeEnabled'] = new_auto
                    controller.save_persistent_config()
                    
                    # 新增：自动超车开关状态短暂显示
                    status_text = "已启用" if new_auto else "已关闭"
                    controller.control_state['overtakeState'] = f"自动超车{status_text}"
                    controller.control_state['overtakeReason'] = f"用户{'开启' if new_auto else '关闭'}自动超车"
                    
                    self.send_json_response({'status': 'success', 'autoOvertake': controller.config['autoOvertakeEnabled']})
                elif 'autol' in data:
                    new_autol = bool(data['autol'])
                    controller.config['autoOvertakeEnabledL'] = new_autol
                    controller.save_persistent_config()
                    
                    # 新增：普通道路自动超车开关状态短暂显示
                    status_text = "已启用" if new_autol else "已关闭"
                    controller.control_state['overtakeState'] = f"普通道路自动超车{status_text}"
                    controller.control_state['overtakeReason'] = f"用户{'开启' if new_autol else '关闭'}普通道路自动超车"
                    
                    self.send_json_response({'status': 'success', 'autoOvertakeL': controller.config['autoOvertakeEnabledL']})
                elif 'return' in data:
                    new_return = bool(data['return'])
                    old_return = controller.config['shouldReturnToLane']
                    controller.config['shouldReturnToLane'] = new_return
                    controller.save_persistent_config()

                    # 如果关闭返回功能，重置相关状态
                    if not new_return and old_return:
                        controller.reset_net_lane_changes()
                    
                    # 状态自然恢复为"等待超车条件"
                    self.send_json_response({'status': 'success', 'returnToLane': controller.config['shouldReturnToLane']})
                else:
                    self.send_json_response({'status': 'error', 'message': '未知操作'})

            def handle_config(self, data):
                """处理配置更新"""
                if 'lane_count_mode' in data:
                    mode = data['lane_count_mode']
                    if mode in ['manual', 'auto', 'op']:
                        controller.config['lane_count_mode'] = mode
                        controller.calculate_lane_count()
                        controller.save_persistent_config()

                if 'lanes' in data and controller.config['lane_count_mode'] == 'manual':
                    lanes = int(data['lanes'])
                    if 1 <= lanes <= 5:
                        controller.config['lane_count'] = lanes
                        controller.config['manual_lane_count'] = lanes
                        controller.save_persistent_config()

                if 'manual_lane_count' in data and controller.config['lane_count_mode'] == 'manual':
                    lanes = int(data['manual_lane_count'])
                    if 1 <= lanes <= 5:
                        controller.config['manual_lane_count'] = lanes
                        controller.config['lane_count'] = lanes
                        controller.save_persistent_config()

                if 'road_type' in data:
                    new_road_type = data['road_type']
                    old_road_type = controller.config['road_type']

                    controller.config['road_type'] = new_road_type

                    if old_road_type == 'highway' and new_road_type == 'normal':
                        controller.reset_net_lane_changes()

                    controller.calculate_lane_count()
                    controller.save_persistent_config()

                self.send_json_response({'status': 'success', 'config': controller.config})

            def handle_params(self, data):
                """处理参数更新 - 修正单位换算"""
                param_map = {
                    'highwayMinSpeed': 'HIGHWAY_MIN_SPEED',
                    'normalMinSpeed': 'NORMAL_ROAD_MIN_SPEED',
                    'speedRatio': 'CRUISE_SPEED_RATIO_THRESHOLD',
                    'followTimeGap': 'FOLLOW_TIME_GAP_THRESHOLD',
                    'maxFollowTime': 'MAX_FOLLOW_TIME',  # 🎯 关键修复：最大跟车时间
                    'minLaneWidth': 'MIN_LANE_WIDTH',
                    'safeLaneWidth': 'SAFE_LANE_WIDTH',
                    'sideLeadDist': 'SIDE_LEAD_DISTANCE_MIN',
                    'sideRelSpeed': 'SIDE_RELATIVE_SPEED_THRESHOLD',
                    'leadRelSpeed': 'LEAD_RELATIVE_SPEED_THRESHOLD',
                    # 🆕 v3.7 新增参数
                    'highwayLeadMinSpeed': 'HIGHWAY_LEAD_MIN_SPEED',
                    'normalLeadMinSpeed': 'NORMAL_LEAD_MIN_SPEED',
                    'earlyOvertakeSpeedRatio': 'EARLY_OVERTAKE_SPEED_RATIO',
                    'earlyOvertakeMinLeadSpeed': 'EARLY_OVERTAKE_MIN_LEAD_SPEED',
                    'earlyOvertakeMinDistance': 'EARLY_OVERTAKE_MIN_DISTANCE',
                    'earlyOvertakeMaxDistance': 'EARLY_OVERTAKE_MAX_DISTANCE',
                    'earlyOvertakeMinSpeedDiff': 'EARLY_OVERTAKE_MIN_SPEED_DIFF'
                }

                for web_key, config_key in param_map.items():
                    if web_key in data:
                        if web_key == 'maxFollowTime':
                            # 修复：将分钟转换为毫秒
                            minutes = float(data[web_key])
                            controller.config[config_key] = int(minutes * 60 * 1000)  # 分钟 → 毫秒
                        elif web_key == 'speedRatio' or web_key == 'earlyOvertakeSpeedRatio':
                            controller.config[config_key] = float(data[web_key]) / 100.0
                        else:
                            controller.config[config_key] = float(data[web_key])

                controller.save_persistent_config()
                self.send_json_response({'status': 'success', 'message': '参数已保存'})

            def send_html_response(self):
                """发送HTML页面"""
                html = self.get_html_content()
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))

            def send_json_status(self):
                """发送JSON状态数据"""
                status_data = controller.get_status_data()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(status_data, ensure_ascii=False).encode('utf-8'))

            def send_json_response(self, data):
                """发送JSON响应"""
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

            def get_html_content(self):
                """获取HTML文件内容"""
                html_file_path = os.path.join(os.path.dirname(__file__), 'web_interface.html')
                try:
                    with open(html_file_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except FileNotFoundError:
                    return "<html><body><h1>错误：未找到HTML界面文件</h1></body></html>"

            def log_message(self, format, *args):
                """禁用访问日志"""
                pass

        return OvertakeHTTPHandler

    def start_web_server(self):
        """启动Web服务器"""
        handler = self.create_web_handler()
        self.web_server = HTTPServer(('0.0.0.0', 8088), handler)
        self.web_server.serve_forever()
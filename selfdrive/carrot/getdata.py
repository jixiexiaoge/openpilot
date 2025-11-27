#!/usr/bin/env python3
"""
Xiaoge 数据接收和 Web 显示工具
从 TCP 服务器（端口 7711）接收数据，并通过 Web 页面实时显示

使用方法：
    python getdata.py
    然后在浏览器中打开 http://localhost:5000
"""

import json
import socket
import struct
import threading
import time
from typing import Dict, Any, Optional
from datetime import datetime
from collections import deque

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import traceback

app = Flask(__name__)
app.config['SECRET_KEY'] = 'xiaoge_data_receiver'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

class XiaogeDataReceiver:
    """Xiaoge 数据接收器"""
    
    def __init__(self, target_ip: str, port: int = 7711):
        """
        初始化数据接收器
        
        参数:
        - target_ip: 目标服务器 IP 地址
        - port: TCP 端口号（默认 7711）
        """
        self.target_ip = target_ip
        self.port = port
        self.sock = None
        self.is_connected = False
        self.is_running = False
        self.receive_thread = None
        self.heartbeat_thread = None
        self.last_heartbeat_time = 0
        
        # 数据缓存
        self.latest_data: Optional[Dict[str, Any]] = None
        self.data_history = deque(maxlen=100)  # 保留最近100条数据
        self.stats = {
            'total_packets': 0,
            'total_bytes': 0,
            'last_update': None,
            'connection_status': 'disconnected',
            'error_count': 0
        }
        
    def recv_all(self, sock: socket.socket, length: int) -> Optional[bytes]:
        """
        接收指定字节数的数据（TCP 需要确保接收完整数据）
        
        参数:
        - sock: socket 对象
        - length: 需要接收的字节数
        
        返回: 接收到的数据（bytes），如果连接关闭则返回 None
        """
        data = bytearray()
        while len(data) < length:
            try:
                packet = sock.recv(length - len(data))
                if not packet:  # 连接已关闭
                    return None
                data.extend(packet)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"接收数据错误: {e}")
                return None
        return bytes(data)
    
    def connect(self) -> bool:
        """连接到 TCP 服务器"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)  # 5秒超时
            self.sock.connect((self.target_ip, self.port))
            self.is_connected = True
            self.stats['connection_status'] = 'connected'
            print(f"✅ 已连接到 {self.target_ip}:{self.port}")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            self.is_connected = False
            self.stats['connection_status'] = 'disconnected'
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
                self.sock = None
            return False
    
    def disconnect(self):
        """断开连接"""
        self.is_connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        self.stats['connection_status'] = 'disconnected'
        print("已断开连接")
    
    def send_heartbeat(self):
        """发送心跳包（CMD 2）"""
        if not self.is_connected or not self.sock:
            return
        
        try:
            self.sock.sendall(struct.pack('!I', 2))  # CMD 2: 心跳请求
            self.last_heartbeat_time = time.time()
        except Exception as e:
            print(f"发送心跳包失败: {e}")
            self.disconnect()
    
    def heartbeat_loop(self):
        """心跳包发送循环（每30秒发送一次）"""
        while self.is_running:
            if self.is_connected:
                # 每30秒发送一次心跳包
                if time.time() - self.last_heartbeat_time > 30:
                    self.send_heartbeat()
            time.sleep(5)  # 每5秒检查一次
    
    def receive_data_loop(self):
        """数据接收主循环"""
        print(f"开始接收数据循环...")
        
        while self.is_running:
            try:
                if not self.is_connected:
                    # 尝试重连
                    if not self.connect():
                        time.sleep(2)  # 等待2秒后重试
                        continue
                
                # 设置超时，避免阻塞
                self.sock.settimeout(1.0)
                
                # 接收数据长度（4字节，大端序）
                length_data = self.recv_all(self.sock, 4)
                if not length_data:
                    print("连接已断开，尝试重连...")
                    self.disconnect()
                    continue
                
                data_length = struct.unpack('!I', length_data)[0]
                
                # 处理心跳响应（长度为0）
                if data_length == 0:
                    continue
                
                # 接收实际数据
                json_data = self.recv_all(self.sock, data_length)
                if not json_data:
                    print("接收数据失败，连接可能已断开")
                    self.disconnect()
                    continue
                
                # 解析 JSON 数据
                try:
                    packet = json.loads(json_data.decode('utf-8'))
                    
                    # 更新统计数据
                    self.stats['total_packets'] += 1
                    self.stats['total_bytes'] += data_length
                    self.stats['last_update'] = datetime.now().isoformat()
                    
                    # 保存最新数据
                    self.latest_data = packet
                    self.data_history.append(packet)
                    
                    # 通过 WebSocket 发送给前端（避免闪烁：只发送变化的数据）
                    socketio.emit('data_update', {
                        'packet': packet,
                        'stats': self.stats
                    })
                    
                except json.JSONDecodeError as e:
                    print(f"JSON 解析错误: {e}")
                    self.stats['error_count'] += 1
                except Exception as e:
                    print(f"数据处理错误: {e}")
                    self.stats['error_count'] += 1
                    traceback.print_exc()
                    
            except socket.timeout:
                # 超时，继续循环（心跳包由独立线程发送）
                continue
            except Exception as e:
                print(f"接收循环错误: {e}")
                self.stats['error_count'] += 1
                self.disconnect()
                time.sleep(1)
    
    def start(self):
        """启动数据接收"""
        if self.is_running:
            return
        
        self.is_running = True
        self.last_heartbeat_time = time.time()
        
        # 启动数据接收线程
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        # 启动心跳包线程
        self.heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        
        print(f"数据接收线程已启动")
    
    def stop(self):
        """停止数据接收"""
        self.is_running = False
        self.disconnect()
        if self.receive_thread:
            self.receive_thread.join(timeout=2.0)
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=1.0)
        print("数据接收已停止")

# 全局数据接收器实例
data_receiver: Optional[XiaogeDataReceiver] = None

@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    """客户端连接事件"""
    print(f"客户端已连接: {request.sid}")
    # 发送当前最新数据（如果有）
    if data_receiver and data_receiver.latest_data:
        emit('data_update', {
            'packet': data_receiver.latest_data,
            'stats': data_receiver.stats
        })

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开事件"""
    print(f"客户端已断开: {request.sid}")

@socketio.on('connect_server')
def handle_connect_server(data):
    """处理连接服务器请求"""
    global data_receiver
    
    target_ip = data.get('target_ip', '').strip()
    if not target_ip:
        emit('connection_status', {
            'status': 'error',
            'message': '请输入目标 IP 地址'
        })
        return
    
    # 如果已有连接，先断开
    if data_receiver:
        data_receiver.stop()
    
    # 创建新的接收器
    data_receiver = XiaogeDataReceiver(target_ip)
    
    # 启动接收
    data_receiver.start()
    
    emit('connection_status', {
        'status': 'connecting',
        'message': f'正在连接到 {target_ip}:7711...'
    })
    
    # 等待连接结果
    time.sleep(0.5)
    if data_receiver.is_connected:
        emit('connection_status', {
            'status': 'connected',
            'message': f'已连接到 {target_ip}:7711'
        })
    else:
        emit('connection_status', {
            'status': 'error',
            'message': f'连接失败，请检查 IP 地址和网络'
        })

@socketio.on('disconnect_server')
def handle_disconnect_server():
    """处理断开服务器请求"""
    global data_receiver
    
    if data_receiver:
        data_receiver.stop()
        data_receiver = None
    
    emit('connection_status', {
        'status': 'disconnected',
        'message': '已断开连接'
    })

@socketio.on('get_latest_data')
def handle_get_latest_data():
    """获取最新数据"""
    if data_receiver and data_receiver.latest_data:
        emit('data_update', {
            'packet': data_receiver.latest_data,
            'stats': data_receiver.stats
        })
    else:
        emit('data_update', {
            'packet': None,
            'stats': data_receiver.stats if data_receiver else {}
        })

def format_value(value, field_name: str = '') -> str:
    """格式化显示值"""
    if value is None:
        return 'N/A'
    
    if isinstance(value, float):
        # 根据字段名决定小数位数
        if 'speed' in field_name.lower() or 'v' in field_name.lower():
            return f"{value:.2f}"
        elif 'angle' in field_name.lower() or 'deg' in field_name.lower():
            return f"{value:.1f}°"
        elif 'dist' in field_name.lower() or 'dRel' in field_name.lower():
            return f"{value:.1f}m"
        else:
            return f"{value:.3f}"
    
    if isinstance(value, bool):
        return "✅" if value else "❌"
    
    return str(value)

if __name__ == '__main__':
    print("=" * 60)
    print("Xiaoge 数据接收和 Web 显示工具")
    print("=" * 60)
    print("启动 Web 服务器...")
    print("请在浏览器中打开: http://localhost:5000")
    print("=" * 60)
    
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        print("\n正在关闭...")
        if data_receiver:
            data_receiver.stop()
        print("已关闭")


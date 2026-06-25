#!/usr/bin/env python3
"""
小鸽数据广播模块
从系统获取实时数据，通过TCP连接传输到7711端口
"""

import json
import socket
import struct
import threading
import time
import traceback
from typing import Dict, Any

import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper


class XiaogeDataBroadcaster:

    def get_ip_address(self):
        """获取本机局域网IP地址"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def __init__(self):
        self.tcp_port = 7711
        self.sequence = 0
        self.device_ip = self.get_ip_address()

        # TCP 客户端连接管理
        self.clients = {}
        self.clients_lock = threading.Lock()
        self.server_socket = None
        self.server_running = False

        # 只订阅 modelV2
        self.sm = messaging.SubMaster(['modelV2'])

    def recvall(self, sock, n):
        """接收指定字节数的数据"""
        data = bytearray()
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        return data

    def send_packet_to_client(self, conn, packet):
        """向单个客户端发送数据包"""
        try:
            size = len(packet)
            conn.sendall(struct.pack('!I', size))
            conn.sendall(packet)
            return True
        except (socket.error, OSError):
            return False

    def handle_client(self, conn, addr):
        """处理单个客户端连接"""
        print(f"Client connected from {addr}")

        with self.clients_lock:
            self.clients[addr] = conn

        try:
            while self.server_running:
                cmd_data = self.recvall(conn, 4)
                if not cmd_data:
                    break

                cmd = struct.unpack('!I', cmd_data)[0]

                if cmd == 2:  # 心跳请求
                    try:
                        conn.sendall(struct.pack('!I', 0))
                    except (socket.error, OSError):
                        break
        except Exception as e:
            print(f"Error handling client {addr}: {e}")
        finally:
            with self.clients_lock:
                self.clients.pop(addr, None)
            try:
                conn.close()
            except:
                pass
            print(f"Client {addr} disconnected")

    def start_tcp_server(self):
        """启动 TCP 服务器"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('0.0.0.0', self.tcp_port))
            self.server_socket.listen(5)

            self.server_running = True
            print(f"TCP server started, listening on port {self.tcp_port}")

            while self.server_running:
                try:
                    conn, addr = self.server_socket.accept()
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(conn, addr),
                        daemon=True
                    )
                    client_thread.start()
                except socket.error as e:
                    if self.server_running:
                        print(f"Error accepting connection: {e}")
                    break
        except Exception as e:
            print(f"TCP server error: {e}")
            traceback.print_exc()
        finally:
            self.server_running = False
            if self.server_socket:
                try:
                    self.server_socket.close()
                except:
                    pass
            print("TCP server stopped")

    def broadcast_to_clients(self, packet):
        """向所有连接的客户端广播数据包"""
        if not packet:
            return

        with self.clients_lock:
            clients_copy = dict(self.clients)

        dead_clients = []

        for addr, conn in clients_copy.items():
            if not self.send_packet_to_client(conn, packet):
                dead_clients.append(addr)

        if dead_clients:
            with self.clients_lock:
                for addr in dead_clients:
                    self.clients.pop(addr, None)
                    try:
                        if addr in clients_copy:
                            clients_copy[addr].close()
                    except:
                        pass

    def shutdown(self):
        """优雅关闭服务器"""
        print("Shutting down TCP server...")

        self.server_running = False

        with self.clients_lock:
            for addr, conn in self.clients.items():
                try:
                    conn.close()
                except:
                    pass
            self.clients.clear()

        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        print("TCP server shutdown complete")

    def collect_model_data(self, modelV2) -> Dict[str, Any]:
        """收集模型数据 - 只保留所需字段"""
        data = {}

        meta = modelV2.meta

        # 车道和道路边缘数据
        data['distanceToRoadEdgeLeft'] = float(meta.distanceToRoadEdgeLeft)
        data['distanceToRoadEdgeRight'] = float(meta.distanceToRoadEdgeRight)
        data['laneWidthLeft'] = float(meta.laneWidthLeft)
        data['laneWidthRight'] = float(meta.laneWidthRight)

        # 变道状态
        data['laneChangeState'] = meta.laneChangeState.raw
        data['laneChangeDirection'] = meta.laneChangeDirection.raw
        data['laneChangeAvailableLeft'] = bool(meta.laneChangeAvailableLeft)
        data['laneChangeAvailableRight'] = bool(meta.laneChangeAvailableRight)

        # 曲率信息 - 最大方向变化率
        if hasattr(modelV2, 'orientationRate') and len(modelV2.orientationRate.z) > 0:
            orientation_rate_z = [float(x) for x in modelV2.orientationRate.z]
            data['maxOrientationRate'] = max(orientation_rate_z, key=abs)
        else:
            data['maxOrientationRate'] = 0.0

        return data

    def create_packet(self, data: Dict[str, Any]) -> bytes:
        """创建数据包"""
        packet_data = {
            'version': 1,
            'sequence': self.sequence,
            'timestamp': time.time(),
            'ip': self.device_ip,
            'data': data
        }

        json_str = json.dumps(packet_data)
        return json_str.encode('utf-8')

    def broadcast_data(self):
        """主循环：收集数据并通过 TCP 推送给所有连接的客户端"""
        rk = Ratekeeper(20, print_delay_threshold=None)

        server_thread = threading.Thread(
            target=self.start_tcp_server,
            daemon=True
        )
        server_thread.start()

        time.sleep(0.5)

        print(f"XiaogeDataBroadcaster started, TCP server listening on port {self.tcp_port}")

        try:
            while True:
                try:
                    self.sm.update(0)

                    data = {}

                    if self.sm.alive['modelV2']:
                        data['modelV2'] = self.collect_model_data(self.sm['modelV2'])

                    if data:
                        packet = self.create_packet(data)

                        try:
                            self.broadcast_to_clients(packet)
                            self.sequence += 1

                            if self.sequence % 100 == 0:
                                with self.clients_lock:
                                    client_count = len(self.clients)
                                print(f"Sent {self.sequence} packets to {client_count} clients, last size: {len(packet)} bytes")
                        except Exception as e:
                            print(f"Failed to send packet to clients: {e}")

                    rk.keep_time()

                except KeyboardInterrupt:
                    print("\nReceived shutdown signal, closing gracefully...")
                    break
                except Exception as e:
                    print(f"XiaogeDataBroadcaster error: {e}")
                    traceback.print_exc()
                    time.sleep(1)
        finally:
            self.shutdown()


def main():
    broadcaster = XiaogeDataBroadcaster()
    broadcaster.broadcast_data()


if __name__ == "__main__":
    main()

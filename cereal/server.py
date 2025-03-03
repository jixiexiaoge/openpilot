import asyncio
import websockets
import cereal.messaging as messaging
import json
import time
from datetime import datetime
import logging
import sys
from typing import Set
from websockets.legacy.server import WebSocketServerProtocol

class OpenpilotDataServer:
    def __init__(self):
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('openpilot_server.log')
            ]
        )
        # 设置 websockets 库的日志级别为 WARNING，减少连接相关的日志
        logging.getLogger('websockets').setLevel(logging.WARNING)

        self.logger = logging.getLogger(__name__)

        # 如果是调试模式，设置更详细的日志
        if '--debug' in sys.argv:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

        # 连接的客户端列表
        self.clients: Set[WebSocketServerProtocol] = set()

        # 运行状态标志
        self.running = True

        # 初始化订阅的服务列表
        self.services = [
            'carState',           # 车辆状态
            'deviceState',        # 设备状态
            'gpsLocationExternal',# GPS位置
            'accelerometer',      # 加速度计数据
            'gyroscope',         # 陀螺仪数据
            'controlsState',      # 控制状态
            'lateralPlan',        # 横向规划
            'longitudinalPlan',   # 纵向规划
            'driverMonitoringState', # 驾驶员监控
            'carControl',         # 车辆控制
            'roadCameraState',    # 道路摄像头
            'modelV2',            # 模型数据
            'pandaStates',        # panda状态
            'peripheralState',    # 外设状态
            'radarState',         # 雷达状态
            'carParams',          # 车辆参数
        ]

        try:
            # 初始化订阅者
            self.logger.info("正在初始化订阅者...")
            self.sm = messaging.SubMaster(self.services)
            self.logger.info("订阅者初始化成功")
        except Exception as e:
            self.logger.error(f"订阅者初始化失败: {str(e)}")
            raise

    def format_data(self):
        """格式化数据为易读的格式"""
        try:
            self.sm.update()

            # 首先验证数据可用性
            data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'),
                'car': {
                    'speed': None,
                    'steeringAngle': None,
                    'cruiseState': {
                        'enabled': None,
                        'speed': None,
                    },
                    'brake': None,
                    'gas': None,
                },
                'device': {
                    'battery': {
                        'percent': None,
                        'charging': None,
                    },
                    'temperature': None,
                    'memory': None,
                },
                'sensors': {
                    'accelerometer': {
                        'x': None,
                        'y': None,
                        'z': None,
                    },
                    'gyroscope': {
                        'x': None,
                        'y': None,
                        'z': None,
                    }
                },
                'gps': {
                    'latitude': None,
                    'longitude': None,
                    'altitude': None,
                    'speed': None,
                    'bearing': None,
                },
                'controls': {
                    'enabled': None,
                    'active': None,
                    'alertText1': None,
                    'alertText2': None,
                },
                'driverMonitoring': {
                    'faceDetected': None,
                    'isDistracted': None,
                }
            }

            # 逐个检查和更新数据
            if self.sm.updated.get('carState'):
                try:
                    data['car'].update({
                        'speed': round(self.sm['carState'].vEgo * 3.6, 2),
                        'steeringAngle': round(self.sm['carState'].steeringAngleDeg, 2),
                        'cruiseState': {
                            'enabled': self.sm['carState'].cruiseState.enabled,
                            'speed': round(self.sm['carState'].cruiseState.speed * 3.6, 2) if self.sm['carState'].cruiseState.speed else None,
                        },
                        'brake': self.sm['carState'].brake,
                        'gas': self.sm['carState'].gas,
                    })
                except Exception as e:
                    self.logger.error(f"处理车辆状态数据时出错: {str(e)}")

            if self.sm.updated.get('deviceState'):
                try:
                    device_state = self.sm['deviceState']
                    device_data = {
                        'battery': {
                            'percent': None,
                            'charging': None,
                        },
                        'temperature': None,
                        'memory': None,
                    }

                    # 检查每个字段是否存在
                    try:
                        device_data['battery']['percent'] = device_state.batteryPercent
                    except Exception:
                        self.logger.debug("设备状态中没有 batteryPercent 字段")

                    try:
                        device_data['battery']['charging'] = device_state.charging
                    except Exception:
                        self.logger.debug("设备状态中没有 charging 字段")

                    try:
                        device_data['temperature'] = device_state.cpuTempC
                    except Exception:
                        # 尝试其他可能的温度字段
                        try:
                            device_data['temperature'] = device_state.cpuTemp
                        except Exception:
                            self.logger.debug("设备状态中没有温度相关字段")

                    try:
                        device_data['memory'] = device_state.memoryUsagePercent
                    except Exception:
                        try:
                            device_data['memory'] = device_state.memoryUsage * 100 if hasattr(device_state, 'memoryUsage') else None
                        except Exception:
                            self.logger.debug("设备状态中没有内存使用相关字段")

                    # 更新数据
                    data['device'].update(device_data)

                except Exception as e:
                    self.logger.error(f"处理设备状态数据时出错: {str(e)}")
                    # 不影响其他数据的继续处理

            if self.sm.updated.get('accelerometer'):
                try:
                    sensor_data = self.sm['accelerometer'].sensor
                    data['sensors']['accelerometer'].update({
                        'x': round(sensor_data[0], 3),
                        'y': round(sensor_data[1], 3),
                        'z': round(sensor_data[2], 3),
                    })
                except Exception as e:
                    self.logger.error(f"处理加速度计数据时出错: {str(e)}")

            if self.sm.updated.get('gyroscope'):
                try:
                    sensor_data = self.sm['gyroscope'].sensor
                    data['sensors']['gyroscope'].update({
                        'x': round(sensor_data[0], 3),
                        'y': round(sensor_data[1], 3),
                        'z': round(sensor_data[2], 3),
                    })
                except Exception as e:
                    self.logger.error(f"处理陀螺仪数据时出错: {str(e)}")

            if self.sm.updated.get('gpsLocationExternal'):
                try:
                    data['gps'].update({
                        'latitude': self.sm['gpsLocationExternal'].latitude,
                        'longitude': self.sm['gpsLocationExternal'].longitude,
                        'altitude': self.sm['gpsLocationExternal'].altitude,
                        'speed': round(self.sm['gpsLocationExternal'].speed * 3.6, 2),
                        'bearing': self.sm['gpsLocationExternal'].bearing,
                    })
                except Exception as e:
                    self.logger.error(f"处理GPS数据时出错: {str(e)}")

            if self.sm.updated.get('controlsState'):
                try:
                    data['controls'].update({
                        'enabled': self.sm['controlsState'].enabled,
                        'active': self.sm['controlsState'].active,
                        'alertText1': self.sm['controlsState'].alertText1,
                        'alertText2': self.sm['controlsState'].alertText2,
                    })
                except Exception as e:
                    self.logger.error(f"处理控制状态数据时出错: {str(e)}")

            if self.sm.updated.get('driverMonitoringState'):
                try:
                    data['driverMonitoring'].update({
                        'faceDetected': self.sm['driverMonitoringState'].faceDetected,
                        'isDistracted': self.sm['driverMonitoringState'].isDistracted,
                    })
                except Exception as e:
                    self.logger.error(f"处理驾驶监控数据时出错: {str(e)}")

            return data

        except Exception as e:
            self.logger.error(f"格式化数据时发生错误: {str(e)}")
            # 返回最小数据集
            return {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'),
                'error': str(e)
            }

    async def register(self, websocket: WebSocketServerProtocol):
        """注册新的客户端连接"""
        self.clients.add(websocket)
        self.logger.info(f"新客户端连接。当前连接数: {len(self.clients)}")

    async def unregister(self, websocket: WebSocketServerProtocol):
        """注销客户端连接"""
        try:
            if websocket in self.clients:
                self.clients.remove(websocket)
                self.logger.info(f"客户端断开连接。当前连接数: {len(self.clients)}")
        except Exception as e:
            self.logger.error(f"注销客户端时出错: {str(e)}")

    def stop(self):
        """停止服务器"""
        self.running = False

    async def send_data(self, websocket: WebSocketServerProtocol):
        """向客户端发送数据"""
        try:
            while self.running:
                try:
                    # 检查连接状态
                    if not websocket.open:
                        self.logger.info("WebSocket 连接已关闭")
                        break

                    data = self.format_data()
                    # 检查是否有任何有效数据
                    has_valid_data = False
                    for key, value in data.items():
                        if key != 'timestamp' and isinstance(value, dict) and any(v is not None for v in value.values()):
                            has_valid_data = True
                            break

                    if not has_valid_data:
                        self.logger.debug("没有有效数据可发送")
                        await asyncio.sleep(1)  # 等待更长时间
                        continue

                    try:
                        await websocket.send(json.dumps(data))
                        await asyncio.sleep(0.1)  # 100ms 更新频率
                    except websockets.exceptions.ConnectionClosed:
                        self.logger.info("客户端断开连接")
                        break

                except asyncio.CancelledError:
                    self.logger.info("数据发送任务被取消")
                    break
                except Exception as e:
                    self.logger.error(f"发送数据时出错: {str(e)}")
                    await asyncio.sleep(1)

        except Exception as e:
            self.logger.error(f"发送数据循环中发生错误: {str(e)}")
        finally:
            await self.unregister(websocket)

    async def handler(self, websocket: WebSocketServerProtocol):
        """处理websocket连接"""
        self.logger.info(f"新的连接请求: {websocket.remote_address}")
        await self.register(websocket)
        try:
            await self.send_data(websocket)
        except asyncio.CancelledError:
            self.logger.info("处理连接的任务被取消")
        except Exception as e:
            self.logger.error(f"处理连接时发生错误: {str(e)}")
        finally:
            await self.unregister(websocket)

async def main():
    server = OpenpilotDataServer()
    try:
        async with websockets.serve(
            server.handler,
            "0.0.0.0",
            8080,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=5
        ) as websocket_server:
            server.logger.info("服务器启动在 ws://0.0.0.0:8080")

            # 等待服务器运行
            try:
                await asyncio.Future()  # 运行永久
            except asyncio.CancelledError:
                server.logger.info("服务器正在关闭...")
                server.stop()
                # 关闭所有连接
                for client in server.clients.copy():
                    await client.close()

    except Exception as e:
        server.logger.error(f"服务器启动失败: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务器已停止")
    except Exception as e:
        print(f"发生错误: {str(e)}")

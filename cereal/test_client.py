#!/usr/bin/env python3
import asyncio
import websockets
import json
import logging
import sys
from datetime import datetime
from typing import Optional, Dict, Any
import signal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('openpilot_client.log')
    ]
)
logger = logging.getLogger(__name__)

# 如果是调试模式，设置更详细的日志
if '--debug' in sys.argv:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)

def format_value(value: Any, unit: str = "") -> str:
    """格式化数值显示"""
    if value is None:
        return "未知"
    return f"{value}{unit}"

class OpenpilotClient:
    def __init__(self, uri: str):
        self.uri = uri
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.running = True
        # 设置信号处理
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

    def handle_signal(self, signum, frame):
        """处理信号"""
        logger.info(f"收到信号 {signum}，准备关闭客户端...")
        self.running = False

    def print_data(self, data: Dict[str, Any]):
        """格式化打印数据"""
        try:
            print("\n=== 实时数据 ===")
            print(f"时间: {data.get('timestamp', '未知')}")

            # 检查是否有错误
            if 'error' in data:
                print(f"错误: {data['error']}")
                return

            # 车辆数据
            car = data.get('car', {})
            print("\n--- 车辆信息 ---")
            print(f"速度: {format_value(car.get('speed'), ' km/h')}")
            print(f"方向盘角度: {format_value(car.get('steeringAngle'), '°')}")
            print(f"刹车: {format_value(car.get('brake'), '%')}")
            print(f"油门: {format_value(car.get('gas'), '%')}")

            cruise = car.get('cruiseState', {})
            print(f"巡航状态: {'开启' if cruise.get('enabled') else '关闭'}")
            print(f"巡航速度: {format_value(cruise.get('speed'), ' km/h')}")

            # 设备状态
            device = data.get('device', {})
            print("\n--- 设备状态 ---")
            battery = device.get('battery', {})
            print(f"电池电量: {format_value(battery.get('percent'), '%')}")
            print(f"充电状态: {'充电中' if battery.get('charging') else '未充电'}")
            print(f"CPU温度: {format_value(device.get('temperature'), '°C')}")
            print(f"内存使用: {format_value(device.get('memory'), '%')}")

            # 传感器数据
            sensors = data.get('sensors', {})
            print("\n--- 传感器数据 ---")
            acc = sensors.get('accelerometer', {})
            if any(v is not None for v in acc.values()):
                print(f"加速度: X={format_value(acc.get('x'))} Y={format_value(acc.get('y'))} Z={format_value(acc.get('z'))}")

            gyro = sensors.get('gyroscope', {})
            if any(v is not None for v in gyro.values()):
                print(f"陀螺仪: X={format_value(gyro.get('x'))} Y={format_value(gyro.get('y'))} Z={format_value(gyro.get('z'))}")

            # GPS数据
            gps = data.get('gps', {})
            print("\n--- GPS信息 ---")
            print(f"纬度: {format_value(gps.get('latitude'), '°')}")
            print(f"经度: {format_value(gps.get('longitude'), '°')}")
            print(f"海拔: {format_value(gps.get('altitude'), ' m')}")
            print(f"速度: {format_value(gps.get('speed'), ' km/h')}")
            print(f"方向: {format_value(gps.get('bearing'), '°')}")

            # 控制状态
            controls = data.get('controls', {})
            print("\n--- 控制状态 ---")
            print(f"系统状态: {'启用' if controls.get('enabled') else '禁用'}")
            print(f"控制状态: {'激活' if controls.get('active') else '未激活'}")
            if controls.get('alertText1'):
                print(f"警告1: {controls['alertText1']}")
            if controls.get('alertText2'):
                print(f"警告2: {controls['alertText2']}")

            # 驾驶监控
            monitoring = data.get('driverMonitoring', {})
            print("\n--- 驾驶监控 ---")
            print(f"面部检测: {'已检测' if monitoring.get('faceDetected') else '未检测'}")
            print(f"注意力状态: {'分心' if monitoring.get('isDistracted') else '专注'}")

            print("\n" + "="*30 + "\n")

        except Exception as e:
            logger.error(f"打印数据时出错: {e}")

    async def connect(self):
        """连接到服务器"""
        retry_count = 0
        max_retries = 5
        retry_delay = 2

        while retry_count < max_retries and self.running:
            try:
                logger.info(f"尝试连接到 {self.uri}")
                async with websockets.connect(
                    self.uri,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5
                ) as websocket:
                    self.websocket = websocket
                    logger.info("连接成功")
                    retry_count = 0  # 重置重试计数

                    while self.running:
                        try:
                            data = await websocket.recv()
                            parsed_data = json.loads(data)
                            self.print_data(parsed_data)
                        except websockets.exceptions.ConnectionClosed as e:
                            logger.error(f"连接已关闭: {e}")
                            break
                        except json.JSONDecodeError as e:
                            logger.error(f"JSON解析错误: {e}")
                        except Exception as e:
                            logger.error(f"接收数据时出错: {e}")
                            break

            except websockets.exceptions.InvalidStatusCode as e:
                logger.error(f"无效的状态码: {e}")
                retry_count += 1
                if self.running:
                    await asyncio.sleep(retry_delay)
            except websockets.exceptions.InvalidURI as e:
                logger.error(f"无效的URI: {e}")
                return  # 直接退出，不需要重试
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"连接关闭: {e}")
                retry_count += 1
                if self.running:
                    await asyncio.sleep(retry_delay)
            except Exception as e:
                logger.error(f"连接错误: {e}")
                retry_count += 1
                if self.running:
                    await asyncio.sleep(retry_delay)

        if retry_count >= max_retries:
            logger.error(f"达到最大重试次数 ({max_retries})，程序退出")

    async def close(self):
        """关闭客户端"""
        self.running = False
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()

async def main():
    client = OpenpilotClient("ws://172.18.20.20:8080")
    try:
        await client.connect()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已停止")
    except Exception as e:
        print(f"发生错误: {e}")
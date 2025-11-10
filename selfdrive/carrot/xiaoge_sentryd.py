#!/usr/bin/env python3
"""
Xiaoge哨兵模式 - 主程序
基于加速度计监测震动，触发拍照并记录到数据库
"""
import numpy as np
import cereal.messaging as messaging
from datetime import datetime
import time
import os
import requests
import sqlite3
import threading
import base64
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from typing import Optional, Tuple
from openpilot.common.params import Params
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths
from PIL import Image

# ============ 配置常量 ============
# 使用openpilot的路径系统，兼容PC和设备
if PC:
    # PC环境：使用comma_home下的目录
    MEDIA_DIR = os.path.join(Paths.comma_home(), "media", "sentry")
else:
    # 设备环境：使用/data/media/sentry
    MEDIA_DIR = "/data/media/sentry"

DB_PATH = os.path.join(MEDIA_DIR, "sentry.db")

# 确保目录存在，设置正确的权限
try:
    os.makedirs(MEDIA_DIR, mode=0o755, exist_ok=True)
except OSError as e:
    print(f"Warning: Failed to create media directory {MEDIA_DIR}: {e}")
    # 如果创建失败，尝试使用备用路径
    if not PC:
        MEDIA_DIR = "/tmp/sentry"
        DB_PATH = os.path.join(MEDIA_DIR, "sentry.db")
        os.makedirs(MEDIA_DIR, mode=0o755, exist_ok=True)

# ============ 数据库管理类 ============
class SentryDB:
    """SQLite数据库管理，处理配置和事件日志"""

    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.lock = threading.Lock()
        self.init_tables()

    def init_tables(self):
        """初始化数据库表结构"""
        with self.lock:
            cursor = self.conn.cursor()

            # 配置表 - 包含推送和邮件相关字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    id INTEGER PRIMARY KEY,
                    sensitivity_threshold REAL DEFAULT 0.08,
                    webhook_url TEXT,
                    webserver_url TEXT,
                    web_password TEXT DEFAULT '8899',
                    push_url TEXT,
                    notification_type TEXT DEFAULT 'api',
                    email_from TEXT,
                    email_to TEXT,
                    email_password TEXT,
                    smtp_server TEXT,
                    smtp_port INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 检查并添加缺失的字段（数据库迁移）
            cursor.execute("PRAGMA table_info(config)")
            columns = [column[1] for column in cursor.fetchall()]
            column_names = set(columns)

            # 添加缺失的字段
            if 'push_url' not in column_names:
                cursor.execute('ALTER TABLE config ADD COLUMN push_url TEXT')
            if 'notification_type' not in column_names:
                cursor.execute('ALTER TABLE config ADD COLUMN notification_type TEXT DEFAULT "api"')
            if 'email_from' not in column_names:
                cursor.execute('ALTER TABLE config ADD COLUMN email_from TEXT')
            if 'email_to' not in column_names:
                cursor.execute('ALTER TABLE config ADD COLUMN email_to TEXT')
            if 'email_password' not in column_names:
                cursor.execute('ALTER TABLE config ADD COLUMN email_password TEXT')
            if 'smtp_server' not in column_names:
                cursor.execute('ALTER TABLE config ADD COLUMN smtp_server TEXT')
            if 'smtp_port' not in column_names:
                cursor.execute('ALTER TABLE config ADD COLUMN smtp_port INTEGER')

            # 事件日志表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT,
                    delta_accel REAL,
                    image_path TEXT,
                    video_path TEXT,
                    front_image_path TEXT,
                    back_image_path TEXT,
                    webhook_sent BOOLEAN DEFAULT 0,
                    notes TEXT
                )
            ''')

            # 插入默认配置
            cursor.execute('SELECT COUNT(*) FROM config')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO config (sensitivity_threshold, web_password)
                    VALUES (0.08, '8899')
                ''')

            self.conn.commit()

    def get_config(self) -> dict:
        """获取配置参数"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM config WHERE id = 1')
            row = cursor.fetchone()
            if row:
                # 兼容旧版本数据库，安全获取字段值
                config = {
                    'sensitivity_threshold': row[1] if len(row) > 1 else 0.08,
                    'webhook_url': row[2] if len(row) > 2 else None,
                    'webserver_url': row[3] if len(row) > 3 else None,
                    'web_password': row[4] if len(row) > 4 else '8899',
                    'push_url': row[5] if len(row) > 5 else None,
                    'notification_type': row[6] if len(row) > 6 else 'api',
                    'email_from': row[7] if len(row) > 7 else None,
                    'email_to': row[8] if len(row) > 8 else None,
                    'email_password': row[9] if len(row) > 9 else None,
                    'smtp_server': row[10] if len(row) > 10 else None,
                    'smtp_port': row[11] if len(row) > 11 else None
                }
                return config
            return {
                'sensitivity_threshold': 0.08,
                'web_password': '8899',
                'push_url': None,
                'notification_type': 'api',
                'email_from': None,
                'email_to': None,
                'email_password': None,
                'smtp_server': None,
                'smtp_port': None
            }

    def update_config(self, **kwargs):
        """更新配置参数"""
        with self.lock:
            cursor = self.conn.cursor()
            fields = []
            values = []
            for key, value in kwargs.items():
                fields.append(f"{key} = ?")
                values.append(value)

            if fields:
                query = f"UPDATE config SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
                cursor.execute(query, values)
                self.conn.commit()

    def log_event(self, event_type: str, delta_accel: float,
                  image_path: Optional[str] = None,
                  video_path: Optional[str] = None,
                  front_image_path: Optional[str] = None,
                  back_image_path: Optional[str] = None,
                  webhook_sent: bool = False,
                  notes: Optional[str] = None) -> int:
        """记录哨兵事件"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO events (event_type, delta_accel, image_path, video_path,
                                  front_image_path, back_image_path, webhook_sent, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (event_type, delta_accel, image_path, video_path,
                  front_image_path, back_image_path, webhook_sent, notes))
            self.conn.commit()
            return cursor.lastrowid

    def get_events(self, limit: int = 50) -> list:
        """获取事件列表"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM events ORDER BY timestamp DESC LIMIT ?
            ''', (limit,))

            events = []
            for row in cursor.fetchall():
                events.append({
                    'id': row[0],
                    'timestamp': row[1],
                    'event_type': row[2],
                    'delta_accel': row[3],
                    'image_path': row[4],
                    'video_path': row[5],
                    'front_image_path': row[6],
                    'back_image_path': row[7],
                    'webhook_sent': row[8],
                    'notes': row[9]
                })
            return events

    def delete_event(self, event_id: int):
        """删除事件记录"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
            self.conn.commit()


# ============ 哨兵模式核心类 ============
class SentryMode:
    """哨兵模式主程序，监测加速度并触发拍照"""

    def __init__(self, db: SentryDB):
        self.sm = messaging.SubMaster(['accelerometer'])
        self.params = Params()
        self.db = db

        self.curr_accel = 0
        self.prev_accel = None
        self.sentry_status = False
        self.secDelay = 0
        self.transition_to_offroad_last = time.monotonic()
        self.offroad_delay = 90
        self.last_timestamp = 0
        self.last_config_reload = time.monotonic()
        self.config_reload_interval = 30  # 每30秒重新加载一次配置

        # 检查OpenCV是否可用（录像功能依赖）
        try:
            import cv2
            self.video_recording_available = True
        except ImportError:
            self.video_recording_available = False
            print("Warning: OpenCV not installed, video recording disabled. Install with: pip3 install opencv-python")

        # 从数据库加载配置
        self.reload_config()
        print("Xiaoge SentryMode initialized")

    def reload_config(self):
        """从数据库重新加载配置"""
        config = self.db.get_config()
        self.sensitivity_threshold = config.get('sensitivity_threshold', 0.08)
        self.webhook_url = config.get('webhook_url')
        self.push_url = config.get('push_url')
        self.notification_type = config.get('notification_type', 'api')
        self.email_from = config.get('email_from')
        self.email_to = config.get('email_to')
        self.email_password = config.get('email_password')
        self.smtp_server = config.get('smtp_server')
        self.smtp_port = config.get('smtp_port')
        self.frontAllowed = self.params.get_bool("RecordFront")

    def takeSnapshot(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """拍摄前后摄像头照片并拼接"""
        try:
            from openpilot.system.camerad.snapshot.snapshot import snapshot, jpeg_write
            pic, fpic = snapshot()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            back_path = None
            front_path = None
            combined_path = None

            if pic is not None:
                back_path = os.path.join(MEDIA_DIR, f"back_{timestamp}.jpg")
                jpeg_write(back_path, pic)

            if fpic is not None:
                front_path = os.path.join(MEDIA_DIR, f"front_{timestamp}.jpg")
                jpeg_write(front_path, fpic)

            if pic is not None and fpic is not None:
                combined_path = os.path.join(MEDIA_DIR, f"360_{timestamp}.jpg")
                self.stitch_images(front_path, back_path, combined_path)

            return back_path, front_path, combined_path
        except Exception as e:
            print(f"Snapshot error: {e}")
            return None, None, None

    def is_camerad_running(self) -> bool:
        """检查camerad是否运行（使用VisionIpcClient连接测试）"""
        try:
            from msgq.visionipc import VisionIpcClient, VisionStreamType
            vipc_client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_WIDE_ROAD, True)
            return vipc_client.connect(False)
        except Exception:
            return False

    def record_wide_camera_video(self, duration: int = 10) -> Optional[str]:
        """录制广角摄像头视频"""
        # 检查OpenCV是否可用
        if not self.video_recording_available:
            print("Video recording disabled: OpenCV not installed")
            return None

        try:
            import cv2
            from msgq.visionipc import VisionIpcClient, VisionStreamType
            from openpilot.system.camerad.snapshot.snapshot import extract_image

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_path = os.path.join(MEDIA_DIR, f"sentry_{timestamp}.mp4")

            # 检查camerad是否运行（使用VisionIpcClient连接测试）
            camerad_running = self.is_camerad_running()

            # 连接到广角摄像头流
            vipc_client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_WIDE_ROAD, True)

            # 如果camerad未运行，启动它
            if not camerad_running:
                print("Wide camera not available, starting camerad...")
                from openpilot.system.manager.process_config import managed_processes
                managed_processes['camerad'].start()
                time.sleep(2)  # 等待camerad启动

            # 连接到摄像头流
            if not vipc_client.connect(True):
                print("Failed to connect to wide camera")
                return None

            # 获取第一帧以确定视频尺寸
            buf = vipc_client.recv()
            if buf is None:
                print("Failed to receive frame")
                return None

            frame = extract_image(buf)
            if frame is None:
                print("Failed to extract image from buffer")
                return None

            height, width = frame.shape[:2]

            # 初始化视频写入器 (使用avc1/H.264编码，更好的浏览器兼容性)
            # 尝试使用avc1，如果不支持则fallback到mp4v
            fourcc = None
            test_file = '/tmp/test_sentry_video.mp4'
            for codec in ['avc1', 'H264', 'mp4v']:
                try:
                    test_fourcc = cv2.VideoWriter_fourcc(*codec)
                    test_writer = cv2.VideoWriter(test_file, test_fourcc, 20, (width, height))
                    if test_writer.isOpened():
                        test_writer.release()
                        # 清理测试文件
                        if os.path.exists(test_file):
                            try:
                                os.remove(test_file)
                            except Exception:
                                pass
                        fourcc = test_fourcc
                        print(f"Using video codec: {codec}")
                        break
                except Exception:
                    continue

            if fourcc is None:
                print("Warning: Failed to find suitable video codec, using default mp4v...")
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')

            fps = 20  # 广角摄像头帧率
            out = cv2.VideoWriter(video_path, fourcc, fps, (width, height))

            if not out.isOpened():
                print(f"Failed to open video writer for {video_path}")
                return None

            print(f"Recording {duration}s video from wide camera ({width}x{height} @ {fps}fps)...")
            start_time = time.monotonic()
            frame_count = 0

            # 录制指定时长
            while (time.monotonic() - start_time) < duration:
                buf = vipc_client.recv()
                if buf is not None:
                    frame = extract_image(buf)
                    if frame is not None:
                        # OpenCV需要BGR格式
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        out.write(frame_bgr)
                        frame_count += 1
                time.sleep(0.05)  # 约20fps

            out.release()
            print(f"Video recording completed: {frame_count} frames, saved to {video_path}")

            # 如果camerad是我们启动的且不在onroad状态，停止它
            if not camerad_running and not self.params.get_bool("IsOnroad"):
                try:
                    from openpilot.system.manager.process_config import managed_processes
                    managed_processes['camerad'].stop()
                except Exception as e:
                    print(f"Error stopping camerad: {e}")

            return video_path if os.path.exists(video_path) else None

        except Exception as e:
            print(f"Video recording error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def send_discord_webhook(self, message: str, image_path: Optional[str] = None) -> bool:
        """发送Discord通知"""
        if not self.webhook_url:
            return False

        data = {"content": message}
        try:
            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as file:
                    files = {"file": file}
                    response = requests.post(self.webhook_url, data=data, files=files, timeout=10)
            else:
                headers = {"Content-Type": "application/json"}
                response = requests.post(self.webhook_url, json=data, headers=headers, timeout=10)

            return response.status_code in [200, 204]
        except Exception as e:
            print(f"Webhook error: {e}")
            return False

    def compress_image_to_base64(self, image_path: Optional[str], max_size: int = 800, quality: int = 75) -> Optional[str]:
        """压缩图片并转换为base64编码"""
        if not image_path or not os.path.exists(image_path):
            return None

        try:
            # 打开图片
            img = Image.open(image_path)

            # 计算缩放比例
            width, height = img.size
            if width > max_size or height > max_size:
                if width > height:
                    new_width = max_size
                    new_height = int(height * (max_size / width))
                else:
                    new_height = max_size
                    new_width = int(width * (max_size / height))
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # 转换为RGB模式（如果不是）
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # 压缩并转换为base64
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            return f"data:image/jpeg;base64,{image_base64}"
        except Exception as e:
            print(f"Image compression error: {e}")
            return None

    def generate_notification_html(self, delta_accel: float, image_base64: Optional[str] = None) -> str:
        """生成统一的HTML通知内容（兼容邮件和API推送）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 优化后的HTML，兼容邮件客户端和Web浏览器
        html_content = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    /* 内联样式，确保邮件客户端兼容 */
    body {{
      font-family: Arial, "Microsoft YaHei", sans-serif;
      padding: 0;
      margin: 0;
      background-color: #f5f5f5;
      -webkit-font-smoothing: antialiased;
    }}
    .container {{
      max-width: 600px;
      margin: 0 auto;
      background-color: #ffffff;
      padding: 20px;
      border-radius: 8px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }}
    .header {{
      text-align: center;
      padding-bottom: 15px;
      border-bottom: 2px solid #e5e5e5;
      margin-bottom: 20px;
    }}
    .header h2 {{
      color: #dc2626;
      margin: 0;
      font-size: 22px;
      font-weight: bold;
    }}
    .info-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 15px 0;
      font-size: 14px;
    }}
    .info-table td {{
      padding: 10px 8px;
      border-bottom: 1px solid #eeeeee;
      vertical-align: top;
    }}
    .info-table td:first-child {{
      font-weight: bold;
      color: #666666;
      width: 35%;
    }}
    .info-table td:last-child {{
      color: #333333;
    }}
    .delta-value {{
      color: #dc2626;
      font-weight: bold;
      font-size: 16px;
    }}
    .image-section {{
      margin: 20px 0;
      text-align: center;
    }}
    .image-section img {{
      max-width: 100%;
      height: auto;
      border-radius: 6px;
      border: 1px solid #e5e5e5;
      display: block;
      margin: 10px auto;
    }}
    .tip-box {{
      margin-top: 20px;
      padding: 12px 15px;
      background-color: #fff3cd;
      border-left: 4px solid #ffc107;
      border-radius: 4px;
      font-size: 13px;
      line-height: 1.6;
      color: #856404;
    }}
    .tip-box strong {{
      color: #78350f;
    }}
    @media only screen and (max-width: 600px) {{
      .container {{
        padding: 15px;
        border-radius: 0;
      }}
      .header h2 {{
        font-size: 20px;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h2>🚨 哨兵模式触发警报</h2>
    </div>

    <table class="info-table">
      <tr>
        <td>触发时间</td>
        <td>{timestamp}</td>
      </tr>
      <tr>
        <td>加速度变化</td>
        <td><span class="delta-value">{delta_accel:.4f}</span></td>
      </tr>
      <tr>
        <td>灵敏度阈值</td>
        <td>{self.sensitivity_threshold:.4f}</td>
      </tr>
      <tr>
        <td>事件类型</td>
        <td>车辆震动检测</td>
      </tr>
    </table>
"""

        # 如果有图片，添加到HTML中
        if image_base64:
            html_content += f"""
    <div class="image-section">
      <strong style="color: #333333; font-size: 14px;">现场照片：</strong>
      <img src="{image_base64}" alt="哨兵照片" />
    </div>
"""

        html_content += """
    <div class="tip-box">
      <strong>提示:</strong> 请及时查看车辆状态，如有异常请立即处理。
    </div>
  </div>
</body>
</html>
"""
        return html_content

    def send_push_notification(self, delta_accel: float, back_path: Optional[str] = None,
                               front_path: Optional[str] = None, combined_path: Optional[str] = None) -> bool:
        """发送推送通知到配置的推送API"""
        if not self.push_url:
            return False

        try:
            # 压缩图片并转换为base64
            image_base64 = None
            if combined_path:
                image_base64 = self.compress_image_to_base64(combined_path)
            elif back_path:
                image_base64 = self.compress_image_to_base64(back_path)

            # 使用统一的HTML生成方法
            html_content = self.generate_notification_html(delta_accel, image_base64)

            # 构建推送数据
            push_data = {
                "title": "🚨 哨兵模式触发警报",
                "content": html_content
            }

            # 发送推送请求
            headers = {"Content-Type": "application/json"}
            response = requests.post(self.push_url, json=push_data, headers=headers, timeout=10)

            if response.status_code in [200, 201, 204]:
                print(f"Push notification sent successfully")
                return True
            else:
                print(f"Push notification failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            print(f"Push notification error: {e}")
            return False

    def get_smtp_config(self, email: str) -> Tuple[Optional[str], Optional[int]]:
        """根据邮箱地址自动获取SMTP服务器配置"""
        email_lower = email.lower() if email else ""

        # 常见邮箱的SMTP配置
        smtp_configs = {
            'gmail.com': ('smtp.gmail.com', 587),
            'qq.com': ('smtp.qq.com', 587),
            '163.com': ('smtp.163.com', 25),
            '126.com': ('smtp.126.com', 25),
            'sina.com': ('smtp.sina.com', 25),
            'sina.cn': ('smtp.sina.cn', 25),
            'sohu.com': ('smtp.sohu.com', 25),
            'yahoo.com': ('smtp.mail.yahoo.com', 587),
            'outlook.com': ('smtp-mail.outlook.com', 587),
            'hotmail.com': ('smtp-mail.outlook.com', 587),
            'live.com': ('smtp-mail.outlook.com', 587),
            'foxmail.com': ('smtp.qq.com', 587),
            '139.com': ('smtp.139.com', 25),
        }

        # 提取邮箱域名
        if '@' in email_lower:
            domain = email_lower.split('@')[1]
            if domain in smtp_configs:
                return smtp_configs[domain]

        return None, None

    def send_email_notification(self, delta_accel: float, back_path: Optional[str] = None,
                            front_path: Optional[str] = None, combined_path: Optional[str] = None) -> bool:
        """发送邮件通知"""
        if not all([self.email_from, self.email_to, self.email_password]):
            print("Email configuration incomplete")
            return False

        try:
            # 获取SMTP配置（如果未配置则自动检测）
            smtp_server = self.smtp_server
            smtp_port = self.smtp_port

            if not smtp_server or not smtp_port:
                smtp_server, smtp_port = self.get_smtp_config(self.email_from)
                if not smtp_server or not smtp_port:
                    print(f"Unable to determine SMTP config for {self.email_from}")
                    return False

            # 压缩图片并转换为base64
            image_base64 = None
            if combined_path:
                image_base64 = self.compress_image_to_base64(combined_path)
            elif back_path:
                image_base64 = self.compress_image_to_base64(back_path)

            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['From'] = self.email_from
            msg['To'] = self.email_to
            msg['Subject'] = "🚨 哨兵模式触发警报"

            # 使用统一的HTML生成方法
            html_content = self.generate_notification_html(delta_accel, image_base64)

            # 添加HTML内容
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(html_part)

            # 发送邮件
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()  # 启用TLS加密
            server.login(self.email_from, self.email_password)
            server.send_message(msg)
            server.quit()

            print(f"Email notification sent successfully to {self.email_to}")
            return True

        except Exception as e:
            print(f"Email notification error: {e}")
            return False

    def stitch_images(self, front_path: str, back_path: str, output_path: str):
        """拼接前后摄像头图片"""
        try:
            front_image = Image.open(front_path)
            back_image = Image.open(back_path)
            front_width, front_height = front_image.size
            back_width, back_height = back_image.size

            if front_height != back_height:
                print("Error: Images must have the same height.")
                return

            result_image = Image.new("RGB", (front_width + back_width, front_height))
            result_image.paste(front_image, (0, 0))
            result_image.paste(back_image, (front_width, 0))
            result_image.save(output_path)
        except Exception as e:
            print(f"Stitch error: {e}")

    def update(self):
        """主循环更新函数"""
        t = time.monotonic()

        # 定期重新加载配置（允许通过Web界面更新配置）
        if t - self.last_config_reload > self.config_reload_interval:
            self.reload_config()
            self.last_config_reload = t

        if (t - self.transition_to_offroad_last) > self.offroad_delay:
            self.curr_accel = np.array(self.sm['accelerometer'].acceleration.v)

            if self.prev_accel is None:
                print("SentryD Active")
                self.prev_accel = self.curr_accel
                return

            delta = abs(np.linalg.norm(self.curr_accel) - np.linalg.norm(self.prev_accel))

            if delta > self.sensitivity_threshold:
                self.last_timestamp = t
                self.secDelay += 1

                if self.secDelay % 150 == 0:
                    self.sentry_status = True
                    print(f"Triggered! Delta: {delta:.4f}")
                    self.secDelay = 0

                    # 第一步: 拍摄初始照片
                    back_path, front_path, combined_path = None, None, None
                    if self.frontAllowed:
                        print("Taking initial snapshot...")
                        back_path, front_path, combined_path = self.takeSnapshot()

                    # 第二步: 录制10秒视频
                    print("Starting 10s video recording...")
                    video_path = None
                    video_recording_failed = False
                    if self.video_recording_available:
                        try:
                            video_path = self.record_wide_camera_video(duration=10)
                            if video_path is None:
                                video_recording_failed = True
                        except Exception as e:
                            print(f"Video recording failed: {e}")
                            video_recording_failed = True
                            import traceback
                            traceback.print_exc()
                    else:
                        video_recording_failed = True

                    # 第三步: 录像结束后再拍一张照片
                    print("Taking final snapshot...")
                    back_path_final, front_path_final, combined_path_final = None, None, None
                    if self.frontAllowed:
                        back_path_final, front_path_final, combined_path_final = self.takeSnapshot()

                    # 发送通知 (使用初始照片)
                    webhook_sent = False
                    notification_sent = False

                    if combined_path or back_path:
                        webhook_sent = self.send_discord_webhook(
                            'ALERT! Sentry Detected Movement!',
                            combined_path or back_path
                        )
                    else:
                        webhook_sent = self.send_discord_webhook('ALERT! Sentry Detected Movement!')

                    # 根据配置选择发送方式
                    if self.notification_type == 'mail':
                        # 发送邮件通知
                        notification_sent = self.send_email_notification(
                            delta_accel=float(delta),
                            back_path=back_path,
                            front_path=front_path,
                            combined_path=combined_path
                        )
                        if video_recording_failed:
                            notes = f"Email sent: {notification_sent}, Video: Failed"
                        elif video_path:
                            notes = f"Email sent: {notification_sent}, Video: {os.path.basename(video_path)}"
                        else:
                            notes = f"Email sent: {notification_sent}, Video: None"
                    else:
                        # 发送API推送通知（默认）
                        notification_sent = self.send_push_notification(
                            delta_accel=float(delta),
                            back_path=back_path,
                            front_path=front_path,
                            combined_path=combined_path
                        )
                        if video_recording_failed:
                            notes = f"Push sent: {notification_sent}, Video: Failed"
                        elif video_path:
                            notes = f"Push sent: {notification_sent}, Video: {os.path.basename(video_path)}"
                        else:
                            notes = f"Push sent: {notification_sent}, Video: None"

                    # 记录到数据库 (包含视频路径和最终照片)
                    self.db.log_event(
                        event_type='motion_detected',
                        delta_accel=float(delta),
                        image_path=combined_path_final or combined_path,  # 优先使用最终照片
                        video_path=video_path,
                        front_image_path=front_path_final or front_path,
                        back_image_path=back_path_final or back_path,
                        webhook_sent=webhook_sent,
                        notes=notes if notification_sent else None
                    )

            elif self.sentry_status and time.monotonic() - self.last_timestamp > 2:
                self.sentry_status = False
                print("Movement Ended")

            self.prev_accel = self.curr_accel

    def start(self):
        """启动哨兵监测循环"""
        while True:
            self.sm.update()
            self.update()
            time.sleep(0.1)


def main():
    """主程序入口"""
    try:
        db = SentryDB()
        print("Database initialized")
        sentry = SentryMode(db)
        sentry.start()
    except KeyboardInterrupt:
        print("\nSentry mode stopped")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()


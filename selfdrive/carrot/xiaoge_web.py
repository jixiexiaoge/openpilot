#!/usr/bin/env python3
"""
Xiaoge哨兵模式 - Web服务器
Flask Web服务器，提供哨兵事件查看和管理界面
"""
import os
import logging
from datetime import timedelta
from flask import Flask, render_template_string, request, jsonify, send_file, redirect, url_for, session
from functools import wraps
from openpilot.system.hardware import PC
from selfdrive.carrot.xiaoge_sentryd import SentryDB, MEDIA_DIR

# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ Flask应用初始化 ============
app = Flask(__name__)
app.secret_key = 'xiaoge_sentry_secret_key_change_this_in_production'

# 会话配置：设置会话超时时间为24小时
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_COOKIE_SECURE'] = False  # 在comma3设备上通常不使用HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # 防止XSS攻击

# CSRF保护（可选，如果安装了flask-wtf）
try:
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect(app)
    logger.info("CSRF protection enabled")
except ImportError:
    logger.warning("flask-wtf not installed, CSRF protection disabled")
    csrf = None

db = SentryDB()

# ============ HTML模板 ============
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>哨兵模式登录</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
            color: #fff;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        .login-container {
            background: rgba(42, 42, 42, 0.95);
            padding: 40px 30px;
            border-radius: 20px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(10px);
        }
        .logo {
            text-align: center;
            margin-bottom: 30px;
        }
        .logo-icon {
            font-size: 60px;
            margin-bottom: 10px;
        }
        h2 {
            text-align: center;
            margin-bottom: 30px;
            font-size: 24px;
            font-weight: 600;
        }
        .input-group {
            margin-bottom: 20px;
        }
        input[type="password"] {
            width: 100%;
            padding: 15px;
            border: 2px solid #3a3a3a;
            border-radius: 10px;
            background: #2a2a2a;
            color: #fff;
            font-size: 16px;
            transition: all 0.3s;
        }
        input[type="password"]:focus {
            outline: none;
            border-color: #007bff;
            background: #333;
        }
        button {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
            border: none;
            border-radius: 10px;
            color: #fff;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0, 123, 255, 0.3);
        }
        button:active {
            transform: translateY(0);
        }
        .error {
            background: rgba(255, 68, 68, 0.2);
            color: #ff4444;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            margin-top: 15px;
            border: 1px solid rgba(255, 68, 68, 0.3);
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <div class="logo-icon">🚨</div>
            <h2>哨兵模式</h2>
        </div>
        <form method="POST">
            <div class="input-group">
                <input type="password" name="password" placeholder="请输入密码" required autofocus>
            </div>
            <button type="submit">登录</button>
        </form>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
    </div>
</body>
</html>
"""

INDEX_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>哨兵模式</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --bg-primary: #1a1a1a;
            --bg-secondary: #2a2a2a;
            --bg-tertiary: #3a3a3a;
            --text-primary: #ffffff;
            --text-secondary: #888888;
            --accent-color: #007bff;
            --danger-color: #ff4444;
            --success-color: #28a745;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: var(--bg-primary);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            padding-bottom: 80px;
        }

        .navbar {
            background: var(--bg-secondary) !important;
            padding: 15px 0;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
            position: sticky;
            top: 0;
            z-index: 1000;
        }

        .navbar-brand {
            font-size: 20px;
            font-weight: 600;
        }

        .container {
            max-width: 800px;
            padding: 20px 15px;
        }

        .config-section {
            background: var(--bg-secondary);
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 25px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        }

        .config-section h5 {
            margin-bottom: 20px;
            font-weight: 600;
        }

        .config-input {
            width: 100%;
            padding: 12px 15px;
            margin: 10px 0;
            background: var(--bg-tertiary);
            border: 1px solid #4a4a4a;
            border-radius: 10px;
            color: var(--text-primary);
            font-size: 15px;
            transition: all 0.3s;
        }

        .config-input:focus {
            outline: none;
            border-color: var(--accent-color);
            background: #444;
        }

        .event-card {
            background: var(--bg-secondary);
            border-radius: 15px;
            margin-bottom: 20px;
            padding: 20px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            transition: transform 0.2s;
        }

        .event-card:hover {
            transform: translateY(-2px);
        }

        .event-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }

        .delta-badge {
            background: var(--danger-color);
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .webhook-badge {
            background: var(--success-color);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 13px;
            margin-left: 8px;
        }

        .timestamp {
            color: var(--text-secondary);
            font-size: 14px;
        }

        .media-container {
            margin: 15px 0;
        }

        .media-container img,
        .media-container video {
            width: 100%;
            border-radius: 12px;
            margin: 10px 0;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
        }

        .media-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin: 10px 0;
        }

        .media-label {
            color: var(--text-secondary);
            font-size: 12px;
            margin-top: 5px;
            text-align: center;
        }

        .btn-group-custom {
            display: flex;
            gap: 10px;
            margin-top: 15px;
            flex-wrap: wrap;
        }

        .btn-custom {
            flex: 1;
            min-width: 120px;
            padding: 10px 15px;
            border-radius: 10px;
            border: none;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            text-decoration: none;
        }

        .btn-primary {
            background: var(--accent-color);
            color: white;
        }

        .btn-primary:hover {
            background: #0056b3;
            transform: translateY(-2px);
            color: white;
        }

        .btn-danger {
            background: var(--danger-color);
            color: white;
        }

        .btn-danger:hover {
            background: #cc0000;
            transform: translateY(-2px);
            color: white;
        }

        .btn-info {
            background: #17a2b8;
            color: white;
        }

        .btn-info:hover {
            background: #138496;
            transform: translateY(-2px);
            color: white;
        }

        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-secondary);
        }

        .empty-state i {
            font-size: 60px;
            margin-bottom: 20px;
            opacity: 0.5;
        }

        @media (max-width: 576px) {
            .btn-group-custom {
                flex-direction: column;
            }

            .btn-custom {
                width: 100%;
            }

            .event-header {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark">
        <div class="container-fluid">
            <span class="navbar-brand">
                <i class="fas fa-shield-alt me-2"></i>哨兵模式
            </span>
            <div>
                <button class="btn btn-sm btn-outline-light me-2" onclick="toggleConfig()">
                    <i class="fas fa-cog"></i> 设置
                </button>
                <a href="/logout" class="btn btn-sm btn-outline-danger">
                    <i class="fas fa-sign-out-alt"></i> 退出
                </a>
            </div>
        </div>
    </nav>

    <div class="container">
        <!-- 配置区域 -->
        <div id="configSection" class="config-section" style="display: none;">
            <h5><i class="fas fa-cog me-2"></i>配置参数</h5>
            <input type="number" id="sensitivity" class="config-input"
                   placeholder="灵敏度阈值 (默认: 0.08)" step="0.01" min="0.01" max="1.0">
            <input type="text" id="webserver" class="config-input"
                   placeholder="Web服务器URL (可选)">

            <!-- 邮件配置（必须） -->
            <h5 style="color: var(--text-primary); margin-top: 25px; margin-bottom: 15px; font-weight: 600;">
                <i class="fas fa-envelope me-2"></i>邮件通知配置 <span style="color: var(--danger-color);">*必填</span>
            </h5>
            <input type="email" id="email_from" class="config-input" required
                   placeholder="发件邮箱 * (推荐: QQ邮箱，例如: yourname@qq.com)">
            <input type="email" id="email_to" class="config-input" required
                   placeholder="收件邮箱 * (推荐: QQ邮箱，例如: yourname@qq.com)">
            <input type="password" id="email_password" class="config-input" required
                   placeholder="邮箱授权码 * (不是登录密码，QQ邮箱在设置->账户->开启SMTP服务后获取)">
            <input type="text" id="smtp_server" class="config-input"
                   placeholder="SMTP服务器 (留空自动检测，QQ邮箱: smtp.qq.com)">
            <input type="number" id="smtp_port" class="config-input"
                   placeholder="SMTP端口 (留空自动检测，QQ邮箱: 587)">
            <small style="color: var(--text-secondary); font-size: 12px; display: block; margin-top: 5px; line-height: 1.6;">
                <strong>推荐使用QQ邮箱：</strong><br>
                1. 登录QQ邮箱网页版 (mail.qq.com)<br>
                2. 设置 -> 账户 -> 开启SMTP服务<br>
                3. 生成授权码（16位字符）<br>
                4. 将授权码填入"邮箱授权码"字段<br>
                支持自动检测：QQ、163、126、Gmail、Outlook等
            </small>

            <!-- Discord Webhook配置（可选） -->
            <h5 style="color: var(--text-primary); margin-top: 25px; margin-bottom: 15px; font-weight: 600;">
                <i class="fab fa-discord me-2"></i>Discord Webhook配置 <span style="color: var(--text-secondary);">(可选)</span>
            </h5>
            <input type="text" id="webhook" class="config-input"
                   placeholder="Discord Webhook URL (可选，例如: https://discord.com/api/webhooks/xxx)">
            <small style="color: var(--text-secondary); font-size: 12px; display: block; margin-top: 5px;">
                如需Discord通知，请填写Discord Webhook URL。不填写则不会发送Discord通知。
            </small>

            <input type="password" id="password" class="config-input"
                   placeholder="修改密码 (留空则不修改)">
            <button class="btn btn-primary w-100" onclick="saveConfig()">
                <i class="fas fa-save me-2"></i>保存配置
            </button>
        </div>

        <!-- 事件列表 -->
        <div id="eventsList">
            {% if events %}
                {% for event in events %}
                <div class="event-card" id="event-{{ event.id }}">
                    <div class="event-header">
                        <div>
                            <span class="delta-badge">
                                <i class="fas fa-exclamation-triangle"></i>
                                加速度: {{ "%.3f"|format(event.delta_accel) }}
                            </span>
                            {% if event.webhook_sent %}
                            <span class="webhook-badge">
                                <i class="fas fa-check"></i> 已通知
                            </span>
                            {% endif %}
                        </div>
                        <span class="timestamp">
                            <i class="far fa-clock me-1"></i>{{ event.timestamp }}
                        </span>
                    </div>

                    <div class="media-container">
                        {% if event.image_path %}
                        <img src="/media/{{ event.image_path.split('/')[-1] }}"
                             alt="360度全景图" loading="lazy">
                        {% endif %}

                        {% if event.front_image_path and event.back_image_path %}
                        <div class="media-grid">
                            <div>
                                <img src="/media/{{ event.front_image_path.split('/')[-1] }}"
                                     alt="前摄像头" loading="lazy">
                                <div class="media-label">前摄像头</div>
                            </div>
                            <div>
                                <img src="/media/{{ event.back_image_path.split('/')[-1] }}"
                                     alt="后摄像头" loading="lazy">
                                <div class="media-label">后摄像头</div>
                            </div>
                        </div>
                        {% endif %}

                        {% if event.video_path %}
                        {% set media_file = event.video_path.split('/')[-1] %}
                        {% if media_file.endswith('.gif') %}
                        <img src="/media/{{ media_file }}" alt="GIF动画" style="max-width: 100%; border-radius: 12px; margin: 10px 0; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);">
                        {% else %}
                        <video controls preload="metadata">
                            <source src="/media/{{ media_file }}" type="video/mp4">
                            您的浏览器不支持视频播放
                        </video>
                        {% endif %}
                        {% endif %}
                    </div>

                    <div class="btn-group-custom">
                        {% if event.image_path %}
                        <a href="/media/{{ event.image_path.split('/')[-1] }}" download
                           class="btn-custom btn-primary">
                            <i class="fas fa-download"></i> 下载图片
                        </a>
                        {% endif %}
                        {% if event.video_path %}
                        {% set media_file = event.video_path.split('/')[-1] %}
                        {% if media_file.endswith('.gif') %}
                        <a href="/media/{{ media_file }}" download
                           class="btn-custom btn-info">
                            <i class="fas fa-file-image"></i> 下载GIF
                        </a>
                        {% else %}
                        <a href="/media/{{ media_file }}" download
                           class="btn-custom btn-info">
                            <i class="fas fa-video"></i> 下载视频
                        </a>
                        {% endif %}
                        {% endif %}
                        <button class="btn-custom btn-danger" onclick="deleteEvent({{ event.id }})">
                            <i class="fas fa-trash"></i> 删除
                        </button>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state">
                    <i class="fas fa-inbox"></i>
                    <h4>暂无哨兵事件</h4>
                    <p>当检测到车辆震动时，事件将显示在这里</p>
                </div>
            {% endif %}
        </div>
    </div>

    <script>
        function toggleConfig() {
            const section = document.getElementById('configSection');
            section.style.display = section.style.display === 'none' ? 'block' : 'none';
            if (section.style.display === 'block') {
                loadConfig();
            }
        }


        async function loadConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                document.getElementById('sensitivity').value = config.sensitivity_threshold || 0.08;
                document.getElementById('webhook').value = config.webhook_url || '';
                document.getElementById('webserver').value = config.webserver_url || '';
                document.getElementById('email_from').value = config.email_from || '';
                document.getElementById('email_to').value = config.email_to || '';
                // 安全：不回显密码，用户需要重新输入
                document.getElementById('email_password').value = '';
                document.getElementById('smtp_server').value = config.smtp_server || '';
                document.getElementById('smtp_port').value = config.smtp_port || '';
            } catch (error) {
                console.error('加载配置失败:', error);
            }
        }

        async function saveConfig() {
            // 输入验证
            const sensitivity = parseFloat(document.getElementById('sensitivity').value);
            if (isNaN(sensitivity) || sensitivity < 0.01 || sensitivity > 1.0) {
                alert('❌ 灵敏度阈值必须在0.01-1.0之间');
                return;
            }

            // 邮件配置验证（必填）
            const emailFrom = document.getElementById('email_from').value.trim();
            const emailTo = document.getElementById('email_to').value.trim();
            const emailPassword = document.getElementById('email_password').value;

            if (!emailFrom || !emailTo || !emailPassword) {
                alert('❌ 邮件配置不完整！\n\n请填写：\n- 发件邮箱\n- 收件邮箱\n- 邮箱授权码\n\n邮件通知是必须配置的。');
                return;
            }

            // 验证邮箱格式
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(emailFrom)) {
                alert('❌ 发件邮箱格式不正确');
                return;
            }
            if (!emailRegex.test(emailTo)) {
                alert('❌ 收件邮箱格式不正确');
                return;
            }

            const data = {
                sensitivity_threshold: sensitivity,
                webhook_url: document.getElementById('webhook').value.trim(),  // Discord Webhook（可选）
                webserver_url: document.getElementById('webserver').value.trim(),
                // 邮件配置（必须）
                email_from: emailFrom,
                email_to: emailTo,
                email_password: emailPassword
            };

            // SMTP服务器和端口（可选，留空自动检测）
            const smtpServer = document.getElementById('smtp_server').value.trim();
            const smtpPortStr = document.getElementById('smtp_port').value.trim();
            if (smtpServer) {
                data.smtp_server = smtpServer;
            }
            if (smtpPortStr) {
                const smtpPort = parseInt(smtpPortStr);
                if (isNaN(smtpPort) || smtpPort < 1 || smtpPort > 65535) {
                    alert('❌ SMTP端口必须在1-65535之间');
                    return;
                }
                data.smtp_port = smtpPort;
            }

            // Web密码（可选）
            const password = document.getElementById('password').value;
            if (password) {
                data.web_password = password;
            }

            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                if (response.ok) {
                    alert('✅ 配置已保存!\n\n邮件通知已配置，Discord Webhook为可选。');
                    document.getElementById('password').value = '';
                    document.getElementById('email_password').value = '';
                    toggleConfig();
                } else {
                    const errorData = await response.json().catch(() => ({}));
                    alert(`❌ 保存失败: ${errorData.message || '请重试'}`);
                }
            } catch (error) {
                console.error('保存配置失败:', error);
                alert('❌ 网络错误，请检查连接');
            }
        }

        async function deleteEvent(eventId) {
            if (!confirm('确定要删除这个事件吗?\\n相关的图片和视频也会被删除。')) return;

            try {
                const response = await fetch(`/api/delete/${eventId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    const element = document.getElementById(`event-${eventId}`);
                    element.style.transition = 'opacity 0.3s';
                    element.style.opacity = '0';
                    setTimeout(() => element.remove(), 300);
                } else {
                    alert('❌ 删除失败，请重试');
                }
            } catch (error) {
                console.error('删除事件失败:', error);
                alert('❌ 网络错误，请检查连接');
            }
        }

        // 自动刷新事件列表
        let autoRefreshInterval = null;

        function startAutoRefresh() {
            autoRefreshInterval = setInterval(async () => {
                try {
                    const response = await fetch('/api/events');
                    const events = await response.json();

                    // 检查是否有新事件
                    const currentCount = document.querySelectorAll('.event-card').length;
                    if (events.length > currentCount) {
                        location.reload(); // 有新事件时刷新页面
                    }
                } catch (error) {
                    console.error('自动刷新失败:', error);
                }
            }, 30000); // 每30秒检查一次
        }

        // 页面加载时启动自动刷新
        window.addEventListener('load', startAutoRefresh);

        // 页面卸载时停止自动刷新
        window.addEventListener('beforeunload', () => {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
            }
        });
    </script>
</body>
</html>
"""

# ============ 路由装饰器 ============
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ============ 路由定义 ============
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        config = db.get_config()
        if password == config.get('web_password', '8899'):
            session['logged_in'] = True
            session.permanent = True  # 启用永久会话
            logger.info(f"User logged in from {request.remote_addr}")
            return redirect(url_for('index'))
        logger.warning(f"Failed login attempt from {request.remote_addr}")
        return render_template_string(LOGIN_HTML, error='密码错误')
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    if 'logged_in' in session:
        logger.info(f"User logged out from {request.remote_addr}")
    session.pop('logged_in', None)
    session.permanent = False
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    events = db.get_events(limit=50)
    return render_template_string(INDEX_HTML, events=events)

@app.route('/api/events')
@login_required
def get_events():
    events = db.get_events(limit=100)
    return jsonify(events)

@app.route('/api/config', methods=['GET', 'POST'])
@login_required
def config():
    if request.method == 'POST':
        data = request.json

        # 输入验证
        if 'sensitivity_threshold' in data:
            threshold = data['sensitivity_threshold']
            if not isinstance(threshold, (int, float)) or threshold < 0.01 or threshold > 1.0:
                logger.warning(f"Invalid sensitivity_threshold: {threshold} from {request.remote_addr}")
                return jsonify({'status': 'error', 'message': '灵敏度阈值必须在0.01-1.0之间'}), 400

        # 邮件配置验证（必填）
        if 'email_from' in data and data['email_from']:
            email_from = data['email_from'].strip()
            if '@' not in email_from or '.' not in email_from.split('@')[1]:
                logger.warning(f"Invalid email_from format from {request.remote_addr}")
                return jsonify({'status': 'error', 'message': '发件邮箱格式不正确'}), 400

        if 'email_to' in data and data['email_to']:
            email_to = data['email_to'].strip()
            if '@' not in email_to or '.' not in email_to.split('@')[1]:
                logger.warning(f"Invalid email_to format from {request.remote_addr}")
                return jsonify({'status': 'error', 'message': '收件邮箱格式不正确'}), 400

        # 邮件配置必须完整（如果提供了部分配置）
        if 'email_from' in data or 'email_to' in data or 'email_password' in data:
            email_from = data.get('email_from', '').strip() if data.get('email_from') else ''
            email_to = data.get('email_to', '').strip() if data.get('email_to') else ''
            email_password = data.get('email_password', '').strip() if data.get('email_password') else ''

            # 检查现有配置
            current_config = db.get_config()
            email_from = email_from or current_config.get('email_from', '')
            email_to = email_to or current_config.get('email_to', '')
            email_password = email_password or current_config.get('email_password', '')

            if not all([email_from, email_to, email_password]):
                logger.warning(f"Incomplete email configuration from {request.remote_addr}")
                return jsonify({'status': 'error', 'message': '邮件配置不完整，请填写发件邮箱、收件邮箱和授权码'}), 400

        if 'smtp_port' in data and data['smtp_port'] is not None:
            port = data['smtp_port']
            if not isinstance(port, int) or port < 1 or port > 65535:
                logger.warning(f"Invalid smtp_port: {port} from {request.remote_addr}")
                return jsonify({'status': 'error', 'message': 'SMTP端口必须在1-65535之间'}), 400

        # 处理空字符串：如果配置项为空字符串，设置为None以清空数据库中的值
        # 但邮件配置不能为空（如果提供了空值，保持现有值）
        cleaned_data = {}
        for k, v in data.items():
            # 邮件配置不能为空（如果提供了空值，不更新，保持现有值）
            if k in ['email_from', 'email_to', 'email_password']:
                if v and v.strip():
                    cleaned_data[k] = v.strip()
                # 如果为空字符串，不更新（保持现有值）
            elif v == '':
                cleaned_data[k] = None  # 清空配置（如webhook_url等可选配置）
            elif v is not None:
                cleaned_data[k] = v

        db.update_config(**cleaned_data)
        logger.info(f"Config updated from {request.remote_addr}")
        return jsonify({'status': 'success'})

    # GET请求时不返回敏感信息
    config = db.get_config()
    # 移除密码字段，保护敏感信息
    config.pop('email_password', None)
    return jsonify(config)

@app.route('/media/<path:filename>')
@login_required
def serve_media(filename):
    """提供媒体文件服务，带安全检查"""
    # 安全检查：防止路径遍历攻击
    filename = os.path.basename(filename)
    file_path = os.path.join(MEDIA_DIR, filename)

    # 确保文件在MEDIA_DIR目录内
    if not os.path.abspath(file_path).startswith(os.path.abspath(MEDIA_DIR)):
        return jsonify({'status': 'error', 'message': 'Invalid file path'}), 403

    if not os.path.exists(file_path):
        return jsonify({'status': 'error', 'message': 'File not found'}), 404

    try:
        return send_file(file_path)
    except Exception as e:
        logger.error(f"Error serving media file {filename} from {request.remote_addr}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to serve file'}), 500

@app.route('/api/delete/<int:event_id>', methods=['DELETE'])
@login_required
def delete_event(event_id):
    events = db.get_events()
    event = next((e for e in events if e['id'] == event_id), None)

    if event:
        # 删除关联的媒体文件
        deleted_files = []
        for path_key in ['image_path', 'video_path', 'front_image_path', 'back_image_path']:
            path = event.get(path_key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    deleted_files.append(path)
                except Exception as e:
                    logger.error(f"Error deleting {path}: {e}")

        db.delete_event(event_id)
        logger.info(f"Event {event_id} deleted from {request.remote_addr}, files: {deleted_files}")
        return jsonify({'status': 'success'})

    logger.warning(f"Event {event_id} not found, requested from {request.remote_addr}")
    return jsonify({'status': 'error', 'message': 'Event not found'}), 404

# ============ 主程序入口 ============
def main():
    """启动Web服务器"""
    # 抑制Flask开发服务器的警告信息
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="werkzeug")

    # 设置werkzeug日志级别，抑制开发服务器警告
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    logger.info("Starting Xiaoge Sentry Web Server on port 8899...")
    logger.info(f"Session timeout: {app.config['PERMANENT_SESSION_LIFETIME']}")
    logger.info(f"CSRF protection: {'enabled' if csrf else 'disabled'}")
    logger.info("Web server is ready, listening on http://0.0.0.0:8899")

    # 在comma3设备上使用threaded模式，避免阻塞主进程
    # PC环境可以使用debug模式，设备环境禁用
    # 设置use_reloader=False避免在comma3设备上出现问题
    app.run(host='0.0.0.0', port=8899, debug=False, threaded=True, use_reloader=False)

if __name__ == "__main__":
    main()


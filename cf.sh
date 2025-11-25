#!/usr/bin/env bash
# install-cloudflared-comma.sh
# 适配 Comma 3/3X 的 Cloudflare Tunnel 安装脚本（Token 模式）
#
# 核心修正与注意点：
#  - 不使用 apt 安装 cloudflared（使用 Cloudflare 官方静态二进制）
#  - 不把 token 写入 config.yml；用 --token 参数启动
#  - 配置与二进制放在 /data/cloudflared（避免被 rootfs 覆盖）
#  - 在必要时短暂 remount 根文件系统为 rw 来写入 systemd 单元，然后恢复 ro
#  - 创建 systemd 服务，使用 EnvironmentFile 存放 token（0600）
#  - 不创建 credentials.json（token 模式下不需要）
#
# 运行（交互）:
#   sudo ./install-cloudflared-comma.sh
# 或非交互方式:
#   sudo ./install-cloudflared-comma.sh comma.example.com AN_EXAMPLE_TOKEN
#
set -euo pipefail

# colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Cloudflare Tunnel 安装 (Comma 3/3X 适配) ===${NC}"

# require root (re-exec with sudo if needed)
if [ "$EUID" -ne 0 ]; then
  echo "需要 root 权限，正在使用 sudo..."
  exec sudo bash "$0" "$@"
fi

# args or prompts
if [ $# -ge 2 ]; then
  CUSTOM_DOMAIN="$1"
  CF_TUNNEL_TOKEN="$2"
else
  if [ -f /COMMA ]; then
    echo -e "${YELLOW}检测到 Comma 设备（/COMMA 存在）${NC}"
  else
    echo -e "${YELLOW}未检测到 /COMMA，继续安装前请确认您在目标设备上运行此脚本${NC}"
    read -p "是否继续? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "已取消"
      exit 1
    fi
  fi

  read -p "请输入您的自定义域名 (例如: comma.yourdomain.com): " CUSTOM_DOMAIN
  read -p "请输入 Cloudflare Tunnel 令牌（Token）: " CF_TUNNEL_TOKEN
fi

if [ -z "$CUSTOM_DOMAIN" ] || [ -z "$CF_TUNNEL_TOKEN" ]; then
  echo -e "${RED}错误: 域名和令牌不能为空${NC}"
  exit 1
fi

# paths
INSTALL_DIR="/data/cloudflared"
BINARY_PATH="$INSTALL_DIR/cloudflared"
CONFIG_PATH="$INSTALL_DIR/config.yml"
ENV_PATH="$INSTALL_DIR/token.env"
SERVICE_PATH="/etc/systemd/system/cloudflared.service"

echo -e "\n${YELLOW}步骤 1/5: 创建目录并准备${NC}"
mkdir -p "$INSTALL_DIR"
chown root:root "$INSTALL_DIR"
chmod 0755 "$INSTALL_DIR"

# detect arch
ARCH=$(uname -m)
case "$ARCH" in
  aarch64|arm64) BIN_NAME="cloudflared-linux-arm64" ;;
  armv7l) BIN_NAME="cloudflared-linux-arm" ;;        # older arm
  x86_64|amd64) BIN_NAME="cloudflared-linux-amd64" ;;
  i386|i686) BIN_NAME="cloudflared-linux-386" ;;
  *)
    echo -e "${YELLOW}未识别的架构: $ARCH ，默认使用 arm64 二进制（如果不对请手动下载并放置到 $BINARY_PATH）${NC}"
    BIN_NAME="cloudflared-linux-arm64"
    ;;
esac

DOWNLOAD_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/${BIN_NAME}"

echo "检测到架构: $ARCH -> 下载: $BIN_NAME"
echo "从: $DOWNLOAD_URL 下载 cloudflared..."

# download binary
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$DOWNLOAD_URL" -o "$BINARY_PATH.part"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$BINARY_PATH.part" "$DOWNLOAD_URL"
else
  echo -e "${RED}错误: 系统没有 curl 或 wget，请先安装或手动把 cloudflared 放到 $BINARY_PATH${NC}"
  exit 1
fi

mv "$BINARY_PATH.part" "$BINARY_PATH"
chmod 0755 "$BINARY_PATH"
echo -e "${GREEN}✓ cloudflared 已下载到 $BINARY_PATH${NC}"

# optional symlink to /usr/local/bin if writable
if [ -w /usr/local/bin ] || [ -d /usr/local/bin ]; then
  ln -sf "$BINARY_PATH" /usr/local/bin/cloudflared 2>/dev/null || true
fi

# create config.yml (do NOT include token or tunnel uuid here)
cat > "$CONFIG_PATH" <<EOF
# Cloudflared config - token 模式下不需要 tunnel: <UUID>
ingress:
  - hostname: $CUSTOM_DOMAIN
    service: ssh://localhost:22

  - hostname: fleet.$CUSTOM_DOMAIN
    service: http://localhost:8082

  - service: http_status:404
EOF

chmod 0644 "$CONFIG_PATH"
echo -e "${GREEN}✓ config 已写入 $CONFIG_PATH${NC}"

# write token env (0600)
cat > "$ENV_PATH" <<EOF
CF_TUNNEL_TOKEN="$CF_TUNNEL_TOKEN"
EOF
chmod 0600 "$ENV_PATH"
echo -e "${GREEN}✓ token 已写入 $ENV_PATH（权限 600）${NC}"

# systemd unit content
SERVICE_CONTENT="[Unit]
Description=Cloudflare Tunnel (cloudflared) - Comma
After=network-online.target
Wants=network-online.target

[Service]
User=root
EnvironmentFile=$ENV_PATH
ExecStart=$BINARY_PATH tunnel run --token \$CF_TUNNEL_TOKEN --config $CONFIG_PATH
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
"

# helper to check if root fs is ro
is_root_ro() {
  # Method 1: findmnt (if available)
  if command -v findmnt >/dev/null 2>&1; then
    local opts
    opts=$(findmnt -n -o OPTIONS / 2>/dev/null || true)
    case ",$opts," in
      *",ro,"*) return 0 ;;
      *) return 1 ;;
    esac
  fi

  # Method 2: /proc/mounts fallback
  if awk '$2 == "/" {print $4}' /proc/mounts | grep -qE "(^|,)ro(,|$)"; then
    return 0
  fi
  return 1
}

WROTE_SERVICE=0
if [ -w "$(dirname "$SERVICE_PATH")" ]; then
  printf "%s" "$SERVICE_CONTENT" > "$SERVICE_PATH"
  WROTE_SERVICE=1
else
  # try remounting root rw temporarily
  if is_root_ro; then
    echo -e "${YELLOW}检测到根文件系统只读，短暂切换为可写以安装 systemd 单元（完成后会恢复）${NC}"
    mount -o remount,rw /
    RESTORE_ROOT_RO=1
    # Ensure we restore ro even if script fails
    trap 'if [ "${RESTORE_ROOT_RO:-0}" -eq 1 ]; then echo "异常退出，正在恢复只读根文件系统..."; mount -o remount,ro /; fi' EXIT

    printf "%s" "$SERVICE_CONTENT" > "$SERVICE_PATH"
    WROTE_SERVICE=1
  else
    echo -e "${YELLOW}根文件系统可写，但 /etc 目录不可写或不存在，尝试写入失败。${NC}"
    printf "%s" "$SERVICE_CONTENT" > "$SERVICE_PATH" || {
      echo -e "${RED}错误: 无法写入 $SERVICE_PATH 。请手动创建 systemd 单元，或以 root 在设备上运行此脚本。${NC}"
      exit 1
    }
    WROTE_SERVICE=1
  fi
fi

if [ "$WROTE_SERVICE" -ne 1 ]; then
  echo -e "${RED}错误: 无法安装 systemd 单元${NC}"
  exit 1
fi

chmod 0644 "$SERVICE_PATH"
echo -e "${GREEN}✓ systemd 单元已写入 $SERVICE_PATH${NC}"

# reload & enable & start
echo "systemctl daemon-reload..."
systemctl daemon-reload

echo "启用并启动 cloudflared 服务..."
systemctl enable --now cloudflared.service

# if we remounted root to rw, restore ro
if [ "${RESTORE_ROOT_RO:-0}" -eq 1 ]; then
  echo "恢复只读根文件系统..."
  mount -o remount,ro /
  RESTORE_ROOT_RO=0
fi

echo -e "\n${GREEN}=== 安装完成 ===${NC}"
echo -e "${YELLOW}服务状态检查:${NC} systemctl status cloudflared --no-pager"
echo -e "${YELLOW}日志查看:${NC} journalctl -u cloudflared -f"
echo ""
echo -e "${YELLOW}客户端/Cloudflare 配置提示:${NC}"
echo "  - 在 Cloudflare Zero Trust 控制台创建或允许主机名："
echo "      $CUSTOM_DOMAIN -> ssh://localhost:22"
echo "      fleet.$CUSTOM_DOMAIN -> http://localhost:8082"
echo "  - SSH 客户端示例 ~/.ssh/config (按需修改 IdentityFile):"
cat <<EOF
Host comma-custom
  HostName $CUSTOM_DOMAIN
  User comma
  Port 22
  IdentityFile ~/.ssh/your_github_key
  ProxyCommand cloudflared access ssh --hostname %h
  PubkeyAuthentication yes

Host comma-fleet
  HostName fleet.$CUSTOM_DOMAIN
  User comma
  Port 8082
  IdentityFile ~/.ssh/your_github_key
  # Fleet 是 HTTP(S)，在浏览器访问 https://fleet.$CUSTOM_DOMAIN
EOF

echo -e "${GREEN}完成！${NC}"

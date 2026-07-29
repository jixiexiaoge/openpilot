#!/usr/bin/bash
set -e

SERVICE_FILE="/data/openpilot/system/flockd.service"
SERVICE_NAME="flockd.service"
SERVICE_OVERRIDE="/etc/systemd/system/${SERVICE_NAME}"
SERVICE_BAKED="/lib/systemd/system/${SERVICE_NAME}"

echo "Installing Flock RF detector systemd service..."

if [ -f "$SERVICE_BAKED" ] && grep -q "/usr/libexec/iqpilot/iqpilot_bundle_runner" "$SERVICE_BAKED"; then
    echo "Using IQ.OS baked ${SERVICE_NAME}; removing stale override if present..."
    sudo mount -o remount,rw /
    sudo rm -f "$SERVICE_OVERRIDE"
    sudo systemctl daemon-reload
    sudo mount -o remount,ro /
else
    if [ ! -f "$SERVICE_FILE" ]; then
        echo "ERROR: Service file not found at $SERVICE_FILE"
        exit 1
    fi

    echo "IQ.OS baked unit unavailable; installing fallback override into /etc/systemd/system..."
    sudo cp "$SERVICE_FILE" "$SERVICE_OVERRIDE"
    sudo systemctl daemon-reload
fi

echo "Enabling $SERVICE_NAME to start at boot..."
sudo systemctl enable "$SERVICE_NAME"

echo "Starting $SERVICE_NAME..."
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "Service status:"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "Useful commands:"
echo "  sudo systemctl status flockd    - Check service status"
echo "  sudo systemctl restart flockd   - Restart service"
echo "  sudo journalctl -u flockd -f    - View live logs"

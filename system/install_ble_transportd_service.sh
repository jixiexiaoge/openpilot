#!/usr/bin/bash
set -e

SERVICE_FILE="/data/openpilot/system/ble-transportd.service"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_NAME="ble-transportd.service"

echo "Installing BLE transportd systemd service..."

if [ ! -f "$SERVICE_FILE" ]; then
    echo "ERROR: Service file not found at $SERVICE_FILE"
    exit 1
fi

echo "Copying service file to $SYSTEMD_DIR..."
sudo cp "$SERVICE_FILE" "$SYSTEMD_DIR/$SERVICE_NAME"

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling $SERVICE_NAME to start at boot..."
sudo systemctl enable "$SERVICE_NAME"

echo "Starting $SERVICE_NAME..."
sudo systemctl start "$SERVICE_NAME"

echo ""
echo "Service status:"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "Useful commands:"
echo "  sudo systemctl status ble-transportd    - Check service status"
echo "  sudo systemctl restart ble-transportd   - Restart service"
echo "  sudo systemctl stop ble-transportd      - Stop service"
echo "  sudo journalctl -u ble-transportd -f    - View live logs"

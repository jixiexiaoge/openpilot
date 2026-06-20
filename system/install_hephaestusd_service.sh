#!/usr/bin/bash
set -e

SERVICE_FILE="/data/openpilot/system/hephaestusd.service"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_NAME="hephaestusd.service"

echo "Installing Hephaestusd systemd service..."

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
echo "✓ Hephaestusd service installed successfully!"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status hephaestusd    - Check service status"
echo "  sudo systemctl restart hephaestusd   - Restart service"
echo "  sudo systemctl stop hephaestusd      - Stop service"
echo "  sudo journalctl -u hephaestusd -f    - View live logs"

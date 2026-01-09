#!/bin/bash
# Monk Bot - Secure Installation Script for Ubuntu 24.04
# Run as root or with sudo

set -e

INSTALL_DIR="/opt/monk_bot"
SERVICE_USER="monkbot"

echo "=== Monk Bot Secure Installation ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./install.sh)"
    exit 1
fi

# Create service user
echo "[1/6] Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "  Created user: $SERVICE_USER"
else
    echo "  User $SERVICE_USER already exists"
fi

# Create directory
echo "[2/6] Setting up directory..."
mkdir -p "$INSTALL_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 750 "$INSTALL_DIR"

# Copy files
echo "[3/6] Copying application files..."
cp bot.py config.py requirements.txt "$INSTALL_DIR/"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"/*.py "$INSTALL_DIR"/requirements.txt
chmod 640 "$INSTALL_DIR"/*.py "$INSTALL_DIR"/requirements.txt

# Create virtual environment
echo "[4/6] Creating virtual environment..."
sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
echo "  Dependencies installed"

# Create .env if not exists
echo "[5/6] Setting up environment file..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    touch "$INSTALL_DIR/.env"
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    echo "  Created .env file (edit with your credentials)"
    echo "  Run: sudo nano $INSTALL_DIR/.env"
else
    echo "  .env already exists (preserving)"
fi

# Install systemd service
echo "[6/6] Installing systemd service..."
cp deploy/systemd/omni_pairs_bot.service /etc/systemd/system/
chmod 644 /etc/systemd/system/omni_pairs_bot.service
systemctl daemon-reload
echo "  Service installed"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit credentials:  sudo nano $INSTALL_DIR/.env"
echo "  2. Start service:     sudo systemctl start omni_pairs_bot"
echo "  3. Enable on boot:    sudo systemctl enable omni_pairs_bot"
echo "  4. Check status:      sudo systemctl status omni_pairs_bot"
echo "  5. View logs:         sudo journalctl -u omni_pairs_bot -f"

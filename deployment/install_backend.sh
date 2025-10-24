#!/bin/bash

# IntegralDB Backend Installation Script

# Exit on error
set -e

# Configuration
INSTALL_DIR="/opt/integraldb"
SERVICE_USER="integraldb"
SERVICE_GROUP="integraldb"
VENV_PATH="$INSTALL_DIR/venv"

# Create service user
echo "Creating service user..."
sudo useradd -r -s /bin/false $SERVICE_USER

# Create installation directory
echo "Creating installation directory..."
sudo mkdir -p $INSTALL_DIR
sudo chown $SERVICE_USER:$SERVICE_GROUP $INSTALL_DIR

# Create Python virtual environment
echo "Setting up Python virtual environment..."
sudo -u $SERVICE_USER python3 -m venv $VENV_PATH

# Install package
echo "Installing IntegralDB package..."
sudo -u $SERVICE_USER $VENV_PATH/bin/pip install -e .

# Create data directories
echo "Creating data directories..."
sudo -u $SERVICE_USER mkdir -p $INSTALL_DIR/data/attachments
sudo -u $SERVICE_USER mkdir -p $INSTALL_DIR/data/credentials

# Copy service file
echo "Installing systemd service..."
sudo cp deployment/integraldb.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "Installation complete!"
echo "To start the service:"
echo "1. Configure your .env file in $INSTALL_DIR"
echo "2. Run: sudo systemctl start integraldb"
echo "3. To enable on boot: sudo systemctl enable integraldb"
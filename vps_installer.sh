#!/bin/bash

# ─── ULTIMATE VPS INSTALLER ───
# For Cipher Bot Hosting Platform
# Supported: Ubuntu, Debian, CentOS, RHEL, Fedora, Arch

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting Ultimate VPS Setup...${NC}"

# 1. Detect OS and Install Dependencies
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    OS=$(uname -s)
fi

echo -e "${GREEN}📦 Detected OS: $OS${NC}"

# Check for sudo
SUDO=""
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
fi

case "$OS" in
    ubuntu|debian|raspbian)
        $SUDO apt update
        $SUDO apt install -y python3 python3-pip python3-venv git curl nodejs npm
        ;;
    centos|rhel|fedora)
        $SUDO dnf install -y python3 python3-pip git curl nodejs npm
        ;;
    arch)
        $SUDO pacman -Syu --noconfirm python python-pip git curl nodejs npm
        ;;
    *)
        echo -e "${RED}⚠️ Unknown OS. Please ensure Python 3, Pip, and Node.js are installed manually.${NC}"
        ;;
esac

# 2. Setup Virtual Environment
echo -e "${BLUE}🐍 Setting up Python environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 3. Install Requirements
echo -e "${BLUE}📥 Installing dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# 4. Check for .env
if [ ! -f ".env" ]; then
    echo -e "${RED}⚠️ .env file not found! Creating from example...${NC}"
    cp .env.example .env
    echo -e "${RED}❗ PLEASE EDIT .env WITH YOUR CREDENTIALS BEFORE STARTING.${NC}"
fi

# 5. Create necessary directories
echo -e "${BLUE}📂 Creating storage directories...${NC}"
mkdir -p storage/{uploads,encfiles,data,logs,backups,photos,tickets,bot_data}
mkdir -p sandbox

# 6. Create Systemd Service (Optional but recommended)
read -p "❓ Do you want to create a systemd service for auto-restart? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    SERVICE_NAME="cipher-host"
    WORKING_DIR=$(pwd)
    USER_NAME=$(whoami)
    
    echo -e "${BLUE}⚙️ Creating systemd service: $SERVICE_NAME...${NC}"
    
    SERVICE_FILE="[Unit]
Description=Cipher Bot Hosting Platform
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$WORKING_DIR
ExecStart=$WORKING_DIR/venv/bin/python3 $WORKING_DIR/bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target"

    echo "$SERVICE_FILE" | $SUDO tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable $SERVICE_NAME
    
    echo -e "${GREEN}✅ Systemd service created and enabled!${NC}"
    echo -e "${GREEN}👉 To start the bot: sudo systemctl start $SERVICE_NAME${NC}"
    echo -e "${GREEN}👉 To check logs: journalctl -u $SERVICE_NAME -f${NC}"
fi

echo -e "${GREEN}✅ Setup Complete!${NC}"
echo "------------------------------------------------"
echo -e "${BLUE}🚀 To start manually, run:${NC}"
echo "   source venv/bin/activate && python3 bot.py"
echo "------------------------------------------------"

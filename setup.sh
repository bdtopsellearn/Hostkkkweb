#!/bin/bash

# ─── UNIVERSAL VPS SETUP SCRIPT ───
# For Cipher Bot Hosting Platform
# Supported: Ubuntu, Debian, CentOS, RHEL, Fedora, Arch

set -e

echo "🚀 Starting Universal VPS Setup..."

# 1. Detect OS and Install Dependencies
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    OS=$(uname -s)
fi

echo "📦 Detected OS: $OS"

case "$OS" in
    ubuntu|debian|raspbian)
        sudo apt update
        sudo apt install -y python3 python3-pip python3-venv git curl nodejs npm
        ;;
    centos|rhel|fedora)
        sudo dnf install -y python3 python3-pip git curl nodejs npm
        ;;
    arch)
        sudo pacman -Syu --noconfirm python python-pip git curl nodejs npm
        ;;
    *)
        echo "⚠️ Unknown OS. Please ensure Python 3, Pip, and Node.js are installed manually."
        ;;
esac

# 2. Setup Virtual Environment
echo "🐍 Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/bin/activate || source venv/bin/activate

# 3. Install Requirements
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Check for .env
if [ ! -f ".env" ]; then
    echo "⚠️ .env file not found! Creating from example..."
    cp .env.example .env
    echo "❗ PLEASE EDIT .env WITH YOUR CREDENTIALS BEFORE STARTING."
fi

# 5. Create necessary directories
echo "📂 Creating storage directories..."
mkdir -p storage/{uploads,encfiles,data,logs,backups,photos,tickets,bot_data}
mkdir -p sandbox

echo "✅ Setup Complete!"
echo "------------------------------------------------"
echo "🚀 To start the bot, run:"
echo "   source venv/bin/activate && python3 bot.py"
echo "------------------------------------------------"

# 🛡️ VPS Deployment Guide (Systemd-Enabled Linux Environments)

Deploying on a standard Virtual Private Server (VPS) running Ubuntu or Debian gives you full kernel control, dedicated resources, and persistent background process management via `systemd`.

---

### Step 1: How to Check if Your VPS Has `systemd`
Before proceeding, verify whether your VPS uses `systemd` as its init system. Run this command in your VPS terminal:

```bash
ps -p 1 -o comm=
```

- **If the output is `systemd`**: Your VPS fully supports systemd services (Proceed with Step 2).
- **If the output is `init`, `openrc`, or anything else**: Your VPS uses a legacy init system; you will need to run the bot inside a `screen` or `tmux` session instead of a systemd service.

You can also check systemd status directly:
```bash
systemctl --version
```

---

### Step 2: System Setup & Dependencies
Log into your VPS via SSH as `root` (or a sudo-enabled user) and install Python 3 and pip:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl
```

---

### Step 3: Clone and Setup the Repository
```bash
git clone https://github.com/Lord-Cipher/cipher-bot-hosting.git /opt/cipher-bot
cd /opt/cipher-bot

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

### Step 4: Configure Environment Variables
Create a `.env` file in `/opt/cipher-bot/.env`:

```env
BOT_TOKEN=your_main_bot_token_here
OWNER_ID=your_telegram_user_id_here
FORCE_POLLING=true
```

---

### Step 5: Create a Systemd Service (For Background Persistence)
Create a systemd service file to ensure your bot starts automatically on boot and restarts if it crashes:

```bash
sudo nano /etc/systemd/system/cipherbot.service
```

Paste the following configuration (adjust paths and user if necessary):

```ini
[Unit]
Description=Lord Cipher Bot Hosting Platform
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/cipher-bot
ExecStart=/opt/cipher-bot/venv/bin/python3 /opt/cipher-bot/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

### Step 6: Enable and Start the Service
Reload systemd, enable the service to start on boot, and start it immediately:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cipherbot
sudo systemctl start cipherbot
```

### Step 7: Monitor Logs & Status
To check if your bot is running smoothly:
```bash
sudo systemctl status cipherbot
```

To view live real-time logs:
```bash
sudo journalctl -u cipherbot -f
```

# 🚀 Railway Deployment Guide (Non-Systemd Container Environment)

Railway runs applications inside isolated **Docker containers** (namespaces/cgroups), meaning traditional init systems like `systemd` are **not present or accessible**. The platform is specifically engineered to detect this and operate seamlessly via built-in keepalive listeners and auto-fallback polling/webhook logic.

---

### Step 1: Repository Preparation
Ensure your project directory contains the following core files:
- `bot.py` — Main platform core & Telegram handlers.
- `security_scanner_free.py` — Conservative security scanner.
- `requirements.txt` — Python dependencies.
- `Procfile` or `Dockerfile` (Optional; Railway auto-detects Python).

---

### Step 2: Environment Variables
In your Railway project settings, configure the following environment variables:

| Variable Name | Value / Description | Required? |
| :--- | :--- | :--- |
| `BOT_TOKEN` | Your main Telegram hosting bot token from `@BotFather`. | **Yes** |
| `OWNER_ID` | Your Telegram Numeric User ID (e.g., `8065173971`). | **Yes** |
| `FORCE_POLLING` | Set to `true` if you want long-polling instead of webhooks. | Optional |

---

### Step 3: Deployment Steps
1. Push your repository to GitHub.
2. Create a new project on [Railway](https://railway.app/) and select **Deploy from GitHub repo**.
3. Select your `cipher-bot-hosting` repository.
4. Add the required environment variables in the Railway Variables tab.
5. Railway will automatically build and start the application using `python3 bot.py`.

---

### How Railway Execution Works Without Systemd
- **Process Management:** Railway manages the container lifecycle directly. If the Python process crashes, Railway restarts the entire container.
- **Keepalive Server:** The bot starts a lightweight HTTP keepalive server on port `8080` (or `PORT` environment variable) to satisfy Railway's health checks.
- **Connection Mode:** If no domain is set, the bot automatically falls back to high-stability **Long Polling**, requiring zero manual domain configuration.

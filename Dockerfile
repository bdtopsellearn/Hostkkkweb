# ─── DOCKERFILE FOR CIPHER BOT HOSTING ───
# Optimized for any VPS with Docker support

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    nodejs \
    npm \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create storage directories
RUN mkdir -p storage/{uploads,encfiles,data,logs,backups,photos,tickets,bot_data} sandbox

# Expose ports (Flask keep-alive / Webhooks)
EXPOSE 10000 10460

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

# Start the bot
CMD ["python", "bot.py"]

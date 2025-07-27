FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for Playwright + your existing tools
RUN apt update && apt install -y \
    ffmpeg aria2 git curl wget gnupg ca-certificates \
    fonts-liberation libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 \
    libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxrandr2 libxss1 libxtst6 xdg-utils libasound2 \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Copy your code
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install spotipy playwright yt-dlp spotdl

# Install Playwright browsers
RUN python -m playwright install

CMD ["python", "bot.py"]

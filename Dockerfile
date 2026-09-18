FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for matplotlib / reportlab fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libfreetype6-dev \
    libpng-dev \
    fonts-dejavu-core \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Directory for persistent database mount
RUN mkdir -p /data

ENV DB_PATH=/data/kirana.db

CMD ["python", "-m", "src.bot.main"]

# ============================================================
# Telegram Video Downloader Bot — Dockerfile
# ============================================================
FROM python:3.11-slim

# Устанавливаем ffmpeg (нужен yt-dlp для слияния видео+аудио),
# curl (для healthcheck и загрузки на файлообменник)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Папка для скачиваний
RUN mkdir -p downloads && chmod +x main.py

# Порт FastAPI
EXPOSE 8000

# Healthcheck — Railway будет следить за жизнеспособностью приложения
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Запуск
CMD ["python", "main.py"]
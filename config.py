"""Загрузка и хранение всей конфигурации бота из переменных окружения (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем переменные из .env (если файл есть).
load_dotenv()

# --- Telegram ---
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
# Список Telegram ID администраторов (через запятую), им доступна команда /stats
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

# --- Реклама ---
# Текст рекламного сообщения (показывается перед скачиванием)
AD_TEXT: str = os.getenv(
    "AD_TEXT",
    "🔥 Этот бот работает полностью бесплатно благодаря рекламе!\n\n"
    "Пожалуйста, поддержите проект — перейдите к рекламодателю по кнопке ниже 👇",
)
# Ссылка на рекламодателя
AD_LINK: str = os.getenv("AD_LINK", "https://example.com")
# Текст inline-кнопки "Перейти к рекламодателю"
AD_BUTTON_LABEL: str = os.getenv("AD_BUTTON_LABEL", "👉 Перейти к рекламодателю")
# Как часто показывать рекламу одному пользователю (в часах).
# 0 = показывать при каждом скачивании; 24 = не чаще раза в сутки.
AD_COOLDOWN_HOURS: float = float(os.getenv("AD_COOLDOWN_HOURS", "0"))

# --- Поддержка автора ---
SUPPORT_URL: str = os.getenv("SUPPORT_URL", AD_LINK)
SUPPORT_TEXT: str = os.getenv("SUPPORT_TEXT", "Спасибо, что пользуетесь ботом! 💛")

# --- Файлы и загрузка ---
# Максимальный размер файла, который мы готовы обработать (по умолчанию 2 ГБ).
# Файлы больше этого размера просто не скачиваем.
MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(2 * 1024 * 1024 * 1024)))
DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", "downloads")
FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "ffmpeg")
YTDLP_PATH: str = os.getenv("YTDLP_PATH", "yt-dlp")

# --- Режим работы: webhook или long polling ---
# USE_WEBHOOK = true  -> используется webhook (подходит для Railway 24/7)
# USE_LONG_POLLING = true (по умолчанию) -> long polling без внешнего URL
USE_WEBHOOK: bool = os.getenv("USE_WEBHOOK", "false").lower() in ("1", "true", "yes")
USE_LONG_POLLING: bool = os.getenv("USE_LONG_POLLING", "true").lower() in ("1", "true", "yes")

WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
# Секретный токен для защиты webhook (Telegram шлёт его в заголовке)
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
# Полный публичный URL приложения, напр. https://mybot.up.railway.app
PUBLIC_URL: str = os.getenv("PUBLIC_URL", "").rstrip("/")

# --- FastAPI / Uvicorn ---
APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT: int = int(os.getenv("PORT", os.getenv("APP_PORT", "8000")))

# --- База данных ---
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Создайте файл .env (см. .env.example).")

# Гарантируем существование папки для скачиваний.
Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

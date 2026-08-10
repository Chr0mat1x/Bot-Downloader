"""Точка входа: FastAPI-приложение с webhook или long-polling + Uvicorn.

Используется для деплоя на Railway 24/7.
"""
import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from uvicorn import Server, Config

# ---------------------------------------------------------------------------
# Настройка логирования
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Импорт конфига и модулей
# ---------------------------------------------------------------------------
import config
import database as db
from handlers import router


# ---------------------------------------------------------------------------
# Инициализация бота и диспетчера
# ---------------------------------------------------------------------------
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
dp.include_router(router)

# FastAPI-приложение (будет запущено через Uvicorn)
app = FastAPI(
    title="Telegram Video Downloader Bot",
    version="1.0.0",
    description="FastAPI + aiogram 3.x — бесплатный бот для скачивания видео",
)


# ---------------------------------------------------------------------------
# Хелсчек
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Проверка живучести приложения."""
    return {"status": "ok", "bot_configured": bool(config.BOT_TOKEN)}


# ---------------------------------------------------------------------------
# Webhook endpoint (если USE_WEBHOOK=True)
# ---------------------------------------------------------------------------
@app.post(config.WEBHOOK_PATH)
async def webhook_handler(request: Request) -> Response:
    """Принимает обновления от Telegram Bot API через webhook."""
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if config.WEBHOOK_SECRET and secret != config.WEBHOOK_SECRET:
        logger.warning("Неверный секретный токен webhook, доступ запрещён.")
        return Response(status_code=403)

    try:
        data = await request.json()
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
        return Response(status_code=200)
    except Exception as exc:
        logger.exception("Ошибка при обработке webhook-обновления: %s", exc)
        return Response(status_code=200)  # Telegram требует 200 OK


# ---------------------------------------------------------------------------
# Запуск приложения (точка входа для Python)
# ---------------------------------------------------------------------------
async def on_startup() -> None:
    """Действия при старте бота и приложения."""
    await db.init_db()
    logger.info("База данных инициализирована.")

    if config.USE_WEBHOOK and config.PUBLIC_URL:
        webhook_url = f"{config.PUBLIC_URL}{config.WEBHOOK_PATH}"
        await bot.set_webhook(
            url=webhook_url,
            secret_token=config.WEBHOOK_SECRET or None,
            allowed_updates=dp.resolve_used_update_types(),
        )
        logger.info("Webhook установлен: %s", webhook_url)
    else:
        # Удаляем webhook, если он был, и запускаем long-polling
        await bot.delete_webhook()
        logger.info("Webhook удалён, используем long-polling.")


async def on_shutdown() -> None:
    """Действия при остановке."""
    try:
        await bot.session.close()
    except Exception as exc:
        logger.warning("Ошибка при закрытии сессии бота: %s", exc)
    logger.info("Бот остановлен.")


@app.on_event("startup")
async def startup_event():
    """FastAPI startup event — инициализация и запуск long-polling в фоне."""
    await on_startup()
    # Long-polling в фоне, если не используется webhook
    if config.USE_LONG_POLLING and not config.USE_WEBHOOK:
        asyncio.create_task(_start_polling())


@app.on_event("shutdown")
async def shutdown_event():
    await on_shutdown()


async def _start_polling() -> None:
    """Запускает бесконечный цикл long-polling с обработкой ошибок."""
    logger.info("Запуск long-polling...")
    await dp.start_polling(bot, skip_updates=True)


# ---------------------------------------------------------------------------
# Прямой запуск (python main.py)
# ---------------------------------------------------------------------------
def main() -> None:
    """Запуск FastAPI-приложения через Uvicorn.

    Startup/shutdown логика (инициализация БД, webhook, long-polling)
    выполняется в событиях FastAPI startup_event / shutdown_event.
    """
    logger.info("Запуск Uvicorn на %s:%s", config.APP_HOST, config.APP_PORT)
    server = Server(
        Config(
            app="main:app",
            host=config.APP_HOST,
            port=config.APP_PORT,
            log_level="info",
            reload=False,
            workers=1,
        )
    )
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
"""Точка входа: FastAPI-приложение с webhook или long-polling + Uvicorn.

Используется для деплоя на Railway 24/7.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import Update
from fastapi import FastAPI, Request, Response
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
    # Ограничиваем все запросы к Telegram Bot API по времени,
    # чтобы при недоступности сети сервер не зависал.
    session=AiohttpSession(timeout=aiohttp.ClientTimeout(total=20)),
)
dp = Dispatcher()
dp.include_router(router)

# Задача long-polling (хранится для корректной остановки)
_polling_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Жизненный цикл приложения
# ---------------------------------------------------------------------------
async def on_startup() -> None:
    """Действия при старте бота и приложения."""
    await db.init_db()
    logger.info("База данных инициализирована.")

    try:
        if config.USE_WEBHOOK and config.PUBLIC_URL:
            webhook_url = f"{config.PUBLIC_URL}{config.WEBHOOK_PATH}"
            await asyncio.wait_for(
                bot.set_webhook(
                    url=webhook_url,
                    secret_token=config.WEBHOOK_SECRET or None,
                    allowed_updates=dp.resolve_used_update_types(),
                ),
                timeout=15,
            )
            logger.info("Webhook установлен: %s", webhook_url)
        else:
            # Удаляем webhook, если он был, и используем long-polling
            await asyncio.wait_for(bot.delete_webhook(), timeout=15)
            logger.info("Webhook удалён, используем long-polling.")
    except Exception as exc:
        # Если Telegram пока недоступен — не роняем сервер;
        # long-polling/webhook попробует переподключиться.
        logger.warning("Не удалось настроить webhook: %s", exc)


async def on_shutdown() -> None:
    """Действия при остановке."""
    if _polling_task is not None:
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
    try:
        await bot.session.close()
    except Exception as exc:
        logger.warning("Ошибка при закрытии сессии бота: %s", exc)
    logger.info("Бот остановлен.")


async def _start_polling() -> None:
    """Long-polling с автоперезапуском при сетевых сбоях."""
    logger.info("Запуск long-polling...")
    while True:
        try:
            await dp.start_polling(bot, handle_signals=False)
            break  # нормальное завершение
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Сбой long-polling: %s. Перезапуск через 5 сек...", exc)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: инициализация и запуск long-polling в фоне."""
    global _polling_task
    await on_startup()
    if config.USE_LONG_POLLING and not config.USE_WEBHOOK:
        _polling_task = asyncio.create_task(_start_polling())
    yield
    await on_shutdown()


# FastAPI-приложение (запускается через Uvicorn)
app = FastAPI(
    title="Telegram Video Downloader Bot",
    version="1.0.0",
    description="FastAPI + aiogram 3.x — бесплатный бот для скачивания видео",
    lifespan=lifespan,
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
# Прямой запуск (python main.py)
# ---------------------------------------------------------------------------
def main() -> None:
    """Запуск FastAPI-приложения через Uvicorn.

    Передаём объект app напрямую (а не строку "main:app"), чтобы избежать
    повторного импорта модуля и дублирования Dispatcher/Router.
    """
    logger.info("Запуск Uvicorn на %s:%s", config.APP_HOST, config.APP_PORT)
    server = Server(
        Config(
            app=app,
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
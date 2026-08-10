"""Обработчики команд, сообщений и callback-запросов бота."""
import asyncio
import logging
import os
import time

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database as db
from downloader import (
    DownloadError,
    VideoDownloader,
    VideoUnavailableError,
    detect_platform,
    upload_to_transfer_sh,
)
from keyboards import ad_keyboard, download_keyboard, help_keyboard, support_keyboard

logger = logging.getLogger(__name__)

router = Router()
downloader = VideoDownloader()

# Лимит Telegram Bot API для отправки файлов (без покупного сервера)
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 МБ


# -------------------- FSM: форма обратной связи --------------------
class FeedbackForm(StatesGroup):
    waiting_for_message = State()


# Множества активных загрузок по пользователям (чтобы не плодить дубли)
_active_downloads: dict[int, set[int]] = {}


# -------------------- Вспомогательные функции --------------------
async def _needs_ad(user_id: int) -> bool:
    """Нужно ли показать рекламу с учётом AD_COOLDOWN_HOURS (0 = всегда)."""
    if config.AD_COOLDOWN_HOURS <= 0:
        return True
    last = await db.last_ad_view(user_id)
    if last is None:
        return True
    return (time.time() - last) >= config.AD_COOLDOWN_HOURS * 3600


async def _send_download_result(message: types.Message, filepath, title: str):
    """Отправляет файл пользователю либо ссылку на скачивание."""
    size = os.path.getsize(filepath)
    caption = f"✅ <b>Готово!</b>\n\n📹 {title}"

    # 1) Файл помещается в лимит Telegram — отправляем напрямую
    if size <= TELEGRAM_FILE_LIMIT:
        try:
            with open(filepath, "rb") as f:
                await message.answer_video(
                    video=types.BufferedInputFile(
                        f.read(), filename=os.path.basename(filepath)
                    ),
                    caption=caption,
                    supports_streaming=True,
                )
            return
        except Exception as exc:
            logger.warning("Не удалось отправить файлом, пробуем файлообменник: %s", exc)

    # 2) Файл больше лимита Telegram, но в пределах MAX_FILE_SIZE — файлообменник
    if size <= config.MAX_FILE_SIZE:
        try:
            await message.answer("⏫ Файл большой, загружаю на файлообменник…")
            link = await upload_to_transfer_sh(filepath)
            await message.answer(
                f"📹 <b>{title}</b>\n\n"
                f"Файл доступен по ссылке:\n{link}\n\n"
                f"📦 Размер: {size / 1024 / 1024:.1f} МБ\n"
                f"⚠️ Ссылка действует ограниченное время.",
            )
            return
        except DownloadError as exc:
            await message.answer(f"❌ Не удалось загрузить на файлообменник: {exc}")

    # 3) Файл больше всех лимитов
    await message.answer(
        f"📹 <b>{title}</b>\n\n"
        f"Размер видео: <b>{size / 1024 / 1024:.1f} МБ</b>\n\n"
        "Видео превышает лимиты Telegram и файлообменника. "
        "Скачайте его через сторонние сервисы.",
    )


async def _process_download(
    message: types.Message,
    url: str,
    pending_id: int,
):
    """Фоновая задача: проверка, загрузка, отправка и очистка."""
    user_id = message.from_user.id
    if user_id not in _active_downloads:
        _active_downloads[user_id] = set()
    _active_downloads[user_id].add(pending_id)

    download_id = None
    try:
        # Получаем информацию о видео
        info = await downloader.get_info(url)
        title = info.title

        # Логируем начало загрузки
        download_id = await db.log_download(
            user_id=user_id,
            url=url,
            platform=info.platform,
            title=title,
            filesize=info.filesize,
        )

        progress_msg = await message.answer("⏳ Идёт загрузка… Это займёт некоторое время.")

        async def progress_cb(percent: float):
            try:
                await progress_msg.edit_text(f"⏳ Загрузка… {percent:.0f}%")
            except Exception:
                pass  # сообщение могло быть изменено или удалено

        filepath = await downloader.download(url, info.id, title, progress_cb=progress_cb)
        await db.update_download(download_id, "done", filesize=os.path.getsize(filepath))

        try:
            await progress_msg.delete()
        except Exception:
            pass

        await _send_download_result(message, filepath, title)

        try:
            filepath.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Не удалось удалить файл %s: %s", filepath, exc)

    except Exception as exc:
        logger.exception("Ошибка при загрузке видео: %s", exc)
        await message.answer(f"❌ Ошибка при загрузке:\n\n{exc}")
        if download_id:
            try:
                await db.update_download(download_id, "error", error=str(exc))
            except Exception:
                pass
    finally:
        active = _active_downloads.get(user_id, set())
        active.discard(pending_id)
        if not active:
            _active_downloads.pop(user_id, None)


# -------------------- Команда /start --------------------
@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await db.register_user(message.from_user.id, message.from_user.username)
    welcome = (
        "👋 <b>Привет! Я — бот для скачивания видео.</b>\n\n"
        "Я умею скачивать видео с <b>YouTube, TikTok, Instagram и VK</b>.\n\n"
        "📌 <b>Как пользоваться:</b>\n"
        "1. Отправь мне ссылку на видео.\n"
        "2. Я проверю, доступно ли оно.\n"
        "3. Посмотри рекламу (так я остаюсь бесплатным).\n"
        "4. Нажми «Скачать» и получи видео.\n\n"
        "Просто вставь ссылку и отправь!"
    )
    await message.answer(welcome, reply_markup=help_keyboard())


# -------------------- Callback: помощь / поддержка --------------------
@router.callback_query(F.data == "help")
async def cb_help(callback: types.CallbackQuery):
    text = (
        "❓ <b>Как пользоваться ботом</b>\n\n"
        "1. Отправьте ссылку на видео (YouTube, TikTok, Instagram, VK).\n"
        "2. Дождитесь проверки доступности.\n"
        "3. Посмотрите рекламу — она помогает боту оставаться бесплатным.\n"
        "4. Нажмите «📥 Скачать видео».\n"
        "5. Дождитесь загрузки — видео придёт файлом или ссылкой.\n\n"
        "⚠️ <b>Ограничения:</b>\n"
        "• Максимальный размер файла: 2 ГБ\n"
        "• Только публичные видео\n"
        "• Загрузка больших файлов может занять несколько минут"
    )
    await callback.message.edit_text(text, reply_markup=help_keyboard())
    await callback.answer()


@router.callback_query(F.data == "support")
async def cb_support(callback: types.CallbackQuery):
    await callback.message.edit_text(
        f"{config.SUPPORT_TEXT}\n\n{config.SUPPORT_URL}",
        reply_markup=support_keyboard(),
    )
    await callback.answer()


# -------------------- Команда /stats (только для админов) --------------------
@router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    s = await db.stats()
    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👤 Пользователей: {s['users']}\n"
        f"📥 Скачиваний (всего): {s['downloads']}\n"
        f"📅 За сегодня: {s['today']}\n"
        f"✅ Успешных: {s['done']}\n"
        f"❌ Ошибок: {s['errors']}\n"
        f"👁 Показов рекламы: {s['ad_views']}"
    )
    await message.answer(text)


# -------------------- Команда /feedback (FSM) --------------------
@router.message(Command("feedback"))
async def cmd_feedback(message: types.Message, state: FSMContext):
    await state.set_state(FeedbackForm.waiting_for_message)
    await message.answer(
        "📝 Напишите ваше сообщение, пожелание или жалобу.\n"
        "Отправьте /cancel, чтобы отменить."
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    current = await state.get_state()
    if current is None:
        await message.answer("Нет активного действия.")
        return
    await state.clear()
    await message.answer("✅ Действие отменено.")


@router.message(FeedbackForm.waiting_for_message)
async def process_feedback(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
        return
    await db.save_feedback(message.from_user.id, message.text)
    await state.clear()
    await message.answer("✅ Спасибо за отзыв! Он будет передан разработчикам.")


# -------------------- Обработка ссылок --------------------
@router.message(F.text)
async def handle_url(message: types.Message):
    url = message.text.strip()
    user_id = message.from_user.id

    # Команды обрабатываются другими хендлерами
    if url.startswith("/"):
        return

    # Определяем платформу
    platform = detect_platform(url)
    if not platform:
        await message.answer(
            "❌ Я не поддерживаю эту платформу.\n\n"
            "Пожалуйста, отправьте ссылку на видео с "
            "YouTube, TikTok, Instagram или VK."
        )
        return

    # Проверяем доступность видео через yt-dlp
    status_msg = await message.answer("🔍 Проверяю ссылку…")
    try:
        info = await downloader.get_info(url)
    except VideoUnavailableError as exc:
        await status_msg.edit_text(f"❌ Видео недоступно.\n\n{exc}")
        return
    except DownloadError as exc:
        await status_msg.edit_text(f"❌ Ошибка при проверке ссылки.\n\n{exc}")
        return
    except Exception:
        logger.exception("Неожиданная ошибка при проверке видео: %s", url)
        await status_msg.edit_text("❌ Произошла неизвестная ошибка. Попробуйте позже.")
        return

    # Удаляем сообщение о проверке
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Создаём pending-загрузку (кнопка «Скачать» ссылается на неё по id)
    pending_id = await db.create_pending(user_id, url, platform)

    # Нужно ли показать рекламу (AD_COOLDOWN_HOURS в .env)
    need_ad = await _needs_ad(user_id)

    base_text = (
        f"📹 <b>{info.title}</b>\n\n"
        f"📍 Платформа: {platform}\n"
        f"⏱ Длительность: {int(info.duration) // 60}:{int(info.duration) % 60:02d}\n"
        f"🎞 Качество: максимальное доступное\n"
        f"📦 Размер: {info.filesize / 1024 / 1024:.1f} МБ\n\n"
    )

    if need_ad:
        await db.record_ad_view(user_id)
        # Рекламное сообщение с текстом AD_TEXT и кнопкой «Перейти к рекламодателю»
        await message.answer(
            f"{config.AD_TEXT}\n\n"
            f"🔗 <a href=\"{config.AD_LINK}\">{config.AD_LINK}</a>",
            reply_markup=ad_keyboard(),
        )
        await message.answer(
            f"{base_text}"
            "Реклама просмотрена ✅\n"
            "👇 Нажмите кнопку, чтобы скачать видео:",
            reply_markup=download_keyboard(pending_id),
        )
    else:
        await message.answer(
            f"{base_text}"
            "👇 Нажмите кнопку, чтобы скачать видео:",
            reply_markup=download_keyboard(pending_id),
        )


# -------------------- Callback: «Скачать» --------------------
@router.callback_query(F.data.startswith("dl:"))
async def cb_download(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        pending_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Некорректные данные.", show_alert=True)
        return

    # Извлекаем данные загрузки; если их нет — кнопка устарела
    pending = await db.pop_pending(pending_id)
    if pending is None:
        await callback.answer(
            "❌ Ссылка устарела. Отправьте видео ещё раз.",
            show_alert=True,
        )
        return

    # Если у пользователя уже идёт загрузка — не начинаем дубликат
    if user_id in _active_downloads:
        await callback.answer("⏳ Загрузка уже идёт. Подождите!", show_alert=True)
        return

    await callback.answer("📥 Начинаем загрузку…")
    try:
        await callback.message.edit_text(
            "📥 Загрузка запущена. Видео придёт в этот чат, когда будет готово."
        )
    except Exception:
        pass

    # Фоновая загрузка через asyncio.subprocess
    asyncio.create_task(
        _process_download(
            callback.message,
            pending["url"],
            pending_id,
        )
    )

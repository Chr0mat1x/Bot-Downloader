"""Inline-клавиатуры бота."""
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config


def help_keyboard():
    """Кнопки на стартовом сообщении."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❓ Как пользоваться", callback_data="help")
    builder.button(text="💛 Поддержать автора", callback_data="support")
    builder.adjust(1)
    return builder.as_markup()


def download_keyboard(pending_id: int):
    """Кнопка запуска загрузки (callback)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Скачать видео", callback_data=f"dl:{pending_id}")
    return builder.as_markup()


def ad_keyboard():
    """Рекламное сообщение: текстом + кнопка перехода к рекламодателю."""
    builder = InlineKeyboardBuilder()
    builder.button(text=config.AD_BUTTON_LABEL, url=config.AD_LINK)
    builder.adjust(1)
    return builder.as_markup()


def support_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💛 Поддержать автора", url=config.SUPPORT_URL)
    builder.adjust(1)
    return builder.as_markup()

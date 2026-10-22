from urllib.parse import quote
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from config.settings import settings


def get_main_webapp_keyboard(initial_query: str = "") -> InlineKeyboardMarkup:
    """Создает инлайн-кнопку для запуска Telegram Mini App."""
    base_url = settings.WEBAPP_URL.rstrip("/")
    target_url = f"{base_url}/?q={quote(initial_query)}" if initial_query else f"{base_url}/"

    btn_text = (
        f"🔎 Открыть все в Mini App ({initial_query[:18]})"
        if initial_query
        else "🚀 Открыть OSINT Терминал"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=btn_text,
                    web_app=WebAppInfo(url=target_url),
                )
            ]
        ]
    )

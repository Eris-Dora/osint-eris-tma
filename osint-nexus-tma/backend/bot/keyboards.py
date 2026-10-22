from urllib.parse import urlencode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from config.settings import settings
from services.llm_router import AVAILABLE_MODELS, LLMRouter


def get_main_webapp_keyboard(initial_query: str | None = None) -> InlineKeyboardMarkup:
    """Главная клавиатура под сообщениями: открытие Mini App + кнопка смены ИИ-модели."""
    base_url = settings.WEBAPP_URL.rstrip("/")
    if initial_query:
        params = urlencode({"q": initial_query})
        target_url = f"{base_url}/?{params}"
    else:
        target_url = f"{base_url}/"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Открыть OSINT Терминал",
                    web_app=WebAppInfo(url=target_url),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧠 Сменить ИИ-модель (Groq / Gemini)",
                    callback_data="open_model_menu",
                )
            ],
        ]
    )


def get_model_selector_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура со списком всех моделей и галочкой ✅ напротив текущей активной."""
    current_key = LLMRouter.get_user_model_key(user_id)
    rows = []

    for key, info in AVAILABLE_MODELS.items():
        prefix = "✅ " if key == current_key else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{info['title']}",
                    callback_data=f"set_model:{key}",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)

import html
import re
from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from services.aggregator import run_full_osint_search
from services.ai_analyst import GeminiOSINTAnalyst
from services.llm_router import LLMRouter, AVAILABLE_MODELS
from .templates import WELCOME_TEXT, HELP_TEXT, format_chat_search_results
from .keyboards import get_main_webapp_keyboard, get_model_selector_keyboard

router = Router()

# Регулярное выражение, которое ловит фразы вроде "поиск по Deni Von Raide", "найди @durov", "пробей Иван Иванов"
SEARCH_INTENT_REGEX = re.compile(
    r"(?:поиск\s+по|найди\s+инфу\s+про|найди\s+про|найди|пробей|исследуй|что\s+нашел\s+поиск\s+по)\s+(.+)$",
    re.IGNORECASE,
)

CHAT_TRIGGERS = (
    "привет", "здравствуй", "кто ты", "что ты", "как дела", "помоги",
    "расскажи", "объясни", "почему", "зачем", "как найти", "что значит",
    "а кто", "а что", "а где", "а как", "подскажи", "можешь", "умеешь",
    "спасибо", "понял", "круто", "хорошо", "давай", "сделай", "проанализируй",
    "и что", "что ты"
)


def extract_search_target(text: str) -> str | None:
    """Если пользователь написал 'привет опиши что нашел поиск по Deni Von Raide', достает 'Deni Von Raide'."""
    match = SEARCH_INTENT_REGEX.search(text.strip())
    if match:
        target = match.group(1).strip(" .,!?\"'«»")
        if len(target) >= 2:
            return target
    return None


def is_conversational_message(text: str) -> bool:
    low = text.lower().strip()
    if "?" in low:
        return True
    if any(low.startswith(trigger) for trigger in CHAT_TRIGGERS):
        return True
    if len(low.split()) > 3:
        return True
    return False


@router.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        text=WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_webapp_keyboard(),
    )


@router.message(Command("model"))
async def cmd_model(message: types.Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    current_key = LLMRouter.get_user_model_key(user_id)
    current_info = AVAILABLE_MODELS[current_key]

    await message.answer(
        text=(
            f"🧠 <b>Управление ИИ-ядром</b>\n\n"
            f"Сейчас активна модель: <b>{current_info['title']}</b>\n"
            f"<i>{current_info['desc']}</i>\n\n"
            f"👇 Выберите модель ниже (переключение происходит мгновенно с сохранением памяти разговора):"
        ),
        parse_mode="HTML",
        reply_markup=get_model_selector_keyboard(user_id),
    )


@router.callback_query(F.data == "open_model_menu")
async def cb_open_model_menu(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    current_key = LLMRouter.get_user_model_key(user_id)
    current_info = AVAILABLE_MODELS[current_key]

    await callback.message.answer(
        text=(
            f"🧠 <b>Выберите активную ИИ-модель:</b>\n"
            f"Текущая: <b>{current_info['title']}</b>"
        ),
        parse_mode="HTML",
        reply_markup=get_model_selector_keyboard(user_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_model:"))
async def cb_set_model(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    model_key = callback.data.split(":", 1)[1]
    selected = LLMRouter.set_user_model(user_id, model_key)

    await callback.message.edit_text(
        text=(
            f"✅ <b>Модель успешно переключена!</b>\n\n"
            f"Активная нейросеть: <b>{selected['title']}</b>\n"
            f"<i>{selected['desc']}</i>\n\n"
            f"Можете продолжать диалог — вся история вашей беседы сохранена."
        ),
        parse_mode="HTML",
        reply_markup=get_model_selector_keyboard(user_id),
    )
    await callback.answer(f"Выбрана: {selected['title']}")


@router.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    await message.answer(
        text=(
            f"{HELP_TEXT}\n\n"
            "💬 <b>Команды ИИ-чата:</b>\n"
            "• <code>/model</code> — переключить ИИ-модель (Groq / DeepSeek / Gemini) прямо во время разговора.\n"
            "• <code>/search запрос</code> — принудительный OSINT-сканер по фразе.\n"
            "• <code>/clear</code> — очистить память диалога."
        ),
        parse_mode="HTML",
        reply_markup=get_main_webapp_keyboard(),
    )


@router.message(Command("clear"))
async def cmd_clear(message: types.Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    GeminiOSINTAnalyst.clear_memory(user_id)
    await message.answer("🧹 Память нашего диалога очищена!")


@router.message(Command("search"))
async def cmd_force_search(message: types.Message) -> None:
    raw_text = (message.text or "").replace("/search", "", 1).strip()
    if len(raw_text) < 2:
        await message.answer("🔎 Укажите запрос, например: <code>/search Deni Von Raide</code>", parse_mode="HTML")
        return
    await _run_osint_and_reply(message, raw_text)


@router.message(F.text)
async def handle_text_or_chat(message: types.Message) -> None:
    text = (message.text or "").strip()
    user_id = message.from_user.id if message.from_user else 0

    if len(text) < 2:
        await message.answer("⚠️ Напишите чуть подробнее.")
        return

    # 1. Проверяем, не просит ли пользователь внутри фразы сделать поиск ("...поиск по Deni Von Raide")
    extracted_target = extract_search_target(text)
    if extracted_target:
        await _run_osint_and_reply(message, extracted_target)
        return

    # 2. Если это обычное сообщение для диалога — общаемся через выбранную ИИ-модель
    if is_conversational_message(text):
        thinking_msg = await message.answer("💭 <i>Генерирую ответ...</i>", parse_mode="HTML")
        ai_data = await GeminiOSINTAnalyst.chat_with_user(user_id=user_id, user_message=text)
        reply_text = html.escape(ai_data["reply"])
        model_title = html.escape(ai_data["model_title"])

        await thinking_msg.edit_text(
            text=f"🤖 <b>ASTRA AI</b> <code>[{model_title}]</code>:\n\n{reply_text}",
            parse_mode="HTML",
            reply_markup=get_main_webapp_keyboard(),
        )
        return

    # 3. Короткий запрос (никнейм, ФИО до 3 слов, домен, email) — сразу запускаем полный OSINT-поиск
    await _run_osint_and_reply(message, text)


async def _run_osint_and_reply(message: types.Message, query: str) -> None:
    user_id = message.from_user.id if message.from_user else 0
    status_msg = await message.answer(
        f"⏳ <b>Сканирую открытые источники по запросу:</b> <code>{html.escape(query)}</code>...",
        parse_mode="HTML",
    )

    data = await run_full_osint_search(query=query, category_filter="all")
    report_html = format_chat_search_results(data)

    # Сохраняем и само ИИ-досье, и список найденных ссылок в память чата!
    top_links = "\n".join(
        f"- {r.get('title')} ({r.get('url')}): {r.get('snippet', '')[:100]}"
        for r in data.get("results", [])[:10]
    )
    GeminiOSINTAnalyst.save_to_memory(
        user_id,
        "Система OSINT (результаты поиска)",
        f"Запрос: {query}\nНайдено ссылок: {data.get('counts', {}).get('all', 0)}\nДосье: {data.get('ai_summary', '')}\nТоп ссылок:\n{top_links}",
    )

    await status_msg.edit_text(
        text=report_html,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_main_webapp_keyboard(initial_query=query),
    )

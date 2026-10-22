import html
from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from services.aggregator import run_full_osint_search
from services.ai_analyst import GeminiOSINTAnalyst
from .templates import WELCOME_TEXT, HELP_TEXT, format_chat_search_results
from .keyboards import get_main_webapp_keyboard

router = Router()

# Признаки того, что пользователь хочет просто пообщаться с ИИ, а не запускать парсеры
CHAT_TRIGGERS = (
    "привет", "здравствуй", "кто ты", "что ты", "как дела", "помоги",
    "расскажи", "объясни", "почему", "зачем", "как найти", "что значит",
    "а кто", "а что", "а где", "а как", "подскажи", "можешь", "умеешь",
    "спасибо", "понял", "круто", "хорошо", "давай", "сделай", "проанализируй"
)


def is_conversational_message(text: str) -> bool:
    """Определяет, пишет ли пользователь вопрос/сообщение для диалога или короткий объект для OSINT-пробива."""
    low = text.lower().strip()
    if "?" in low:
        return True
    if any(low.startswith(trigger) for trigger in CHAT_TRIGGERS):
        return True
    # Если в сообщении больше 3 слов — это почти всегда фраза для общения с ИИ
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


@router.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    await message.answer(
        text=(
            f"{HELP_TEXT}\n\n"
            "💬 <b>Режим живого ИИ-чата:</b>\n"
            "• Просто пишите мне любые вопросы (с вопросительным знаком или обычными предложениями) — я отвечу как ИИ-собеседник с доступом в Google.\n"
            "• Отправьте <code>/search ваш запрос</code>, если хотите принудительно запустить OSINT-сканер по длинной фразе.\n"
            "• Отправьте <code>/clear</code>, чтобы очистить память нашего диалога."
        ),
        parse_mode="HTML",
        reply_markup=get_main_webapp_keyboard(),
    )


@router.message(Command("clear"))
async def cmd_clear(message: types.Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    GeminiOSINTAnalyst.clear_memory(user_id)
    await message.answer("🧹 Память нашего диалога очищена! Можем начать с чистого листа.")


@router.message(Command("search"))
async def cmd_force_search(message: types.Message) -> None:
    """Принудительный запуск OSINT-сканера через /search <запрос>."""
    raw_text = (message.text or "").replace("/search", "", 1).strip()
    if len(raw_text) < 2:
        await message.answer("🔎 Укажите запрос после команды, например: <code>/search @durov</code>", parse_mode="HTML")
        return
    await _run_osint_and_reply(message, raw_text)


@router.message(F.text)
async def handle_text_or_chat(message: types.Message) -> None:
    text = (message.text or "").strip()
    user_id = message.from_user.id if message.from_user else 0

    if len(text) < 2:
        await message.answer("⚠️ Напишите чуть подробнее.")
        return

    # 1. Если это разговорная фраза или вопрос — общаемся через Gemini AI с памятью
    if is_conversational_message(text):
        thinking_msg = await message.answer("💭 <i>ASTRA AI думает...</i>", parse_mode="HTML")
        ai_reply = await GeminiOSINTAnalyst.chat_with_user(user_id=user_id, user_message=text)
        await thinking_msg.edit_text(
            text=f"🤖 <b>ASTRA AI:</b>\n\n{html.escape(ai_reply)}",
            parse_mode="HTML",
            reply_markup=get_main_webapp_keyboard(),
        )
        return

    # 2. Иначе (никнейм, ФИО, домен, email, телефон) — запускаем полный OSINT-пробив
    await _run_osint_and_reply(message, text)


async def _run_osint_and_reply(message: types.Message, query: str) -> None:
    user_id = message.from_user.id if message.from_user else 0
    status_msg = await message.answer(
        f"⏳ <b>Сканирую открытые источники по запросу:</b> <code>{html.escape(query)}</code>...",
        parse_mode="HTML",
    )

    data = await run_full_osint_search(query=query, category_filter="all")
    report_html = format_chat_search_results(data)

    # Сохраняем результаты поиска в память диалога, чтобы пользователь мог задавать вопросы по ним!
    if data.get("ai_summary"):
        GeminiOSINTAnalyst.save_to_memory(
            user_id,
            "Система OSINT (результат последнего поиска)",
            f"Объект: {query}\nДосье: {data['ai_summary']}",
        )

    await status_msg.edit_text(
        text=report_html,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_main_webapp_keyboard(initial_query=query),
    )

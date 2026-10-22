import html
from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from services.aggregator import run_full_osint_search
from .templates import WELCOME_TEXT, HELP_TEXT, format_chat_search_results
from .keyboards import get_main_webapp_keyboard

router = Router()


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
        text=HELP_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_webapp_keyboard(),
    )


@router.message(F.text)
async def handle_direct_search(message: types.Message) -> None:
    query = (message.text or "").strip()
    if len(query) < 2:
        await message.answer("⚠️ Слишком короткий запрос (минимум 2 символа).")
        return

    status_msg = await message.answer(
        f"⏳ <b>Сканирую открытые источники по запросу:</b> <code>{html.escape(query)}</code>...",
        parse_mode="HTML",
    )

    data = await run_full_osint_search(query=query, category_filter="all")
    report_html = format_chat_search_results(data)

    await status_msg.edit_text(
        text=report_html,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_main_webapp_keyboard(initial_query=query),
    )

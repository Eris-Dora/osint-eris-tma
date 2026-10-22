import html
from typing import Dict, Any


WELCOME_TEXT = (
    "🛡 <b>ASTRA er1daV1 // AI Deep Search</b>\n\n"
    "Добро пожаловать в автономную систему поиска упоминаний и цифрового следа с поддержкой <b>Gemini AI + Google Search Grounding</b>.\n\n"
    "<b>Возможности:</b>\n"
    "• 🧠 <b>ИИ-Досье (Google Live):</b> автоматический анализ объекта и прямой поиск в Google.\n"
    "• 💬 <b>Соцсети и Профили:</b> Instagram, TikTok, Telegram, VK, YouTube, X, GitHub, Reddit, Steam.\n"
    "• 📚 <b>Форумы и Архивы:</b> Wikipedia, Habr, StackOverflow, Wayback Machine, PDF/DOCX.\n\n"
    "👇 Нажмите кнопку ниже, чтобы открыть <b>Mini App дашборд</b>, или отправьте запрос сообщением в чат."
)

HELP_TEXT = (
    "ℹ️ <b>Справка по использованию ASTRA OSINT</b>\n\n"
    "1. <b>Через Mini App:</b> нажмите кнопку ниже для работы с карточками, вкладками и ИИ-досье.\n"
    "2. <b>Прямо в чате:</b> отправьте никнейм (<code>@durov</code>), ФИО, домен или фразу — бот соберет ИИ-сводку и топ ссылок."
)


def format_chat_search_results(data: Dict[str, Any]) -> str:
    """Форматирует ИИ-досье и результаты поиска для отправки в чат Telegram."""
    query = html.escape(data.get("query", ""))
    counts = data.get("counts", {})
    elapsed = data.get("elapsed_seconds", 0)
    ai_summary = html.escape(data.get("ai_summary", ""))
    results = data.get("results", [])

    if not results and not ai_summary:
        return (
            f"🔍 По запросу <code>{query}</code> ничего не найдено.\n"
            f"Попробуйте изменить формулировку или воспользоваться поиском в Mini App."
        )

    lines = [
        f"✅ <b>Отчет по запросу:</b> <code>{query}</code>",
        f"⏱ <i>Время: {elapsed} сек. | Найдено ссылок: {counts.get('all', 0)}</i>\n",
    ]

    if ai_summary:
        lines.append(f"🧠 <b>ИИ-Досье (Gemini + Google):</b>\n{ai_summary[:1200]}\n")

    lines.append(
        f"📊 <b>Источники:</b> Упоминания: {counts.get('mentions', 0)} · Соцсети: {counts.get('socials', 0)} · Форумы: {counts.get('forums', 0)}\n"
    )

    for idx, item in enumerate(results[:6], start=1):
        title = html.escape(item.get("title", "Без названия")[:85])
        url = item.get("url", "")
        source = html.escape(item.get("source", "Web"))
        lines.append(f"{idx}. <a href='{url}'><b>{title}</b></a> <code>[{source}]</code>")

    if len(results) > 6:
        lines.append(f"\n➕ <i>Еще {len(results) - 6} результатов доступно внутри Mini App.</i>")

    return "\n".join(lines)

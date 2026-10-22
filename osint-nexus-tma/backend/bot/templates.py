import html
from typing import Dict, Any


WELCOME_TEXT = (
    "🛡 <b> er1daV1 // Deep Search Terminal</b>\n\n"
    "Добро пожаловать в автономную систему поиска упоминаний и цифрового следа по открытым источникам.\n\n"
    "<b>Возможности:</b>\n"
    "• 🌐 <b>Упоминания и СМИ:</b> точный поиск текста, ФИО, email, телефонов, доменов и веб-архивов.\n"
    "• 💬 <b>Соцсети и Профили:</b> проверка никнеймов и дорки по Telegram, VK, Instagram, X, LinkedIn.\n"
    "• 📚 <b>Форумы и Документы:</b> Reddit, HackerNews, Habr, GitHub, PDF/XLSX/DOCX.\n\n"
    "👇 Нажмите кнопку ниже, чтобы открыть <b>Mini App дашборд</b>, или просто отправьте поисковый запрос сообщением в этот чат."
)

HELP_TEXT = (
    "ℹ️ <b>Справка по использованию er1daV1 </b>\n\n"
    "1. <b>Через Mini App (рекомендуется):</b> нажмите кнопку <i>«🚀 Открыть OSINT Терминал»</i> для работы с удобными вкладками, фильтрами и карточками.\n"
    "2. <b>Прямо в чате:</b> отправьте любое слово, никнейм (например, <code>@durov</code>), домен или фразу — бот проведет экспресс-сканирование и пришлет топ результатов."
)


def format_chat_search_results(data: Dict[str, Any]) -> str:
    """Форматирует результаты поиска для отправки обычным сообщением в чат Telegram."""
    query = html.escape(data.get("query", ""))
    counts = data.get("counts", {})
    elapsed = data.get("elapsed_seconds", 0)
    results = data.get("results", [])

    if not results:
        return (
            f"🔍 По запросу <code>{query}</code> ничего не найдено.\n"
            f"Попробуйте изменить формулировку или воспользоваться расширенным поиском в Mini App."
        )

    lines = [
        f"✅ <b>Отчет по запросу:</b> <code>{query}</code>",
        f"⏱ <i>Время: {elapsed} сек. | Всего найдено: {counts.get('all', 0)}</i>",
        f"📊 Упоминания: <b>{counts.get('mentions', 0)}</b> · Соцсети: <b>{counts.get('socials', 0)}</b> · Форумы/Код: <b>{counts.get('forums', 0)}</b>\n",
    ]

    for idx, item in enumerate(results[:8], start=1):
        title = html.escape(item.get("title", "Без названия")[:90])
        url = item.get("url", "")
        source = html.escape(item.get("source", "Web"))
        snippet = html.escape(item.get("snippet", "")[:140])
        lines.append(
            f"{idx}. <a href='{url}'><b>{title}</b></a>\n"
            f"   <code>[{source}]</code> <i>{snippet}...</i>"
        )

    if len(results) > 8:
        lines.append(
            f"\n➕ <i>Еще {len(results) - 8} результатов доступно внутри Mini App.</i>"
        )

    return "\n".join(lines)

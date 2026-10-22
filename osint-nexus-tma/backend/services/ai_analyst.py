import logging
from typing import Dict, Any, List
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

# Оперативная память диалогов по user_id (хранит последние 12 реплик каждого пользователя)
CHAT_MEMORY: Dict[int, List[Dict[str, str]]] = {}


class GeminiOSINTAnalyst:
    """
    Асинхронный модуль ИИ-разведки и живого общения на базе Gemini 2.5 Flash
    с поддержкой выхода в интернет (Google Search Grounding) и памяти диалога.
    """

    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    @classmethod
    def save_to_memory(cls, user_id: int, role: str, text: str) -> None:
        if user_id not in CHAT_MEMORY:
            CHAT_MEMORY[user_id] = []
        CHAT_MEMORY[user_id].append({"role": role, "text": text[:1500]})
        # Держим последние 12 сообщений, чтобы не перегружать контекст
        if len(CHAT_MEMORY[user_id]) > 12:
            CHAT_MEMORY[user_id] = CHAT_MEMORY[user_id][-12:]

    @classmethod
    def clear_memory(cls, user_id: int) -> None:
        CHAT_MEMORY.pop(user_id, None)

    @classmethod
    async def chat_with_user(cls, user_id: int, user_message: str) -> str:
        """Ведет живой диалог с пользователем в чате Telegram с доступом в Google."""
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            return (
                "⚠️ Ключ <code>GEMINI_API_KEY</code> еще не добавлен в настройки Render (Environment).\n"
                "Добавьте его, чтобы я мог общаться и искать информацию через ИИ!"
            )

        cls.save_to_memory(user_id, "Пользователь", user_message)

        history_lines = [
            f"{msg['role']}: {msg['text']}" for msg in CHAT_MEMORY.get(user_id, [])
        ]
        conversation_context = "\n\n".join(history_lines)

        system_prompt = (
            "Ты — ASTRA OSINT AI, умный, дружелюбный и профессиональный кибер-аналитик и ассистент в Telegram. "
            "Ты умеешь общаться на любые темы, отвечать на вопросы по прошлым результатам поиска, "
            "помогать с OSINT-разведкой и при необходимости искать свежие факты через Google. "
            "Отвечай четко, живо, по делу, на русском языке. Не используй сложную Markdown-разметку со звездочками, "
            "пиши чистым текстом с буллитами (•) и эмодзи.\n\n"
            f"История вашего диалога:\n{conversation_context}\n\n"
            "Ответь на последнее сообщение пользователя:"
        )

        payload = {
            "contents": [{"parts": [{"text": system_prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.5,
                "maxOutputTokens": 900,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(f"{cls.API_URL}?key={api_key}", json=payload)

                if resp.status_code != 200:
                    payload.pop("tools", None)
                    resp = await client.post(f"{cls.API_URL}?key={api_key}", json=payload)

                if resp.status_code != 200:
                    logger.warning(f"Gemini Chat HTTP {resp.status_code}: {resp.text[:200]}")
                    return "⚠️ Не удалось получить ответ от Gemini API. Проверьте правильность ключа GEMINI_API_KEY в Render."

                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return "🤔 Нейросеть не смогла сформулировать ответ. Попробуйте перефразировать."

                parts = candidates[0].get("content", {}).get("parts", [])
                reply_text = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()

                if reply_text:
                    cls.save_to_memory(user_id, "ASTRA AI", reply_text)
                    return reply_text
                return "🤔 Получен пустой ответ от модели."
        except Exception as exc:
            logger.warning(f"Ошибка в chat_with_user: {exc}")
            return f"⚠️ Ошибка связи с ИИ-модулем: {exc}"

    @classmethod
    async def analyze_and_ground(
        cls, query: str, existing_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            return {"ai_summary": "", "grounded_results": []}

        context_lines = []
        for idx, item in enumerate(existing_results[:12], 1):
            context_lines.append(
                f"{idx}. [{item.get('source', 'Web')}] {item.get('title', '')} — {item.get('url', '')} ({item.get('snippet', '')[:120]})"
            )
        context_block = "\n".join(context_lines) if context_lines else "Предварительных ссылок нет."

        prompt = (
            f"Ты — профессиональный OSINT-аналитик. Исследуй объект/запрос: «{query}».\n"
            f"Используй поиск Google, чтобы найти актуальную информацию: профили в соцсетях "
            f"(Instagram, Telegram, VK, TikTok, X, YouTube, GitHub), упоминания в СМИ, форумах, биографию или доменную информацию.\n\n"
            f"Уже найденные системой ссылки:\n{context_block}\n\n"
            f"Напиши краткое, четкое и структурированное OSINT-досье на русском языке (4-6 пунктов с буллитами •):\n"
            f"• Кто или что это (основная суть / род деятельности / описание объекта).\n"
            f"• Обнаруженные соцсети, аккаунты и никнеймы.\n"
            f"• Ключевые упоминания, проекты, связанные ресурсы или факты.\n"
            f"Пиши без воды и без вводных фраз."
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 700,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=18.0) as client:
                resp = await client.post(f"{cls.API_URL}?key={api_key}", json=payload)

                if resp.status_code != 200:
                    payload.pop("tools", None)
                    resp = await client.post(f"{cls.API_URL}?key={api_key}", json=payload)

                if resp.status_code != 200:
                    return {"ai_summary": "", "grounded_results": []}

                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return {"ai_summary": "", "grounded_results": []}

                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                ai_summary = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()

                grounded_results: List[Dict[str, Any]] = []
                grounding_meta = candidate.get("groundingMetadata", {})
                chunks = grounding_meta.get("groundingChunks", [])

                for chunk in chunks:
                    web = chunk.get("web", {})
                    uri = web.get("uri", "")
                    title = web.get("title", "Google Search Result")
                    if uri:
                        cat = "mentions"
                        u_low = uri.lower()
                        if any(s in u_low for s in ("instagram.com", "t.me", "vk.com", "tiktok.com", "x.com", "twitter.com", "youtube.com", "linkedin.com")):
                            cat = "socials"
                        elif any(f in u_low for f in ("habr.com", "reddit.com", "github.com", "pikabu.ru", "vc.ru", "medium.com")):
                            cat = "forums"

                        grounded_results.append(
                            {
                                "title": f"🌐 {title}",
                                "url": uri,
                                "snippet": f"Найдено нейросетью Gemini напрямую через живой поиск Google по запросу «{query}».",
                                "source": "Google AI Grounding",
                                "category": cat,
                                "date": "Live",
                            }
                        )

                return {
                    "ai_summary": ai_summary,
                    "grounded_results": grounded_results,
                }
        except Exception as exc:
            logger.warning(f"Ошибка GeminiOSINTAnalyst: {exc}")
            return {"ai_summary": "", "grounded_results": []}

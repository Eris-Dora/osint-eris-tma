import logging
from typing import Dict, Any, List
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

# Оперативная память диалогов по user_id
CHAT_MEMORY: Dict[int, List[Dict[str, str]]] = {}


class GeminiOSINTAnalyst:
    """
    Универсальный ИИ-модуль:
    1) Поддерживает ключи AQ... (Google Cloud Vertex AI Express)
    2) Поддерживает ключи AIza... (Google AI Studio Gemini)
    3) Поддерживает ключи gsk_... (Бесплатный Groq Cloud API)
    """

    AISTUDIO_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    VERTEX_URL = "https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-flash:generateContent"
    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

    @classmethod
    def save_to_memory(cls, user_id: int, role: str, text: str) -> None:
        if user_id not in CHAT_MEMORY:
            CHAT_MEMORY[user_id] = []
        CHAT_MEMORY[user_id].append({"role": role, "text": text[:1500]})
        if len(CHAT_MEMORY[user_id]) > 12:
            CHAT_MEMORY[user_id] = CHAT_MEMORY[user_id][-12:]

    @classmethod
    def clear_memory(cls, user_id: int) -> None:
        CHAT_MEMORY.pop(user_id, None)

    @classmethod
    async def _call_llm(cls, prompt: str, use_search: bool = True, temp: float = 0.4) -> Dict[str, Any]:
        """Универсальный маршрутизатор запросов к ИИ (AQ... / AIza... / gsk_...)."""
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            return {"text": "", "grounded": [], "error": "Ключ GEMINI_API_KEY пуст в настройках Render."}

        # ВАРИАНТ А: Если пользователь вставил бесплатный ключ от Groq (gsk_...)
        if api_key.startswith("gsk_"):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        cls.GROQ_URL,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temp,
                            "max_tokens": 900,
                        },
                    )
                    if resp.status_code == 200:
                        text = resp.json()["choices"][0]["message"]["content"].strip()
                        return {"text": text, "grounded": [], "error": ""}
                    return {"text": "", "grounded": [], "error": f"Groq HTTP {resp.status_code}: {resp.text[:150]}"}
            except Exception as exc:
                return {"text": "", "grounded": [], "error": str(exc)}

        # ВАРИАНТ Б: Ключ от Google (AQ... для Vertex AI или AIza... для AI Studio)
        base_url = cls.VERTEX_URL if api_key.startswith("AQ.") else cls.AISTUDIO_URL

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temp,
                "maxOutputTokens": 850,
            },
        }
        if use_search:
            payload["tools"] = [{"google_search": {}}]

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                # 1. Пробуем основной эндпоинт с google_search
                resp = await client.post(f"{base_url}?key={api_key}", json=payload)

                # 2. Если с google_search не прошло, пробуем без tools
                if resp.status_code != 200 and "tools" in payload:
                    payload.pop("tools", None)
                    resp = await client.post(f"{base_url}?key={api_key}", json=payload)

                # 3. Если ключ AQ... вдруг требует AIStudio URL (или наоборот), пробуем альтернативный URL
                if resp.status_code != 200:
                    alt_url = cls.AISTUDIO_URL if base_url == cls.VERTEX_URL else cls.VERTEX_URL
                    resp = await client.post(f"{alt_url}?key={api_key}", json=payload)

                if resp.status_code != 200:
                    err_detail = resp.text[:220]
                    logger.warning(f"Google AI Error {resp.status_code}: {err_detail}")
                    return {"text": "", "grounded": [], "error": f"Код {resp.status_code}: {err_detail}"}

                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return {"text": "", "grounded": [], "error": "Пустой список кандидатов от модели."}

                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                reply_text = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()

                grounded_results: List[Dict[str, Any]] = []
                grounding_meta = candidate.get("groundingMetadata", {})
                for chunk in grounding_meta.get("groundingChunks", []):
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
                                "snippet": "Найдено нейросетью напрямую через живой поиск Google.",
                                "source": "Google AI Grounding",
                                "category": cat,
                                "date": "Live",
                            }
                        )

                return {"text": reply_text, "grounded": grounded_results, "error": ""}
        except Exception as exc:
            logger.warning(f"Ошибка обращения к LLM: {exc}")
            return {"text": "", "grounded": [], "error": str(exc)}

    @classmethod
    async def chat_with_user(cls, user_id: int, user_message: str) -> str:
        """Ведет живой диалог с пользователем в чате Telegram."""
        cls.save_to_memory(user_id, "Пользователь", user_message)

        history_lines = [f"{msg['role']}: {msg['text']}" for msg in CHAT_MEMORY.get(user_id, [])]
        conversation_context = "\n\n".join(history_lines)

        system_prompt = (
            "Ты — ASTRA OSINT AI, умный, дружелюбный и профессиональный кибер-аналитик и ассистент в Telegram. "
            "Ты умеешь общаться на любые темы, отвечать на вопросы по прошлым результатам поиска и помогать с OSINT-разведкой. "
            "Отвечай четко, живо, на русском языке. Не используй сложную разметку со звездочками, пиши чистым текстом с буллитами (•) и эмодзи.\n\n"
            f"История вашего диалога:\n{conversation_context}\n\n"
            "Ответь на последнее сообщение пользователя:"
        )

        res = await cls._call_llm(system_prompt, use_search=True, temp=0.5)
        if res["text"]:
            cls.save_to_memory(user_id, "ASTRA AI", res["text"])
            return res["text"]

        return f"⚠️ Ответ от API не получен.\nДетали от сервера: {res['error']}"

    @classmethod
    async def analyze_and_ground(
        cls, query: str, existing_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        context_lines = []
        for idx, item in enumerate(existing_results[:12], 1):
            context_lines.append(
                f"{idx}. [{item.get('source', 'Web')}] {item.get('title', '')} — {item.get('url', '')} ({item.get('snippet', '')[:120]})"
            )
        context_block = "\n".join(context_lines) if context_lines else "Предварительных ссылок нет."

        prompt = (
            f"Ты — профессиональный OSINT-аналитик. Исследуй объект/запрос: «{query}».\n"
            f"Найди актуальную информацию: профили в соцсетях (Instagram, Telegram, VK, TikTok, X, YouTube, GitHub), "
            f"упоминания в СМИ, форумах, биографию или доменную информацию.\n\n"
            f"Уже найденные системой ссылки:\n{context_block}\n\n"
            f"Напиши краткое, четкое и структурированное OSINT-досье на русском языке (4-6 пунктов с буллитами •):\n"
            f"• Кто или что это (основная суть / род деятельности / описание объекта).\n"
            f"• Обнаруженные соцсети, аккаунты и никнеймы.\n"
            f"• Ключевые упоминания, проекты, связанные ресурсы или факты.\n"
            f"Пиши без воды и без вводных фраз."
        )

        res = await cls._call_llm(prompt, use_search=True, temp=0.2)
        return {
            "ai_summary": res["text"],
            "grounded_results": res["grounded"],
        }

import logging
from typing import Dict, Any, List
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

# Оперативная память диалогов по user_id
CHAT_MEMORY: Dict[int, List[Dict[str, str]]] = {}


class GeminiOSINTAnalyst:
    """
    Автоматически запрашивает у Google список доступных моделей (ListModels)
    и выбирает рабочую модель без жесткой привязки к одному URL.
    """

    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    _working_endpoint: str | None = None

    CANDIDATE_MODELS = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash-latest",
    ]

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
    async def _discover_models(cls, client: httpx.AsyncClient, api_key: str) -> List[str]:
        """Спрашивает у самого сервера Google, какие модели доступны для этого ключа."""
        discovered: List[str] = []
        for ver in ("v1beta", "v1"):
            try:
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/{ver}/models?key={api_key}"
                )
                if resp.status_code == 200:
                    for m in resp.json().get("models", []):
                        methods = m.get("supportedGenerationMethods", [])
                        name = m.get("name", "")
                        if "generateContent" in methods and "gemini" in name.lower():
                            clean = name.replace("models/", "")
                            if clean not in discovered:
                                discovered.append(clean)
                    if discovered:
                        discovered.sort(key=lambda x: (0 if "flash" in x else 1, x))
                        return discovered
            except Exception:
                pass
        return discovered

    @classmethod
    def _build_endpoints(cls, model_name: str, api_key: str) -> List[str]:
        endpoints = [
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}",
            f"https://generativelanguage.googleapis.com/v1/models/{model_name}:generateContent?key={api_key}",
            f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model_name}:generateContent?key={api_key}",
        ]
        if api_key.startswith("AQ."):
            return [endpoints[2], endpoints[0], endpoints[1]]
        return endpoints

    @classmethod
    async def _call_llm(cls, prompt: str, use_search: bool = True, temp: float = 0.4) -> Dict[str, Any]:
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            return {"text": "", "grounded": [], "error": "Ключ GEMINI_API_KEY пуст в настройках Render."}

        # Поддержка бесплатных ключей Groq (gsk_...)
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

        base_payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temp, "maxOutputTokens": 850},
        }

        try:
            async with httpx.AsyncClient(timeout=22.0) as client:
                if cls._working_endpoint:
                    resp = await client.post(cls._working_endpoint, json=base_payload)
                    if resp.status_code == 200:
                        return cls._parse_response(resp.json())
                    cls._working_endpoint = None

                discovered = await cls._discover_models(client, api_key)
                models_to_try = discovered + [m for m in cls.CANDIDATE_MODELS if m not in discovered]

                last_error = ""
                for model_name in models_to_try:
                    for endpoint in cls._build_endpoints(model_name, api_key):
                        if use_search:
                            payload_search = {**base_payload, "tools": [{"google_search": {}}]}
                            resp = await client.post(endpoint, json=payload_search)
                            if resp.status_code == 200:
                                cls._working_endpoint = endpoint
                                return cls._parse_response(resp.json())

                        resp = await client.post(endpoint, json=base_payload)
                        if resp.status_code == 200:
                            cls._working_endpoint = endpoint
                            return cls._parse_response(resp.json())

                        last_error = f"HTTP {resp.status_code} ({model_name}): {resp.text[:160]}"

                return {"text": "", "grounded": [], "error": last_error}
        except Exception as exc:
            return {"text": "", "grounded": [], "error": str(exc)}

    @classmethod
    def _parse_response(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        candidates = data.get("candidates", [])
        if not candidates:
            return {"text": "", "grounded": [], "error": "Пустой ответ от модели."}

        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        reply_text = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()

        grounded_results: List[Dict[str, Any]] = []
        for chunk in candidate.get("groundingMetadata", {}).get("groundingChunks", []):
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

    @classmethod
    async def chat_with_user(cls, user_id: int, user_message: str) -> str:
        cls.save_to_memory(user_id, "Пользователь", user_message)
        history_lines = [f"{msg['role']}: {msg['text']}" for msg in CHAT_MEMORY.get(user_id, [])]
        conversation_context = "\n\n".join(history_lines)

        prompt = (
            "Ты — ASTRA OSINT AI, умный, дружелюбный и профессиональный кибер-аналитик и ассистент в Telegram. "
            "Ты умеешь общаться на любые темы, отвечать на вопросы по прошлым результатам поиска и помогать с OSINT-разведкой. "
            "Отвечай четко, живо, на русском языке. Пиши чистым текстом с буллитами (•) и эмодзи.\n\n"
            f"История вашего диалога:\n{conversation_context}\n\n"
            "Ответь на последнее сообщение пользователя:"
        )

        res = await cls._call_llm(prompt, use_search=True, temp=0.5)
        if res["text"]:
            cls.save_to_memory(user_id, "ASTRA AI", res["text"])
            return res["text"]

        return f"⚠️ Ответ от API не получен.\nДетали от сервера: {res['error']}"

    @classmethod
    async def analyze_and_ground(
        cls, query: str, existing_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        context_lines = [
            f"{idx}. [{item.get('source', 'Web')}] {item.get('title', '')} — {item.get('url', '')} ({item.get('snippet', '')[:120]})"
            for idx, item in enumerate(existing_results[:12], 1)
        ]
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

import logging
from typing import Dict, Any, List
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

# Выбранная модель для каждого пользователя (user_id -> model_key)
USER_MODELS: Dict[int, str] = {}

# Справочник доступных моделей для переключения на лету
AVAILABLE_MODELS: Dict[str, Dict[str, str]] = {
    "groq_llama70b": {
        "provider": "groq",
        "model_id": "llama-3.3-70b-versatile",
        "title": "⚡ Groq · Llama 3.3 70B",
        "desc": "Флагманская быстрая модель Meta",
    },
    "groq_qwen": {
        "provider": "groq",
        "model_id": "qwen-qwq-32b",
        "title": "🧠 Groq · Qwen QwQ 32B",
        "desc": "Глубокая логика и аналитика",
    },
    "groq_fast": {
        "provider": "groq",
        "model_id": "llama-3.1-8b-instant",
        "title": "🚀 Groq · Llama 3.1 8B Instant",
        "desc": "Мгновенные ответы за 0.2 сек",
    },
    "gemini_flash": {
        "provider": "gemini",
        "model_id": "gemini-auto",
        "title": "🌐 Google · Gemini Flash + Search",
        "desc": "Модель Google с живым поиском",
    },
}


class LLMRouter:
    """Отвечает исключительно за сетевые запросы к Groq и Google Gemini API и переключение моделей."""

    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    _working_gemini_endpoint: str | None = None

    CANDIDATE_GEMINI_MODELS = [
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash-latest",
    ]

    @classmethod
    def get_user_model_key(cls, user_id: int) -> str:
        if user_id in USER_MODELS and USER_MODELS[user_id] in AVAILABLE_MODELS:
            return USER_MODELS[user_id]
        if cls.get_groq_key():
            return "groq_llama70b"
        return "gemini_flash"

    @classmethod
    def set_user_model(cls, user_id: int, model_key: str) -> Dict[str, str]:
        if model_key in AVAILABLE_MODELS:
            USER_MODELS[user_id] = model_key
            return AVAILABLE_MODELS[model_key]
        return AVAILABLE_MODELS["groq_llama70b"]

    @classmethod
    def get_groq_key(cls) -> str:
        if settings.GROQ_API_KEY.strip():
            return settings.GROQ_API_KEY.strip()
        if settings.GEMINI_API_KEY.strip().startswith("gsk_"):
            return settings.GEMINI_API_KEY.strip()
        return ""

    @classmethod
    def get_gemini_key(cls) -> str:
        key = settings.GEMINI_API_KEY.strip()
        if key and not key.startswith("gsk_"):
            return key
        return ""

    @classmethod
    async def generate(
        cls, prompt: str, user_id: int = 0, use_search: bool = True, temp: float = 0.4
    ) -> Dict[str, Any]:
        """Главный метод: отправляет запрос в выбранную пользователем модель."""
        model_key = cls.get_user_model_key(user_id)
        model_info = AVAILABLE_MODELS.get(model_key, AVAILABLE_MODELS["groq_llama70b"])

        if model_info["provider"] == "groq":
            res = await cls._call_groq(model_info["model_id"], prompt, temp)
            res["model_title"] = model_info["title"]
            return res

        res = await cls._call_gemini(prompt, use_search=use_search, temp=temp)
        res["model_title"] = model_info["title"]
        return res

    @classmethod
    async def _call_groq(cls, model_id: str, prompt: str, temp: float = 0.4) -> Dict[str, Any]:
        groq_key = cls.get_groq_key()
        if not groq_key:
            return {
                "text": "",
                "grounded": [],
                "error": "Ключ GROQ_API_KEY (gsk_...) не задан в настройках Render.",
            }
        try:
            async with httpx.AsyncClient(timeout=22.0) as client:
                resp = await client.post(
                    cls.GROQ_URL,
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temp,
                        "max_tokens": 1000,
                    },
                )
                # Если дополнительная модель временно недоступна, переключаемся на флагманскую Llama 3.3 70B
                if resp.status_code != 200 and model_id != "llama-3.3-70b-versatile":
                    resp = await client.post(
                        cls.GROQ_URL,
                        headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temp,
                            "max_tokens": 1000,
                        },
                    )
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"].strip()
                    return {"text": text, "grounded": [], "error": ""}
                return {"text": "", "grounded": [], "error": f"Groq HTTP {resp.status_code}: {resp.text[:160]}"}
        except Exception as exc:
            return {"text": "", "grounded": [], "error": str(exc)}

    @classmethod
    async def _discover_gemini_models(cls, client: httpx.AsyncClient, api_key: str) -> List[str]:
        discovered: List[str] = []
        for ver in ("v1beta", "v1"):
            try:
                resp = await client.get(f"https://generativelanguage.googleapis.com/{ver}/models?key={api_key}")
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
    async def _call_gemini(cls, prompt: str, use_search: bool = True, temp: float = 0.4) -> Dict[str, Any]:
        api_key = cls.get_gemini_key()
        if not api_key:
            if cls.get_groq_key():
                return await cls._call_groq("llama-3.3-70b-versatile", prompt, temp)
            return {"text": "", "grounded": [], "error": "Ключ GEMINI_API_KEY не задан в Render."}

        base_payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temp, "maxOutputTokens": 850},
        }

        try:
            async with httpx.AsyncClient(timeout=22.0) as client:
                if cls._working_gemini_endpoint:
                    resp = await client.post(cls._working_gemini_endpoint, json=base_payload)
                    if resp.status_code == 200:
                        return cls._parse_gemini_response(resp.json())
                    cls._working_gemini_endpoint = None

                discovered = await cls._discover_gemini_models(client, api_key)
                models_to_try = discovered + [m for m in cls.CANDIDATE_GEMINI_MODELS if m not in discovered]

                last_error = ""
                for model_name in models_to_try:
                    endpoints = [
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}",
                        f"https://generativelanguage.googleapis.com/v1/models/{model_name}:generateContent?key={api_key}",
                        f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model_name}:generateContent?key={api_key}",
                    ]
                    if api_key.startswith("AQ."):
                        endpoints = [endpoints[2], endpoints[0], endpoints[1]]

                    for endpoint in endpoints:
                        if use_search:
                            resp = await client.post(
                                endpoint, json={**base_payload, "tools": [{"google_search": {}}]}
                            )
                            if resp.status_code == 200:
                                cls._working_gemini_endpoint = endpoint
                                return cls._parse_gemini_response(resp.json())

                        resp = await client.post(endpoint, json=base_payload)
                        if resp.status_code == 200:
                            cls._working_gemini_endpoint = endpoint
                            return cls._parse_gemini_response(resp.json())

                        last_error = f"HTTP {resp.status_code} ({model_name}): {resp.text[:140]}"

                if cls.get_groq_key():
                    return await cls._call_groq("llama-3.3-70b-versatile", prompt, temp)

                return {"text": "", "grounded": [], "error": last_error}
        except Exception as exc:
            return {"text": "", "grounded": [], "error": str(exc)}

    @classmethod
    def _parse_gemini_response(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        candidates = data.get("candidates", [])
        if not candidates:
            return {"text": "", "grounded": [], "error": "Пустой ответ от Gemini."}

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

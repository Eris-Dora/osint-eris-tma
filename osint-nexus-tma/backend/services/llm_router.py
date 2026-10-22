import logging
import re
from typing import Dict, Any, List
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

# Выбранная модель для каждого пользователя (user_id -> model_key)
USER_MODELS: Dict[int, str] = {}

# Актуальный каталог моделей (Groq + Google Gemini + OpenRouter)
AVAILABLE_MODELS: Dict[str, Dict[str, str]] = {
    "groq_gpt_oss_120b": {
        "provider": "groq",
        "model_id": "openai/gpt-oss-120b",
        "title": "⚡ Groq · GPT-OSS 120B",
        "desc": "Новейшая флагманская модель 120B на чипах Groq",
    },
    "groq_compound": {
        "provider": "groq",
        "model_id": "groq/compound",
        "title": "🧠 Groq · Compound AI",
        "desc": "Агентная система Groq для глубокого анализа",
    },
    "groq_kimi_k2": {
        "provider": "groq",
        "model_id": "moonshotai/kimi-k2-instruct",
        "title": "🌙 Groq · Kimi K2 Instruct",
        "desc": "Мощная аналитическая модель с отличным русским языком",
    },
    "groq_llama4_scout": {
        "provider": "groq",
        "model_id": "meta-llama/llama-4-scout-17b-16e-instruct",
        "title": "🦙 Groq · Llama 4 Scout 17B",
        "desc": "Быстрая модель поколения Llama 4",
    },
    "groq_gpt_oss_20b": {
        "provider": "groq",
        "model_id": "openai/gpt-oss-20b",
        "title": "🚀 Groq · GPT-OSS 20B Instant",
        "desc": "Мгновенные ответы за доли секунды",
    },
    "gemini_flash": {
        "provider": "gemini",
        "model_id": "gemini-auto",
        "title": "🌐 Google · Gemini Flash + Search",
        "desc": "Модель Google с прямым выходом в поиск Google",
    },
    "openrouter_deepseek": {
        "provider": "openrouter",
        "model_id": "deepseek/deepseek-chat-v3-0324:free",
        "title": "🌌 OpenRouter · DeepSeek V3 (Free)",
        "desc": "Полная версия DeepSeek V3 (нужен OPENROUTER_API_KEY)",
    },
}


class LLMRouter:
    """Отвечает за сетевые запросы к Groq, Google Gemini и OpenRouter API с авто-обнаружением моделей."""

    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

    _working_gemini_endpoint: str | None = None
    _cached_groq_models: List[str] = []

    CANDIDATE_GEMINI_MODELS = [
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash-preview-05-20",
        "gemini-1.5-flash-latest",
    ]

    @classmethod
    def _clean_think_tags(cls, text: str) -> str:
        """Убирает технические теги <think>...</think> у рассуждающих моделей."""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return cleaned if cleaned else text.strip()

    @classmethod
    def get_user_model_key(cls, user_id: int) -> str:
        if user_id in USER_MODELS and USER_MODELS[user_id] in AVAILABLE_MODELS:
            return USER_MODELS[user_id]
        if cls.get_groq_key():
            return "groq_gpt_oss_120b"
        return "gemini_flash"

    @classmethod
    def set_user_model(cls, user_id: int, model_key: str) -> Dict[str, str]:
        if model_key in AVAILABLE_MODELS:
            USER_MODELS[user_id] = model_key
            return AVAILABLE_MODELS[model_key]
        return AVAILABLE_MODELS["groq_gpt_oss_120b"]

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
        model_key = cls.get_user_model_key(user_id)
        model_info = AVAILABLE_MODELS.get(model_key, AVAILABLE_MODELS["groq_gpt_oss_120b"])
        provider = model_info["provider"]

        if provider == "groq":
            res = await cls._call_groq(model_info["model_id"], prompt, temp)
            res["model_title"] = res.get("used_model_title") or model_info["title"]
            return res

        if provider == "openrouter":
            res = await cls._call_openrouter(model_info["model_id"], prompt, temp)
            res["model_title"] = model_info["title"]
            return res

        res = await cls._call_gemini(prompt, use_search=use_search, temp=temp)
        res["model_title"] = model_info["title"]
        return res

    @classmethod
    async def _discover_groq_models(cls, client: httpx.AsyncClient, groq_key: str) -> List[str]:
        """Запрашивает у самого сервера Groq список реально доступных для этого ключа текстовых моделей."""
        if cls._cached_groq_models:
            return cls._cached_groq_models

        discovered: List[str] = []
        try:
            resp = await client.get(
                cls.GROQ_MODELS_URL,
                headers={"Authorization": f"Bearer {groq_key}"},
            )
            if resp.status_code == 200:
                for m in resp.json().get("data", []):
                    m_id = m.get("id", "")
                    low = m_id.lower()
                    # Отсекаем аудио-модели (whisper, tts) и системные гарды (guard/safeguard)
                    if any(skip in low for skip in ("whisper", "tts", "playai", "guard", "orpheus")):
                        continue
                    discovered.append(m_id)

                if discovered:
                    # Приоритет самым мощным моделям (120b, 70b, compound, kimi, llama-4, qwen)
                    def _priority(name: str) -> int:
                        n = name.lower()
                        if "120b" in n or "70b" in n:
                            return 0
                        if "compound" in n or "kimi" in n or "llama-4" in n or "qwen" in n:
                            return 1
                        return 2

                    discovered.sort(key=lambda x: (_priority(x), x))
                    cls._cached_groq_models = discovered
        except Exception as exc:
            logger.warning(f"Не удалось получить список моделей Groq: {exc}")
        return discovered

    @classmethod
    async def _call_groq(cls, model_id: str, prompt: str, temp: float = 0.4) -> Dict[str, Any]:
        groq_key = cls.get_groq_key()
        if not groq_key:
            return {
                "text": "",
                "grounded": [],
                "error": "Ключ GROQ_API_KEY (gsk_...) не задан в настройках Render.",
            }

        headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                # 1. Пробуем запрошенную пользователем модель
                resp = await client.post(
                    cls.GROQ_URL,
                    headers=headers,
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temp,
                        "max_tokens": 2048,
                    },
                )
                if resp.status_code == 200:
                    raw_text = resp.json()["choices"][0]["message"]["content"]
                    return {"text": cls._clean_think_tags(raw_text), "grounded": [], "error": ""}

                # 2. Если модель вернула 404 (устарела или недоступна) — запрашиваем живой список у Groq!
                cls._cached_groq_models = []
                available = await cls._discover_groq_models(client, groq_key)

                last_err = f"Groq HTTP {resp.status_code}: {resp.text[:160]}"
                for fallback_model in available:
                    if fallback_model == model_id:
                        continue
                    resp_fb = await client.post(
                        cls.GROQ_URL,
                        headers=headers,
                        json={
                            "model": fallback_model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temp,
                            "max_tokens": 2048,
                        },
                    )
                    if resp_fb.status_code == 200:
                        raw_text = resp_fb.json()["choices"][0]["message"]["content"]
                        return {
                            "text": cls._clean_think_tags(raw_text),
                            "grounded": [],
                            "error": "",
                            "used_model_title": f"⚡ Groq · {fallback_model}",
                        }
                    last_err = f"Groq HTTP {resp_fb.status_code} ({fallback_model}): {resp_fb.text[:140]}"

                return {"text": "", "grounded": [], "error": last_err}
        except Exception as exc:
            return {"text": "", "grounded": [], "error": str(exc)}

    @classmethod
    async def _call_openrouter(cls, model_id: str, prompt: str, temp: float = 0.4) -> Dict[str, Any]:
        or_key = settings.OPENROUTER_API_KEY.strip()
        if not or_key:
            if cls.get_groq_key():
                return await cls._call_groq("openai/gpt-oss-120b", prompt, temp)
            return {
                "text": "",
                "grounded": [],
                "error": "Ключ OPENROUTER_API_KEY не задан в Render (или выберите модель Groq).",
            }
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    cls.OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {or_key}", "Content-Type": "application/json"},
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temp,
                    },
                )
                if resp.status_code == 200:
                    raw_text = resp.json()["choices"][0]["message"]["content"]
                    return {"text": cls._clean_think_tags(raw_text), "grounded": [], "error": ""}
                return {"text": "", "grounded": [], "error": f"OpenRouter HTTP {resp.status_code}: {resp.text[:160]}"}
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
                        discovered.sort(
                            key=lambda x: (
                                0 if "2.0-flash" in x else (1 if "flash-lite" in x else (2 if "flash" in x else 3)),
                                x,
                            )
                        )
                        return discovered
            except Exception:
                pass
        return discovered

    @classmethod
    async def _call_gemini(cls, prompt: str, use_search: bool = True, temp: float = 0.4) -> Dict[str, Any]:
        api_key = cls.get_gemini_key()
        if not api_key:
            if cls.get_groq_key():
                return await cls._call_groq("openai/gpt-oss-120b", prompt, temp)
            return {"text": "", "grounded": [], "error": "Ключ GEMINI_API_KEY не задан в Render."}

        base_payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temp,
                "maxOutputTokens": 4096,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
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
                    return await cls._call_groq("openai/gpt-oss-120b", prompt, temp)

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

import logging
from typing import Dict, Any, List
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)


class LLMRouter:
    """
    Отдельный сетевой модуль для связи с ИИ-провайдерами (Google AI Studio, Vertex AI, Groq).
    Автоматически опрашивает ListModels и кэширует рабочую модель.
    """

    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    _working_endpoint: str | None = None

    CANDIDATE_MODELS = [
        "gemini-3-flash-preview",
        "gemini-3.0-flash-preview",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash-latest",
    ]

    @classmethod
    async def _discover_models(cls, client: httpx.AsyncClient, api_key: str) -> List[str]:
        """Запрашивает у сервера Google список реально доступных моделей для текущего ключа."""
        discovered: List[str] = []
        urls = [
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
            f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
        ]
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    for m in resp.json().get("models", []):
                        methods = m.get("supportedGenerationMethods", [])
                        name = m.get("name", "")
                        if "generateContent" in methods and "gemini" in name.lower():
                            clean_name = name.replace("models/", "")
                            if clean_name not in discovered:
                                discovered.append(clean_name)
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
    async def generate(cls, prompt: str, use_search: bool = True, temp: float = 0.4) -> Dict[str, Any]:
        """Отправляет запрос к доступной LLM и возвращает словарь: {text, grounded, error}."""
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            return {"text": "", "grounded": [], "error": "Ключ GEMINI_API_KEY пуст в настройках Render."}

        # Поддержка ключей Groq (gsk_...)
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

        # Работа с Google API
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
            logger.warning(f"Ошибка LLMRouter: {exc}")
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
        chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
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
                        "snippet": "Найдено нейросетью напрямую через живой поиск Google.",
                        "source": "Google AI Grounding",
                        "category": cat,
                        "date": "Live",
                    }
                )

        return {"text": reply_text, "grounded": grounded_results, "error": ""}

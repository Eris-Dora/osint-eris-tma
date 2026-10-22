import logging
from typing import Dict, Any, List
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)


class GeminiOSINTAnalyst:
    """
    Асинхронный модуль ИИ-разведки на базе Gemini 2.5 Flash
    с поддержкой живого выхода в интернет (Google Search Grounding).
    """

    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    @classmethod
    async def analyze_and_ground(
        cls, query: str, existing_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            return {"ai_summary": "", "grounded_results": []}

        # Формируем краткий контекст из уже найденных ссылок (топ-12)
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
                resp = await client.post(
                    f"{cls.API_URL}?key={api_key}",
                    json=payload,
                )

                # Если бесплатный тариф не поддерживает google_search для конкретного ключа,
                # делаем мгновенный фолбэк на анализ без инструмента google_search
                if resp.status_code != 200:
                    payload.pop("tools", None)
                    resp = await client.post(
                        f"{cls.API_URL}?key={api_key}",
                        json=payload,
                    )

                if resp.status_code != 200:
                    logger.warning(f"Gemini API HTTP {resp.status_code}: {resp.text[:200]}")
                    return {"ai_summary": "", "grounded_results": []}

                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return {"ai_summary": "", "grounded_results": []}

                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                ai_summary = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()

                # Извлекаем реальные ссылки, которые Gemini нашел напрямую в Google
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

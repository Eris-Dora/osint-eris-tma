import asyncio
import logging
from typing import List, Dict, Any
from duckduckgo_search import AsyncDDGS
from config.settings import settings

logger = logging.getLogger(__name__)


class DorkEngine:
    """Модуль поисковых дорков и новостей через DuckDuckGo (без API ключей)."""

    DORK_TEMPLATES = {
        "mentions": '"{query}"',
        "socials": (
            'site:t.me OR site:vk.com OR site:instagram.com OR '
            'site:linkedin.com OR site:x.com OR site:twitter.com OR '
            'site:tiktok.com OR site:facebook.com "{query}"'
        ),
        "forums": (
            'site:habr.com OR site:pikabu.ru OR site:vc.ru OR '
            'site:4pda.to OR site:medium.com OR site:pastebin.com OR '
            'filetype:pdf OR filetype:xlsx OR filetype:docx "{query}"'
        ),
    }

    @classmethod
    async def _fetch_ddg_text(cls, dork_query: str, category: str, source_label: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            async with AsyncDDGS() as ddgs:
                raw_items = await ddgs.atext(
                    keywords=dork_query,
                    region="wt-wt",
                    safesearch="off",
                    max_results=settings.MAX_RESULTS_PER_SOURCE,
                )
                for item in raw_items or []:
                    results.append(
                        {
                            "title": item.get("title", "Без названия"),
                            "url": item.get("href", ""),
                            "snippet": item.get("body", "Описание отсутствует"),
                            "source": source_label,
                            "category": category,
                            "date": "",
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка DDG Text ({category}): {exc}")
        return results

    @classmethod
    async def _fetch_ddg_news(cls, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            async with AsyncDDGS() as ddgs:
                raw_news = await ddgs.anews(
                    keywords=query,
                    region="wt-wt",
                    safesearch="off",
                    max_results=settings.MAX_RESULTS_PER_SOURCE,
                )
                for item in raw_news or []:
                    results.append(
                        {
                            "title": item.get("title", "Новость"),
                            "url": item.get("url", ""),
                            "snippet": item.get("body", ""),
                            "source": f"News · {item.get('source', 'СМИ')}",
                            "category": "mentions",
                            "date": item.get("date", "")[:10] if item.get("date") else "",
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка DDG News: {exc}")
        return results

    @classmethod
    async def search_all_dorks(cls, query: str) -> List[Dict[str, Any]]:
        """Запускает параллельный поиск по всем доркам и новостям."""
        q_clean = query.strip()
        tasks = [
            cls._fetch_ddg_text(cls.DORK_TEMPLATES["mentions"].format(query=q_clean), "mentions", "Web Mention"),
            cls._fetch_ddg_text(cls.DORK_TEMPLATES["socials"].format(query=q_clean), "socials", "Social Dork"),
            cls._fetch_ddg_text(cls.DORK_TEMPLATES["forums"].format(query=q_clean), "forums", "Forums & Docs"),
            cls._fetch_ddg_news(q_clean),
        ]
        batches = await asyncio.gather(*tasks, return_exceptions=True)
        merged: List[Dict[str, Any]] = []
        for batch in batches:
            if isinstance(batch, list):
                merged.extend(batch)
        return merged

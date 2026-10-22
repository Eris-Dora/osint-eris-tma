import asyncio
import logging
from typing import List, Dict, Any
from duckduckgo_search import AsyncDDGS

logger = logging.getLogger(__name__)


class DorkEngine:
    """Расширенный мульти-потоковый поиск через DuckDuckGo (широкий охват + прицельные дорки)."""

    @classmethod
    async def _fetch_ddg_text(
        cls, dork_query: str, category: str, source_label: str, limit: int = 18
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            async with AsyncDDGS() as ddgs:
                raw_items = await ddgs.atext(
                    keywords=dork_query,
                    region="wt-wt",
                    safesearch="off",
                    max_results=limit,
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
            logger.warning(f"Ошибка DDG Text ({source_label}): {exc}")
        return results

    @classmethod
    async def _fetch_ddg_news(cls, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            async with AsyncDDGS() as ddgs:
                raw_news = await ddgs.anews(
                    keywords=query,
                    region="wt-wt",
                    safesearch="off",
                    max_results=limit,
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
        """Запускает 7 параллельных поисковых векторов для максимального охвата."""
        q = query.strip().lstrip("@")

        tasks = [
            # 1. Широкий глобальный поиск (без жестких кавычек — находит максимум страниц)
            cls._fetch_ddg_text(q, "mentions", "Global Web", limit=20),
            # 2. Точное вхождение фразы
            cls._fetch_ddg_text(f'"{q}"', "mentions", "Exact Match", limit=15),
            # 3. Прицельный поиск по Instagram и TikTok
            cls._fetch_ddg_text(
                f'(site:instagram.com OR site:tiktok.com) "{q}"',
                "socials",
                "Instagram / TikTok",
                limit=15,
            ),
            # 4. Прицельный поиск по Telegram, VK, YouTube, X, LinkedIn
            cls._fetch_ddg_text(
                f'(site:t.me OR site:vk.com OR site:youtube.com OR site:x.com OR site:linkedin.com) "{q}"',
                "socials",
                "TG / VK / Socials",
                limit=15,
            ),
            # 5. Форумы, блоги и статьи (Habr, Pikabu, VC, DTF, 4PDA, Medium)
            cls._fetch_ddg_text(
                f'(site:habr.com OR site:pikabu.ru OR site:vc.ru OR site:dtf.ru OR site:4pda.to OR site:medium.com) {q}',
                "forums",
                "Forums & Blogs",
                limit=15,
            ),
            # 6. Документы, базы и пастбины (PDF, XLSX, DOCX, TXT, Pastebin)
            cls._fetch_ddg_text(
                f'(filetype:pdf OR filetype:xlsx OR filetype:docx OR site:pastebin.com OR site:docs.google.com) "{q}"',
                "forums",
                "Docs & Leaks",
                limit=12,
            ),
            # 7. Свежие новости и СМИ
            cls._fetch_ddg_news(q, limit=15),
        ]

        batches = await asyncio.gather(*tasks, return_exceptions=True)
        merged: List[Dict[str, Any]] = []
        for batch in batches:
            if isinstance(batch, list):
                merged.extend(batch)
        return merged

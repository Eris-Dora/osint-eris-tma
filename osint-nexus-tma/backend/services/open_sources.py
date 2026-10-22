import asyncio
import logging
from typing import List, Dict, Any
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OSINTNexusBot/1.0",
    "Accept": "application/json",
}


class OpenSourcesEngine:
    """Прямой опрос открытых API: Reddit, HackerNews, GitHub, Wayback Machine."""

    @staticmethod
    async def search_reddit(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            url = "https://www.reddit.com/search.json"
            params = {"q": query, "limit": 8, "sort": "relevance"}
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                children = resp.json().get("data", {}).get("children", [])
                for child in children:
                    data = child.get("data", {})
                    permalink = data.get("permalink", "")
                    results.append(
                        {
                            "title": data.get("title", "Reddit Thread"),
                            "url": f"https://www.reddit.com{permalink}" if permalink else data.get("url", ""),
                            "snippet": (data.get("selftext", "") or f"Сабреддит: r/{data.get('subreddit', '')}")[:240],
                            "source": f"Reddit · r/{data.get('subreddit', 'all')}",
                            "category": "forums",
                            "date": "",
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка Reddit API: {exc}")
        return results

    @staticmethod
    async def search_hackernews(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            url = "https://hn.algolia.com/api/v1/search"
            params = {"query": query, "hitsPerPage": 8}
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                hits = resp.json().get("hits", [])
                for hit in hits:
                    object_id = hit.get("objectID", "")
                    item_url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
                    title = hit.get("title") or hit.get("story_title") or "HackerNews Mention"
                    comment = hit.get("comment_text") or f"Автор: {hit.get('author', 'unknown')} | Очки: {hit.get('points', 0)}"
                    results.append(
                        {
                            "title": title,
                            "url": item_url,
                            "snippet": comment[:240],
                            "source": "HackerNews",
                            "category": "forums",
                            "date": (hit.get("created_at") or "")[:10],
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка HackerNews API: {exc}")
        return results

    @staticmethod
    async def search_github(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            url = "https://api.github.com/search/repositories"
            params = {"q": query, "per_page": 6}
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for repo in items:
                    results.append(
                        {
                            "title": repo.get("full_name", "GitHub Repo"),
                            "url": repo.get("html_url", ""),
                            "snippet": repo.get("description") or f"Язык: {repo.get('language', 'N/A')} | ⭐ {repo.get('stargazers_count', 0)}",
                            "source": "GitHub",
                            "category": "forums",
                            "date": (repo.get("updated_at") or "")[:10],
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка GitHub API: {exc}")
        return results

    @staticmethod
    async def search_wayback(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        # Проверяем Wayback Machine, если в запросе нет пробелов (похоже на домен, ник или email)
        if " " in query.strip():
            return results
        try:
            url = "https://web.archive.org/cdx/search/cdx"
            params = {
                "url": f"*{query.strip()}*",
                "output": "json",
                "limit": 6,
                "collapse": "urlkey",
            }
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 1:
                    for row in data[1:]:
                        timestamp, original_url, mime = row[1], row[2], row[3]
                        formatted_date = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
                        results.append(
                            {
                                "title": f"Архивная копия: {original_url}",
                                "url": f"https://web.archive.org/web/{timestamp}/{original_url}",
                                "snippet": f"Сохранено в Wayback Machine ({formatted_date}), тип: {mime}",
                                "source": "Archive.org",
                                "category": "mentions",
                                "date": formatted_date,
                            }
                        )
        except Exception as exc:
            logger.warning(f"Ошибка Wayback API: {exc}")
        return results

    @classmethod
    async def search_all_open_sources(cls, query: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(headers=HEADERS, timeout=settings.HTTP_TIMEOUT, follow_redirects=True) as client:
            tasks = [
                cls.search_reddit(client, query),
                cls.search_hackernews(client, query),
                cls.search_github(client, query),
                cls.search_wayback(client, query),
            ]
            batches = await asyncio.gather(*tasks, return_exceptions=True)
            merged: List[Dict[str, Any]] = []
            for batch in batches:
                if isinstance(batch, list):
                    merged.extend(batch)
            return merged

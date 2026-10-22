import asyncio
import logging
from typing import List, Dict, Any
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OSINTNexusBot/2.0",
    "Accept": "application/json",
}


class OpenSourcesEngine:
    """Прямой опрос открытых баз: Reddit, HackerNews, GitHub (Users + Repos), Wikipedia (RU/EN), StackOverflow, Wayback."""

    @staticmethod
    async def search_reddit(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            url = "https://www.reddit.com/search.json"
            params = {"q": query, "limit": 12, "sort": "relevance"}
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
                            "snippet": (data.get("selftext", "") or f"Обсуждение в сабреддите r/{data.get('subreddit', '')}")[:240],
                            "source": f"Reddit · r/{data.get('subreddit', 'all')}",
                            "category": "forums",
                            "date": "",
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка Reddit API: {exc}")
        return results

    @staticmethod
    async def search_wikipedia(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for lang in ("ru", "en"):
            try:
                url = f"https://{lang}.wikipedia.org/w/api.php"
                params = {
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 5,
                }
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    search_items = resp.json().get("query", {}).get("search", [])
                    for item in search_items:
                        title = item.get("title", "")
                        snippet = (
                            item.get("snippet", "")
                            .replace('<span class="searchmatch">', "")
                            .replace("</span>", "")
                            .replace("&quot;", '"')
                        )
                        page_url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
                        results.append(
                            {
                                "title": f"{title} ({lang.upper()})",
                                "url": page_url,
                                "snippet": snippet,
                                "source": f"Wikipedia · {lang.upper()}",
                                "category": "mentions",
                                "date": (item.get("timestamp") or "")[:10],
                            }
                        )
            except Exception as exc:
                logger.warning(f"Ошибка Wikipedia ({lang}): {exc}")
        return results

    @staticmethod
    async def search_github_all(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        # 1. Поиск пользователей/организаций GitHub
        try:
            u_resp = await client.get("https://api.github.com/search/users", params={"q": query, "per_page": 5})
            if u_resp.status_code == 200:
                for user in u_resp.json().get("items", []):
                    results.append(
                        {
                            "title": f"GitHub User: @{user.get('login')}",
                            "url": user.get("html_url", ""),
                            "snippet": f"Тип аккаунта: {user.get('type', 'User')} | ID: {user.get('id')}",
                            "source": "GitHub · Profile",
                            "category": "socials",
                            "date": "",
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка GitHub Users API: {exc}")

        # 2. Поиск репозиториев
        try:
            r_resp = await client.get("https://api.github.com/search/repositories", params={"q": query, "per_page": 8})
            if r_resp.status_code == 200:
                for repo in r_resp.json().get("items", []):
                    results.append(
                        {
                            "title": repo.get("full_name", "GitHub Repo"),
                            "url": repo.get("html_url", ""),
                            "snippet": repo.get("description") or f"Язык: {repo.get('language', 'N/A')} | ⭐ {repo.get('stargazers_count', 0)}",
                            "source": "GitHub · Repo",
                            "category": "forums",
                            "date": (repo.get("updated_at") or "")[:10],
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка GitHub Repos API: {exc}")
        return results

    @staticmethod
    async def search_hackernews(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            url = "https://hn.algolia.com/api/v1/search"
            params = {"query": query, "hitsPerPage": 8}
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                for hit in resp.json().get("hits", []):
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
    async def search_stackoverflow(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            url = "https://api.stackexchange.com/2.3/search/advanced"
            params = {"order": "desc", "sort": "relevance", "q": query, "site": "stackoverflow", "pagesize": 6}
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    results.append(
                        {
                            "title": item.get("title", "StackOverflow Question"),
                            "url": item.get("link", ""),
                            "snippet": f"Ответов: {item.get('answer_count', 0)} | Просмотров: {item.get('view_count', 0)} | Теги: {', '.join(item.get('tags', []))}",
                            "source": "StackOverflow",
                            "category": "forums",
                            "date": "",
                        }
                    )
        except Exception as exc:
            logger.warning(f"Ошибка StackOverflow API: {exc}")
        return results

    @staticmethod
    async def search_wayback(client: httpx.AsyncClient, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        clean_q = query.strip().lstrip("@")
        if " " in clean_q:
            return results
        try:
            url = "https://web.archive.org/cdx/search/cdx"
            params = {
                "url": f"*{clean_q}*",
                "output": "json",
                "limit": 8,
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
                                "title": f"Веб-архив: {original_url}",
                                "url": f"https://web.archive.org/web/{timestamp}/{original_url}",
                                "snippet": f"Сохраненная историческая копия страницы от {formatted_date} ({mime})",
                                "source": "Wayback Machine",
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
                cls.search_wikipedia(client, query),
                cls.search_reddit(client, query),
                cls.search_github_all(client, query),
                cls.search_hackernews(client, query),
                cls.search_stackoverflow(client, query),
                cls.search_wayback(client, query),
            ]
            batches = await asyncio.gather(*tasks, return_exceptions=True)
            merged: List[Dict[str, Any]] = []
            for batch in batches:
                if isinstance(batch, list):
                    merged.extend(batch)
            return merged

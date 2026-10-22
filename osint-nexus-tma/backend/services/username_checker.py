import asyncio
import re
from typing import List, Dict, Any
import httpx
from config.settings import settings

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")

PLATFORMS = [
    {
        "name": "Telegram",
        "url": "https://t.me/{username}",
        "check_text": "tgme_page_title",
    },
    {
        "name": "GitHub",
        "url": "https://github.com/{username}",
        "check_text": None,
    },
    {
        "name": "Habr",
        "url": "https://habr.com/ru/users/{username}/",
        "check_text": None,
    },
    {
        "name": "Reddit",
        "url": "https://www.reddit.com/user/{username}/about.json",
        "check_text": '"kind": "t2"',
    },
    {
        "name": "Dev.to",
        "url": "https://dev.to/{username}",
        "check_text": None,
    },
    {
        "name": "Keybase",
        "url": "https://keybase.io/{username}",
        "check_text": None,
    },
]


class UsernameChecker:
    """Асинхронная проверка существования профилей по никнейму."""

    @staticmethod
    def is_valid_username(query: str) -> str | None:
        cleaned = query.strip().lstrip("@")
        if USERNAME_REGEX.match(cleaned) and "." not in cleaned.strip("."):
            return cleaned
        return None

    @classmethod
    async def _probe_platform(
        cls, client: httpx.AsyncClient, platform: Dict[str, Any], username: str
    ) -> Dict[str, Any] | None:
        target_url = platform["url"].format(username=username)
        try:
            resp = await client.get(target_url)
            if resp.status_code == 200:
                marker = platform.get("check_text")
                if marker and marker not in resp.text:
                    return None
                display_url = target_url.replace("/about.json", "")
                return {
                    "title": f"Профиль @{username} на {platform['name']}",
                    "url": display_url,
                    "snippet": f"Обнаружен активный аккаунт пользователя {username} на платформе {platform['name']}.",
                    "source": f"Profile · {platform['name']}",
                    "category": "socials",
                    "date": "Active",
                }
        except Exception:
            return None
        return None

    @classmethod
    async def check_username(cls, raw_query: str) -> List[Dict[str, Any]]:
        username = cls.is_valid_username(raw_query)
        if not username:
            return []

        headers = {"User-Agent": "Mozilla/5.0 (compatible; OSINTProbe/1.0)"}
        async with httpx.AsyncClient(headers=headers, timeout=6.0, follow_redirects=True) as client:
            tasks = [cls._probe_platform(client, p, username) for p in PLATFORMS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return [r for r in results if isinstance(r, dict)]

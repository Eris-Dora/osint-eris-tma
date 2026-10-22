import asyncio
import re
from typing import List, Dict, Any
import httpx

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")

# Расширенный список платформ (Соцсети, Мессенджеры, Стриминг, IT, Блоги)
PLATFORMS = [
    {
        "name": "Telegram",
        "url": "https://t.me/{username}",
        "check_text": "tgme_page_title",
        "not_found_text": "tgme_page_icon",
    },
    {
        "name": "Instagram",
        "url": "https://www.instagram.com/{username}/",
        "check_text": "{username}",
        "not_found_text": "Page Not Found",
    },
    {
        "name": "TikTok",
        "url": "https://www.tiktok.com/@{username}",
        "check_text": "{username}",
        "not_found_text": "Couldn't find this account",
    },
    {
        "name": "VK (ВКонтакте)",
        "url": "https://vk.com/{username}",
        "check_text": "page_name",
        "not_found_text": "404 Not Found",
    },
    {
        "name": "YouTube",
        "url": "https://www.youtube.com/@{username}",
        "check_text": "channelId",
        "not_found_text": "404 Not Found",
    },
    {
        "name": "GitHub",
        "url": "https://github.com/{username}",
        "check_text": None,
        "not_found_text": "Not Found",
    },
    {
        "name": "GitLab",
        "url": "https://gitlab.com/{username}",
        "check_text": "{username}",
        "not_found_text": "Sign in",
    },
    {
        "name": "Reddit",
        "url": "https://www.reddit.com/user/{username}/about.json",
        "check_text": '"kind": "t2"',
        "not_found_text": '"error": 404',
    },
    {
        "name": "Habr",
        "url": "https://habr.com/ru/users/{username}/",
        "check_text": "{username}",
        "not_found_text": "Страница не найдена",
    },
    {
        "name": "Twitch",
        "url": "https://m.twitch.tv/{username}",
        "check_text": "{username}",
        "not_found_text": "Sorry. Unless you've got a time machine",
    },
    {
        "name": "Pinterest",
        "url": "https://www.pinterest.com/{username}/",
        "check_text": "{username}",
        "not_found_text": "User not found",
    },
    {
        "name": "Steam Community",
        "url": "https://steamcommunity.com/id/{username}",
        "check_text": "actual_persona_name",
        "not_found_text": "The specified profile could not be found",
    },
    {
        "name": "SoundCloud",
        "url": "https://soundcloud.com/{username}",
        "check_text": "{username}",
        "not_found_text": "We can't find that user",
    },
    {
        "name": "Medium",
        "url": "https://medium.com/@{username}",
        "check_text": "{username}",
        "not_found_text": "PAGE NOT FOUND",
    },
    {
        "name": "Dev.to",
        "url": "https://dev.to/{username}",
        "check_text": None,
        "not_found_text": "404",
    },
    {
        "name": "Linktree",
        "url": "https://linktr.ee/{username}",
        "check_text": "{username}",
        "not_found_text": "The page you’re looking for doesn’t exist",
    },
    {
        "name": "Keybase",
        "url": "https://keybase.io/{username}",
        "check_text": None,
        "not_found_text": "404",
    },
]


class UsernameChecker:
    """Глубокая асинхронная проверка никнеймов по 17+ соцсетям + быстрые ссылки Instagram/X."""

    @staticmethod
    def extract_username(query: str) -> str | None:
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
                body_lower = resp.text.lower()
                not_found = platform.get("not_found_text")
                if not_found and not_found.lower() in body_lower:
                    return None

                marker = platform.get("check_text")
                if marker:
                    expected = marker.format(username=username).lower()
                    if expected not in body_lower:
                        return None

                display_url = target_url.replace("/about.json", "").replace("https://m.twitch.tv/", "https://twitch.tv/")
                return {
                    "title": f"Аккаунт @{username} в {platform['name']}",
                    "url": display_url,
                    "snippet": f"Подтвержденный профиль пользователя {username} на площадке {platform['name']}.",
                    "source": f"Social · {platform['name']}",
                    "category": "socials",
                    "date": "Active",
                }
        except Exception:
            return None
        return None

    @classmethod
    async def check_username(cls, raw_query: str) -> List[Dict[str, Any]]:
        username = cls.extract_username(raw_query)
        if not username:
            return []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        }

        async with httpx.AsyncClient(headers=headers, timeout=7.5, follow_redirects=True) as client:
            tasks = [cls._probe_platform(client, p, username) for p in PLATFORMS]
            probed = await asyncio.gather(*tasks, return_exceptions=True)
            found = [r for r in probed if isinstance(r, dict)]

        # Так как Instagram и X (Twitter) иногда закрывают прямой парсинг с облачных IP,
        # всегда добавляем прямые OSINT-карточки для мгновенной проверки профиля в 1 клик:
        found.insert(
            0,
            {
                "title": f"📸 Instagram: проверить @{username}",
                "url": f"https://www.instagram.com/{username}/",
                "snippet": f"Прямой переход к профилю и упоминаниям @{username} в Instagram.",
                "source": "Instagram Direct",
                "category": "socials",
                "date": "Direct",
            },
        )
        found.insert(
            1,
            {
                "title": f"🐦 X (Twitter): профиль и твиты @{username}",
                "url": f"https://x.com/{username}",
                "snippet": f"Прямой переход к странице пользователя @{username} в соцсети X (Twitter).",
                "source": "X / Twitter",
                "category": "socials",
                "date": "Direct",
            },
        )

        return found

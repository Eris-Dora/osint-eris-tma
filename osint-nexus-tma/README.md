# 🛡 OSINT Nexus — Telegram Mini App & Deep Search Bot

Автономная система глубокого поиска упоминаний, проверки никнеймов и сбора открытых данных (OSINT) со встроенным Telegram Mini App.

## Структура
- `webapp/` — Фронтенд Telegram Mini App (чистый HTML/CSS/JS для GitHub Pages / Vercel).
- `backend/` — Асинхронный сервер на `FastAPI` + `Aiogram 3.x` + поисковое ядро (`duckduckgo-search`, GitHub, Reddit, HackerNews, Wayback Machine, Username Checker).

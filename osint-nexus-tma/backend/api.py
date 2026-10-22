from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from config.settings import settings
from services.aggregator import run_full_osint_search


api_app = FastAPI(
    title="OSINT Nexus TMA API",
    version="1.0.0",
    docs_url="/docs",
)

# Настройка CORS для бесшовной работы с GitHub Pages / Vercel / Telegram WebApp
api_app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=160)
    category: str = Field(default="all")


@api_app.get("/health")
async def health_check():
    """Эндпоинт для проверки жизнеспособности сервера (UptimeRobot / Render Health Check)."""
    return {"status": "ok", "service": "osint-nexus-backend"}


@api_app.get("/api/search")
async def search_get(
    q: str = Query(..., min_length=2, max_length=160, description="Поисковый запрос"),
    category: str = Query("all", description="Категория: all, mentions, socials, forums"),
):
    """GET-маршрут поиска для вызовов из Telegram Mini App."""
    clean_q = q.strip()
    if len(clean_q) < 2:
        raise HTTPException(status_code=400, detail="Запрос должен содержать минимум 2 символа.")
    return await run_full_osint_search(query=clean_q, category_filter=category)


@api_app.post("/api/search")
async def search_post(payload: SearchRequest):
    """POST-маршрут поиска для вызовов из Telegram Mini App."""
    return await run_full_osint_search(
        query=payload.query.strip(),
        category_filter=payload.category,
    )

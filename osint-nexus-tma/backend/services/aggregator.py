import asyncio
import time
from typing import Dict, Any, List
from .dork_engine import DorkEngine
from .open_sources import OpenSourcesEngine
from .username_checker import UsernameChecker
from .ai_analyst import GeminiOSINTAnalyst


async def run_full_osint_search(query: str, category_filter: str = "all") -> Dict[str, Any]:
    """
    Выполняет параллельный сбор данных из всех бесплатных OSINT-источников,
    обогащает выдачу через Gemini Google Search Grounding и строит ИИ-досье.
    """
    start_time = time.perf_counter()
    clean_query = query.strip()

    # 1. Параллельный запуск всех базовых поисковых модулей
    dork_task = DorkEngine.search_all_dorks(clean_query)
    open_sources_task = OpenSourcesEngine.search_all_open_sources(clean_query)
    username_task = UsernameChecker.check_username(clean_query)

    dork_results, open_results, username_results = await asyncio.gather(
        dork_task, open_sources_task, username_task
    )

    preliminary_combined: List[Dict[str, Any]] = username_results + open_results + dork_results

    # 2. Запуск ИИ-аналитика (живой поиск Google + генерация сводки по найденным данным)
    ai_data = await GeminiOSINTAnalyst.analyze_and_ground(clean_query, preliminary_combined)
    ai_summary: str = ai_data.get("ai_summary", "")
    grounded_results: List[Dict[str, Any]] = ai_data.get("grounded_results", [])

    # Объединяем ссылки от Google AI, профили соцсетей и остальные находки
    raw_combined: List[Dict[str, Any]] = username_results + grounded_results + open_results + dork_results

    # Дедупликация по нормализованному URL
    seen_urls = set()
    unique_items: List[Dict[str, Any]] = []

    for item in raw_combined:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        norm_url = url.rstrip("/").lower()
        if norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)
        unique_items.append(item)

    counts = {
        "all": len(unique_items),
        "mentions": sum(1 for i in unique_items if i.get("category") == "mentions"),
        "socials": sum(1 for i in unique_items if i.get("category") == "socials"),
        "forums": sum(1 for i in unique_items if i.get("category") == "forums"),
    }

    if category_filter and category_filter != "all":
        filtered_items = [i for i in unique_items if i.get("category") == category_filter]
    else:
        filtered_items = unique_items

    elapsed_sec = round(time.perf_counter() - start_time, 2)

    return {
        "query": clean_query,
        "elapsed_seconds": elapsed_sec,
        "ai_summary": ai_summary,
        "counts": counts,
        "results": filtered_items,
    }
    

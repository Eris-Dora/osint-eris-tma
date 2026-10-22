import asyncio
import logging
from contextlib import asynccontextmanager
import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from config.settings import settings
from api import api_app
from bot.handlers import router as bot_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("osint-nexus")

bot_instance: Bot | None = None
dp_instance: Dispatcher | None = None
polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управляет одновременным запуском и остановкой Telegram-бота вместе с FastAPI."""
    global bot_instance, dp_instance, polling_task

    token = settings.BOT_TOKEN.strip()
    if token and token != "1234567890:AAH_ваш_токен_здесь":
        bot_instance = Bot(token=token)
        dp_instance = Dispatcher()
        dp_instance.include_router(bot_router)

        # Сбрасываем старый webhook, если был, и запускаем polling в фоне
        await bot_instance.delete_webhook(drop_pending_updates=True)
        polling_task = asyncio.create_task(
            dp_instance.start_polling(bot_instance, handle_signals=False)
        )
        logger.info("🤖 Telegram-бот успешно запущен в режиме Long Polling.")
    else:
        logger.warning("⚠️ BOT_TOKEN не задан. Запущен только REST API сервер.")

    yield

    # Корректное завершение при остановке контейнера
    if polling_task and not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    if bot_instance:
        await bot_instance.session.close()
        logger.info("🛑 Сессия Telegram-бота закрыта.")


api_app.router.lifespan_context = lifespan


if __name__ == "__main__":
    uvicorn.run(
        "main:api_app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=False,
    )

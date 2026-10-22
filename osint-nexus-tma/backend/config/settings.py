import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Глобальные настройки бэкенда, бота и CORS."""

    BOT_TOKEN: str = "8532736583:AAGwUbWDe5fV832v4giiHI2XYHBafmMVoRA"
    WEBAPP_URL: str = "https://telegram.org"
    PORT: int = 8000
    CORS_ORIGINS: str = "*"

    # Таймауты и лимиты для парсеров
    HTTP_TIMEOUT: float = 12.0
    MAX_RESULTS_PER_SOURCE: int = 12

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()

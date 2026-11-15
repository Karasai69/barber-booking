from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Часовой пояс барбершопа: в нём записан график мастеров.
    TIMEZONE: str = "Asia/Almaty"

    # Нужен только боту. API и тесты работают и без него.
    TELEGRAM_BOT_TOKEN: SecretStr | None = None
    # Кому бот присылает ежедневный отчёт. Свой id можно узнать командой /myid в боте.
    ADMIN_TELEGRAM_ID: int | None = None

    REDIS_URL: str = "redis://localhost:6379/0"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()

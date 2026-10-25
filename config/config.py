from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str

    OPENROUTER_API_KEY: str | None = None
    TWELVE_DATA_API_KEY: str | None = None
    MARKETAUX_API_KEY: str | None = None

    # Authentication is disabled until an explicit secret is configured.
    # Never fall back to a known secret in source code.
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRES_IN: int = 60  # minutes
    REFRESH_TOKEN_EXPIRES_IN: int = 7  # days

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()

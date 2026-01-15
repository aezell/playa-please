"""
Application configuration - loaded from environment variables
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # App settings
    secret_key: str = "dev-secret-key-change-in-production"
    database_url: str = "sqlite:///./better_supermix.db"

    # URLs
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"

    # Algorithm settings
    discovery_ratio: float = 0.25  # 25% discovery, 75% familiar
    min_artist_gap: int = 5  # Minimum songs between same artist
    max_genre_ratio: float = 0.4  # Max 40% from any single genre
    queue_prefetch_size: int = 20  # Songs to pre-generate

    # Stream settings
    stream_cache_hours: int = 2

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

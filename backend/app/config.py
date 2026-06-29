"""Application configuration using pydantic-settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application settings
    app_name: str = "Claude Deck"
    app_version: str = "2.0.1"
    debug: bool = False

    # API settings
    api_v1_prefix: str = "/api/v1"

    # CORS settings
    cors_origins: list[str] = ["http://localhost:5173"]
    cors_credentials: bool = True
    cors_methods: list[str] = ["*"]
    cors_headers: list[str] = ["*"]

    # Database settings
    database_url: str = "sqlite+aiosqlite:///./claude_registry.db"

    # Agent Bridge attachment settings
    bridge_attachment_dir: str = "~/.claude-registry/bridge-attachments"
    bridge_attachment_agent_root: str | None = None
    bridge_attachment_max_bytes: int = 10 * 1024 * 1024
    bridge_attachment_retention_days: int = 7
    bridge_attachment_max_per_session_per_day: int = 100

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000


# Global settings instance
settings = Settings()

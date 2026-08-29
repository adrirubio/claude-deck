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

    # GitHub integration (autonomous dispatch)
    github_token: str = ""
    github_app_id: str = ""
    github_app_private_key_path: str = ""
    github_app_bot_login: str = ""
    github_app_token_refresh_margin_seconds: int = 300
    github_dispatch_interval_seconds: int = 60
    github_check_signal_grace_seconds: int = 120
    github_owner_registration_grace_seconds: int = 120
    github_leader_ack_timeout_seconds: int = 300
    github_design_ack_multiplier: int = 3
    github_owner_idle_timeout_seconds: int = 900
    github_nudge_grace_seconds: int = 180
    github_min_available_memory_mb: int = 3000
    github_stale_lease_backstop_seconds: int = 21600
    github_brief_delivery_max_nudges: int = 2
    github_continuation_proposal_expiry_seconds: int = 3600
    github_continuation_leader_nudge_cooldown_seconds: int = 180
    github_continuation_owner_ack_nudge_cooldown_seconds: int = 180
    github_recovery_nudge_cooldown_seconds: int = 180

    # Agent Mail identity settings
    mail_capability_tokens_required: bool = False
    operator_token: str = ""

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000


# Global settings instance
settings = Settings()

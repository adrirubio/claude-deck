"""Application configuration using pydantic-settings."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application settings
    app_name: str = "Albiex Synth City"
    app_version: str = "4.0.0"
    debug: bool = False

    # API settings
    api_v1_prefix: str = "/api/v1"

    # CORS settings
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    cors_credentials: bool = True
    cors_methods: list[str] = ["*"]
    cors_headers: list[str] = ["*"]

    # Database settings
    database_url: str = Field(default="sqlite+aiosqlite:///./synth_city.db", repr=False)

    # Agent Bridge attachment settings
    bridge_attachment_dir: str = "~/.albiex-synth-city/bridge-attachments"
    bridge_attachment_agent_root: str | None = None
    bridge_attachment_max_bytes: int = 10 * 1024 * 1024
    bridge_attachment_retention_days: int = 7
    bridge_attachment_max_per_session_per_day: int = 100

    # GitHub integration (autonomous dispatch)
    github_token: str = Field(default="", repr=False)
    github_app_id: str = ""
    github_app_private_key_path: str = Field(default="", repr=False)
    github_app_bot_login: str = ""
    github_app_token_refresh_margin_seconds: int = 300
    github_dispatch_interval_seconds: int = 60
    github_check_signal_grace_seconds: int = 120
    github_owner_registration_grace_seconds: int = 120
    github_leader_ack_timeout_seconds: int = 300
    github_leader_ack_max_wait_seconds: int = Field(default=1800, ge=30, le=86400)
    github_design_ack_multiplier: int = 3
    github_owner_idle_timeout_seconds: int = 900
    github_team_idle_timeout_seconds: int = Field(default=1800, ge=30, le=86400)
    # A pending context request or handoff older than this, addressed to an idle member, is shown
    # as unanswered on the team summary and the Supervisor check-in (#752).
    mail_request_unanswered_seconds: int = Field(default=1200, ge=60, le=86400)
    github_nudge_grace_seconds: int = 180
    github_min_available_memory_mb: int = 3000
    github_stale_lease_backstop_seconds: int = 21600
    github_brief_delivery_max_nudges: int = 2
    github_continuation_proposal_expiry_seconds: int = 3600
    github_continuation_leader_nudge_cooldown_seconds: int = 180
    github_continuation_owner_ack_nudge_cooldown_seconds: int = 180
    github_recovery_nudge_cooldown_seconds: int = 180
    github_recovery_only_attempt: str = Field(default="", repr=False)
    # Existing external supervisors can supply their HOLD markers. Paths are never
    # exposed to agents or public coordination responses. Unreadable paths halt work.
    github_coordination_hold_paths: list[str] = Field(default_factory=list, repr=False)

    # Agent Mail identity settings
    mail_capability_tokens_required: bool = True
    operator_token: str = Field(default="", repr=False)

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000

    # Test instance (scripts/e2e-instance.sh). No dispatch scheduler, no
    # start-up relay cleanup (it signals every tmux client on the host) and no
    # GitHub network access. Never set this on a real installation.
    test_instance: bool = False
    # A test instance reports these on /health, so the E2E harness can refuse
    # a server that belongs to another run. Ignored unless test_instance is set.
    test_instance_root: str = Field(default="", repr=False)
    test_instance_token: str = Field(default="", repr=False)


# Global settings instance
settings = Settings()

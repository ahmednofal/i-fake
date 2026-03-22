"""Application settings loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="IFAKE_",
        extra="ignore",
        frozen=False,
    )

    # ── AI Provider ────────────────────────────────────────────────────────────
    ai_provider: Literal["gemini", "openai", "anthropic", "local"] = "gemini"

    # Google Gemini (free tier — https://aistudio.google.com/app/apikey)
    gemini_api_key: Optional[str] = Field(default=None)
    gemini_model: str = "gemini-2.5-flash"

    openai_api_key: Optional[str] = Field(default=None)
    openai_model: str = "gpt-4o"

    anthropic_api_key: Optional[str] = Field(default=None)
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # Local provider — any OpenAI-compatible endpoint (Ollama, llama.cpp, LM Studio)
    local_model_url: str = "http://localhost:11434/v1"
    local_model_name: str = "llama3"

    # ── Browser ────────────────────────────────────────────────────────────────
    headless: bool = True
    browser_type: Literal["chromium", "firefox", "webkit"] = "firefox"
    proxy_url: Optional[str] = None          # "http://user:pass@host:port"
    slow_mo_ms: int = 0                       # extra slow-mo (ms) — useful for debugging

    # Path to the *installed* Firefox binary (auto-detected if empty)
    firefox_executable: str = ""
    # Path to a real Firefox profile to copy cookies/localStorage from when
    # seeding a new persona profile.  Auto-detected from ~/.mozilla/firefox if empty.
    firefox_real_profile: str = ""

    # When set, ATTACH to an already-running browser via CDP instead of launching
    # a new one.  Set to the browser's remote debugging URL, e.g.:
    #   http://localhost:9222
    # Firefox: enable via about:config (remote.enabled=true, remote.active-protocols=3)
    #          then start with:  firefox --remote-debugging-port 9222
    # Chrome:  start with:  google-chrome --remote-debugging-port=9222
    attach_cdp_url: str = ""

    # ── Personas ───────────────────────────────────────────────────────────────
    personas_dir: Path = Field(
        default_factory=lambda: Path.home() / ".i_fake" / "personas"
    )
    max_active_personas: int = 5
    persona_rotation_days: int = 7

    # ── Scheduling ─────────────────────────────────────────────────────────────
    sessions_per_day: int = 3
    min_session_gap_minutes: int = 60

    # ── Paths / logging ────────────────────────────────────────────────────────
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".i_fake")
    log_level: str = "INFO"

    def ensure_dirs(self) -> None:
        for d in [
            self.data_dir,
            self.personas_dir,
            self.data_dir / "sessions",
            self.data_dir / "logs",
        ]:
            d.mkdir(parents=True, exist_ok=True)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

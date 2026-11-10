"""Settings loaded from the environment and `.env`."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """A required setting is missing for the chosen mode."""


class Settings(BaseSettings):
    """AutoPatch configuration. Secrets are `SecretStr` so they never print."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "anthropic/claude-sonnet-4.5"
    github_token: SecretStr = SecretStr("")
    sandbox_image: str = "autopatch-sandbox:latest"
    sandbox_timeout_seconds: int = 60
    sandbox_memory: str = "512m"
    max_attempts: int = 3
    max_context_chars: int = 30000
    runs_dir: str = "runs"
    work_dir: str = ""  # where working copies are created; empty = system temp dir

    def require_keys(self, dry_run: bool) -> None:
        """Fail fast if a key needed for this mode is missing."""
        missing = []
        if not self.openrouter_api_key.get_secret_value():
            missing.append("OPENROUTER_API_KEY")
        if not dry_run and not self.github_token.get_secret_value():
            missing.append("GITHUB_TOKEN (not needed with --dry-run)")
        if missing:
            raise ConfigError(
                "Missing required setting(s): " + ", ".join(missing)
                + ". Copy .env.example to .env and fill them in."
            )


settings = Settings()

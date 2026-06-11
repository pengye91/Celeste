"""
Unified environment configuration for the Celeste-DAG engine.

Uses pydantic-settings to provide a single source of truth for all
configuration, loading from environment variables and .env files.
"""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineSettings(BaseSettings):
    """Central configuration for the Celeste-DAG engine.

    All settings can be overridden via environment variables or a .env file
    in the working directory.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # --- Runtime environment ---
    ENVIRONMENT: Literal["local", "production"] = "local"

    # --- Database ---
    DATABASE_URL: SecretStr = SecretStr("sqlite+aiosqlite:///celeste.db")

    # --- Engine tuning ---
    MAX_PARALLEL_SUBPROCESSES: int = 4

    @field_validator("MAX_PARALLEL_SUBPROCESSES")
    @classmethod
    def _validate_max_parallel(cls, v: int) -> int:
        if v < 1 or v > 64:
            raise ValueError("MAX_PARALLEL_SUBPROCESSES must be between 1 and 64")
        return v

    # --- Environment Agent Protocol ---
    SNAPSHOT_TIMEOUT_MS: int = 5000
    SNAPSHOT_FULL_INTERVAL_CALLS: int = 10
    SNAPSHOT_FULL_INTERVAL_SECONDS: int = 300
    PLANNER_TIMEOUT_MS: int = 60000
    PLANNER_MAX_RETRIES: int = 2
    MAX_OPA_CYCLES: int = 100
    MAX_LLM_TOKENS: int = 50000
    OPA_HISTORY_MAX_CYCLES: int = 5
    EVALUATOR_CACHE_ENABLED: bool = True
    EVALUATOR_CACHE_TTL_SECONDS: int = 3600

    @field_validator("SNAPSHOT_TIMEOUT_MS", "PLANNER_TIMEOUT_MS")
    @classmethod
    def _validate_timeout_ms(cls, v: int) -> int:
        if v < 100:
            raise ValueError("timeout values must be >= 100")
        return v

    @field_validator("MAX_OPA_CYCLES")
    @classmethod
    def _validate_max_opa_cycles(cls, v: int) -> int:
        if v < 1:
            raise ValueError("MAX_OPA_CYCLES must be >= 1")
        return v

    @field_validator("MAX_LLM_TOKENS")
    @classmethod
    def _validate_max_llm_tokens(cls, v: int) -> int:
        if v < 1000:
            raise ValueError("MAX_LLM_TOKENS must be >= 1000")
        return v

    @field_validator("OPA_HISTORY_MAX_CYCLES")
    @classmethod
    def _validate_opa_history_max_cycles(cls, v: int) -> int:
        if v < 0:
            raise ValueError("OPA_HISTORY_MAX_CYCLES must be >= 0")
        return v

    @field_validator("PLANNER_MAX_RETRIES")
    @classmethod
    def _validate_planner_max_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError("PLANNER_MAX_RETRIES must be >= 0")
        return v

    STRICT_SECURITY_MODE: bool = True

    # --- Workspace isolation ---
    WORKSPACE_ENGINE: Literal["local_tmp", "git_worktree", "docker", "firecracker"] = "local_tmp"

    # --- LLM configuration ---
    LLM_PROVIDER: Literal["anthropic", "openai", "gemini", "ollama"] = "anthropic"
    LLM_MODEL: str = "claude-3-5-sonnet-20241022"
    LLM_API_KEY: SecretStr | None = None
    LLM_BASE_URL: str | None = None


# --- Singleton accessor ---

_settings: EngineSettings | None = None


def get_settings() -> EngineSettings:
    """Return the cached EngineSettings singleton.

    Creates the instance on first call, then returns the same object
    on every subsequent call.
    """
    global _settings
    if _settings is None:
        _settings = EngineSettings()
    return _settings


def reset_settings() -> None:
    """Reset the cached singleton so the next get_settings() call creates a fresh instance."""
    global _settings
    _settings = None

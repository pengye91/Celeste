"""
Tests for config/settings.py — EngineSettings and get_settings().

Follows strict TDD: these tests are written BEFORE the implementation.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from celeste_dag.config.settings import EngineSettings, get_settings, reset_settings


# ---------------------------------------------------------------------------
# Autouse fixture: reset singleton before every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    """Ensure the settings singleton is reset before each test."""
    reset_settings()
    yield
    reset_settings()


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

class TestDefaults:
    """All fields must have correct default values."""

    def test_default_environment(self) -> None:
        s = EngineSettings()
        assert s.ENVIRONMENT == "local"

    def test_snapshot_timeout_ms_default(self) -> None:
        s = EngineSettings()
        assert s.SNAPSHOT_TIMEOUT_MS == 5000

    def test_planner_timeout_ms_default(self) -> None:
        s = EngineSettings()
        assert s.PLANNER_TIMEOUT_MS == 60000

    def test_max_opa_cycles_default(self) -> None:
        s = EngineSettings()
        assert s.MAX_OPA_CYCLES == 100

    def test_max_llm_tokens_default(self) -> None:
        s = EngineSettings()
        assert s.MAX_LLM_TOKENS == 50000

    def test_evaluator_cache_enabled_default(self) -> None:
        s = EngineSettings()
        assert s.EVALUATOR_CACHE_ENABLED is True

    def test_default_database_url(self) -> None:
        s = EngineSettings()
        assert s.DATABASE_URL.get_secret_value() == "sqlite+aiosqlite:///celeste.db"

    def test_default_max_parallel_subprocesses(self) -> None:
        s = EngineSettings()
        assert s.MAX_PARALLEL_SUBPROCESSES == 4

    def test_default_strict_security_mode(self) -> None:
        s = EngineSettings()
        assert s.STRICT_SECURITY_MODE is True

    def test_default_workspace_engine(self) -> None:
        s = EngineSettings()
        assert s.WORKSPACE_ENGINE == "local_tmp"

    def test_default_llm_provider(self) -> None:
        s = EngineSettings()
        assert s.LLM_PROVIDER == "anthropic"

    def test_default_llm_model(self) -> None:
        s = EngineSettings()
        assert s.LLM_MODEL == "claude-3-5-sonnet-20241022"

    def test_default_llm_api_key_is_none(self) -> None:
        s = EngineSettings()
        assert s.LLM_API_KEY is None

    def test_default_llm_base_url_is_none(self) -> None:
        s = EngineSettings()
        assert s.LLM_BASE_URL is None


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------

class TestEnvOverrides:
    """Settings must be overridable via environment variables."""

    def test_environment_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        s = EngineSettings()
        assert s.ENVIRONMENT == "production"

    def test_database_url_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
        s = EngineSettings()
        assert s.DATABASE_URL.get_secret_value() == "postgresql+asyncpg://user:pass@localhost/db"

    def test_max_parallel_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_PARALLEL_SUBPROCESSES", "16")
        s = EngineSettings()
        assert s.MAX_PARALLEL_SUBPROCESSES == 16

    def test_strict_security_override_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRICT_SECURITY_MODE", "false")
        s = EngineSettings()
        assert s.STRICT_SECURITY_MODE is False

    def test_strict_security_override_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRICT_SECURITY_MODE", "true")
        s = EngineSettings()
        assert s.STRICT_SECURITY_MODE is True

    def test_workspace_engine_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSPACE_ENGINE", "docker")
        s = EngineSettings()
        assert s.WORKSPACE_ENGINE == "docker"

    def test_llm_provider_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        s = EngineSettings()
        assert s.LLM_PROVIDER == "openai"

    def test_llm_model_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        s = EngineSettings()
        assert s.LLM_MODEL == "gpt-4o"

    def test_llm_api_key_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_API_KEY", "sk-test-secret-key")
        s = EngineSettings()
        assert s.LLM_API_KEY is not None
        assert s.LLM_API_KEY.get_secret_value() == "sk-test-secret-key"

    def test_llm_base_url_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
        s = EngineSettings()
        assert s.LLM_BASE_URL == "http://localhost:11434"


# ---------------------------------------------------------------------------
# .env file loading
# ---------------------------------------------------------------------------

class TestEnvFile:
    """Settings must load from a .env file."""

    def test_load_from_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "ENVIRONMENT=production\n"
            "LLM_PROVIDER=gemini\n"
            "LLM_MODEL=gemini-2.0-flash\n"
            "LLM_API_KEY=sk-from-env-file\n"
        )
        monkeypatch.chdir(tmp_path)
        # Clear any env vars that might interfere
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        s = EngineSettings(_env_file=str(env_file))
        assert s.ENVIRONMENT == "production"
        assert s.LLM_PROVIDER == "gemini"
        assert s.LLM_MODEL == "gemini-2.0-flash"
        assert s.LLM_API_KEY is not None
        assert s.LLM_API_KEY.get_secret_value() == "sk-from-env-file"


# ---------------------------------------------------------------------------
# Validation errors for Literal fields
# ---------------------------------------------------------------------------

class TestValidation:
    """Invalid values must raise ValidationError."""

    def test_invalid_environment(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(ENVIRONMENT="staging")

    def test_invalid_workspace_engine(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(WORKSPACE_ENGINE="kubernetes")

    def test_invalid_llm_provider(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(LLM_PROVIDER="azure")

    def test_invalid_max_parallel_not_int(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(MAX_PARALLEL_SUBPROCESSES="not_a_number")

    def test_invalid_strict_security_not_bool(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(STRICT_SECURITY_MODE="not_a_bool")

    def test_valid_environment_local(self) -> None:
        s = EngineSettings(ENVIRONMENT="local")
        assert s.ENVIRONMENT == "local"

    def test_valid_environment_production(self) -> None:
        s = EngineSettings(ENVIRONMENT="production")
        assert s.ENVIRONMENT == "production"

    def test_valid_workspace_engines(self) -> None:
        for engine in ("local_tmp", "git_worktree", "docker", "firecracker"):
            s = EngineSettings(WORKSPACE_ENGINE=engine)
            assert s.WORKSPACE_ENGINE == engine

    def test_valid_llm_providers(self) -> None:
        for provider in ("anthropic", "openai", "gemini", "ollama"):
            s = EngineSettings(LLM_PROVIDER=provider)
            assert s.LLM_PROVIDER == provider

    def test_snapshot_timeout_validation(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(SNAPSHOT_TIMEOUT_MS=50)

    def test_max_opa_cycles_validation(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(MAX_OPA_CYCLES=0)


# ---------------------------------------------------------------------------
# MAX_PARALLEL_SUBPROCESSES bounds validation
# ---------------------------------------------------------------------------

class TestMaxParallelBounds:
    """MAX_PARALLEL_SUBPROCESSES must be between 1 and 64 inclusive."""

    def test_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(MAX_PARALLEL_SUBPROCESSES=0)

    def test_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(MAX_PARALLEL_SUBPROCESSES=-1)

    def test_above_64_raises(self) -> None:
        with pytest.raises(ValidationError):
            EngineSettings(MAX_PARALLEL_SUBPROCESSES=100)

    def test_one_is_valid(self) -> None:
        s = EngineSettings(MAX_PARALLEL_SUBPROCESSES=1)
        assert s.MAX_PARALLEL_SUBPROCESSES == 1

    def test_64_is_valid(self) -> None:
        s = EngineSettings(MAX_PARALLEL_SUBPROCESSES=64)
        assert s.MAX_PARALLEL_SUBPROCESSES == 64


# ---------------------------------------------------------------------------
# DATABASE_URL is SecretStr
# ---------------------------------------------------------------------------

class TestDatabaseUrlSecret:
    """DATABASE_URL must be a SecretStr that hides in repr."""

    def test_database_url_is_secret_str(self) -> None:
        s = EngineSettings(DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db")
        assert s.DATABASE_URL.get_secret_value() == "postgresql+asyncpg://user:pass@localhost/db"

    def test_database_url_hidden_in_repr(self) -> None:
        s = EngineSettings(DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db")
        repr_str = repr(s)
        assert "postgresql+asyncpg://user:pass@localhost/db" not in repr_str

    def test_database_url_hidden_in_model_dump(self) -> None:
        s = EngineSettings(DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db")
        dumped = s.model_dump()
        assert "postgresql+asyncpg://user:pass@localhost/db" not in str(dumped)


# ---------------------------------------------------------------------------
# SecretStr for LLM_API_KEY
# ---------------------------------------------------------------------------

class TestSecretStr:
    """LLM_API_KEY must be a SecretStr that hides in repr."""

    def test_api_key_is_secret_str(self) -> None:
        s = EngineSettings(LLM_API_KEY="sk-super-secret")
        assert s.LLM_API_KEY is not None
        assert s.LLM_API_KEY.get_secret_value() == "sk-super-secret"

    def test_api_key_hidden_in_repr(self) -> None:
        s = EngineSettings(LLM_API_KEY="sk-super-secret")
        repr_str = repr(s)
        assert "sk-super-secret" not in repr_str

    def test_api_key_hidden_in_model_dump(self) -> None:
        s = EngineSettings(LLM_API_KEY="sk-super-secret")
        dumped = s.model_dump()
        assert "sk-super-secret" not in str(dumped)


# ---------------------------------------------------------------------------
# get_settings() singleton
# ---------------------------------------------------------------------------

class TestGetSettings:
    """get_settings() must return a cached singleton."""

    def test_returns_same_instance(self) -> None:
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_returns_engine_settings_instance(self) -> None:
        s = get_settings()
        assert isinstance(s, EngineSettings)

    def test_singleton_reset(self) -> None:
        s1 = get_settings()
        # Reset and get again
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2


# ---------------------------------------------------------------------------
# reset_settings() public API
# ---------------------------------------------------------------------------

class TestResetSettings:
    """reset_settings() must clear the singleton."""

    def test_reset_clears_singleton(self) -> None:
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2

    def test_reset_is_idempotent(self) -> None:
        reset_settings()
        reset_settings()  # should not raise
        s = get_settings()
        assert isinstance(s, EngineSettings)


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------

class TestModelConfig:
    """Verify the model_config is set correctly."""

    def test_env_file_config(self) -> None:
        config = EngineSettings.model_config
        assert "env_file" in config
        assert config["env_file"] == ".env"

    def test_env_file_encoding(self) -> None:
        config = EngineSettings.model_config
        assert config.get("env_file_encoding") == "utf-8"


# ---------------------------------------------------------------------------
# Re-exports from config/__init__.py
# ---------------------------------------------------------------------------

class TestReexports:
    """Public API must be re-exported from config/__init__.py."""

    def test_engine_settings_reexported(self) -> None:
        from celeste_dag.config import EngineSettings as ES
        assert ES is EngineSettings

    def test_get_settings_reexported(self) -> None:
        from celeste_dag.config import get_settings as gs
        assert gs is get_settings

    def test_reset_settings_reexported(self) -> None:
        from celeste_dag.config import reset_settings as rs
        assert rs is reset_settings

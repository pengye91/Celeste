"""
Test that all declared project dependencies are importable.

This is the most fundamental test: if dependencies cannot be imported,
nothing else can work. It catches packaging issues, missing dependencies,
and version incompatibilities early.
"""

import importlib

import pytest


# --- Core web framework ---
@pytest.mark.parametrize("module_name", ["fastapi", "uvicorn"])
def test_web_framework_imports(module_name: str) -> None:
    """FastAPI and uvicorn must be importable."""
    importlib.import_module(module_name)


# --- Async HTTP client ---
def test_httpx_import() -> None:
    """httpx is the async HTTP client used throughout the project."""
    import httpx

    # Verify async client exists (critical for the engine)
    assert hasattr(httpx, "AsyncClient")


# --- Data validation ---
@pytest.mark.parametrize("module_name", ["pydantic", "pydantic_settings"])
def test_pydantic_imports(module_name: str) -> None:
    """Pydantic v2 and pydantic-settings must be importable."""
    mod = importlib.import_module(module_name)
    # Verify we have pydantic v2+
    if module_name == "pydantic":
        version = getattr(mod, "VERSION", "0")
        major = int(version.split(".")[0])
        assert major >= 2, f"pydantic must be >= 2.0, got {version}"


# --- Database ---
@pytest.mark.parametrize(
    "module_name", ["sqlalchemy", "aiosqlite"]
)
def test_database_imports(module_name: str) -> None:
    """SQLAlchemy (with async support) and async SQLite driver must be importable."""
    mod = importlib.import_module(module_name)
    if module_name == "sqlalchemy":
        version = getattr(mod, "__version__", "0")
        major = int(version.split(".")[0])
        assert major >= 2, f"sqlalchemy must be >= 2.0, got {version}"


def test_sqlalchemy_async_extension() -> None:
    """The sqlalchemy[asyncio] extra must be installed."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        create_async_engine,
    )

    assert callable(create_async_engine)
    assert AsyncSession is not None


def test_asyncpg_import() -> None:
    """asyncpg is the async PostgreSQL driver."""
    import asyncpg

    assert hasattr(asyncpg, "connect")


# --- LLM SDKs ---
@pytest.mark.parametrize(
    "module_name", ["anthropic", "openai", "google.generativeai"]
)
def test_llm_sdk_imports(module_name: str) -> None:
    """All LLM provider SDKs must be importable."""
    mod = importlib.import_module(module_name)
    assert mod is not None


# --- Test tooling ---
@pytest.mark.parametrize("module_name", ["pytest", "pytest_asyncio"])
def test_dev_dependencies_importable(module_name: str) -> None:
    """Dev dependencies (pytest, pytest-asyncio) must be available."""
    importlib.import_module(module_name)


# --- Project package ---
def test_project_package_importable() -> None:
    """The celeste package itself must be importable after install."""
    import celeste

    assert celeste is not None

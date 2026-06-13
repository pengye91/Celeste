"""Regression tests for PHARMA-2 / PHARMA-13.

These tests assert that the pharma example's configuration sources are
consistent with each other. The audit found that celeste_config.yml is
never loaded by EngineSettings — the engine only reads .env / env vars.
The fix is either to delete the dead YAML or document the .env-only model.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PHARMA_DIR = REPO_ROOT / "examples" / "pharma-coldchain"
PHARMA_YAML = PHARMA_DIR / "celeste_config.yml"
PHARMA_README = PHARMA_DIR / "README.md"
PHARMA_RUN_LOCAL = PHARMA_DIR / "run_local.py"


@pytest.fixture
def fresh_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip celeste-related env vars so EngineSettings uses only its defaults."""
    for key in list(os.environ):
        if key.startswith(
            ("DATABASE_URL", "LLM_", "MAX_", "OPA_", "SNAPSHOT_", "PLANNER_",
             "EVALUATOR_", "WORKSPACE_", "REDIS_URL", "ENVIRONMENT")
        ):
            monkeypatch.delenv(key, raising=False)


def test_pharma2_no_celeste_config_yml_or_it_is_documented_as_dead() -> None:
    """The pharma example must not ship a celeste_config.yml that the engine
    silently ignores.

    EngineSettings (src/celeste/config/settings.py) only reads .env and env
    vars. Either celeste_config.yml must be gone, or — if it remains — its
    top-of-file header must clearly state that it is documentation only
    and not loaded by the engine.
    """
    if not PHARMA_YAML.is_file():
        return  # deleted — that's a valid resolution.

    text = PHARMA_YAML.read_text().lower()
    # Either the file says "not loaded" / "documentation only" / "deprecated"
    claimed_loaded = (
        "all values can be overridden via environment variables or a .env file"
        in text
    )
    claimed_dead = any(
        phrase in text
        for phrase in (
            "not loaded by the engine",
            "documentation only",
            "deprecated",
            "not currently loaded",
        )
    )
    assert not (claimed_loaded and not claimed_dead), (
        f"{PHARMA_YAML.name} claims to be loaded but EngineSettings does "
        "not read it. Either delete it or update its header to clearly "
        "say it is documentation only."
    )


def test_pharma13_run_local_does_not_suggest_yaml_config() -> None:
    """run_local.py must not direct users to a YAML file the engine ignores."""
    text = PHARMA_RUN_LOCAL.read_text()
    # run_local.py must not reference the dead YAML file by name
    assert "celeste_config.yml" not in text, (
        "run_local.py references celeste_config.yml, which EngineSettings "
        "never loads. Users following that pointer will be confused."
    )


def test_pharma_readme_does_not_advertise_celeste_config_yml() -> None:
    """The README must not advertise celeste_config.yml as the config source
    (unless the README explicitly disclaims it)."""
    text = PHARMA_README.read_text()
    if "celeste_config.yml" not in text:
        return  # README doesn't mention it — fine.
    # If it is mentioned, the surrounding context must disclaim it as dead.
    lower = text.lower()
    assert (
        "not loaded" in lower
        or "deprecated" in lower
        or "documentation only" in lower
        or "ignored" in lower
    ), (
        "README references celeste_config.yml but does not disclaim it as "
        "not loaded. Either remove the reference or add a 'not loaded' "
        "disclaimer."
    )
"""Regression tests for DX-002, DX-003, PHARMA-7, PHARMA-10.

These tests assert that the pharma example documentation matches the
runtime behavior so contributors are not misled. Each test corresponds
to a specific audit finding ID.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Locations of the docs we are auditing.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_README = REPO_ROOT / "README.md"
PHARMA_README = REPO_ROOT / "examples" / "pharma-coldchain" / "README.md"
PHARMA_RUN_LOCAL = REPO_ROOT / "examples" / "pharma-coldchain" / "run_local.py"
PHARMA_DOCKER_COMPOSE = REPO_ROOT / "examples" / "pharma-coldchain" / "docker-compose.yml"
PHARMA_ENV_EXAMPLE = REPO_ROOT / "examples" / "pharma-coldchain" / ".env.example"
PHARMA_TOOLS_DIR = REPO_ROOT / "examples" / "pharma-coldchain" / "tools"
PHARMA_UNDERSCORE_TOOLS_DIR = REPO_ROOT / "examples" / "pharma_coldchain" / "tools"


# ---------------------------------------------------------------------------
# DX-002: docs must reference LLM_API_KEY, not provider-specific env vars.
# ---------------------------------------------------------------------------

# Files that should NOT advertise ANTHROPIC_API_KEY/OPENAI_API_KEY/GOOGLE_API_KEY.
DX002_TARGETS = [
    MAIN_README,
    PHARMA_README,
    PHARMA_RUN_LOCAL,
    PHARMA_DOCKER_COMPOSE,
    PHARMA_ENV_EXAMPLE,
]


@pytest.mark.parametrize("path", DX002_TARGETS, ids=lambda p: p.name)
def test_dx002_no_provider_specific_env_vars(path: Path) -> None:
    """Docs must not advertise ANTHROPIC_API_KEY/OPENAI_API_KEY/GOOGLE_API_KEY.

    The engine only reads LLM_API_KEY (see celeste/config/settings.py:99).
    Provider-specific env vars are silently ignored. Showing them in docs
    causes silent auth failures.
    """
    assert path.is_file(), f"missing fixture: {path}"
    text = path.read_text()
    forbidden = re.findall(r"\b(ANTHROPIC_API_KEY|OPENAI_API_KEY|GOOGLE_API_KEY)\b", text)
    assert not forbidden, (
        f"{path.name} still references provider-specific env vars "
        f"(LLM_API_KEY is the only env var the engine reads): {forbidden}"
    )


def test_dx002_pharma_readme_references_llm_api_key() -> None:
    """The pharma README should advertise LLM_API_KEY as the canonical key."""
    text = PHARMA_README.read_text()
    assert "LLM_API_KEY" in text, (
        "pharma README should reference LLM_API_KEY; it is the only key the "
        "engine reads"
    )


# ---------------------------------------------------------------------------
# DX-003: README test count must match reality. The audit found 823 tests;
# the README still claims 693. We assert the badge matches pytest's actual
# collected count (or, at minimum, is not the stale 693).
# ---------------------------------------------------------------------------


def test_dx003_main_readme_test_count_not_stale() -> None:
    """The README badge/test count must not be the stale "693" value."""
    text = MAIN_README.read_text()
    # The stale "693" must be gone from the README. The new value should
    # match what pytest actually collects (which we do not run here to keep
    # this test hermetic; the test simply asserts the stale value is removed).
    assert "693" not in text, (
        "README still claims '693 tests passing'; this is stale "
        "(see docs/audit-2026-06-13.json finding DX-003). Update to the "
        "current count or remove the badge."
    )


# ---------------------------------------------------------------------------
# PHARMA-7: README claims tools/ lives at examples/pharma-coldchain/tools/
# but the actual module is at examples/pharma_coldchain/tools/. Either the
# docs must be honest or the directory must exist. We assert the docs reflect
# reality.
# ---------------------------------------------------------------------------


def test_pharma7_tools_directory_documented_consistently_with_reality() -> None:
    """The pharma README's directory tree must match the actual filesystem.

    The audit found a contradiction: README shows tools/ at the hyphenated
    path, but the actual Python module uses the underscore path because
    hyphens are illegal in module names. We allow two acceptable resolutions:
      (a) README corrects the path to the underscore form, OR
      (b) a tools/ directory exists at the hyphenated path.
    """
    text = PHARMA_README.read_text()
    # The README's directory tree block always lists "tools/" with cold_chain.py etc.
    has_hyphen_tools_dir = bool(re.search(r"pharma-coldchain/tools", text))
    tools_dir_exists = PHARMA_TOOLS_DIR.is_dir()
    underscore_tools_exist = PHARMA_UNDERSCORE_TOOLS_DIR.is_dir()

    assert underscore_tools_exist, "expected underscore tools dir to exist"
    if has_hyphen_tools_dir:
        # README claims the hyphenated dir exists — it must actually exist.
        assert tools_dir_exists, (
            "README references examples/pharma-coldchain/tools/ but the "
            "directory does not exist. Either create the directory or fix "
            "the README to point at examples/pharma_coldchain/tools/."
        )


# ---------------------------------------------------------------------------
# PHARMA-10: README claims "47 nodes, 23 OPA cycles" as if they were runtime
# guarantees. They are aspirational — replace with a dynamic description.
# ---------------------------------------------------------------------------


def test_pharma10_no_hardcoded_node_or_cycle_counts() -> None:
    """The README must not advertise fixed node/cycle counts.

    The pharma scenario is LLM-driven; node count and cycle count vary per
    run. Static numbers like "47 nodes, 23 OPA cycles" mislead readers.
    """
    text = PHARMA_README.read_text()
    # Allow any of: "47 nodes", "23 OPA cycles", "47 nodes, 23 OPA cycles"
    has_node_count = re.search(r"\b47\s+nodes?\b", text, flags=re.IGNORECASE)
    has_cycle_count = re.search(r"\b23\s+opa\s+cycles?\b", text, flags=re.IGNORECASE)
    assert not has_node_count, (
        "README still advertises '47 nodes' as if it were a runtime "
        "guarantee; the pharma scenario generates nodes dynamically per "
        "LLM call."
    )
    assert not has_cycle_count, (
        "README still advertises '23 OPA cycles' as if it were a runtime "
        "guarantee; the OPA loop runs until goal_achieved or max_cycles."
    )
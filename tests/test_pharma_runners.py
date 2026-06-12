"""Tests for the pharma cold-chain example runner scripts.

Follows strict TDD. Covers:
- run_local.py imports and function signatures
- run_remote.py stub imports and function signatures
- run_embedded.py stub imports and function signatures
- verify.py imports and evaluate_workflow wrapper
- All runner scripts import cleanly without side effects at module level
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import tests — verify all scripts can be imported cleanly
# ---------------------------------------------------------------------------


def _add_example_to_path() -> None:
    """Ensure the example directory is on sys.path for imports."""
    example_dir = str(
        Path(__file__).resolve().parent.parent
        / "examples"
        / "pharma-coldchain"
    )
    if example_dir not in sys.path:
        sys.path.insert(0, example_dir)


class TestRunLocal:
    """Tests for run_local.py — local mode pharma scenario runner."""

    def test_import_cleanly(self):
        """run_local.py must import without raising exceptions at module level."""
        _add_example_to_path()
        # Importing run_local should not trigger execution (guarded by __name__)
        module = importlib.import_module("run_local")
        assert module is not None

    def test_run_pharma_local_function_exists(self):
        """run_local.py must export a run_pharma_local async function."""
        _add_example_to_path()
        import run_local

        assert hasattr(run_local, "run_pharma_local")
        assert callable(run_local.run_pharma_local)

    def test_run_pharma_local_signature(self):
        """run_pharma_local must accept optional database_url and api_key."""
        _add_example_to_path()
        import inspect
        import run_local

        sig = inspect.signature(run_local.run_pharma_local)
        params = list(sig.parameters.keys())
        # Should accept at least database_url and api_key as optional kwargs
        assert "database_url" in params or "kwargs" in str(sig)


class TestRunRemote:
    """Tests for run_remote.py — remote mode stub."""

    def test_import_cleanly(self):
        """run_remote.py must import without raising exceptions."""
        _add_example_to_path()
        module = importlib.import_module("run_remote")
        assert module is not None

    def test_run_pharma_remote_function_exists(self):
        """run_remote.py must export a run_pharma_remote async function."""
        _add_example_to_path()
        import run_remote

        assert hasattr(run_remote, "run_pharma_remote")
        assert callable(run_remote.run_pharma_remote)


class TestRunEmbedded:
    """Tests for run_embedded.py — embedded mode stub."""

    def test_import_cleanly(self):
        """run_embedded.py must import without raising exceptions."""
        _add_example_to_path()
        module = importlib.import_module("run_embedded")
        assert module is not None

    def test_run_pharma_embedded_function_exists(self):
        """run_embedded.py must export a run_pharma_embedded async function."""
        _add_example_to_path()
        import run_embedded

        assert hasattr(run_embedded, "run_pharma_embedded")
        assert callable(run_embedded.run_pharma_embedded)


class TestVerify:
    """Tests for verify.py — evaluation wrapper."""

    def test_import_cleanly(self):
        """verify.py must import without raising exceptions."""
        _add_example_to_path()
        module = importlib.import_module("verify")
        assert module is not None

    def test_verify_workflow_function_exists(self):
        """verify.py must export a verify_workflow async function."""
        _add_example_to_path()
        import verify

        assert hasattr(verify, "verify_workflow")
        assert callable(verify.verify_workflow)

    def test_verify_workflow_accepts_mode_flag(self):
        """verify_workflow must accept mode and workflow_id parameters."""
        _add_example_to_path()
        import inspect
        import verify

        sig = inspect.signature(verify.verify_workflow)
        params = list(sig.parameters.keys())
        assert "mode" in params, f"Expected 'mode' parameter, got {params}"
        assert "workflow_id" in params, f"Expected 'workflow_id' parameter, got {params}"


class TestRunnerIntegration:
    """Integration tests for runner scripts using mocked dependencies."""

    @pytest.mark.asyncio
    async def test_run_local_with_mocked_engine(self):
        """run_pharma_local should call Engine.run with mocked dependencies."""
        _add_example_to_path()
        import run_local

        # Patch the local Engine reference in run_local (imported at module
        # level, so we must patch run_local.Engine, not celeste.core.engine.Engine).
        with patch.object(
            run_local, "Engine", autospec=True
        ) as mock_engine_cls, patch.object(
            run_local, "_load_goal", return_value="Test goal"
        ), patch.object(
            run_local, "_build_llm_client",
            return_value=MagicMock(),
        ):
            mock_engine = MagicMock()
            mock_engine.start = AsyncMock()
            mock_engine.stop = AsyncMock()
            mock_engine.run = AsyncMock()
            mock_engine_cls.return_value = mock_engine

            result = await run_local.run_pharma_local(
                database_url="sqlite+aiosqlite:///test.db",
                api_key="sk-test",
            )

            assert result is not None
            mock_engine.start.assert_called_once()
            mock_engine.run.assert_called_once()
            mock_engine.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_with_mocked_evaluator(self):
        """verify_workflow should call celeste.evaluation.Evaluator."""
        _add_example_to_path()
        import verify

        # Patch the local Evaluator reference in verify (imported at module
        # level, so we must patch verify.Evaluator, not celeste.evaluation.Evaluator).
        with patch.object(
            verify, "Evaluator", autospec=True
        ) as mock_evaluator_cls:
            mock_evaluator = MagicMock()
            # evaluate() is async — return a MagicMock that quacks like a report
            mock_report = MagicMock()
            mock_report.overall = "PASS"
            mock_report.features = {}
            mock_report.warnings = []
            mock_report.token_cost = MagicMock()
            mock_report.token_cost.model_dump.return_value = {"total": 0}
            mock_evaluator.evaluate = AsyncMock(return_value=mock_report)
            mock_evaluator.assertions = MagicMock()
            mock_evaluator_cls.return_value = mock_evaluator

            result = await verify.verify_workflow(
                workflow_id="wf-test-001",
                mode="local",
            )

            assert result is not None
            mock_evaluator.evaluate.assert_called_once()

"""Cross-mode parity and model-agnosticism compliance checks.

These checks require data from multiple workflow runs and are therefore
best-effort when only a single workflow is available.
"""

from __future__ import annotations

from typing import Any

from celeste.evaluation.schemas import CrossModeEvidence, ModelAgnosticismEvidence


class ComplianceChecker:
    """Check compliance across execution modes and LLM providers."""

    def check_cross_mode(
        self,
        mode_results: dict[str, dict[str, Any]],
    ) -> CrossModeEvidence:
        """Compare results from Local, Remote, and Embedded modes.

        Args:
            mode_results: Mapping from mode name to result dict.
                Each result dict should contain a ``final_state_hash`` key.
        """
        hashes = {
            mode: data.get("final_state_hash", "")
            for mode, data in mode_results.items()
        }
        match = len(set(hashes.values())) == 1 if hashes else None
        return CrossModeEvidence(
            modes_tested=list(mode_results.keys()),
            state_hashes=hashes,
            match=match,
        )

    def check_model_agnosticism(
        self,
        provider_results: dict[str, dict[str, Any]],
    ) -> ModelAgnosticismEvidence:
        """Compare results from different LLM providers.

        Args:
            provider_results: Mapping from provider name to result dict.
                Each result dict should contain a ``final_state_hash`` key.
        """
        hashes = {
            provider: data.get("final_state_hash", "")
            for provider, data in provider_results.items()
        }
        match = len(set(hashes.values())) == 1 if hashes else None
        return ModelAgnosticismEvidence(
            providers_tested=list(provider_results.keys()),
            state_hashes=hashes,
            match=match,
        )

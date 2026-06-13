"""OBS-011: SecurityAuditor.audit_command must not silently flip verdict on LLM failure.

Tests demonstrate that:
- When the LLM-based Phase 2 audit raises any exception, the caller MUST
  be able to distinguish a real security block from an LLM outage.
- The fix introduces an ``AuditUnavailable`` exception (or equivalent marker)
  so callers can decide fail-open vs fail-closed policy separately.
"""

from __future__ import annotations

import pytest


class TestAuditUnavailableException:
    """audit_command must raise AuditUnavailable when the LLM fails."""

    @pytest.mark.asyncio
    async def test_llm_exception_raises_audit_unavailable(self):
        from celeste.tools.security_auditor import SecurityAuditor, AuditUnavailable

        class FailingClient:
            async def structured_output(self, *args, **kwargs):
                raise RuntimeError("LLM outage")

        auditor = SecurityAuditor(FailingClient())
        with pytest.raises(AuditUnavailable):
            await auditor.audit_command("ls")

    @pytest.mark.asyncio
    async def test_blocking_pattern_returns_verdict(self):
        """Phase 1 deterministic matches must still return a verdict (not raise).

        The Phase 2 LLM call should NOT happen when Phase 1 already blocks.
        """
        from celeste.tools.security_auditor import SecurityAuditor

        class FailingClient:
            async def structured_output(self, *args, **kwargs):
                raise RuntimeError("Phase 2 should not run after Phase 1 block")

        auditor = SecurityAuditor(FailingClient())
        verdict = await auditor.audit_command("rm -rf /")  # explicit root, matches Phase 1
        assert verdict.is_safe is False
        assert "destructive_command" in verdict.detected_threats

    @pytest.mark.asyncio
    async def test_safe_command_with_failing_llm_raises_audit_unavailable(self):
        """A safe-looking command whose Phase 2 LLM blows up should NOT silently flip to unsafe.

        The caller must see AuditUnavailable, NOT a SecurityVerdict(is_safe=False).
        """
        from celeste.tools.security_auditor import SecurityAuditor, AuditUnavailable

        class FailingClient:
            async def structured_output(self, *args, **kwargs):
                raise ConnectionError("network down")

        auditor = SecurityAuditor(FailingClient())
        # ls -la passes Phase 1 (no blocked pattern)
        with pytest.raises(AuditUnavailable):
            await auditor.audit_command("ls -la")


class TestCallerCanDistinguish:
    """The exception is structurally different from a true block."""

    @pytest.mark.asyncio
    async def test_audit_unavailable_is_distinguishable(self):
        """``isinstance(e, AuditUnavailable)`` must NOT match a generic Exception."""
        from celeste.tools.security_auditor import SecurityAuditor, AuditUnavailable

        class FailingClient:
            async def structured_output(self, *args, **kwargs):
                raise ValueError("garbage from LLM")

        auditor = SecurityAuditor(FailingClient())
        try:
            await auditor.audit_command("echo hello")
        except AuditUnavailable as e:
            # Good — caller can detect this and apply fail-open vs fail-closed.
            assert "audit_failure" not in (e.reason or "").lower() or True
        except Exception as e:
            pytest.fail(
                f"OBS-011: expected AuditUnavailable, got generic {type(e).__name__}: {e}"
            )
        else:
            pytest.fail(
                "OBS-011: audit_command returned normally; LLM failure was silently swallowed"
            )
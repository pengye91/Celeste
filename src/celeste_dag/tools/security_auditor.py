"""
Heuristic LLM Security Audit classifier.

Checks commands/actions BEFORE execution using a two-phase approach:
1. FAST: Deterministic regex check against known dangerous patterns.
2. DEEP: LLM-based heuristic classification for borderline commands.
"""

from __future__ import annotations

import re
from typing import Literal, cast

from pydantic import BaseModel

from celeste_dag.core.llm.base import BaseLLMClient, LLMMessage


class SecurityVerdict(BaseModel):
    """Result of a security audit."""

    is_safe: bool
    risk_level: Literal["safe", "low", "medium", "high", "critical"]
    reason: str
    detected_threats: list[str] = []


# ---------------------------------------------------------------------------
# Blocked pattern definitions
# ---------------------------------------------------------------------------

# Each entry is (compiled_regex, threat_name, default_risk_level).
# Order matters: more specific patterns should come first.
_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # --- Fork bomb ---
    (
        re.compile(r":\(\)\{.*:\|:&.*\}.*:"),
        "fork_bomb",
        "critical",
    ),
    # --- Dangerous destructive commands ---
    # Catches "rm -rf /", "rm -f /", "rm -fr /", etc. (I3: single pattern, no duplicate)
    (
        re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?/($|\s)", re.IGNORECASE),
        "destructive_command",
        "critical",
    ),
    (
        re.compile(r"\bmkfs\b", re.IGNORECASE),
        "destructive_command",
        "critical",
    ),
    (
        re.compile(r"\bdd\s+if=", re.IGNORECASE),
        "destructive_command",
        "critical",
    ),
    # --- Network exfiltration ---
    (
        re.compile(r"\bcurl\b.*\|\s*\bbase64\b", re.IGNORECASE),
        "network_exfiltration",
        "high",
    ),
    (
        re.compile(r"\bwget\b.*\|\s*sh\b", re.IGNORECASE),
        "network_exfiltration",
        "high",
    ),
    (
        re.compile(r"\bnc\s+-e\b", re.IGNORECASE),
        "reverse_shell",
        "critical",
    ),
    # --- Privilege escalation ---
    (
        re.compile(r"\bsudo\s+su\b", re.IGNORECASE),
        "privilege_escalation",
        "high",
    ),
    (
        re.compile(r"\bchmod\s+777\s+/", re.IGNORECASE),
        "privilege_escalation",
        "high",
    ),
    (
        re.compile(r"\bchown\s+root\b", re.IGNORECASE),
        "privilege_escalation",
        "high",
    ),
    # --- Path traversal ---
    (
        re.compile(r"\.\./"),
        "path_traversal",
        "high",
    ),
    # NOTE: Broad shell metacharacters (bare |, ;, &&, $(), backticks) are
    # intentionally NOT in Phase 1. They produce too many false positives on
    # legitimate shell usage. They will be caught by Phase 2 (LLM) if needed.
]


class SecurityAuditor:
    """Heuristic LLM Security Audit classifier.

    Uses a two-phase approach:
    1. **FAST** -- deterministic regex check against blocked patterns (no LLM).
    2. **DEEP** -- LLM-based heuristic classification for commands that pass
       the fast check.
    """

    def __init__(self, llm_client: BaseLLMClient) -> None:
        self._client = llm_client

    # ------------------------------------------------------------------
    # Phase 1: Deterministic check
    # ------------------------------------------------------------------

    def check_deterministic(self, command: str) -> SecurityVerdict | None:
        """Fast deterministic check against blocked patterns.

        Returns ``None`` if the command passes (no threats detected by regex).
        Returns a ``SecurityVerdict`` with ``is_safe=False`` if a blocked
        pattern is matched.
        """
        # Empty or whitespace-only commands are harmless
        stripped = command.strip()
        if not stripped:
            return None

        for pattern, threat_name, risk_level in _BLOCKED_PATTERNS:
            if pattern.search(stripped):
                return SecurityVerdict(
                    is_safe=False,
                    risk_level=cast(Literal["safe", "low", "medium", "high", "critical"], risk_level),
                    reason=f"Blocked pattern detected: {threat_name}",
                    detected_threats=[threat_name],
                )

        return None

    # ------------------------------------------------------------------
    # Phase 2: Full audit (deterministic + LLM)
    # ------------------------------------------------------------------

    async def audit_command(self, command: str, context: str = "") -> SecurityVerdict:
        """Audit a command for security threats.

        Two-phase check:
        1. FAST: Deterministic regex check against blocked patterns.
        2. DEEP: If the fast pass succeeds, use the LLM to classify safety.

        Returns a :class:`SecurityVerdict` indicating the result.
        """
        # Empty command is trivially safe
        if not command.strip():
            return SecurityVerdict(
                is_safe=True,
                risk_level="safe",
                reason="Empty command.",
            )

        # Phase 1: Deterministic check
        det_result = self.check_deterministic(command)
        if det_result is not None:
            return det_result

        # Phase 2: LLM-based heuristic classification
        system_prompt = (
            "You are a security auditor. Classify the following command "
            "for safety. Respond with a JSON object matching this schema: "
            '{"is_safe": bool, "risk_level": "safe"|"low"|"medium"|"high"|"critical", '
            '"reason": string, "detected_threats": [string]}. '
            "Only output the JSON object, no other text."
        )

        user_parts = [f"Command: {command}"]
        if context:
            user_parts.append(f"Context: {context}")
        user_content = "\n".join(user_parts)

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_content),
        ]

        try:
            result = await self._client.structured_output(
                messages=messages,
                response_model=SecurityVerdict,
            )
            return cast(SecurityVerdict, result)
        except Exception as e:
            return SecurityVerdict(
                is_safe=False,
                risk_level="high",
                reason=f"Security audit failed: {str(e)}",
                detected_threats=["audit_failure"],
            )

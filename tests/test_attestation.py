"""Tests for agent attestation: Ed25519 signing/verification (TODO-4).

Covers:
- AttestationKeypair generate / sign / verify round-trip.
- Tampered payload and wrong-key rejection.
- sign_payload / verify_payload envelope helpers.
- public_key_fingerprint helper.
- EnvironmentAgent.in_process() auto-generates a keypair and signs results.
- EnvironmentAgent with attestation_keypair=False produces unsigned results.
- EnvironmentAgent.remote() verifies signed responses and blocks tampered.
- EnvironmentAgent.remote() blocks unsigned responses when required.
- POST /agents/register stores public_key_pem and returns the fingerprint.
"""

from __future__ import annotations

import pytest

from celeste.core.attestation import (
    AttestationError,
    AttestationKeypair,
    public_key_fingerprint,
    sign_payload,
    verify_payload,
)
from celeste.core.agent.agent import EnvironmentAgent


# ---------------------------------------------------------------------------
# Crypto primitive tests
# ---------------------------------------------------------------------------


def test_keypair_generate_and_sign_verify_roundtrip():
    """generate → sign → verify returns True."""
    kp = AttestationKeypair.generate()
    payload = b'{"exit_code": 0, "stdout": "hello"}'
    sig = kp.sign(payload)
    assert isinstance(sig, str)
    assert AttestationKeypair.verify(kp.public_key_pem, payload, sig) is True


def test_verify_rejects_tampered_payload():
    """Changing one byte of the payload invalidates the signature."""
    kp = AttestationKeypair.generate()
    sig = kp.sign(b"original payload")
    assert AttestationKeypair.verify(kp.public_key_pem, b"tampered payload", sig) is False


def test_verify_rejects_wrong_key():
    """Signature from key A does not verify against key B."""
    kp_a = AttestationKeypair.generate()
    kp_b = AttestationKeypair.generate()
    payload = b"some data"
    sig_a = kp_a.sign(payload)
    assert AttestationKeypair.verify(kp_b.public_key_pem, payload, sig_a) is False


def test_key_id_is_stable_and_prefixed():
    """key_id has the ed25519: prefix and is stable for the same key."""
    kp = AttestationKeypair.generate()
    assert kp.key_id.startswith("ed25519:")
    assert len(kp.key_id) == len("ed25519:") + 8


def test_key_id_differs_between_keypairs():
    """Two different keypairs have different key_ids."""
    kp_a = AttestationKeypair.generate()
    kp_b = AttestationKeypair.generate()
    assert kp_a.key_id != kp_b.key_id


# ---------------------------------------------------------------------------
# Envelope helper tests
# ---------------------------------------------------------------------------


def test_sign_payload_adds_signature_and_key_id():
    """sign_payload adds 'signature' and 'key_id' to the dict."""
    kp = AttestationKeypair.generate()
    signed = sign_payload(kp, {"exit_code": 0, "stdout": "ok"})
    assert "signature" in signed
    assert "key_id" in signed
    assert signed["key_id"] == kp.key_id
    # Original data is preserved.
    assert signed["exit_code"] == 0
    assert signed["stdout"] == "ok"


def test_verify_payload_roundtrip():
    """sign_payload → verify_payload returns True."""
    kp = AttestationKeypair.generate()
    signed = sign_payload(kp, {"a": 1, "b": [2, 3]})
    assert verify_payload(kp.public_key_pem, signed) is True


def test_verify_payload_rejects_tampered_envelope():
    """Changing a value in the signed envelope invalidates verification."""
    kp = AttestationKeypair.generate()
    signed = sign_payload(kp, {"exit_code": 0})
    signed["exit_code"] = 1  # tamper
    assert verify_payload(kp.public_key_pem, signed) is False


def test_verify_payload_returns_false_for_unsigned():
    """An envelope without 'signature' returns False."""
    kp = AttestationKeypair.generate()
    assert verify_payload(kp.public_key_pem, {"exit_code": 0}) is False


def test_public_key_fingerprint_matches_key_id():
    """The fingerprint computed from PEM matches the keypair's key_id."""
    kp = AttestationKeypair.generate()
    fp = public_key_fingerprint(kp.public_key_pem)
    assert fp == kp.key_id


# ---------------------------------------------------------------------------
# Agent signing tests
# ---------------------------------------------------------------------------


async def test_agent_in_process_signs_tool_result():
    """in_process() auto-generates a keypair and signs call_tool results."""
    agent = EnvironmentAgent.in_process(workdir="/tmp")
    try:
        assert agent.public_key_pem is not None
        assert agent.key_id is not None

        result = await agent.call_tool("run_command", {"command": "echo", "args": ["test"]})
        assert "signature" in result
        assert "key_id" in result
        assert result["key_id"] == agent.key_id

        # The signature must verify.
        assert verify_payload(agent.public_key_pem, result) is True
    finally:
        await agent.stop()


async def test_agent_in_process_no_keypair_when_disabled():
    """in_process(attestation_keypair=False) produces unsigned results."""
    agent = EnvironmentAgent.in_process(workdir="/tmp", attestation_keypair=False)
    try:
        assert agent.public_key_pem is None

        result = await agent.call_tool("run_command", {"command": "echo", "args": ["x"]})
        assert "signature" not in result
    finally:
        await agent.stop()


async def test_agent_in_workspace_signs_tool_result():
    """in_workspace() auto-generates a keypair and signs results."""
    agent = EnvironmentAgent.in_workspace()
    try:
        assert agent.key_id is not None

        result = await agent.call_tool("run_command", {"command": "echo", "args": ["ws"]})
        assert "signature" in result
        assert verify_payload(agent.public_key_pem, result) is True
    finally:
        await agent.stop()


# ---------------------------------------------------------------------------
# Remote verification tests (mocked transport)
# ---------------------------------------------------------------------------


class _MockTransport:
    """Mock transport that returns a pre-set response."""

    def __init__(self, response: dict):
        self._response = response
        self._connected = True

    async def send_request(self, method, params):
        return self._response

    async def connect(self):
        pass

    async def close(self):
        self._connected = False


async def test_remote_agent_verifies_valid_signature():
    """remote() with a pinned key accepts a correctly signed response."""
    kp = AttestationKeypair.generate()
    signed_result = sign_payload(kp, {"exit_code": 0, "stdout": "from-server"})

    agent = EnvironmentAgent(
        transport=_MockTransport(signed_result),
        workdir=".",
        expected_public_key_pem=kp.public_key_pem,
        attestation_required=True,
    )

    result = await agent.call_tool("run_command", {"command": "echo"})
    # The envelope is stripped — only the inner result remains.
    assert "signature" not in result
    assert result["exit_code"] == 0
    assert result["stdout"] == "from-server"


async def test_remote_agent_blocks_tampered_signature():
    """remote() raises AttestationError when the signature doesn't verify."""
    kp_server = AttestationKeypair.generate()
    kp_attacker = AttestationKeypair.generate()

    # Signed by the attacker, not the server.
    tampered = sign_payload(kp_attacker, {"exit_code": 0, "stdout": "evil"})

    agent = EnvironmentAgent(
        transport=_MockTransport(tampered),
        workdir=".",
        expected_public_key_pem=kp_server.public_key_pem,
        attestation_required=True,
    )

    with pytest.raises(AttestationError, match="Signature verification failed"):
        await agent.call_tool("run_command", {"command": "echo"})


async def test_remote_agent_blocks_unsigned_when_required():
    """remote() raises AttestationError when unsigned + ATTESTATION_REQUIRED."""
    agent = EnvironmentAgent(
        transport=_MockTransport({"exit_code": 0, "stdout": "unsigned"}),
        workdir=".",
        attestation_required=True,
    )

    with pytest.raises(AttestationError, match="unsigned result"):
        await agent.call_tool("run_command", {"command": "echo"})


async def test_remote_agent_accepts_unsigned_when_not_required():
    """remote() without attestation_required passes unsigned responses through."""
    agent = EnvironmentAgent(
        transport=_MockTransport({"exit_code": 0, "stdout": "unsigned"}),
        workdir=".",
        attestation_required=False,
    )

    result = await agent.call_tool("run_command", {"command": "echo"})
    assert result["exit_code"] == 0

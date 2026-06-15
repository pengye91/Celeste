"""Agent attestation: Ed25519 signing/verification for agent outputs (TODO-4).

Each agent generates an Ed25519 keypair on first start. The agent signs every
audit verdict and tool-execution result it produces. The engine verifies
signatures against the agent's registered public key. If verification fails,
the tool call is blocked.

This closes the "compromised target environment can bypass agent-side audit"
gap: the engine has cryptographic proof that the agent actually ran its
audit, not just a bare assertion.

Design: self-signed keypair model. Each agent generates its own keypair,
publishes the public key via registration, and signs outputs. The engine
pins the public key at registration time. No external CA / Sigstore needed;
upgradeable later by replacing ``generate()`` with a Sigstore-backed flow.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature


class AttestationError(Exception):
    """Raised when signature verification fails or is required but missing."""


class AttestationKeypair:
    """Ed25519 keypair for signing agent outputs.

    Use :meth:`generate` to create a new keypair on agent first start, or
    :meth:`from_private_key_pem` to load a persisted key.
    """

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def generate(cls) -> "AttestationKeypair":
        """Generate a new Ed25519 keypair."""
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_private_key_pem(
        cls, pem: str, password: bytes | None = None
    ) -> "AttestationKeypair":
        """Load a keypair from a PEM-encoded private key (for persistence)."""
        key = serialization.load_pem_private_key(
            pem.encode() if isinstance(pem, str) else pem,
            password=password,
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Expected an Ed25519 private key")
        return cls(key)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def public_key_pem(self) -> str:
        """PEM-encoded public key (for registration / pinning)."""
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    @property
    def key_id(self) -> str:
        """Short fingerprint of the public key for identification.

        Format: ``ed25519:<8 hex chars>`` — the first 4 bytes of the
        SHA-256 hash of the DER-encoded public key.
        """
        der = self._public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        digest = hashlib.sha256(der).hexdigest()[:8]
        return f"ed25519:{digest}"

    # ------------------------------------------------------------------
    # Signing / verification
    # ------------------------------------------------------------------

    def sign(self, payload: bytes) -> str:
        """Sign a payload, return base64-encoded signature."""
        sig = self._private_key.sign(payload)
        return base64.b64encode(sig).decode("utf-8")

    @staticmethod
    def verify(public_key_pem: str, payload: bytes, signature_b64: str) -> bool:
        """Verify a signature against a public key.

        Returns True if the signature is valid, False otherwise. Never
        raises — callers use the boolean to decide whether to block.
        """
        try:
            pub_key = serialization.load_pem_public_key(
                public_key_pem.encode() if isinstance(public_key_pem, str) else public_key_pem,
            )
            if not isinstance(pub_key, Ed25519PublicKey):
                return False
            signature = base64.b64decode(signature_b64)
            pub_key.verify(signature, payload)
            return True
        except (InvalidSignature, ValueError, Exception):
            return False


# ---------------------------------------------------------------------------
# Signed envelope helpers
# ---------------------------------------------------------------------------

# The reserved keys that are NOT part of the signed payload — they are the
# envelope metadata added on top.
_ENVELOPE_KEYS = {"signature", "key_id"}


def _canonical_json(data: dict[str, Any]) -> bytes:
    """Serialize a dict to canonical JSON for signing.

    Keys are sorted and separators are compact so the signature is
    deterministic regardless of dict insertion order.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign_payload(keypair: AttestationKeypair, payload: dict[str, Any]) -> dict[str, Any]:
    """Add ``signature`` and ``key_id`` to a dict, signing its canonical JSON.

    The signature covers the payload WITHOUT the envelope keys, so the
    recipient strips ``signature`` / ``key_id`` and verifies the rest.

    Returns a new dict with the original keys plus ``signature`` and
    ``key_id``.
    """
    # Build the payload to sign (everything except envelope keys, if present).
    signing_data = {k: v for k, v in payload.items() if k not in _ENVELOPE_KEYS}
    canonical = _canonical_json(signing_data)
    signature = keypair.sign(canonical)
    return {**payload, "signature": signature, "key_id": keypair.key_id}


def verify_payload(public_key_pem: str, envelope: dict[str, Any]) -> bool:
    """Verify a signed envelope.

    Strips ``signature`` and ``key_id`` from the envelope, serializes the
    remaining keys to canonical JSON, and verifies the signature.

    Returns True if valid, False otherwise.
    """
    signature_b64 = envelope.get("signature")
    if not signature_b64:
        return False
    signing_data = {k: v for k, v in envelope.items() if k not in _ENVELOPE_KEYS}
    canonical = _canonical_json(signing_data)
    return AttestationKeypair.verify(public_key_pem, canonical, signature_b64)


def public_key_fingerprint(public_key_pem: str) -> str:
    """Compute the short fingerprint of a PEM public key.

    Useful for display (e.g. in the agents list UI) without exposing the
    full key.
    """
    der = serialization.load_pem_public_key(
        public_key_pem.encode() if isinstance(public_key_pem, str) else public_key_pem,
    ).public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return f"ed25519:{hashlib.sha256(der).hexdigest()[:8]}"

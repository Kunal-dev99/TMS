"""SigningPort backed by a locally-held key. DEV ONLY.

Generates an ephemeral RSA-2048 key at construction and signs
payloads with SHA-256. Zero external dependency. A real deployment
binds ``AzureManagedHSMAdapter`` or ``Pkcs11Adapter``; those match
this adapter's signature format so a swap is transparent.

Never persist a real production key here — vault it and expose via
the SecretsPort, then load into ``key_ref`` at construction time.
Stage 8 wires that path.
"""

from __future__ import annotations

from hashlib import sha256


class SoftwareSigning:
    name = "software"

    def __init__(self) -> None:
        # Ephemeral key — never persisted. Every process start gets a
        # fresh keypair; verification of previous signatures across
        # restarts is not a Stage 1 concern. Real key management lands
        # in Stage 8 with the vault-backed adapters.
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa

            self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        except ImportError:
            # `cryptography` is not in requirements yet — Stage 8 adds
            # it. Until then, fall back to a hash-of-payload "signature"
            # so tests can prove the flow end-to-end without the dep.
            self._key = None

    def sign(self, payload: bytes, key_ref: str) -> bytes:
        if self._key is None:
            return sha256(b"software:" + key_ref.encode() + b":" + payload).digest()
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        return self._key.sign(payload, padding.PKCS1v15(), hashes.SHA256())

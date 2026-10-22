"""API keys: generated once, shown once, stored as SHA-256 plus a short display prefix.

Keys carry 256 bits of randomness, so a fast unsalted hash is sufficient (no password-style KDF needed):
nobody can brute-force the preimage, and an indexed lookup by hash stays O(1).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

KEY_SCHEME = "rmcp_"
DISPLAY_PREFIX_LEN = len(KEY_SCHEME) + 8


@dataclass(frozen=True)
class NewApiKey:
    plaintext: str  # return to the caller once, never persist
    prefix: str
    key_hash: str


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def display_prefix(plaintext: str) -> str:
    return plaintext[:DISPLAY_PREFIX_LEN]


def generate_api_key() -> NewApiKey:
    plaintext = KEY_SCHEME + secrets.token_urlsafe(32)
    return NewApiKey(plaintext=plaintext, prefix=display_prefix(plaintext), key_hash=hash_api_key(plaintext))


def looks_like_api_key(value: str) -> bool:
    return value.startswith(KEY_SCHEME) and len(value) > DISPLAY_PREFIX_LEN

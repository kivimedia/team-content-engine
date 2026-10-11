"""Authenticated encryption for editorial text stored in the standalone database."""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator

PREFIX = "enc:v1:"


def _cipher() -> AESGCM:
    try:
        key = base64.b64decode(os.environ.get("TCE_STANDALONE_ENCRYPTION_KEY", ""), validate=True)
    except (ValueError, base64.binascii.Error):
        key = b""
    if len(key) != 32:
        raise RuntimeError("Standalone encryption key is unavailable")
    return AESGCM(key)


def encrypt_text(value: str | None, purpose: str) -> str | None:
    if value is None or value.startswith(PREFIX):
        return value
    nonce = secrets.token_bytes(12)
    sealed = nonce + _cipher().encrypt(nonce, value.encode(), purpose.encode())
    return PREFIX + base64.b64encode(sealed).decode()


def decrypt_text(value: str | None, purpose: str) -> str | None:
    if value is None or not value.startswith(PREFIX):
        return value  # Legacy rows remain readable until the migration backfills them.
    sealed = base64.b64decode(value[len(PREFIX):], validate=True)
    return _cipher().decrypt(sealed[:12], sealed[12:], purpose.encode()).decode()


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, purpose: str):
        super().__init__()
        self.purpose = purpose

    def process_bind_param(self, value, dialect):
        return encrypt_text(value, self.purpose)

    def process_result_value(self, value, dialect):
        return decrypt_text(value, self.purpose)

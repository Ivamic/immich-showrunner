# SPDX-License-Identifier: AGPL-3.0-or-later
"""Symmetric encryption of secrets stored in the database (the Immich key for writes)."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, secret_key: str) -> None:
        # Fernet needs exactly 32 url-safe base64 bytes; derive them from the configured secret.
        digest = hashlib.sha256(secret_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("cannot decrypt: wrong secret key or corrupted data") from exc


def hash_token(token: str) -> str:
    """Session tokens are stored hashed, so a database leak does not expose live sessions."""
    return hashlib.sha256(token.encode()).hexdigest()

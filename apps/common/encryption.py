"""
AES-256-GCM field-level encryption for sensitive data (e.g. MFA secrets, phone numbers).

Usage:
    from apps.common.encryption import encrypt_field, decrypt_field

    stored = encrypt_field("+256700123456")
    original = decrypt_field(stored)

The ENCRYPTION_KEY setting must be a URL-safe base64-encoded 32-byte value.
Generate one with:
    python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

The ``cryptography`` package is required. The application will refuse to start
without it — never silently fall back to a weaker cipher for sensitive fields.
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from django.conf import settings

_NONCE_SIZE = 12  # 96-bit nonce recommended for AES-GCM


def _get_key() -> bytes:
    """Decode and validate the 32-byte encryption key from settings."""
    raw = settings.ENCRYPTION_KEY
    if not raw:
        raise ValueError(
            "ENCRYPTION_KEY is not configured. "
            "Set it to a base64url-encoded 32-byte random value."
        )
    if isinstance(raw, str):
        raw = raw.encode("ascii")
    padding_needed = (4 - len(raw) % 4) % 4
    raw_padded = raw + b"=" * padding_needed
    key_bytes = base64.urlsafe_b64decode(raw_padded)
    if len(key_bytes) != 32:
        raise ValueError(
            f"ENCRYPTION_KEY must decode to exactly 32 bytes; got {len(key_bytes)}."
        )
    return key_bytes


def encrypt_field(plaintext: str) -> str:
    """Encrypt *plaintext* using AES-256-GCM. Returns a URL-safe base64-encoded token."""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext_with_tag).decode("ascii")


def decrypt_field(token: str) -> str:
    """
    Decrypt a token produced by *encrypt_field*.

    Raises ``ValueError`` if the token is malformed or the authentication tag
    does not verify (i.e. the data has been tampered with).
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii") + b"==")
    except Exception as exc:
        raise ValueError("Malformed encryption token.") from exc

    if len(raw) < _NONCE_SIZE + 16:  # nonce + minimum GCM tag length
        raise ValueError("Encryption token is too short.")

    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = raw[:_NONCE_SIZE]
    ciphertext_with_tag = raw[_NONCE_SIZE:]
    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
    except Exception as exc:
        raise ValueError("Decryption failed — token is invalid or has been tampered with.") from exc
    return plaintext_bytes.decode("utf-8")

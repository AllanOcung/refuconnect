"""
AES-256-GCM field-level encryption for sensitive data (e.g. phone numbers).

Usage:
    from apps.common.encryption import encrypt_field, decrypt_field

    stored = encrypt_field("+256700123456")
    original = decrypt_field(stored)

The ENCRYPTION_KEY setting must be a URL-safe base64-encoded 32-byte value.
Generate one with:
    python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

If the ``cryptography`` package is not installed (local development without it),
a HMAC-SHA256 based stub is used instead. The stub is NOT secure for production —
it provides confidentiality only if the key is secret. Never use in production.
"""
import base64
import os

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AESGCM = None  # type: ignore[assignment,misc]
    _CRYPTO_AVAILABLE = False

from django.conf import settings  # noqa: E402

_NONCE_SIZE = 12  # 96-bit nonce recommended for AES-GCM

# Stub prefix so tokens produced without cryptography are identifiable
_STUB_PREFIX = b"STUB:"


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
    # Add padding if needed for urlsafe_b64decode
    padding_needed = (4 - len(raw) % 4) % 4
    raw_padded = raw + b"=" * padding_needed
    key_bytes = base64.urlsafe_b64decode(raw_padded)
    if len(key_bytes) != 32:
        raise ValueError(
            f"ENCRYPTION_KEY must decode to exactly 32 bytes; got {len(key_bytes)}."
        )
    return key_bytes


def _get_key_or_none() -> bytes | None:
    """Return the key bytes, or None if ENCRYPTION_KEY is not set."""
    try:
        return _get_key()
    except ValueError:
        return None


def encrypt_field(plaintext: str) -> str:
    """
    Encrypt *plaintext* using AES-256-GCM when the ``cryptography`` package is
    available, otherwise use a HMAC-XOR stream-cipher stub.

    **The stub is NOT secure for production.** Install ``cryptography`` before
    deploying to any non-development environment.

    Returns a URL-safe base64-encoded token.
    """
    if _CRYPTO_AVAILABLE:
        key = _get_key()
        aesgcm = _AESGCM(key)
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        token = base64.urlsafe_b64encode(nonce + ciphertext_with_tag)
        return token.decode("ascii")

    # ── Stub path (no cryptography package) ──────────────────────────────────
    import hashlib
    import hmac as _hmac

    key = _get_key()
    nonce = os.urandom(_NONCE_SIZE)
    plaintext_bytes = plaintext.encode("utf-8")
    # XOR each byte with HMAC-SHA256 derived key stream (NOT authenticated)
    keystream = _hmac.new(key, nonce, hashlib.sha256).digest()
    # Extend keystream if plaintext is longer than 32 bytes
    while len(keystream) < len(plaintext_bytes):
        keystream += _hmac.new(key, keystream, hashlib.sha256).digest()
    cipher = bytes(a ^ b for a, b in zip(plaintext_bytes, keystream))
    raw = _STUB_PREFIX + nonce + cipher
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decrypt_field(token: str) -> str:
    """
    Decrypt a token previously produced by *encrypt_field*.

    Raises ``ValueError`` if the token is malformed or (AES-GCM mode only)
    the authentication tag does not verify.
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii") + b"==")
    except Exception as exc:
        raise ValueError("Malformed encryption token.") from exc

    # Detect which mode produced the token
    if raw.startswith(_STUB_PREFIX):
        # ── Stub path ─────────────────────────────────────────────────────
        import hashlib
        import hmac as _hmac

        body = raw[len(_STUB_PREFIX):]
        if len(body) < _NONCE_SIZE:
            raise ValueError("Encryption token is too short.")
        nonce = body[:_NONCE_SIZE]
        cipher = body[_NONCE_SIZE:]
        key = _get_key()
        keystream = _hmac.new(key, nonce, hashlib.sha256).digest()
        while len(keystream) < len(cipher):
            keystream += _hmac.new(key, keystream, hashlib.sha256).digest()
        plaintext_bytes = bytes(a ^ b for a, b in zip(cipher, keystream))
        return plaintext_bytes.decode("utf-8")

    # ── AES-GCM path ─────────────────────────────────────────────────────────
    if not _CRYPTO_AVAILABLE:
        raise ValueError(
            "Cannot decrypt an AES-GCM token: 'cryptography' package is not installed."
        )
    if len(raw) < _NONCE_SIZE + 16:  # nonce + minimum tag length
        raise ValueError("Encryption token is too short.")
    key = _get_key()
    aesgcm = _AESGCM(key)
    nonce = raw[:_NONCE_SIZE]
    ciphertext_with_tag = raw[_NONCE_SIZE:]
    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
    except Exception as exc:
        raise ValueError("Decryption failed — token is invalid or has been tampered with.") from exc
    return plaintext_bytes.decode("utf-8")

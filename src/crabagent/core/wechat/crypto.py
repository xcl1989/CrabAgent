"""AES-128-ECB encryption/decryption for iLink media payloads.

The iLink protocol uses AES-128-ECB for media (image/voice/file) encryption.
The key may arrive in three encoding formats — hex, base64, or raw string.
This module auto-detects and handles all three.
"""

from __future__ import annotations

import base64
import hashlib
import logging

logger = logging.getLogger(__name__)


def _normalize_key(key_data: str | bytes) -> bytes:
    """Normalise the encryption key to a 16-byte AES-128 key.

    The iLink protocol may supply the key as:
    1. **Hex string** — ``a1b2c3...`` (32 hex chars = 16 bytes)
    2. **Base64 string** — standard base64 encoding
    3. **Raw ASCII string** — used directly (truncated/padded to 16 bytes)

    Auto-detects format and returns a 16-byte key.
    """
    if isinstance(key_data, bytes):
        raw = key_data
    else:
        raw = key_data.encode("utf-8")

    # Try hex decode (exactly 32 hex chars → 16 bytes)
    try:
        text = key_data if isinstance(key_data, str) else key_data.decode("ascii", errors="ignore")
        if len(text) == 32 and all(c in "0123456789abcdefABCDEF" for c in text):
            return bytes.fromhex(text)
    except Exception:
        pass

    # Try base64 decode
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 16:
            return decoded
    except Exception:
        pass

    # Fallback: hash to 16 bytes
    return hashlib.md5(raw).digest()  # noqa: S324


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 16:
        return data  # No valid padding
    return data[:-pad_len]


def encrypt(plaintext: bytes, key: str | bytes) -> bytes:
    """AES-128-ECB encrypt ``plaintext`` with ``key``."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    k = _normalize_key(key)
    cipher = Cipher(algorithms.AES(k), modes.ECB())
    encryptor = cipher.encryptor()
    padded = _pkcs7_pad(plaintext)
    return encryptor.update(padded) + encryptor.finalize()


def decrypt(ciphertext: bytes, key: str | bytes) -> bytes:
    """AES-128-ECB decrypt ``ciphertext`` with ``key``."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    k = _normalize_key(key)
    cipher = Cipher(algorithms.AES(k), modes.ECB())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    return _pkcs7_unpad(padded)


def decrypt_base64(b64_ciphertext: str, key: str | bytes) -> bytes:
    """Convenience: decrypt a base64-encoded ciphertext."""
    return decrypt(base64.b64decode(b64_ciphertext), key)


def encrypt_to_base64(plaintext: bytes, key: str | bytes) -> str:
    """Convenience: encrypt and return base64-encoded string."""
    return base64.b64encode(encrypt(plaintext, key)).decode("ascii")

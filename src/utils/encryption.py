"""
src/utils/encryption.py

AES-256-GCM encryption/decryption for compressed video segments.

Government requirement (Cody Hayashi, NIWC Pacific):
    Segments stored on-device must be encrypted at rest.
    Decryption only occurs during authorised review.

File format (.enc):
    Bytes  0 –  11  : Nonce (random, 12 bytes)
    Bytes 12 –  27  : Salt (random, 16 bytes; used only in password mode)
    Bytes 28 –  43  : Auth tag (16 bytes, produced by GCM)
    Bytes 44 – end  : Ciphertext (AES-256-GCM, no padding)

Key modes:
    Password mode  — `password` arg; key = PBKDF2-HMAC-SHA256(password, salt, 600_000 iters)
    Raw-key mode   — `key` arg; must be exactly 32 bytes (256-bit); salt field is zeros

GCM authenticates the ciphertext with a 128-bit tag.  Any bit-flip or
truncation in the ciphertext is detected before a single byte of plaintext
is returned.  This is the primary difference from the previous CBC mode.

Usage:
    from utils.encryption import encrypt_file, decrypt_file, generate_key

    # Password-based (interactive / human-facing):
    encrypt_file("segment_001.mp4", password="s3cr3t")
    decrypt_file("segment_001.mp4.enc", password="s3cr3t")

    # Raw-key mode (programmatic / key-file):
    key = generate_key()                       # save this 32-byte value securely
    encrypt_file("segment_001.mp4", key=key)
    decrypt_file("segment_001.mp4.enc", key=key)

    # Key file:
    with open("camera.key", "rb") as f:
        key = f.read()
    encrypt_file("segment_001.mp4", key=key)

Security notes:
    - Each call to encrypt_file() generates a fresh nonce (and salt in password mode).
    - The original plaintext file is deleted after successful encryption.
    - GCM authentication prevents silent bit-flip attacks that CBC allows.
    - In password mode use a strong passphrase; PBKDF2 with 600k iterations makes
      brute-force expensive but a weak password is still a weak password.
    - Raw keys must be stored securely (HSM, encrypted key store, environment
      variable — NOT hard-coded in source).

Author: Bloodawn (KheivenD) — CBC implementation
        victort29 — GCM upgrade (authenticated encryption)
"""

import os
from pathlib import Path
from typing import Optional, Union

# ---------------------------------------------------------------------------
# Dependency guard — give a helpful error if `cryptography` is missing.
# ---------------------------------------------------------------------------
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidTag
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CRYPTO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NONCE_SIZE    = 12       # GCM standard nonce length (bytes)
SALT_SIZE     = 16       # Salt length for PBKDF2 (bytes)
TAG_SIZE      = 16       # GCM authentication tag length (bytes)
KEY_SIZE      = 32       # AES-256 key length (bytes)
PBKDF2_ITERS  = 600_000  # NIST recommendation for PBKDF2-HMAC-SHA256 (2023)
HEADER_SIZE   = NONCE_SIZE + SALT_SIZE + TAG_SIZE   # 44 bytes total

# Raw-key mode stores zeros in the salt field; the value is ignored on decrypt.
_ZERO_SALT = b"\x00" * SALT_SIZE


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def generate_key() -> bytes:
    """
    Generate a cryptographically random 32-byte (256-bit) AES key.

    Returns:
        32 random bytes suitable for use as a raw AES-256 key.

    Example:
        key = generate_key()
        with open("camera.key", "wb") as f:
            f.write(key)
    """
    return os.urandom(KEY_SIZE)


def derive_key(password: Union[str, bytes], salt: bytes, iterations: int = PBKDF2_ITERS) -> bytes:
    """
    Derive a 256-bit AES key from a password using PBKDF2-HMAC-SHA256.

    Args:
        password:   Passphrase (str or bytes).
        salt:       Random salt (at least 16 bytes).  Must be the same salt
                    used during encryption when decrypting.
        iterations: PBKDF2 iteration count.  Default is 600,000 (NIST 2023).

    Returns:
        32-byte derived key.

    Raises:
        RuntimeError: If the `cryptography` package is not installed.
    """
    _require_crypto()
    if isinstance(password, str):
        password = password.encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=iterations,
        backend=default_backend(),
    )
    return kdf.derive(password)


# ---------------------------------------------------------------------------
# Core encrypt / decrypt
# ---------------------------------------------------------------------------

def encrypt_file(
    path: Union[str, Path],
    password: Optional[str] = None,
    key: Optional[bytes] = None,
    delete_original: bool = True,
    output_path: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Encrypt a file in-place using AES-256-GCM.

    Exactly one of `password` or `key` must be supplied.

    Args:
        path:            Path to the plaintext file to encrypt.
        password:        Passphrase for PBKDF2-based key derivation.
        key:             Raw 32-byte AES-256 key (bypasses PBKDF2).
        delete_original: If True (default), delete the plaintext file after
                         successful encryption.
        output_path:     Where to write the .enc file.  Defaults to
                         `<path>.enc` (e.g. segment_001.mp4 → segment_001.mp4.enc).

    Returns:
        Path to the encrypted output file.

    Raises:
        ValueError:  Bad arguments (both/neither key/password, wrong key size).
        FileNotFoundError: Input file does not exist.
        RuntimeError: `cryptography` package not installed.
    """
    _require_crypto()
    _validate_key_args(password, key)

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"encrypt_file: input not found: {path}")

    out_path = Path(output_path) if output_path else path.with_suffix(path.suffix + ".enc")

    nonce = os.urandom(NONCE_SIZE)
    salt  = os.urandom(SALT_SIZE) if password is not None else _ZERO_SALT

    if password is not None:
        aes_key = derive_key(password, salt)
    else:
        aes_key = _validate_raw_key(key)  # type: ignore[arg-type]

    plaintext = path.read_bytes()
    ciphertext, tag = _aes_gcm_encrypt(plaintext, aes_key, nonce)

    out_path.write_bytes(nonce + salt + tag + ciphertext)

    if delete_original:
        path.unlink()

    return out_path


def decrypt_file(
    path: Union[str, Path],
    password: Optional[str] = None,
    key: Optional[bytes] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Decrypt a file previously encrypted with encrypt_file().

    Exactly one of `password` or `key` must be supplied.

    The nonce, salt, and auth tag are read from the file header;
    you do not need to supply them separately.

    Args:
        path:        Path to the `.enc` file.
        password:    Passphrase used during encryption.
        key:         Raw 32-byte AES-256 key used during encryption.
        output_path: Where to write the decrypted file.  Defaults to
                     stripping the trailing `.enc` suffix.

    Returns:
        Path to the decrypted output file.

    Raises:
        ValueError:  Bad arguments or file header too short.
        FileNotFoundError: Input file does not exist.
        RuntimeError: `cryptography` package not installed, or authentication
                      fails (wrong key, tampered ciphertext, or corrupted file).
    """
    _require_crypto()
    _validate_key_args(password, key)

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"decrypt_file: input not found: {path}")

    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        raise ValueError(
            f"decrypt_file: file too short to contain a valid header "
            f"(expected ≥{HEADER_SIZE} bytes, got {len(data)})"
        )

    nonce      = data[:NONCE_SIZE]
    salt       = data[NONCE_SIZE:NONCE_SIZE + SALT_SIZE]
    tag        = data[NONCE_SIZE + SALT_SIZE:HEADER_SIZE]
    ciphertext = data[HEADER_SIZE:]

    if password is not None:
        aes_key = derive_key(password, salt)
    else:
        aes_key = _validate_raw_key(key)  # type: ignore[arg-type]

    try:
        plaintext = _aes_gcm_decrypt(ciphertext, aes_key, nonce, tag)
    except InvalidTag:
        raise RuntimeError(
            "decrypt_file: authentication failed — wrong key or file has been tampered with."
        )
    except Exception as exc:
        raise RuntimeError(
            f"decrypt_file: decryption failed — wrong key or corrupted file. "
            f"({type(exc).__name__}: {exc})"
        ) from exc

    if output_path:
        out_path = Path(output_path)
    else:
        name = path.name
        if name.endswith(".enc"):
            out_path = path.with_name(name[:-4])
        else:
            out_path = path.with_suffix(".dec")

    out_path.write_bytes(plaintext)
    return out_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_crypto() -> None:
    """Raise a helpful RuntimeError if the cryptography package is missing."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError(
            "The `cryptography` package is required for encryption but is not installed. "
            "Install it with:  pip install cryptography"
        )


def _validate_key_args(password: Optional[str], key: Optional[bytes]) -> None:
    """Ensure exactly one of password / key is provided."""
    if password is None and key is None:
        raise ValueError("encrypt/decrypt requires either `password` or `key`.")
    if password is not None and key is not None:
        raise ValueError("Provide either `password` or `key`, not both.")


def _validate_raw_key(key: bytes) -> bytes:
    """Check that a raw key is exactly KEY_SIZE bytes."""
    if not isinstance(key, (bytes, bytearray)):
        raise ValueError(f"key must be bytes, got {type(key).__name__}")
    if len(key) != KEY_SIZE:
        raise ValueError(
            f"key must be exactly {KEY_SIZE} bytes for AES-256 (got {len(key)} bytes). "
            f"Use generate_key() to create a valid key."
        )
    return bytes(key)


def _aes_gcm_encrypt(plaintext: bytes, key: bytes, nonce: bytes) -> tuple[bytes, bytes]:
    """Encrypt plaintext with AES-256-GCM. Returns (ciphertext, tag)."""
    cipher    = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()
    return ciphertext, encryptor.tag


def _aes_gcm_decrypt(ciphertext: bytes, key: bytes, nonce: bytes, tag: bytes) -> bytes:
    """Decrypt AES-256-GCM ciphertext and verify the auth tag."""
    cipher    = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


# ---------------------------------------------------------------------------
# CLI convenience (python -m utils.encryption or python encryption.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import argparse

    p = argparse.ArgumentParser(description="AES-256-GCM file encryption utility")
    sub = p.add_subparsers(dest="cmd", required=True)

    enc_p = sub.add_parser("encrypt", help="Encrypt a file")
    enc_p.add_argument("file")
    enc_key = enc_p.add_mutually_exclusive_group(required=True)
    enc_key.add_argument("--password", help="Passphrase (PBKDF2 key derivation)")
    enc_key.add_argument("--key-file", help="Path to raw 32-byte key file")

    dec_p = sub.add_parser("decrypt", help="Decrypt a .enc file")
    dec_p.add_argument("file")
    dec_key = dec_p.add_mutually_exclusive_group(required=True)
    dec_key.add_argument("--password", help="Passphrase used during encryption")
    dec_key.add_argument("--key-file", help="Path to raw 32-byte key file")

    args = p.parse_args()

    raw_key = None
    if args.key_file:
        with open(args.key_file, "rb") as f:
            raw_key = f.read()

    if args.cmd == "encrypt":
        out = encrypt_file(args.file, password=args.password, key=raw_key)
        print(f"Encrypted → {out}")
    else:
        out = decrypt_file(args.file, password=args.password, key=raw_key)
        print(f"Decrypted → {out}")

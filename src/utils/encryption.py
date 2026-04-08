"""
src/utils/encryption.py

AES-256-CBC encryption/decryption for compressed video segments.

Government requirement (Cody Hayashi, NIWC Pacific):
    Segments stored on-device must be encrypted at rest.
    Decryption only occurs during authorised review.

File format (.enc):
    Bytes  0 –  15  : IV (random, 16 bytes)
    Bytes 16 –  31  : Salt (random, 16 bytes; used only in password mode)
    Bytes 32 – end  : Ciphertext (AES-256-CBC, PKCS7-padded)

Key modes:
    Password mode  — `password` arg; key = PBKDF2-HMAC-SHA256(password, salt, 600_000 iters)
    Raw-key mode   — `key` arg; must be exactly 32 bytes (256-bit); salt field is zeros

The IV and salt are unique per file.  Knowing the password/key but not the IV
is insufficient to decrypt — both are stored in the .enc file header.

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
    - Each call to encrypt_file() generates a fresh IV (and salt in password mode).
    - The original plaintext file is deleted after successful encryption.
    - In password mode use a strong passphrase; PBKDF2 with 600k iterations makes
      brute-force expensive but a weak password is still a weak password.
    - Raw keys must be stored securely (HSM, encrypted key store, environment
      variable — NOT hard-coded in source).

Author: Bloodawn (KheivenD)
"""

import os
import struct
from pathlib import Path
from typing import Optional, Union

# ---------------------------------------------------------------------------
# Dependency guard — give a helpful error if `cryptography` is missing.
# ---------------------------------------------------------------------------
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CRYPTO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IV_SIZE       = 16       # AES block size / IV length (bytes)
SALT_SIZE     = 16       # Salt length for PBKDF2 (bytes)
KEY_SIZE      = 32       # AES-256 key length (bytes)
PBKDF2_ITERS  = 600_000  # NIST recommendation for PBKDF2-HMAC-SHA256 (2023)
HEADER_SIZE   = IV_SIZE + SALT_SIZE   # 32 bytes total

# Sentinel: raw-key mode uses a zero salt in the header so the format is
# identical; the salt field is simply ignored during decryption.
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
    Encrypt a file in-place using AES-256-CBC.

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

    # Generate fresh IV and (if password mode) salt for this file.
    iv   = os.urandom(IV_SIZE)
    salt = os.urandom(SALT_SIZE) if password is not None else _ZERO_SALT

    # Resolve key.
    if password is not None:
        aes_key = derive_key(password, salt)
    else:
        aes_key = _validate_raw_key(key)  # type: ignore[arg-type]

    # Read plaintext, encrypt, write header + ciphertext.
    plaintext = path.read_bytes()
    ciphertext = _aes_cbc_encrypt(plaintext, aes_key, iv)

    out_path.write_bytes(iv + salt + ciphertext)

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

    The IV and (in password mode) the salt are read from the file header;
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
        RuntimeError: `cryptography` package not installed, or decryption
                      fails (wrong key / corrupted file).
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

    # Parse header.
    iv        = data[:IV_SIZE]
    salt      = data[IV_SIZE:IV_SIZE + SALT_SIZE]
    ciphertext = data[HEADER_SIZE:]

    # Resolve key.
    if password is not None:
        aes_key = derive_key(password, salt)
    else:
        aes_key = _validate_raw_key(key)  # type: ignore[arg-type]

    # Decrypt.
    try:
        plaintext = _aes_cbc_decrypt(ciphertext, aes_key, iv)
    except Exception as exc:
        raise RuntimeError(
            f"decrypt_file: decryption failed — wrong key or corrupted file. "
            f"({type(exc).__name__}: {exc})"
        ) from exc

    # Determine output path.
    if output_path:
        out_path = Path(output_path)
    else:
        # Strip the .enc suffix: segment_001.mp4.enc → segment_001.mp4
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


def _aes_cbc_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """Encrypt plaintext with AES-256-CBC + PKCS7 padding."""
    padder    = sym_padding.PKCS7(128).padder()
    padded    = padder.update(plaintext) + padder.finalize()
    cipher    = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt AES-256-CBC ciphertext and remove PKCS7 padding."""
    cipher    = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded    = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder  = sym_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


# ---------------------------------------------------------------------------
# CLI convenience (python -m utils.encryption or python encryption.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys

    p = argparse.ArgumentParser(description="AES-256-CBC file encryption utility")
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

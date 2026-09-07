# Session Log - 2026-04-21 (Victor De Souza Teixeira)

## Overview
Session focused on Milestone 3 security requirements: upgrading the encryption
layer from AES-256-CBC to AES-256-GCM and adding GPU detection utilities for
the enhancement module. Work completed on the `dev` branch and submitted as PR #12.

## Key Deliverables

**Encryption Upgrade (PR #12)**
Replaced AES-256-CBC with AES-256-GCM across the encryption module. GCM adds a
128-bit authentication tag to each ciphertext, enabling tamper detection - a
direct requirement from Cody Hayashi at NIWC Pacific. The new file format stores
nonce + salt + tag + ciphertext as a single blob. Added `encrypt_bytes()` and
`decrypt_bytes()` helpers for in-memory use without touching the filesystem.

**GPU Detection Utilities**
Added `detect_gpu()` and `best_device()` to the enhancement module, surfacing
CUDA/MPS availability at runtime. Both functions are exposed via `/api/gpu_info`
on the dashboard so operators can confirm hardware acceleration is active.

## Testing
24 unit tests written covering:
- Round-trip encrypt/decrypt correctness
- Tamper detection (modified tag, modified ciphertext, modified nonce)
- In-memory `encrypt_bytes()`/`decrypt_bytes()` interface
- GPU device detection on CPU-only fallback

All 24 tests passed.

## Breaking Changes
Existing `.enc` files encrypted with AES-256-CBC are incompatible with the new
format and must be re-encrypted using the updated module.

## Open Items
- Store IV + salt in DB per segment (per-segment decryption support)
- Password-protected incident clip export

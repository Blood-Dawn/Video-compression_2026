# Encryption round trip: verified across a genuinely separate install

Date: 2026-09-30
Author: Bloodawn (KheivenD)

## Why this exists

The unit tests in `tests/test_encryption.py` and `tests/test_encryption_cross_install.py`
prove the AES-256-GCM implementation in `src/utils/encryption.py` is correct
in isolation. This doc records a manual, one-time check of the actual
end-user scenario: encrypt a real clip on one install of SVCS, move only the
`.enc` file somewhere else, and decrypt it there with a completely separate
install that shares no process, no venv, and no application state with the
first.

## What "somewhere else" means here

The mobile app was considered as the "somewhere else" first, since the user
request specifically suggested an emulator. It turned out not to add real
coverage: the Android client (`mobile/android/`) never implements its own
AES-GCM - it is a thin REST client against the desktop's Flask API
(`encrypted_dir` is just a config string it displays, see
`LibraryModels.kt`). Sending a file to the phone and back would only test the
HTTP transfer, not the encryption format. The scenario that actually matters
is desktop install A -> desktop install B, since that is the real deployment
shape (a camera's SVCS box encrypts, a reviewer's separate SVCS box decrypts).

So "somewhere else" here is a second, independently `git worktree add`'d
checkout of the `mobile` branch in a sibling directory, with its own `uv
sync --frozen` (its own resolved `cryptography` install, its own `.venv`,
never opened by the same Python process as the first install). That is as
close to "a fresh install on a different machine" as a single dev box gets
without literally provisioning a second machine, and it is enough to rule
out the class of bug this check exists for: something silently relying on
in-process or in-repo state that would not travel with the file.

## What was run

Install A (this checkout, `fix/realesrgan-small-crop-padding` at the time):

```
sha256(data/samples/cdnet_mp4/baseline/baseline_office.mp4) = 613fe63f19dc1f6ce7d5f141f8b7d78f8710f9dfb9db8227c864970cd7dbdf37
size = 3,794,914 bytes

encrypt_file(clip.mp4, password="correct horse battery staple")
  -> clip.mp4.enc, 3,794,958 bytes (= original + 44-byte header, as documented)
```

The `.enc` file (nothing else - no config, no database, no key store) was
copied to Install B.

Install B (separate `uv sync --frozen` worktree, own `.venv`):

```
decrypt_file(clip.mp4.enc, password="correct horse battery staple")
  -> clip_decrypted.mp4, 3,794,914 bytes

sha256(clip_decrypted.mp4) = 613fe63f19dc1f6ce7d5f141f8b7d78f8710f9dfb9db8227c864970cd7dbdf37
```

The hash matches byte-for-byte. Password-mode and raw-key-mode round trips,
plus wrong-password and tampered-ciphertext rejection, are additionally
covered automatically (across a fresh OS process each time, see that file's
docstring) by `tests/test_encryption_cross_install.py`, which runs in CI on
every change to this area.

## Interoperability with software other than SVCS itself

`tests/test_encryption_cross_install.py::test_format_decrypts_with_independent_aes_gcm_primitives`
reimplements the `.enc` layout (`nonce[12] + salt[16] + tag[16] + ciphertext`,
PBKDF2-HMAC-SHA256 with 600,000 iterations for password mode) directly
against `cryptography`'s low-level `AESGCM` primitive, never importing
`utils.encryption`. It passes, which means the format is plain, standard
AES-256-GCM: any other compliant implementation that parses the same header
layout - a different language's crypto library, a small OpenSSL/Python
script written from the docstring alone - can decrypt these files too. There
is nothing SVCS-proprietary about the cryptography itself, only the 44-byte
header convention, which is documented in `src/utils/encryption.py`'s module
docstring.

## Conclusion

The encryption round trip works exactly as designed: a file encrypted on one
install decrypts correctly, byte-for-byte, on a completely independent
install given only the `.enc` file and the password or key - no shared
state, database record, or device-bound secret is involved anywhere in the
path. Wrong passwords and tampered files are rejected rather than silently
mis-decrypted, on both the original and the fresh install.
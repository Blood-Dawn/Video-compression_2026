# Encryption code: cleanup plan and handoff

Written 2026-11-10 for Victor (victort29), who wrote the GCM upgrade of `src/utils/encryption.py` and is the natural owner of this work. It continues the cleanup tracked in `docs/CODE-CLEANUP-PLAN.md` (branch `chore/code-quality-wave1`). That plan deliberately stopped at the encryption code because the working rules say to ask before changing encryption, token or authentication code. This document records what was left alone and why, what was touched indirectly, and what the next steps are.

## 1. Scope

| File | Lines | What it is |
|---|---|---|
| `src/utils/encryption.py` | 402 | The crypto core: AES-256-GCM file encryption and decryption, PBKDF2 key derivation, raw key mode, streaming in 1 MiB chunks, atomic publish of the output file |
| `src/gui/routes/encryption_bp.py` | 441 | The three HTTP routes: `/api/keygen`, `/api/encrypt`, `/api/decrypt`, plus the trusted folder checks |
| `src/compression/roi_encoder.py` | n/a | Calls `encrypt_file` after each segment when a run has `encrypt` on (the `_stream_encrypt*` fields) |
| `src/pipeline/pipeline.py`, `src/gui/routes/pipeline_bp.py` | n/a | Pass `encrypt`, `encrypt_password`, `encrypt_key_file` through to the encoder |

File format (from the module docstring): 12 byte nonce, 16 byte salt (zeros in raw key mode), 16 byte GCM tag, then ciphertext. Password mode derives the key with PBKDF2-HMAC-SHA256 at 600,000 iterations. `docs/SECURITY.md` lists the crypto review as SEC-D2 (random nonce per call, tag verified before any plaintext is returned, wrong password fails cleanly) and the earlier route fixes SEC-005 and SEC-006.

## 2. What was done during the cleanup

Nothing in the encryption code itself was edited. Things that touched it indirectly, all on the branch:

1. **`cryptography` upgraded from 49.0.0 to 50.0.2** in `uv.lock` and `requirements.txt` (commit "Upgrade 14 locked packages with known security advisories"). pip-audit had flagged two advisories on 49.0.0. The encryption tests (`tests/test_encryption.py`, `tests/test_encryption_cross_install.py`, `tests/test_perf_utils_encryption.py`, 34 tests in all) passed against 50.0.2 in a test environment with exactly the upgraded versions. Not done: an encrypt then decrypt round trip of a real multi gigabyte file on the new version, and the Windows installer build with the new lock.
2. **`/api/start` validation split into helpers** (`_validate_encrypt_inputs` in `src/gui/routes/pipeline_bp.py`). This is the check that rejects `encrypt: true` with no password or key file. It was moved verbatim and verified by feeding the same 31 payloads to the old and new versions (identical status codes and messages, including the encrypt cases: no credential, password, key file, missing key file, key file that is a directory).
3. **Flask `SECRET_KEY` file creation hardened** (`src/gui/secret_key.py`). This is the session cookie key, not the video encryption key. It is mentioned only so nobody confuses the two.
4. **CI now audits dependencies and blocks on advisories**, so a future `cryptography` advisory fails CI instead of waiting for a person to notice.

## 3. What was deliberately not touched, and the numbers

Measured with radon 6.0.1 on 2026-11-10.

| Function | Complexity | Grade |
|---|---|---|
| `api_encrypt` in `encryption_bp.py` | 27 | D |
| `api_decrypt` in `encryption_bp.py` | 25 | D |
| `api_keygen` | 7 | B |
| `decrypt_file` in `encryption.py` | 9 | B |
| `encrypt_file` | 6 | B |
| everything else in both files | 5 or less | A |

So the crypto core is already simple. The two route handlers are the only complexity problem, and they are almost entirely request handling (path checks, error mapping), not cryptography. Both are in the ratchet baseline (`scripts/complexity_baseline.json`), so they cannot get worse unnoticed.

## 4. Invariants that must not change

Any refactor here is only acceptable if all of these hold afterwards:

1. **Bytes on disk.** For the same plaintext, key, nonce and salt, the `.enc` bytes are identical. The header layout, the sizes and the tag position do not move. Files encrypted by an older build must still decrypt, and files encrypted after the change must decrypt with the old code. `tests/test_encryption_cross_install.py` is the guard for the second half.
2. **Nothing is written on a failed check.** A wrong key, a flipped bit or a truncated file must raise before any plaintext reaches the caller or the disk (the tag is verified first). The `.part` and publish logic (`_side_path`, `_publish`) must keep the output atomic.
3. **Route contract.** Same paths, same JSON field names, same status codes and messages. Today: 400 for missing `file_path`, missing credential, an `.enc` input to encrypt or a non `.enc` input to decrypt, and an unreadable key file; 403 for a path outside the trusted folders and for a failed decrypt; 404 for a missing file; 503 when `cryptography` is not installed; 500 for an unexpected crash. The route count guards in `tests/test_gui_blueprint_registration.py` and `tests/test_gui_routes_resolve.py` stay as they are.
4. **Trusted folder checks stay exactly as strict.** `file_path`, `key_file` and the encrypted output folder must all sit under the trusted roots (SEC-005, SEC-006). No check may be moved after the file is opened or read.
5. **Source files are kept.** `/api/encrypt` passes `delete_original=False` (the source clip stays); the library function defaults to deleting the plaintext. Do not change either default.
6. **No secret reaches a log or a response.** Passwords, key bytes and key file contents must never be logged. Error messages show file names, not full paths, where they do today.

## 5. Proposed work, in order

Each item is one commit, in the style used so far: smallest change, full test suite run before the commit, and the commit message says what was verified and what was not.

**Step 0. Characterization first (no source change).** Add tests that pin today's route behavior before moving any code: one test per row of the status code table in section 4, driven through the Flask test client with a temp folder as the trusted root. Add a known answer test for the file format: encrypt with a fixed key, patching the nonce source, and compare against bytes captured from the current code. This is the safety net for everything below.

**Step 1. Differential harness.** Reuse the method from the earlier steps. Load the previous version of `encryption_bp.py` from git (`git show HEAD:src/gui/routes/encryption_bp.py`) as a second module, register both blueprints on separate Flask apps, and post the same set of requests (valid, every error path, odd inputs such as an empty password, a directory as `file_path`, a symlink, a key file outside the roots). Compare status, JSON and the files created. Keep the script out of the repo or under `scripts/`; the earlier ones are in the job notes of the session that produced this plan and are about 60 lines each.

**Step 2. Split `api_decrypt` (25).** Extract, in this order, each returning `(value, error_response)` so the handler keeps its early returns: request parsing, trusted path and key file validation, destination preparation (the `Decrypted/` folder and removing a stale copy), and response building (the inline small file versus chunked streaming). Target: handler under 12, helpers under 10.

**Step 3. Split `api_encrypt` (27).** Same shape: request parsing, trusted path and key file validation, destination choice (the `encrypted_dir` setting with the fallback to a sibling `Encrypted/`), the call, and the follow up that records the result in the segments database. Target the same numbers. The two handlers share the key file and trusted root logic, so extract that once and use it from both (this also removes a copy of SEC-005 logic).

**Step 4. Remove or justify the `TypeError` fallback in `api_encrypt`.** The handler calls `_encrypt_file(..., output_path=target_enc)` and on `TypeError` retries without `output_path`, then renames the result. `encrypt_file` has always had `output_path`, so the retry can only run when a `TypeError` comes from somewhere else inside the encryption call, for example a wrong argument type. In that case it re-runs the encryption and renames the output, which can hide the real error. Recommended: delete the fallback, let that case return the normal 500, add a test for it. This is a behavior change on an error path, so it is called out separately.

**Step 5. Documentation fix.** The `run_pipeline` docstring in `src/pipeline/pipeline.py` says segments are encrypted "with AES-256-CBC". The code is GCM (the module docstring says so and explains why). Fix the docstring.

**Step 6. Ratchet.** Run `python scripts/complexity_ratchet.py --update` with radon installed to lock the lower numbers into `scripts/complexity_baseline.json`, and update the status lines in `docs/CODE-CLEANUP-PLAN.md`.

## 6. How to verify (what "done" means)

- The full suite passes: `python -m pytest tests -q`. It takes about four minutes. **Never run two pytest processes at once**; they share `.pytest_tmp` and produce spurious failures.
- Step 1's differential run shows zero differences for every case, and the case list includes every status code in section 4.
- The file format is unchanged: the known answer test from Step 0 still passes, and `tests/test_encryption_cross_install.py` passes.
- A real clip round trip on the new code: encrypt a recorded segment through `/api/encrypt`, decrypt it through `/api/decrypt`, and compare the SHA-256 of the result with the original. Do this once through the dashboard and once through the API.
- `scripts/pipeline_characterize.py` is not needed here (this work does not touch the compression path), but run it if `roi_encoder.py` is edited.
- `radon cc` shows both handlers under 15 and the ratchet passes.
- No em dashes or en dashes in any file (a test fails on them), and no new documentation path that does not exist (the doc link check).

## 7. Open questions for the owner

1. **Decrypted copies stay on disk.** `/api/decrypt` writes the plaintext to `Decrypted/<name>` next to the `.enc` and keeps it, as well as streaming it to the browser (a deliberate choice recorded in the code: the metrics player replays the kept copy). The module docstring, though, says decryption should only happen during authorised review. Plaintext left beside the encrypted file defeats encryption at rest until someone deletes it. Options: delete the copy after a time limit, delete it when the browser finishes the download, or leave it and say so clearly in the UI. This is a product decision, not a refactor.
2. **Passwords travel in a JSON body.** That is fine on localhost but the shipping config binds all interfaces when credentials are set (see the bind warning in `src/gui/auth.py`). Worth stating in the docs that remote use needs a private network or TLS in front.
3. **Key files must live under the trusted roots.** A user who keeps keys on a separate drive gets a 403. That is intentional (SEC-005) but the error text could say which roots are allowed on the encrypt path as the decrypt path does for `file_path`.
4. **`cryptography` 50 is a new major version.** The tests pass, but a real world encrypt then decrypt on the installer build has not been done (see section 2).

## 8. Environment notes for whoever picks this up

- Tools used for measuring, none of them project dependencies: `radon` for complexity, `vulture` for dead code, `ruff` for lint, `pip-audit`, `zizmor` for workflows. In CI, `vulture`, `radon` and `pip-audit` are installed by the workflow steps; locally put them in a throwaway virtual environment.
- When committing from this tool's shell, do not put `sed -n` or `grep -n` in the same command as `git commit`: the commit hook mistakes `-n` for `--no-verify` and blocks it.
- The branch is `chore/code-quality-wave1`. It has been pushed; open the pull request from it or branch off it.

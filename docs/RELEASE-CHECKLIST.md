# SVCS release checklist

A repeatable checklist for cutting a public release. The build/verify steps are
done by whoever prepares the release; **tagging and publishing the GitHub Release
is the owner's action** (it's a gated step — see `docs/BLOCKERS.md`).

Versions follow the installer name: `SVCS-Setup-<version>.exe`. The first public
drop is the **unsigned beta** `v2.0.0-beta`.

---

## 1. Pre-flight (clean checkout)

- [ ] `git switch app && git pull` — release from `app`, working tree clean.
- [ ] Confirm the version in `pyproject.toml` / installer matches the intended tag.
- [ ] `uv sync --extra enhance --extra crash-reporting` — env matches the lockfile.

## 2. Quality gate

- [ ] `pwsh scripts/run_tests.ps1` → **green** (≥513 passed, 0 failed, 3 webcam skips).
- [ ] No `[ ]` non-gated tasks remain for this milestone in `docs/CLAUDE-CODE-MASTER-PLAN.md`.

## 3. Build the installer

- [ ] `pwsh installer/build.ps1 -Installer` (vendors FFmpeg, runs PyInstaller, then `iscc`).
- [ ] Output present: `installer/dist/SVCS-Setup-<version>.exe`.
- [ ] Note the unpacked size and the installer size for the release notes.

## 4. Smoke-test the installer

- [ ] On a clean Windows VM (no Python, no FFmpeg): install → launch → dashboard opens.
- [ ] Run a short clip through a preset; confirm a compressed `.mp4` is produced
      and plays. Validate with `ffprobe`, not `cv2`.
- [ ] ONNX object detection works (no torch present).
- [ ] Uninstall leaves `%APPDATA%` user data intact.

## 5. Checksums

- [ ] Generate `SHA256SUMS.txt` next to the installer:
      ```powershell
      Get-FileHash .\SVCS-Setup-<version>.exe -Algorithm SHA256 |
        ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } |
        Out-File -Encoding ascii SHA256SUMS.txt
      ```
- [ ] Verify the printed hash matches what the download page tells users to check.

## 6. Draft the GitHub Release  🚦 *owner publishes*

- [ ] Draft a release from the **draft notes** (`docs/release-notes-v2.0.0-beta.md`).
- [ ] Attach `SVCS-Setup-<version>.exe` and `SHA256SUMS.txt`.
- [ ] Mark it a **pre-release**; the title/notes state clearly it is an
      **unsigned beta** and SmartScreen will warn.
- [ ] **Owner action:** create the tag (`v2.0.0-beta`) and click *Publish*.
      The agent does not tag or publish (gated — `docs/BLOCKERS.md`).

## 7. Post-publish

- [ ] Confirm the download page link (`docs/site/index.html` → Releases/latest) resolves to the new asset.
- [ ] Spot-check the published `SHA256SUMS.txt` against a fresh download.
- [ ] Open a tracking issue for the next milestone (signing — TASK 5b.1).

---

*Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.4 — release checklist).*

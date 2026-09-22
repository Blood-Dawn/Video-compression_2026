# Release checklist

A repeatable, step-by-step process for cutting a desktop beta build. Every
step here is something the agent (or any contributor) can run; the actual
publish/tag is the last step and is explicitly gated to the repo owner.

The current published beta tag is `v2.2.0-beta`; the next release bumps this.

## Steps

1. **run_tests** - from the repo root, with the project venv active:
   `pytest -q`. All tests must pass (or have a documented, reviewed skip) on
   both the Linux and Windows CI matrix before continuing. `tests/security/`
   in particular must be green; it is the guard against auth, CSRF, SQLi,
   XSS, SSRF, path-traversal, and crypto regressions.
2. **build** - `installer\build.ps1` from the repo root with the venv
   active. Use `-Edition server` for the desktop/server build (the default)
   or `-Edition field` for the offline field kit. Add `-Installer` to also
   package `dist\SVCS` into an Inno Setup `SVCS-Setup-*.exe`. Add `-Sign` to
   Authenticode-sign the bundle and the installer (see "Code signing"
   below); without a cert configured, signing degrades to a warning and the
   build still completes unsigned.
3. **smoke** - `build.ps1` launches the freshly built exe and confirms it
   answers on `http://127.0.0.1:5000` within `-SmokeTimeoutSec` (default 60s)
   unless `-SkipSmoke` was passed. Do not skip this for a release build: a
   build that produces an exe that never binds its port is a silent failure.
4. **checksum / sha256** - after the build, compute SHA-256 for every
   artifact you are about to publish (the installer exe and the mobile APK)
   and write them to `dist/SHA256SUMS.txt`, one `<hash>  <filename>` line per
   artifact:
   `Get-FileHash dist\SVCS-Setup-<version>.exe -Algorithm SHA256`.
   These are what let a user verify their download was not tampered with in
   transit, and what the release notes point to.
5. **draft** - write (or update) `docs/release-notes-v<version>-beta.md`
   before touching GitHub. It must say plainly that the build is an unsigned
   beta, explain the Windows SmartScreen warning users will hit and how to
   proceed past it, list the SHA-256 checksums from the step above, and
   state the license (AGPL-3.0). Draft it as a normal file in this repo, not
   directly in the GitHub release editor, so it goes through the same
   review as everything else.
6. **owner / publish / tag** - tagging the commit (`git tag vX.Y.Z-beta`),
   pushing the tag, and publishing the GitHub Release with the built
   artifacts attached is the repo owner's action alone. Nothing before this
   step should touch the public `origin` remote's tags or releases. The
   owner reviews the draft notes and checksums from steps 4-5, then
   publishes.

## Code signing

`installer\build.ps1 -Sign` signs both the bundle exe and the installer exe
via `signtool`, SHA-256 file digest, RFC3161 timestamp (`/fd SHA256 /tr ...`)
so the signature stays valid after the cert expires. The certificate is read
from the environment (`SVCS_SIGN_CERT` or `SVCS_SIGN_THUMBPRINT`, plus
`SVCS_SIGN_PASSWORD` for a `.pfx`) and is never committed to the repo. With
no cert configured, `-Sign` prints a warning and the build still produces an
unsigned exe rather than failing outright - see `docs/BLOCKERS.md` for the
current status of getting a real cert.

## Notes

- This checklist governs the desktop/server exe and the Inno Setup
  installer. The mobile APK has its own build step under `mobile/android`
  and is versioned independently (see `mobile/CHANGES-SUMMER-2026.md`-style
  per-round notes).
- If a step here stops matching how a release actually gets made, fix the
  checklist in the same PR that changes the process. A checklist nobody
  follows is worse than no checklist.

Author: Bloodawn (KheivenD), 2026-09-21.

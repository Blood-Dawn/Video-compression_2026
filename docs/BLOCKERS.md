# Blockers

Things that gate a fully "done" public release but are not code defects: the
kind of item that needs an owner decision, a paid resource, or time, rather
than a fix a contributor can just make.

## Open

### Code signing cert (blocks: a signed v2.2.0-beta or later release)

The signing step itself is wired and tested: `installer\build.ps1 -Sign`
signs both the bundle exe and the installer via `signtool` (SHA-256 digest,
RFC3161 timestamp), reading the certificate from the environment
(`SVCS_SIGN_CERT` / `SVCS_SIGN_THUMBPRINT` + `SVCS_SIGN_PASSWORD`) so no
secret ever lives in the repo. What's missing is the certificate itself.

A free option for open-source projects: [SignPath.io](https://signpath.io)
issues no-cost code-signing certificates to qualifying OSS projects (an
active public repo, a real release process, and a maintainer willing to go
through their review). `docs/RELEASE-CHECKLIST.md` documents the signing
step; this entry is the reminder that it is currently exercised in
unsigned/degraded mode because no cert is configured, not because it is
broken.

Owner action needed: apply to SignPath (or acquire a commercial cert),
then set `SVCS_SIGN_THUMBPRINT` (or `SVCS_SIGN_CERT` + `SVCS_SIGN_PASSWORD`)
in the build environment and re-run `build.ps1 -Sign -Installer`.

### v2.2.0-beta desktop exe is stale relative to `main`

`dist/SVCS-Setup-2.2.0.dev0.exe` (the artifact currently attached to the
GitHub v2.2.0-beta release) was built 2026-08-17, before the chunked
resumable upload, zone/behavior events, job registry, and mobile push
features landed on `main`. It also predates the chunked-upload filename
sanitization fix. A fresh build from current `main`, using
`docs/RELEASE-CHECKLIST.md`, is owner-gated the same way any publish is:
someone with a Windows machine and the project venv needs to run
`build.ps1 -Installer` (optionally `-Sign`, see above) and re-publish.

## Resolved

- Release-checklist, release-notes, and this blockers doc did not exist on
  `main` even though `tests/test_release_artifacts.py`,
  `tests/test_signing_step.py`, and `tests/test_version_consistency.py`
  assumed they did (referencing the older `v2.1.0-beta` tag). Written
  2026-09-21 and repointed at the actual current tag, `v2.2.0-beta`.

Author: Bloodawn (KheivenD), 2026-09-21.

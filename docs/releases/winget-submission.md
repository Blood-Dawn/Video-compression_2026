# Submitting SVCS to winget (owner action)

This is the exact procedure to publish SVCS to the public winget repository
(`microsoft/winget-pkgs`) so that `winget install Blood-Dawn.SVCS` works for
everyone. It is **owner-gated**: it requires a published GitHub Release and (in
practice) a code-signed installer. See `docs/plans/BLOCKERS.md`.

The manifest lives in `installer/winget/` (three files):

- `Blood-Dawn.SVCS.yaml` (version)
- `Blood-Dawn.SVCS.installer.yaml` (installer)
- `Blood-Dawn.SVCS.locale.en-US.yaml` (default locale)

## 1. Publish the GitHub Release asset

The installer manifest points at:

```
https://github.com/Blood-Dawn/Video-compression_2026/releases/download/v2.1.0.dev0/SVCS-Setup-2.1.0.dev0.exe
```

So a GitHub Release tagged `v2.1.0.dev0` must exist with that exact `.exe`
attached. Build it first:

```powershell
. .venv\Scripts\Activate.ps1
pwsh installer\build.ps1 -Installer
```

(Activate the venv first or PyInstaller is not found.)

## 2. Recompute the SHA256 against the released asset

The `InstallerSha256` in the manifest MUST match the byte-for-byte asset that is
actually attached to the Release. After building (or downloading the published
asset), recompute and patch it:

```powershell
pwsh scripts\winget_validate.ps1 -Recompute
```

This hashes `dist/SVCS-Setup-<version>.exe` and rewrites `InstallerSha256` in
`Blood-Dawn.SVCS.installer.yaml`. Pass `-InstallerPath` to point at a downloaded
copy of the published asset instead.

## 3. Validate locally

```powershell
pwsh scripts\winget_validate.ps1
```

This runs `winget validate --manifest installer/winget` (needs the "App
Installer" package from the Microsoft Store). The structural test
`tests/test_winget_manifest.py` already checks the files load and carry the
required keys, but `winget validate` is the authoritative schema check.

## 4. Submit (two options)

### Option A: wingetcreate (recommended)

```powershell
winget install Microsoft.WingetCreate
wingetcreate submit --token <github-pat> installer\winget
```

`wingetcreate submit` forks `microsoft/winget-pkgs`, copies the manifest into
`manifests/b/Blood-Dawn/SVCS/2.1.0.dev0/`, and opens the PR for you.

### Option B: manual fork PR

1. Fork `https://github.com/microsoft/winget-pkgs`.
2. Copy the three files to
   `manifests/b/Blood-Dawn/SVCS/2.1.0.dev0/`.
3. Commit, push, and open a PR. The winget CI bot validates the manifest and
   installs the package in a sandbox.

## 5. Code signing (why this is gated)

Microsoft's winget pipeline runs the installer in a sandbox and is far more
likely to accept (and SmartScreen far less likely to warn on) a **code-signed**
installer. SVCS signing is tied to the existing gated signing certificate (see
`docs/plans/BLOCKERS.md`). Until the installer is signed with a real Authenticode
certificate, treat winget submission as a release-time owner step, not a CI step.

## Notes

- `PackageVersion: 2.1.0.dev0` is a pre-release marker. For a public submission
  the owner will likely cut a clean `2.1.0` tag and bump all three manifests
  plus `pyproject.toml` together (the version-pin test enforces they agree).
- The app bundles ffmpeg, the ONNX runtime, and the model, so the winget install
  needs no extra dependencies.

# Installing SVCS

SVCS (Surveillance Video Compression System) ships as a self-contained Windows
app. FFmpeg, the ONNX runtime, and the detection model are bundled, so once it is
installed it works with no extra dependencies. Pick whichever path you like.

## Install from the terminal (fastest)

### One-line installer menu

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/Blood-Dawn/Video-compression_2026/app/installer/Install-SVCS.ps1 | iex
```

This opens a small SVCS-themed menu (a dark, amber-accented window, or a text
menu over SSH) where you pick what to install:

- **SVCS core app** (required) - the app itself.
- **AI plate reader** (optional) - an ONNX OCR and detection path installed into
   the core environment with the documented `--no-deps` recipe. EasyOCR remains
   a legacy separate-environment option because its headless OpenCV dependency
   can clobber the core contrib build. See `../RESEARCH.md` and
   `../testing/PLATES-VALIDATION.md`.
- **Local RTSP server (MediaMTX)** (optional) - for local RTSP/HLS testing;
  downloaded into the app data folder.
- **Sample clips** (optional) - a couple of CDnet surveillance clips to try.

Useful flags:

```powershell
# See exactly what each selected component WOULD do, without doing it:
pwsh installer/Install-SVCS.ps1 -DryRun

# Headless / SSH (text menu instead of the window):
pwsh installer/Install-SVCS.ps1 -NoGui

# Skip the menu and install a fixed set:
pwsh installer/Install-SVCS.ps1 -Components core,mediamtx
```

Only the core app install is per-machine and needs an elevated ("Run as
administrator") terminal; the optional components install into your user profile.

### winget

Once the package is published to the public winget repository:

```powershell
winget install Blood-Dawn.SVCS
```

The app bundles its dependencies, so that single command gives you a working
install. (Until the manifest is public, the one-line installer above downloads
the GitHub Release instead. Maintainers: see
[winget-submission.md](winget-submission.md).)

## Download the installer manually

1. Go to the
   [Releases page](https://github.com/Blood-Dawn/Video-compression_2026/releases/latest).
2. Download `SVCS-Setup-<version>.exe`.
3. (Recommended) Verify it against the published `SHA256SUMS.txt`:

   ```powershell
   Get-FileHash .\SVCS-Setup-<version>.exe -Algorithm SHA256
   ```

   and compare the hash to the one in `SHA256SUMS.txt`.
4. Run the installer and follow the prompts (or run it silently with
   `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`).

## Run from source

If you would rather run from source (any OS), see the "How to run it" section in
the [README](../README.md): install [uv](https://docs.astral.sh/uv/), run
`uv sync`, install FFmpeg, and start the dashboard. A
   [Docker image](../BUILD-AND-RELEASE.md) is also available for server use.

## After installing

Launch SVCS from the Start menu (or run the app) and open the dashboard at
`http://127.0.0.1:5000`. First run lets you choose where compressed output is
saved. To compress files as they are saved into a folder (the live "save then
compress" workflow), use the **AUTO-COMPRESS** tab.

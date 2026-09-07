# SVCS Build and Release

How SVCS is built, packaged, and shipped: the two build editions, how the
installer and container image are produced, why the bundled FFmpeg carries the
license it does, the ONNX path that keeps the install small, and the checklist
for cutting a release, including publishing to winget. This replaces seven
narrower documents that covered these topics separately. The dated source
records remain in `docs/` for provenance and are listed in the canonical
source-record section below.

For the current test suite and how to run it, see `docs/TESTING.md`. For the
system's architecture, see `docs/SYSTEM-ARCHITECTURE.md`.

## 1. Two builds from one codebase: Server and Field

SVCS ships as two downloadable builds from the same source tree. Which one
runs is decided by the `SVCS_EDITION` environment variable, or by an
`edition.txt` marker the PyInstaller build writes into the frozen bundle,
defaulting to Server.

| | SVCS (Server) | SVCS-Field (offline) |
|---|---|---|
| Who it is for | A shop, NAS, or operator running a dashboard for others | A technician in the field compressing footage on a laptop, offline |
| Network bind | Localhost by default; can bind the LAN with auth required | Forced to `127.0.0.1`; never binds the network |
| Auth | Basic auth required for any non-localhost bind | Not needed, since the bind is always localhost |
| RTSP server, HLS live streaming | Yes | Removed; the routes are not even registered |
| Telemetry | Opt-in usage stats, off by default | A hard kill-switch, always off |
| Local compression, all modes, library, auto-compress, retention, encryption, plate reading | Yes | Yes |

The Field build keeps auto-compress and retention on purpose, since watching a
local folder and bounding its size is exactly a field technician's workflow.
It drops only the two surfaces that make a machine into a server, RTSP and
HLS, so it has no network server at all.

Edition resolution checks, in order, the `SVCS_EDITION` environment variable,
then the frozen bundle's `edition.txt` marker, then falls back to Server so
that running from source and the full test suite are unaffected. The Field
build forces a loopback bind at more than one layer (both the CLI entry point
and the WSGI module entry point), so a defense-in-depth gap in one does not
leave the other exposed.

Building the two executables is an owner-run step on Windows, with the venv
active:

```powershell
pwsh installer/build.ps1                  # server build -> dist/SVCS/SVCS.exe
pwsh installer/build.ps1 -Edition field    # field build  -> dist/SVCS-Field/SVCS-Field.exe
```

Both come from one `installer/svcs.spec`, parameterized by which edition the
build script is producing.

## 2. Packaging and deployment

Two deployment scenarios drove the early packaging research: a server-hosted
web app that multiple operators reach over a network, and a standalone laptop
with no network access at all for field use. Four packaging options were
evaluated for these (a Docker container, a PyInstaller single-file executable,
an Electron shell wrapping the Flask backend, and a tarball with a setup
script); Docker and a native Windows installer are what shipped, and stayed.

**Docker (implemented).** The image builds on the same slim ONNX path as the
Windows installer: detection runs on ONNX Runtime rather than PyTorch, so the
built image is a few gigabytes smaller than a torch/CUDA image would be. FFmpeg
comes from the distro package, dependencies install from the committed lock
file for reproducibility, and the detection model is baked in.

```bash
# Recommended: set a real password first, then let compose wire it through.
SVCS_DASHBOARD_PASSWORD='a-long-passphrase' docker compose up --build
```

Because the container binds `0.0.0.0`, the same non-localhost auth policy
applies as any other network bind: the container will not serve an
unauthenticated dashboard, and exits instead if credentials are missing and no
explicit opt-out was given. Terminate TLS at a reverse proxy for anything past
a trusted LAN, since Basic auth alone is plaintext on the wire.

**Windows installer (implemented).** PyInstaller freezes the application, and
Inno Setup wraps the frozen bundle into a single `SVCS-Setup-<version>.exe`
that vendors FFmpeg so a fresh machine needs nothing preinstalled. This is
covered in detail in the sections below.

**Considered and not used.** A bare PyInstaller executable was ruled out as
the primary path because of first-run antivirus friction and long, fragile
build times once OpenCV and the enhancement models are in the bundle. An
Electron shell around the existing Flask app remains a plausible stretch goal
(it would add relatively little risk, since the existing HTML/JS front end
needs no change to run inside it) but was not the path taken. A plain tarball
with a setup script is the simplest option for a systems administrator doing a
manual install and remains a fallback worth keeping in mind for that audience,
but was not built out.

**Compliance notes carried from the original deployment research**, since the
project's sponsor is a defense agency: the software stack (Python, Flask,
OpenCV, FFmpeg) has no components from a banned country of origin, and none of
the licenses involved (BSD, Apache-2.0, and FFmpeg's GPL/LGPL depending on
build, discussed below) create a distribution problem for an open-source,
source-available project. Camera hardware compliance is a separate concern
from the software, since SVCS only reads whatever RTSP stream a camera
exposes.

## 3. FFmpeg bundling and licensing

The installer vendors a specific FFmpeg binary so the app is self-contained,
with no separate "install FFmpeg first" step. At runtime SVCS resolves FFmpeg
in order: the bundled binary first, then a binary on `PATH`, then the bare
name `ffmpeg` as a last resort. A development checkout keeps using whatever
FFmpeg is already on `PATH`; the bundled binary only matters in the frozen
build.

**Why the bundled build is GPL, not LGPL.** The codec policy chosen for the
compression modes needs `libx264` for modes 0 and 1 (universal playback and a
clean royalty position relative to HEVC) and `libsvtav1` for modes 2 and 3.
`libx264` is GPL-2.0-or-later, so an LGPL FFmpeg build does not include it, and
using an LGPL build would leave modes 0 and 1 without an H.264 encoder.
Bundling a full GPL FFmpeg is license-compatible with the app's own AGPL-3.0
license, since AGPL-3.0 is compatible with GPL-2.0-or-later code. `libx265`
(HEVC) is present in the GPL build but is never selected by the app; its
patent licensing is fragmented and not royalty-free, so its presence in the
binary is irrelevant to what SVCS actually encodes.

**The seam for a future non-GPL fork**, should one ever be needed, is to swap
the bundle to an LGPL FFmpeg build and change the mode 0/1 default encoder from
`libx264` to `libopenh264` (BSD-licensed, included in LGPL builds). SVT-AV1
needs no change, since it is already BSD-licensed. That combination keeps the
entire bundled stack permissive with no GPL code, but is not in force for the
current AGPL edition.

The build script fetches a pinned FFmpeg release and places the binaries where
the PyInstaller spec bundles them from; the pinned version and download source
are recorded next to the fetch step in the build script itself, so they stay
current with whatever is actually shipping.

## 4. The ONNX slim install path

Early builds bundled PyTorch for object detection, which put the installer in
the multiple-gigabyte range. Switching detection to ONNX Runtime brought that
down sharply.

| Date | Build | Detection backend | Unpacked size |
|---|---|---|---|
| 2026-06-02 | Torch and Ultralytics bundled | PyTorch | about 4,632 MB |
| 2026-06-03 | Torch, Ultralytics, and CUDA excluded | ONNX Runtime | 339 MB |

That is roughly a 13.7x reduction in the unpacked bundle, comfortably inside
the target range, with detection working end to end on the ONNX backend. The
actual installer download compresses further: `SVCS-Setup-2.0.0.dev0.exe` came
out to 210.6 MB, about a 22x drop from the earliest PyTorch-era unpacked
bundle.

The detection model itself is a nano-sized YOLO network exported to ONNX from
its original PyTorch checkpoint; the `.onnx` weights are not committed to the
repository and are either shipped alongside the installer or fetched on first
run. A parity test asserts the ONNX backend agrees with the original PyTorch
model on detection results within a small tolerance, and skips cleanly when
the model or the test clip is not present, such as in a CI environment where
the model is a build artifact rather than a tracked file.

The enhancement model (Real-ESRGAN, used for optional post-process
upscaling) is not on the ONNX path yet; its dynamic input shapes and custom
upsampling made a clean export brittle enough that it was deliberately
deferred in favor of shipping the detector's win first, since detection runs
on every frame while enhancement is opt-in and comparatively rare.

## 5. Cutting a release

A repeatable checklist for a public release. Building and verifying is done by
whoever prepares the release; tagging and publishing the actual GitHub Release
is an owner action, gated on human judgment rather than automated.

1. **Pre-flight.** Switch to a clean checkout of the release branch, confirm
   the version recorded in the project's package metadata matches the intended
   tag, and sync the environment against the lock file.
2. **Quality gate.** Run the full test suite and confirm it is green.
3. **Build the installer**, which vendors FFmpeg, runs PyInstaller, and then
   compiles the Inno Setup script, producing
   `installer/dist/SVCS-Setup-<version>.exe`. Record both the unpacked bundle
   size and the final installer size for the release notes.
4. **Smoke-test the installer** on a clean Windows machine with no Python and
   no FFmpeg preinstalled: install, launch, confirm the dashboard opens, run a
   short clip through a preset and validate the output with `ffprobe` (not
   `cv2`, since a decode library mismatch would hide the very bug being
   checked for), confirm ONNX detection works with no PyTorch present, and
   confirm an uninstall leaves user data intact.
5. **Generate checksums.** A `SHA256SUMS.txt` next to the installer, verified
   against what the download page tells users to check.
6. **Draft the GitHub Release** from the prepared draft notes, attach the
   installer and its checksum file, and mark it a pre-release with the notes
   stating plainly that an unsigned beta will trigger a SmartScreen warning.
   Tagging and publishing itself is the owner's action.
7. **Code signing**, once a certificate is available, is wired into the build
   script as an opt-in flag that Authenticode-signs both the frozen bundle and
   the installer. It needs a Windows code-signing certificate, which is an
   owner-obtained resource; a free signing program for open-source projects is
   worth investigating before purchasing a commercial certificate. An unsigned
   beta ships without this step; a general-availability build should be
   signed.
8. **Post-publish.** Confirm the download page's "latest release" link
   resolves to the new asset, spot-check the published checksum file against a
   fresh download, and open a tracking item for the next milestone.

## 6. Publishing to winget

Publishing to the public winget repository, so that `winget install
Blood-Dawn.SVCS` works for anyone, is an owner-gated action: it requires a
published GitHub Release and, in practice, a code-signed installer, since
Microsoft's pipeline is far more likely to accept, and SmartScreen far less
likely to warn on, a signed binary. The manifest lives under
`installer/winget/` as three files: the version manifest, the installer
manifest, and the default-locale manifest.

The procedure, once a release is published: recompute the installer's SHA-256
against the exact byte-for-byte asset attached to the release and patch it
into the installer manifest (a helper script does both steps), validate the
manifest locally against the structural test suite and the official `winget
validate` schema checker, then submit either through `wingetcreate`, which
forks the `microsoft/winget-pkgs` repository and opens the pull request
automatically, or by forking that repository manually and opening the pull
request by hand. The winget continuous-integration bot then validates the
manifest and installs the package in a sandbox before a human reviewer merges
it.

Until the installer is code-signed, winget submission should be treated as a
release-time owner step, not something a routine build performs.

## 7. Linux AppImage and current build evidence

The Linux distribution path is an AppImage built by `installer/build.sh` and
the repository CI workflow. It is the portable offline artifact for Linux; the
Windows path remains the Inno Setup installer and the server deployment path
remains Docker. The AppImage build is owner-published: the CI artifact must be
smoke-tested, attached to the release, and checked against the release notes.

The two edition builds share the same source and spec. The Server edition
includes LAN-facing authentication, RTSP, and HLS surfaces. The Field edition
forces loopback and omits RTSP and HLS while retaining local compression,
auto-compress, retention, encryption, and plate reading. Verify the edition
marker in the frozen bundle instead of inferring it from the output folder.

The slim ONNX build is the shipping baseline. The YOLOv8-nano ONNX detector is
parity-tested and avoids bundling PyTorch or CUDA. Real-ESRGAN remains an
optional enhancement model and is not part of the slim detector path. The
optional plate-reader models are also not assumed to be bundled: their package
licenses and weight licenses must be checked separately before adding them to a
frozen installer.

The historical size evidence is retained in `build/build-metrics.md`: the unpacked
bundle dropped from about 4,632 MB in the Torch build to about 339 MB on the
ONNX path, and the early installer measured about 210.6 MB. These figures are
milestone measurements, not release guarantees; every release records fresh
bundle and installer sizes.

## 8. Canonical source records

The detailed source records remain beside this document for dated evidence:
`build/BUILDS.md`, `build/deployment_packaging.md`, `build/ffmpeg-licensing.md`,
`build/onnx-models.md`, `build/build-metrics.md`, `releases/RELEASE-CHECKLIST.md`,
and `releases/winget-submission.md`. Update this document when a current build policy or
release procedure changes; keep those records dated rather than deleting them.

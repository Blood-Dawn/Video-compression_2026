<#
.SYNOPSIS
    Install the ONNX license-plate reader into the SAME environment as SVCS core.

.DESCRIPTION
    R4 Phase 5. The recommended plate-reader backend is the ONNX ALPR stack
    (fast-plate-ocr + open-image-models, both MIT, torch-free, running on the
    core onnxruntime). Those packages declare opencv-python-headless as a
    REQUIRED dependency, which would clobber SVCS's opencv-contrib-python and
    remove cv2.bgsegm / MOG2. This script installs them with --no-deps so the
    existing opencv-contrib cv2 satisfies their runtime `import cv2`, then adds
    the ONLY missing runtime dependency (rich). onnxruntime / numpy / pyyaml /
    tqdm are already SVCS core deps.

    Validated end-to-end in docs/PLATES-VALIDATION.md.

    Run from the repo root with the SVCS venv active (or pass -Python):

        pwsh scripts/install_plates.ps1
        pwsh scripts/install_plates.ps1 -Python .\.venv\Scripts\python.exe

    After install, the dashboard's plate reader auto-detects the "onnx-alpr"
    backend (GET /api/enhance/plates/status). Models download from the Hugging
    Face hub on first use.

.NOTES
    --no-deps is NOT resolver-enforced: re-audit the cv2/numpy expectations of
    fast-plate-ocr / open-image-models on every upgrade (docs/BLOCKERS.md).
    Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 5).
#>

[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$Verify   # after install, import the packages to confirm they load
)

$ErrorActionPreference = "Stop"

Write-Host "==> Installing ONNX ALPR plate reader (no opencv-python-headless)..."

# 1) The ONNX ALPR packages, WITHOUT their deps (so headless is not pulled).
& $Python -m pip install --no-deps fast-plate-ocr open-image-models
if ($LASTEXITCODE -ne 0) { throw "pip install --no-deps failed (exit $LASTEXITCODE)" }

# 2) rich (only missing runtime dep beyond SVCS core) AND onnxruntime >= 1.19.2.
#    The PLATE DETECTOR (open-image-models) pins onnxruntime>=1.19.2, which is
#    HIGHER than SVCS core's >=1.16.0. Because step 1 is --no-deps, that floor is
#    not enforced - so ensure it here, or the detector would silently fail to
#    load and the reader would run OCR-only with no plate detection (review fix).
& $Python -m pip install rich "onnxruntime>=1.19.2"
if ($LASTEXITCODE -ne 0) { throw "pip install rich / onnxruntime>=1.19.2 failed (exit $LASTEXITCODE)" }

# 3) Confirm the core contrib cv2 is still intact (not clobbered).
$check = @'
import sys
import cv2
ok = hasattr(cv2, "bgsegm")
print("cv2", cv2.__version__, "bgsegm" , ("OK" if ok else "MISSING (clobbered!)"))
sys.exit(0 if ok else 1)
'@
& $Python -c $check
if ($LASTEXITCODE -ne 0) {
    throw "opencv-contrib was clobbered (cv2.bgsegm missing). A headless opencv " +
          "must have been pulled in. Reinstall opencv-contrib-python."
}

if ($Verify) {
    Write-Host "==> Verifying the ONNX backend loads (OCR + detector)..."
    $verify = @'
import sys
sys.path.insert(0, "src")
from enhancement.plate_reader import _select_backend
b = _select_backend("auto")
det = bool(getattr(b, "detector_available", False))
print("selected OCR backend:", b.name, "| ocr:", b.available, "| detector:", det)
if not (b.name == "onnx-alpr" and b.available):
    sys.exit(1)                                  # OCR itself must load
if not det:
    # Detector down (usually onnxruntime < 1.19.2): OCR-only mode still works,
    # but warn loudly rather than pass silently.
    print("WARNING: plate DETECTOR did not load - running OCR-only (no plate "
          "detection). Ensure onnxruntime>=1.19.2 in this environment.")
    sys.exit(2)
sys.exit(0)
'@
    & $Python -c $verify
    if ($LASTEXITCODE -eq 1) { throw "ONNX OCR backend did not load / was not selected." }
    elseif ($LASTEXITCODE -eq 2) {
        Write-Warning "Plate detector unavailable (OCR-only). Check onnxruntime>=1.19.2."
    }
}

Write-Host "==> Done. The dashboard will auto-detect the 'onnx-alpr' plate backend."
Write-Host "    Models download from the Hugging Face hub on first use."

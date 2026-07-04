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

# 2) The only runtime dep beyond SVCS core.
& $Python -m pip install rich
if ($LASTEXITCODE -ne 0) { throw "pip install rich failed (exit $LASTEXITCODE)" }

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
    Write-Host "==> Verifying the ONNX backend loads..."
    $verify = @'
import sys
sys.path.insert(0, "src")
from enhancement.plate_reader import _select_backend
b = _select_backend("auto")
print("selected OCR backend:", b.name, "| available:", b.available)
sys.exit(0 if b.name == "onnx-alpr" and b.available else 1)
'@
    & $Python -c $verify
    if ($LASTEXITCODE -ne 0) { throw "ONNX backend did not load / was not selected." }
}

Write-Host "==> Done. The dashboard will auto-detect the 'onnx-alpr' plate backend."
Write-Host "    Models download from the Hugging Face hub on first use."

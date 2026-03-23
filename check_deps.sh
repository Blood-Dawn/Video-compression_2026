#!/usr/bin/env bash
# check_deps.sh
# Run this script from the project root to verify your environment is ready.
# Usage: bash check_deps.sh

set -euo pipefail

PASS=0
FAIL=0

green()  { echo -e "\033[32m✅  $1\033[0m"; }
red()    { echo -e "\033[31m❌  $1\033[0m"; }
yellow() { echo -e "\033[33m⚠️   $1\033[0m"; }
header() { echo -e "\n\033[1m$1\033[0m"; }

header "========================================="
header " Capstone Compression — Dependency Check "
header "========================================="

# ── 1. Python version ─────────────────────────────────────────────────────────
header "[1/6] Python version"

PYTHON_BIN=""
for bin in python3 python; do
    if command -v "$bin" &>/dev/null; then
        PYTHON_BIN="$bin"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    red "Python not found. Install Python 3.9 or higher."
    FAIL=$((FAIL + 1))
else
    PY_VER=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.major)")
    PY_MINOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.minor)")
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 9 ]; then
        green "Python $PY_VER found at $(command -v $PYTHON_BIN)"
        PASS=$((PASS + 1))
    else
        red "Python $PY_VER is too old. Need 3.9 or higher."
        echo "    → Install from https://www.python.org or use pyenv."
        FAIL=$((FAIL + 1))
    fi
fi

# ── 2. FFmpeg ─────────────────────────────────────────────────────────────────
header "[2/6] FFmpeg (system binary)"

if command -v ffmpeg &>/dev/null; then
    FFMPEG_VER=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
    green "FFmpeg $FFMPEG_VER found at $(command -v ffmpeg)"
    PASS=$((PASS + 1))
else
    red "FFmpeg not found on PATH."
    echo "    → Ubuntu/Debian:  sudo apt update && sudo apt install ffmpeg -y"
    echo "    → macOS:          brew install ffmpeg"
    echo "    → Windows WSL2:   sudo apt update && sudo apt install ffmpeg -y"
    FAIL=$((FAIL + 1))
fi

# ── 3. Python packages ────────────────────────────────────────────────────────
header "[3/6] Python packages (from requirements.txt)"

if [ -z "$PYTHON_BIN" ]; then
    yellow "Skipping package check — Python not found."
else
    PACKAGES=(
        "cv2"
        "numpy"
        "PIL"
        "ffmpeg"
        "tqdm"
        "yaml"
        "click"
        "skimage"
        "scipy"
        "jupyter"
        "matplotlib"
        "pandas"
        "pytest"
    )

    ALL_PKG_OK=1
    for pkg in "${PACKAGES[@]}"; do
        if "$PYTHON_BIN" -c "import $pkg" &>/dev/null 2>&1; then
            green "  import $pkg — OK"
            PASS=$((PASS + 1))
        else
            red "  import $pkg — MISSING"
            echo "      → Run: pip install -r requirements.txt"
            FAIL=$((FAIL + 1))
            ALL_PKG_OK=0
        fi
    done

    if [ "$ALL_PKG_OK" -eq 1 ]; then
        echo ""
        green "All Python packages are installed."
    else
        echo ""
        red "Some packages are missing. Run: pip install -r requirements.txt"
    fi
fi

# ── 4. Virtual environment ────────────────────────────────────────────────────
header "[4/6] Virtual environment"

if [ -n "${VIRTUAL_ENV:-}" ]; then
    green "Virtual environment active: $VIRTUAL_ENV"
    PASS=$((PASS + 1))
elif [ -d "venv" ]; then
    yellow "A 'venv' folder exists but is not currently active."
    echo "    → Activate it with:  source venv/bin/activate"
else
    yellow "No virtual environment detected."
    echo "    → Create one with:  python3 -m venv venv"
    echo "    → Then activate:    source venv/bin/activate"
    echo "    → Then install:     pip install -r requirements.txt"
fi

# ── 5. Required directories ───────────────────────────────────────────────────
header "[5/6] Required directories"

DIRS=("data/samples" "outputs" "logs" "notebooks" "docs")

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        green "  $dir/ — exists"
        PASS=$((PASS + 1))
    else
        yellow "  $dir/ — missing (creating it now)"
        mkdir -p "$dir"
        green "  $dir/ — created"
        PASS=$((PASS + 1))
    fi
done

# ── 6. Test video clips ───────────────────────────────────────────────────────
header "[6/6] Test video clips"

VIDEO_COUNT=$(find data/samples -maxdepth 1 \( -name "*.mp4" -o -name "*.avi" -o -name "*.mov" \) 2>/dev/null | wc -l | tr -d ' ')

if [ "$VIDEO_COUNT" -gt 0 ]; then
    green "Found $VIDEO_COUNT test clip(s) in data/samples/"
    find data/samples -maxdepth 1 \( -name "*.mp4" -o -name "*.avi" -o -name "*.mov" \) | while read -r f; do
        echo "      → $f"
    done
    PASS=$((PASS + 1))
else
    yellow "No test clips found in data/samples/"
    echo "    → Ask a teammate for the shared test clips."
    echo "    → Or place any .mp4 file in data/samples/ for testing."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
header "========================================="
header " Summary"
header "========================================="

if [ "$FAIL" -eq 0 ]; then
    echo ""
    green "All checks passed. You are ready to run the pipeline."
    echo ""
    echo "  Quick start:"
    echo "    python src/pipeline/pipeline.py \\"
    echo "      --input data/samples/your_clip.mp4 \\"
    echo "      --camera-id cam_test \\"
    echo "      --output outputs/ \\"
    echo "      --preview"
    echo ""
else
    echo ""
    red "$FAIL check(s) failed. Fix the issues above before running the pipeline."
    echo "  See DEV.md → Section 10 (Common Problems and Fixes) for help."
    echo ""
fi

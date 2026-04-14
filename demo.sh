#!/usr/bin/env bash
# demo.sh
# One-click demo launcher for the selective video compression pipeline.
# Runs the pipeline on the test clip with sensible defaults and shows
# a live preview of the foreground mask alongside the original feed.
#
# Usage:
#   bash demo.sh                          # default: test clip, mode0
#   bash demo.sh --mode mode1             # frame gating mode
#   bash demo.sh --input 0               # live webcam
#   bash demo.sh --input /path/to/my.mp4 # custom clip
#
# Author: Bloodawn (KheivenD)
# EGN 4950C Capstone — Group 16 — Spring 2026

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_INPUT="data/samples/test_clip.mp4"
DEFAULT_CAMERA_ID="cam_demo"
DEFAULT_OUTPUT="outputs/"
DEFAULT_SEGMENT=60        # seconds per output segment
DEFAULT_METHOD="MOG2"
DEFAULT_WARMUP=120        # frames before encoding starts
DEFAULT_MODE="mode0"

# ─── Parse optional overrides from CLI ────────────────────────────────────────

INPUT="${1:-}"
CAMERA_ID="$DEFAULT_CAMERA_ID"
OUTPUT="$DEFAULT_OUTPUT"
SEGMENT="$DEFAULT_SEGMENT"
METHOD="$DEFAULT_METHOD"
WARMUP="$DEFAULT_WARMUP"
MODE="$DEFAULT_MODE"

# Allow passing --input, --mode, etc. after the script name
while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)     INPUT="$2";     shift 2 ;;
    --camera-id) CAMERA_ID="$2"; shift 2 ;;
    --output)    OUTPUT="$2";    shift 2 ;;
    --segment)   SEGMENT="$2";   shift 2 ;;
    --method)    METHOD="$2";    shift 2 ;;
    --warmup)    WARMUP="$2";    shift 2 ;;
    --mode)      MODE="$2";      shift 2 ;;
    *) shift ;;
  esac
done

# Fall back to default input if none given
if [[ -z "$INPUT" ]]; then
  INPUT="$DEFAULT_INPUT"
fi

# ─── Pre-flight checks ────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Selective Video Compression Pipeline — Live Demo       ║"
echo "║   EGN 4950C Capstone · Group 16 · FAU Spring 2026        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
  echo "ERROR: python3 not found. Install Python 3.9+ and try again."
  exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python   : $PYTHON_VERSION"

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
  echo ""
  echo "ERROR: ffmpeg not found. Install FFmpeg and ensure it is on PATH."
  echo "  Ubuntu:  sudo apt install ffmpeg -y"
  echo "  macOS:   brew install ffmpeg"
  exit 1
fi

FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
echo "  FFmpeg   : $FFMPEG_VERSION"

# Activate venv if present and not already active
if [[ -z "${VIRTUAL_ENV:-}" && -f "venv/bin/activate" ]]; then
  echo "  Venv     : activating venv/"
  source venv/bin/activate
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "  Venv     : $VIRTUAL_ENV (already active)"
else
  echo "  Venv     : none — using system Python"
fi

# Create output directory
mkdir -p "$OUTPUT"
echo "  Output   : $OUTPUT"

# Warn if test clip is missing (don't abort — user may be passing a live camera)
if [[ "$INPUT" != "0" && ! -f "$INPUT" ]]; then
  echo ""
  echo "WARNING: Input file not found: $INPUT"
  echo "  Place a test .mp4 clip at $DEFAULT_INPUT, or pass a custom path:"
  echo "    bash demo.sh --input /path/to/your/clip.mp4"
  echo ""
fi

# ─── Launch ───────────────────────────────────────────────────────────────────

echo ""
echo "  Mode     : $MODE ($(
  case "$MODE" in
    mode0) echo "24/7 continuous — all frames encoded" ;;
    mode1) echo "frame gating — active frames only" ;;
    mode2) echo "background keyframe + object patches" ;;
    mode3) echo "object-only forensic mode" ;;
    *)     echo "$MODE" ;;
  esac
))"
echo "  Input    : $INPUT"
echo "  Camera   : $CAMERA_ID"
echo "  Segment  : ${SEGMENT}s"
echo "  Warmup   : ${WARMUP} frames"
echo "  Method   : $METHOD"
echo ""
echo "  Press Ctrl+C to stop."
echo "  Press Q in the preview window to stop."
echo ""

python3 src/pipeline/pipeline.py \
  --input     "$INPUT" \
  --camera-id "$CAMERA_ID" \
  --output    "$OUTPUT" \
  --segment   "$SEGMENT" \
  --method    "$METHOD" \
  --warmup    "$WARMUP" \
  --mode      "$MODE" \
  --preview

echo ""
echo "Demo finished. Output segments in: $OUTPUT"
echo "Query the metadata database:"
echo "  sqlite3 $OUTPUT/metadata.db \"SELECT camera_id, file_path, file_size, target_detected FROM segments;\""
echo ""

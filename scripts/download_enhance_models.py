"""
scripts/download_enhance_models.py

Fetches the weight files every real SR Model dropdown option needs, straight
from their original upstream sources (no re-hosting - see DEV.md ->
"Enhancement Module Setup" for the full attribution/license table).

Usage:
    uv run python scripts/download_enhance_models.py            # all 6 models
    uv run python scripts/download_enhance_models.py espcn edsr # just these
    uv run python scripts/download_enhance_models.py --dest D:\\models

Safe to re-run: an already-present file (matched by name) is skipped unless
--force is given.

Author: Bloodawn (KheivenD), 2026-09-24 (M0 TASK - real AI-enhance models).
"""

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# (filename, source URL, approx size for the progress message)
_FILES = {
    "espcn": [
        ("ESPCN_x2.pb", "https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x2.pb", "86 KB"),
        ("ESPCN_x3.pb", "https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x3.pb", "92 KB"),
        ("ESPCN_x4.pb", "https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x4.pb", "100 KB"),
    ],
    "fsrcnn": [
        ("FSRCNN_x2.pb", "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x2.pb", "39 KB"),
        ("FSRCNN_x3.pb", "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x3.pb", "40 KB"),
        ("FSRCNN_x4.pb", "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x4.pb", "42 KB"),
    ],
    "edsr": [
        ("EDSR_x2.pb", "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x2.pb", "37 MB"),
        ("EDSR_x3.pb", "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x3.pb", "37 MB"),
        ("EDSR_x4.pb", "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x4.pb", "37 MB"),
    ],
    "lapsrn": [
        ("LapSRN_x2.pb", "https://github.com/fannymonori/TF-LapSRN/raw/master/export/LapSRN_x2.pb", "1.3 MB"),
        ("LapSRN_x4.pb", "https://github.com/fannymonori/TF-LapSRN/raw/master/export/LapSRN_x4.pb", "2.6 MB"),
        ("LapSRN_x8.pb", "https://github.com/fannymonori/TF-LapSRN/raw/master/export/LapSRN_x8.pb", "3.9 MB"),
    ],
    "realesrgan": [
        ("RealESRGAN_x4plus.pth",
         "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth", "64 MB"),
    ],
    "realesrnet": [
        ("RealESRNet_x4plus.pth",
         "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.1/RealESRNet_x4plus.pth", "64 MB"),
    ],
}


def _download(url: str, dest: Path, size_hint: str) -> bool:
    print(f"  {dest.name:<24} ({size_hint}) ... ", end="", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "svcs-enhance-model-fetcher"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
            out.write(resp.read())
        print(f"OK ({dest.stat().st_size:,} bytes)")
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"FAILED ({exc})")
        if dest.exists():
            dest.unlink()  # don't leave a partial/empty file behind
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "models", nargs="*", choices=list(_FILES) + [[]],
        help="Which models to fetch (default: all 6). "
             f"Choices: {', '.join(_FILES)}",
    )
    parser.add_argument(
        "--dest", default=str(REPO_ROOT / "models"),
        help="Destination directory (default: <repo>/models)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-download even if a file with the same name already exists",
    )
    args = parser.parse_args()

    wanted = args.models or list(_FILES)
    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading weights for: {', '.join(wanted)}")
    print(f"Destination: {dest_dir}\n")

    ok_count = 0
    fail_count = 0
    skip_count = 0
    for model in wanted:
        for filename, url, size_hint in _FILES[model]:
            dest = dest_dir / filename
            if dest.exists() and not args.force:
                print(f"  {filename:<24} already present, skipping (use --force to redo)")
                skip_count += 1
                continue
            if _download(url, dest, size_hint):
                ok_count += 1
            else:
                fail_count += 1

    print(f"\nDone: {ok_count} downloaded, {skip_count} already present, {fail_count} failed.")
    if fail_count:
        print("A failed model falls back to bicubic honestly - see the SR ENHANCE chip "
              "in the dashboard - it just won't be the AI you picked. Re-run this script "
              "to retry, or fetch the URL manually (see DEV.md -> 'Enhancement Module Setup').")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())

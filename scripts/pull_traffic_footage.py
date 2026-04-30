"""
pull_traffic_footage.py

Download live HLS traffic camera footage for offline SVCS testing.

Usage:
    uv run python scripts/pull_traffic_footage.py

Requirements:
    ffmpeg on PATH
    pip install requests beautifulsoup4 (or: uv add requests beautifulsoup4)

This script tries two sources:
    1. goakamai.org  -- Hawaii state traffic cameras (Cody's recommendation).
                        All cameras stream 24/7 at full HD. Pull the HLS URL
                        from the page source and record for RECORD_SECONDS.
    2. Fallback list -- Known public HLS streams if gookami is unreachable.

Output goes to: data/samples/traffic/
Each clip is saved as: <camera_id>_<timestamp>.mp4
"""

import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUTPUT_DIR = Path("data/samples/traffic")
RECORD_SECONDS = 120    # how many seconds to record per clip (2 min default)
TIMEOUT_S = 10          # HTTP request timeout


# ---------------------------------------------------------------------------
# Known fallback public HLS streams (no login required)
# ---------------------------------------------------------------------------

FALLBACK_STREAMS = [
    # video.js test streams (Cody mentioned these as public test sources)
    {
        "id": "videojs_elephants_dream",
        "url": "https://d2zihajmogu5jn.cloudfront.net/elephantsdream/hls/ed_hd.m3u8",
        "note": "video.js public test stream (Elephant's Dream, indoor, no traffic)",
    },
    # DOT public feeds (GDOT Georgia, no login)
    {
        "id": "gdot_atlanta_i285",
        "url": "https://511ga.org/video-stream?id=GA4-CAM--0001",
        "note": "GDOT live camera feed -- try if HLS URL visible in page source",
    },
]


# ---------------------------------------------------------------------------
# gookami.org scraper
# ---------------------------------------------------------------------------

def scrape_gookami_streams(n: int = 3) -> list[dict]:
    """
    Attempt to find HLS stream URLs from gookami.org Hawaii traffic cameras.

    gookami.org embeds the camera HLS URLs directly in the page HTML.
    Strategy: fetch the main page, find <source> or <video> tags or JS strings
    containing .m3u8 URLs. Return up to n streams as {id, url, note} dicts.

    If the site is unreachable this returns an empty list and the caller falls
    back to FALLBACK_STREAMS.
    """
    try:
        resp = requests.get("https://www.goakamai.org", timeout=TIMEOUT_S, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print(f"[goakamai] Could not reach site: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    m3u8_urls = set()

    # Look in <source src="..."> tags
    for tag in soup.find_all("source"):
        src = tag.get("src", "")
        if ".m3u8" in src:
            m3u8_urls.add(src)

    # Look in raw HTML text (JS variables, data attributes, etc.)
    import re
    for match in re.findall(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', resp.text):
        m3u8_urls.add(match)

    results = []
    for i, url in enumerate(sorted(m3u8_urls)[:n]):
        results.append({
            "id": f"gookami_cam_{i+1:02d}",
            "url": url,
            "note": "Hawaii DOT traffic camera via gookami.org",
        })

    if results:
        print(f"[goakamai] Found {len(results)} stream(s).")
    else:
        print("[goakamai] No .m3u8 URLs found in page source.")

    return results


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------

def record_stream(stream: dict, output_dir: Path, duration_s: int) -> Path | None:
    """
    Record `duration_s` seconds of an HLS stream to an .mp4 file using FFmpeg.

    Returns the output path on success, None on failure.
    """
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out = output_dir / f"{stream['id']}_{ts}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", stream["url"],
        "-t", str(duration_s),
        "-c", "copy",               # stream copy, no re-encode
        "-an",                      # drop audio (saves space; SVCS is video-only)
        str(out),
    ]

    print(f"\n[record] {stream['id']} -> {out.name}")
    print(f"         Source: {stream['url']}")
    print(f"         Duration: {duration_s}s")

    try:
        result = subprocess.run(cmd, timeout=duration_s + 60, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[record] FFmpeg error:\n{result.stderr[-800:]}")
            return None
        size_mb = out.stat().st_size / 1e6 if out.exists() else 0
        print(f"[record] Done. File size: {size_mb:.1f} MB")
        return out
    except subprocess.TimeoutExpired:
        print("[record] Timed out.")
        return None
    except FileNotFoundError:
        print("[record] ffmpeg not found on PATH. Install FFmpeg and try again.")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {OUTPUT_DIR.resolve()}\n")

    # Try gookami first
    streams = scrape_gookami_streams(n=3)

    # Fall back to known public streams if gookami came up empty
    if not streams:
        print("[main] Using fallback streams.")
        streams = FALLBACK_STREAMS

    saved = []
    for stream in streams:
        path = record_stream(stream, OUTPUT_DIR, RECORD_SECONDS)
        if path:
            saved.append(path)

    print(f"\n{'='*60}")
    print(f"Saved {len(saved)} clip(s):")
    for p in saved:
        print(f"  {p}")

    if not saved:
        print("\nNo clips were saved. Possible causes:")
        print("  - gookami.org unreachable and fallback streams also failed")
        print("  - ffmpeg not installed")
        print("\nManual steps:")
        print("  1. Open https://gookami.org in your browser.")
        print("  2. Right-click a camera embed, Inspect Element.")
        print("  3. Find the .m3u8 URL in the <video> or <source> tag.")
        print("  4. Run:  ffmpeg -i <url> -t 120 -c copy data/samples/traffic/clip.mp4")


if __name__ == "__main__":
    main()

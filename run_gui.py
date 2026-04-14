#!/usr/bin/env python3
"""
run_gui.py  —  Launch the SVCS web dashboard.

Usage:
    python run_gui.py              # default: http://localhost:5000
    python run_gui.py --port 8080  # custom port
    python run_gui.py --host 0.0.0.0 --port 5000  # accessible over LAN

The dashboard opens in your browser at http://localhost:5000
Drop your test videos into the data/ folder and click the ⟳ button
to find them automatically.

Author: Bloodawn (KheivenD)
"""

import argparse
import sys
import webbrowser
from pathlib import Path
from threading import Timer

# Make src/ importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gui.app import app


def _open_browser(host: str, port: int):
    h = "localhost" if host == "0.0.0.0" else host
    webbrowser.open(f"http://{h}:{port}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SVCS Web Dashboard")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1). "
                             "Use 0.0.0.0 to allow LAN access.")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open browser")
    args = parser.parse_args()

    print(f"\n{'━'*55}")
    print(f"  SVCS Dashboard")
    print(f"  http://{args.host}:{args.port}")
    print(f"{'━'*55}")
    print(f"  Drop test videos into:  {Path('data').resolve()}")
    print(f"  Outputs written to:     {Path('outputs').resolve()}")
    print(f"  Press Ctrl+C to stop.")
    print(f"{'━'*55}\n")

    if not args.no_browser:
        Timer(1.2, _open_browser, args=[args.host, args.port]).start()

    app.run(host=args.host, port=args.port, debug=False, threaded=True)

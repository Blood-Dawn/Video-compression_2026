"""
src/utils/rtsp_server.py

Optional local RTSP server manager using MediaMTX (MIT-licensed).
https://github.com/bluenviron/mediamtx

Lets developers and demo operators run a local RTSP stream without any
external server or cloud dependency.  The binary is downloaded on first use
and cached in <project_root>/tools/mediamtx/.

Typical flow:
    mgr = RtspServerManager(tools_dir=Path("tools"))
    mgr.download()              # first time: pulls the right binary for the OS
    mgr.start()                 # starts mediamtx on rtsp://localhost:8554/
    mgr.push("highway.mp4")    # FFmpeg loops the file into rtsp://localhost:8554/live
    # point the HLS panel at rtsp://localhost:8554/live
    mgr.stop()                  # stops everything cleanly

Author: EGN 4950C Group 16
"""

import platform
import subprocess
import tarfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

try:                                       # bundled-first ffmpeg resolution (TASK 2.3)
    from utils.ffmpeg import ffmpeg_path
except ImportError:                        # pragma: no cover - import path shim
    from src.utils.ffmpeg import ffmpeg_path

# ── MediaMTX release config ───────────────────────────────────────────────────

MEDIAMTX_VERSION = "1.9.3"
_GITHUB_BASE = (
    f"https://github.com/bluenviron/mediamtx/releases/download/v{MEDIAMTX_VERSION}"
)
RTSP_PORT = 8554
DEFAULT_STREAM = "live"


def _platform_asset() -> tuple[str, str]:
    """Return (archive_filename, executable_name) for the current platform/arch."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine in ("amd64", "x86_64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    elif "arm" in machine:
        arch = "armv7"
    else:
        arch = "amd64"  # safest fallback

    if system == "windows":
        return f"mediamtx_v{MEDIAMTX_VERSION}_windows_{arch}.zip", "mediamtx.exe"
    elif system == "darwin":
        return f"mediamtx_v{MEDIAMTX_VERSION}_darwin_{arch}.tar.gz", "mediamtx"
    else:  # linux and everything else
        return f"mediamtx_v{MEDIAMTX_VERSION}_linux_{arch}.tar.gz", "mediamtx"


# ── Manager ───────────────────────────────────────────────────────────────────


class RtspServerManager:
    """Download, start, stop, and monitor a local MediaMTX RTSP server."""

    def __init__(self, tools_dir: Path):
        self.tools_dir = tools_dir
        self._lock = threading.Lock()

        # subprocess handles
        self._proc: Optional[subprocess.Popen] = None
        self._push_proc: Optional[subprocess.Popen] = None

        # mutable state (all access under _lock)
        self._server_running: bool = False
        self._pushing: bool = False
        self._push_source: Optional[str] = None
        self._push_stream: Optional[str] = None
        self._download_progress: Optional[str] = None  # "0%" … "100%" | "extracting" | "done"
        self._download_error: Optional[str] = None
        self._server_error: Optional[str] = None
        self._downloading: bool = False

    # ── paths ─────────────────────────────────────────────────────────────────

    @property
    def _exe_name(self) -> str:
        _, exe = _platform_asset()
        return exe

    @property
    def binary_path(self) -> Path:
        return self.tools_dir / "mediamtx" / self._exe_name

    def binary_present(self) -> bool:
        return self.binary_path.exists()

    # ── download ──────────────────────────────────────────────────────────────

    def start_download(self, progress_cb: Optional[Callable[[str], None]] = None) -> threading.Thread:
        """Start the download in a daemon thread.  Returns the thread."""
        with self._lock:
            if self._downloading:
                raise RuntimeError("Download already in progress")
            self._downloading = True
            self._download_progress = "0%"
            self._download_error = None

        def _worker():
            try:
                self._do_download(progress_cb)
            except Exception as exc:
                with self._lock:
                    self._download_error = str(exc)
                    self._download_progress = None
            finally:
                with self._lock:
                    self._downloading = False

        t = threading.Thread(target=_worker, daemon=True, name="mediamtx-download")
        t.start()
        return t

    def _do_download(self, progress_cb: Optional[Callable[[str], None]]) -> None:
        fname, _exe = _platform_asset()
        url = f"{_GITHUB_BASE}/{fname}"
        dest_dir = self.tools_dir / "mediamtx"
        dest_dir.mkdir(parents=True, exist_ok=True)
        archive = dest_dir / fname

        def _reporthook(block_num: int, block_size: int, total_size: int):
            if total_size > 0:
                pct = min(100, int(block_num * block_size * 100 / total_size))
                with self._lock:
                    self._download_progress = f"{pct}%"
                if progress_cb:
                    progress_cb(f"{pct}%")

        urllib.request.urlretrieve(url, archive, _reporthook)

        with self._lock:
            self._download_progress = "extracting"
        if progress_cb:
            progress_cb("extracting")

        if fname.endswith(".zip"):
            with zipfile.ZipFile(archive, "r") as z:
                z.extractall(dest_dir)
        else:
            with tarfile.open(archive, "r:gz") as t:
                t.extractall(dest_dir)

        archive.unlink(missing_ok=True)

        # Make executable on Unix/macOS
        if platform.system() != "Windows":
            self.binary_path.chmod(0o755)

        with self._lock:
            self._download_progress = "done"
        if progress_cb:
            progress_cb("done")

    # ── server lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Start MediaMTX.  Raises RuntimeError if not ready or already running."""
        with self._lock:
            if self._server_running:
                raise RuntimeError("RTSP server is already running")
        if not self.binary_present():
            raise RuntimeError("MediaMTX binary not found. Run download first.")

        # MediaMTX works fine with no config file; defaults open port 8554
        proc = subprocess.Popen(
            [str(self.binary_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(self.binary_path.parent),
        )
        with self._lock:
            self._proc = proc
            self._server_running = True
            self._server_error = None

    def stop(self) -> None:
        """Stop MediaMTX and any active FFmpeg push."""
        self.stop_push()
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        with self._lock:
            self._proc = None
            self._server_running = False

    def is_running(self) -> bool:
        """Return True if the server process is alive."""
        with self._lock:
            proc = self._proc
            running = self._server_running
        if running and proc and proc.poll() is not None:
            # Died unexpectedly
            with self._lock:
                self._server_running = False
                self._server_error = "MediaMTX exited unexpectedly"
            return False
        return running

    # ── push ─────────────────────────────────────────────────────────────────

    def push(self, video_path: str, stream_name: str = DEFAULT_STREAM) -> None:
        """Loop video_path into the RTSP server via FFmpeg.

        The video is re-read from the start each loop (-stream_loop -1) at
        real-time pace (-re) so it acts like a live camera feed.
        Audio is dropped because surveillance pipelines don't use it.
        """
        self.stop_push()

        rtsp_dest = f"rtsp://localhost:{RTSP_PORT}/{stream_name}"
        cmd = [
            ffmpeg_path(), "-y",
            "-re",               # real-time pacing (simulate live camera)
            "-stream_loop", "-1",  # loop indefinitely
            "-i", video_path,
            "-vcodec", "copy",   # passthrough (no re-encode needed)
            "-an",               # drop audio
            "-f", "rtsp",
            rtsp_dest,
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with self._lock:
            self._push_proc = proc
            self._pushing = True
            self._push_source = video_path
            self._push_stream = stream_name

    def stop_push(self) -> None:
        """Stop the active FFmpeg push process."""
        with self._lock:
            proc = self._push_proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        with self._lock:
            self._push_proc = None
            self._pushing = False
            self._push_source = None
            self._push_stream = None

    # ── state snapshot ────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Return a JSON-serialisable snapshot of current manager state."""
        running = self.is_running()  # also detects unexpected exits

        with self._lock:
            pushing = self._pushing
            push_source = self._push_source
            push_stream = self._push_stream
            # Detect push process that exited on its own
            pp = self._push_proc
            if pushing and pp and pp.poll() is not None:
                self._pushing = False
                self._push_source = None
                self._push_stream = None
                pushing = False
                push_source = None
                push_stream = None

        return {
            "binary_present": self.binary_present(),
            "version": MEDIAMTX_VERSION,
            "server_running": running,
            "pushing": pushing,
            "push_source": push_source,
            "push_stream": push_stream,
            "rtsp_url": (
                f"rtsp://localhost:{RTSP_PORT}/{push_stream or DEFAULT_STREAM}"
                if running else None
            ),
            "downloading": self._downloading,
            "download_progress": self._download_progress,
            "download_error": self._download_error,
            "server_error": self._server_error,
        }

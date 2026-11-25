"""
src/gui/native_dialog.py

Native open-file and pick-folder dialogs shown on the server PC.

Why this exists: the old /api/browse route ran ``sys.executable -c <tkinter
script>``. In the installed app ``sys.executable`` is SVCS.exe, which does not
understand ``-c``, so every Browse button that used /api/browse silently did
nothing (the Encrypt and Unlock pages, the Home source picker). The Library
picker had already been moved to PowerShell; this module gives every picker the
same working path.

On Windows the dialogs run in a PowerShell child (WinForms, STA thread) owned by
a hidden top-most form, so the dialog opens in front of the browser instead of
behind it. Elsewhere tkinter is used, but only from a real Python interpreter.

Author: Bloodawn (KheivenD), 2026-11-25 (button sweep).
"""
from __future__ import annotations

import subprocess
import sys

try:
    from gui.logging_setup import log
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log

#: Filters per picker kind: (title, WinForms filter, tkinter filetypes).
_VIDEO_EXT = ("*.mp4 *.avi *.mov *.mkv *.ts *.m4v *.wmv *.flv *.mpg *.mpeg *.dav "
              "*.264 *.h264 *.265 *.hevc *.g64 *.sdv *.mxf")
KINDS = {
    "video": ("Select a video file",
              "Video files|" + _VIDEO_EXT.replace(" ", ";") + "|All files|*.*",
              [("Video files", _VIDEO_EXT), ("All files", "*.*")]),
    "enc": ("Select an encrypted video",
            "Encrypted video (*.enc)|*.enc|All files|*.*",
            [("Encrypted video", "*.enc"), ("All files", "*.*")]),
    "key": ("Select a key file",
            "Key file (*.key)|*.key|All files|*.*",
            [("Key file", "*.key"), ("All files", "*.*")]),
    "any": ("Select a file", "All files|*.*", [("All files", "*.*")]),
}

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no console flash from the frozen app


def _ps_quote(text: str) -> str:
    """Single-quote a value for PowerShell."""
    return "'" + str(text).replace("'", "''") + "'"


def _run_powershell(body: str, timeout: int) -> str:
    """Run a WinForms dialog script and return what it printed (UTF-8)."""
    ps = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; "
        "ShowInTaskbar=$false; WindowState='Minimized'}; "
        + body
    )
    kwargs = {"capture_output": True, "timeout": timeout}
    if sys.platform == "win32":
        kwargs["creationflags"] = _NO_WINDOW
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", ps],
        **kwargs)
    out = result.stdout or b""
    if isinstance(out, bytes):
        out = out.decode("utf-8", errors="replace")
    return out.strip().lstrip("﻿")


def _run_tk(script: str, timeout: int) -> str:
    if getattr(sys, "frozen", False):
        # A frozen exe cannot run "-c"; report instead of launching a second app.
        log.warning("Native file dialog is not available in this build on %s.", sys.platform)
        return ""
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, timeout=timeout)
    return (result.stdout or "").strip()


def pick_file(kind: str = "video", timeout: int = 300) -> str:
    """Show an open-file dialog. Returns the chosen path, or "" if cancelled."""
    title, win_filter, tk_types = KINDS.get(kind, KINDS["any"])
    try:
        if sys.platform == "win32":
            return _run_powershell(
                "$d = New-Object System.Windows.Forms.OpenFileDialog; "
                f"$d.Title = {_ps_quote(title)}; $d.Filter = {_ps_quote(win_filter)}; "
                "$d.Multiselect = $false; "
                "if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) "
                "{ [Console]::Out.Write($d.FileName) }; $owner.Dispose()",
                timeout)
        script = (
            "import tkinter as tk; from tkinter import filedialog; "
            "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); "
            f"path = filedialog.askopenfilename(title={title!r}, filetypes={tk_types!r}); "
            "root.destroy(); print(path or '', end='')")
        return _run_tk(script, timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.warning("File picker failed: %s", exc)
        return ""


def pick_folder(title: str = "Select a folder", timeout: int = 300) -> str:
    """Show a pick-folder dialog. Returns the chosen folder, or "" if cancelled."""
    try:
        if sys.platform == "win32":
            return _run_powershell(
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$d.Description = {_ps_quote(title)}; $d.ShowNewFolderButton = $true; "
                "if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) "
                "{ [Console]::Out.Write($d.SelectedPath) }; $owner.Dispose()",
                timeout)
        script = (
            "import tkinter as tk; from tkinter import filedialog; "
            "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); "
            f"path = filedialog.askdirectory(title={title!r}); "
            "root.destroy(); print(path or '', end='')")
        return _run_tk(script, timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.warning("Folder picker failed: %s", exc)
        return ""

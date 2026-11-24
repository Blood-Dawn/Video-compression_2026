"""
SVCS Unlock: a tiny standalone viewer for SVCS-encrypted videos (.enc).

Double-click an .enc file (or run `SVCS-Unlock.exe file.enc`). It asks for the
password or key file, unlocks the video to a private temporary folder, plays it
in your default video player, and deletes the unlocked copy when you close the
window. It needs nothing else from SVCS, so it can be sent along with a clip.

Only this file, utils/encryption.py and the `cryptography` package are required.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

try:
    from utils.encryption import decrypt_file
except ModuleNotFoundError:  # pragma: no cover - source or bundled layouts
    from src.utils.encryption import decrypt_file


def unlock(enc_path, password: str | None = None, keyfile: str | None = None) -> Path:
    """Decrypt ``enc_path`` into a fresh private temp folder; return the video path.

    Raises ValueError for a missing credential, RuntimeError for a wrong
    password or key (authentication fails), FileNotFoundError for a bad path.
    The temp folder is removed again if decryption fails.
    """
    enc = Path(enc_path)
    if not enc.is_file():
        raise FileNotFoundError(f"File not found: {enc}")
    key = None
    if keyfile:
        key = Path(keyfile).read_bytes()
        password = None
    elif not password:
        raise ValueError("Enter the password or choose a key file.")
    work = Path(tempfile.mkdtemp(prefix="svcs_unlock_"))
    name = enc.name[:-4] if enc.name.lower().endswith(".enc") else enc.name + ".mp4"
    try:
        return decrypt_file(enc, password=password, key=key, output_path=work / name)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def cleanup(video_path) -> bool:
    """Delete the unlocked copy and its temp folder. True when it is gone."""
    folder = Path(video_path).parent
    if not folder.name.startswith("svcs_unlock_"):
        return False          # never remove anything we did not create
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


def _run_gui(initial: str | None) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    try:
        import os as _os, sys as _sys
        _base = getattr(_sys, "_MEIPASS", None) or _os.path.join(_os.path.dirname(__file__), "..", "..", "installer")
        _ico = _os.path.join(_base, "svcs_unlock.ico")
        if _os.path.exists(_ico):
            root.iconbitmap(_ico)
    except Exception:
        pass
    root.title("SVCS Unlock")
    root.resizable(False, False)
    state = {"video": None}
    pad = {"padx": 14, "pady": 6}

    file_var = tk.StringVar(value=initial or "")
    pw_var = tk.StringVar()
    key_var = tk.StringVar()
    msg_var = tk.StringVar(value="Pick the locked video, then enter its password or key file.")

    tk.Label(root, text="Locked video (.enc)").grid(row=0, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=file_var, width=48).grid(row=1, column=0, **pad)
    tk.Button(root, text="Browse...", command=lambda: file_var.set(
        filedialog.askopenfilename(filetypes=[("Locked video", "*.enc"), ("All files", "*.*")])
        or file_var.get())).grid(row=1, column=1, **pad)
    tk.Label(root, text="Password").grid(row=2, column=0, sticky="w", **pad)
    pw = tk.Entry(root, textvariable=pw_var, show="*", width=48)
    pw.grid(row=3, column=0, columnspan=2, sticky="w", **pad)
    tk.Label(root, text="or key file").grid(row=4, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=key_var, width=48).grid(row=5, column=0, **pad)
    tk.Button(root, text="Choose...", command=lambda: key_var.set(
        filedialog.askopenfilename(filetypes=[("Key file", "*.key"), ("All files", "*.*")])
        or key_var.get())).grid(row=5, column=1, **pad)
    tk.Label(root, textvariable=msg_var, wraplength=420, justify="left").grid(
        row=6, column=0, columnspan=2, sticky="w", **pad)

    def go(_evt=None):
        try:
            video = unlock(file_var.get().strip(), pw_var.get(), key_var.get().strip() or None)
        except (ValueError, FileNotFoundError) as e:
            msg_var.set(str(e))
            return
        except Exception:
            msg_var.set("That password or key did not unlock this video.")
            return
        state["video"] = video
        pw_var.set("")
        msg_var.set("Playing now. Close this window when you are done. "
                    "The unlocked copy is deleted when you close it.")
        try:
            os.startfile(str(video))          # Windows default player
        except AttributeError:                # non-Windows dev runs
            import subprocess
            subprocess.Popen(["xdg-open", str(video)])

    def done():
        if state["video"] is not None and not cleanup(state["video"]):
            messagebox.showwarning(
                "SVCS Unlock",
                "The unlocked copy is still in use by your video player, so it could not be "
                "deleted yet. Close the player, then delete this folder:\n"
                + str(Path(state["video"]).parent))
        root.destroy()

    tk.Button(root, text="Unlock and play", command=go, default="active").grid(
        row=7, column=0, columnspan=2, **pad)
    root.bind("<Return>", go)
    root.protocol("WM_DELETE_WINDOW", done)
    pw.focus_set()
    root.mainloop()
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return _run_gui(argv[0] if argv else None)


if __name__ == "__main__":
    raise SystemExit(main())
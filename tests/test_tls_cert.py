"""
tests/test_tls_cert.py

The self-signed certificate behind the phone's HTTPS link: created once,
kept (so the fingerprint a phone pinned keeps matching), and served for real.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
import hashlib
import re
import socket
import ssl
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import tls_cert  # noqa: E402


def test_cert_is_created_and_fingerprint_is_stable(tmp_path):
    cert, key, fp1 = tls_cert.ensure_cert(tmp_path)
    assert cert.is_file() and key.is_file()
    assert re.fullmatch(r"[0-9a-f]{64}", fp1)
    _, _, fp2 = tls_cert.ensure_cert(tmp_path)
    assert fp1 == fp2                      # reused, not regenerated


def test_unreadable_cert_is_replaced(tmp_path):
    _, _, fp1 = tls_cert.ensure_cert(tmp_path)
    (tmp_path / "cert.pem").write_text("junk")
    _, _, fp2 = tls_cert.ensure_cert(tmp_path)
    assert fp1 != fp2
    assert re.fullmatch(r"[0-9a-f]{64}", fp2)


def test_https_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("SVCS_HTTPS", "0")
    assert tls_cert.https_enabled() is False
    assert tls_cert.start_https_listener(object(), "127.0.0.1") is None


def test_listener_serves_the_pinned_certificate(tmp_path, monkeypatch):
    from flask import Flask
    monkeypatch.setattr(tls_cert, "tls_dir", lambda: tmp_path)
    monkeypatch.setattr(tls_cert, "_info", None)
    app = Flask("t")

    @app.route("/ping")
    def ping():
        return "pong"

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    info = tls_cert.start_https_listener(app, "127.0.0.1", port)
    assert info and info["port"] == port

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with ctx.wrap_socket(raw) as tls:
            der = tls.getpeercert(binary_form=True)
    assert hashlib.sha256(der).hexdigest() == info["fingerprint"]

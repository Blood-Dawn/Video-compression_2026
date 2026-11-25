"""
src/gui/tls_cert.py

HTTPS for the phone link.

The dashboard stays on plain HTTP so the browser and desktop app keep working
at http://localhost:5000. Next to it, a second listener serves the same app
over HTTPS (default port 5443) using a self-signed certificate created on
first start and kept, so its fingerprint stays the same between runs.

A self-signed certificate cannot be checked against a certificate authority,
so the phone does not try. Instead the Pair panel shows the certificate's
SHA-256 fingerprint (and puts it in the QR code), the phone stores it, and
from then on it accepts that certificate and nothing else. That defeats
anyone on the Wi-Fi who tries to sit in the middle, which is the risk plain
HTTP leaves open.

  * ``SVCS_HTTPS=0`` turns the HTTPS listener off.
  * ``SVCS_HTTPS_PORT`` changes the port (default 5443).

Files, in the SVCS data folder under ``tls/``: ``cert.pem`` and ``key.pem``.
The certificate is regenerated only when it is missing, unreadable, or within
30 days of expiring. Regenerating changes the fingerprint, so phones must pair
again.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
from __future__ import annotations

import datetime
import ipaddress
import os
import socket
import threading
from pathlib import Path

DEFAULT_PORT = 5443
_VALID_DAYS = 3650
_RENEW_BEFORE_DAYS = 30

_lock = threading.Lock()
_info: dict | None = None


def tls_dir() -> Path:
    try:
        from utils.paths import data_dir
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.utils.paths import data_dir
    d = Path(data_dir()) / "tls"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _local_ips() -> list[str]:
    """This machine's addresses a phone might use (best effort)."""
    ips = {"127.0.0.1"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for res in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(res[4][0])
    except OSError:
        pass
    return sorted(ips)


def _generate(cert_path: Path, key_path: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SVCS server")])
    names = [x509.DNSName("localhost")]
    host = socket.gethostname()
    if host:
        names.append(x509.DNSName(host))
    for ip in _local_ips():
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=_VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def fingerprint_of(cert_path: Path) -> str:
    """SHA-256 of the certificate in DER form, as 64 lowercase hex characters."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    digest = hashes.Hash(hashes.SHA256())
    digest.update(cert.public_bytes(serialization.Encoding.DER))
    return digest.finalize().hex()


def _usable(cert_path: Path, key_path: Path) -> bool:
    if not (cert_path.is_file() and key_path.is_file()):
        return False
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        left = cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)
        return left > datetime.timedelta(days=_RENEW_BEFORE_DAYS)
    except Exception:  # noqa: BLE001 - unreadable means regenerate
        return False


def ensure_cert(directory: Path | None = None) -> tuple[Path, Path, str]:
    """(cert path, key path, fingerprint), creating the certificate if needed."""
    d = Path(directory) if directory else tls_dir()
    d.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = d / "cert.pem", d / "key.pem"
    with _lock:
        if not _usable(cert_path, key_path):
            _generate(cert_path, key_path)
    return cert_path, key_path, fingerprint_of(cert_path)


def https_enabled() -> bool:
    return os.environ.get("SVCS_HTTPS", "1").strip().lower() not in ("0", "false", "no", "off")


def info() -> dict | None:
    """{"port": int, "fingerprint": hex} while the HTTPS listener runs, else None."""
    return dict(_info) if _info else None


def start_https_listener(app, host: str, port: int | None = None) -> dict | None:
    """Serve ``app`` over HTTPS on a background thread. Never raises.

    Returns the info dict, or None when HTTPS is switched off or could not
    start (the plain HTTP server is unaffected either way).
    """
    global _info
    if not https_enabled():
        return None
    try:
        import ssl
        from werkzeug.serving import make_server
        try:
            port = int(port or os.environ.get("SVCS_HTTPS_PORT") or DEFAULT_PORT)
        except ValueError:
            port = DEFAULT_PORT
        cert_path, key_path, fp = ensure_cert()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(str(cert_path), str(key_path))
        server = make_server(host, port, app, threaded=True, ssl_context=ctx)
        threading.Thread(target=server.serve_forever, name="svcs-https", daemon=True).start()
        with _lock:
            _info = {"port": port, "fingerprint": fp}
        return dict(_info)
    except Exception as exc:  # noqa: BLE001 - HTTPS is an addition, never a reason not to start
        try:
            from gui.logging_setup import log
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.gui.logging_setup import log
        log.warning("HTTPS listener not started: %s", exc)
        return None

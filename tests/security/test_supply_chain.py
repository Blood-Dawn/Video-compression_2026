"""
tests/security/test_supply_chain.py  (SEC-008, SEC-016)

SEC-008: the runtime dependencies flagged by pip-audit (cryptography, urllib3)
must stay at or above the fixed versions in uv.lock, so they cannot silently slip
back to a known-vulnerable pin.

SEC-016: the irm|iex installer's direct-download path must fetch over HTTPS and
surface the SHA256 of the downloaded installer so the operator can verify it
against the Release SHA256SUMS (the winget path pins the hash; this is the
manual-verify mitigation for the fallback).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _locked_version(pkg: str):
    """Return the version string pinned for ``pkg`` in uv.lock, or None."""
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    # uv.lock is TOML: [[package]] blocks with name = "..." then version = "...".
    for m in re.finditer(r'name = "([^"]+)"\s*\nversion = "([^"]+)"', text):
        if m.group(1) == pkg:
            return m.group(2)
    return None


def _ver_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def test_cryptography_not_known_vulnerable():
    v = _locked_version("cryptography")
    assert v is not None, "cryptography not found in uv.lock"
    assert _ver_tuple(v) >= (48, 0, 1), f"cryptography {v} < 48.0.1 (GHSA-537c-gmf6-5ccf)"


def test_urllib3_not_known_vulnerable():
    v = _locked_version("urllib3")
    assert v is not None, "urllib3 not found in uv.lock"
    assert _ver_tuple(v) >= (2, 7, 0), f"urllib3 {v} < 2.7.0 (PYSEC-2026-141/142)"


def test_installer_download_is_https_and_shows_checksum():
    ps1 = (ROOT / "installer" / "Install-SVCS.ps1").read_text(encoding="utf-8")
    # The installer asset URL is fetched over HTTPS from the official repo...
    assert 'https://github.com/$Repo/releases/download/' in ps1
    # ...and Invoke-WebRequest never downloads the installer over plain http://.
    for line in ps1.splitlines():
        if "Invoke-WebRequest" in line and "releases/download" in line:
            assert "http://" not in line
    # The direct-download path surfaces a SHA256 for manual verification (SEC-016).
    assert "Get-FileHash" in ps1 and "SHA256" in ps1

"""
tests/test_winget_manifest.py

Structural tests for the winget package manifest (R3.2a).

These do NOT submit anything and do NOT run winget (the public submission is
owner-gated; see docs/BLOCKERS.md). They only assert the three manifest files
load as YAML, carry the keys winget requires, agree with each other, and pin the
version to pyproject.toml so the manifest cannot drift from the package.

Author: Bloodawn (KheivenD), 2026-06-21 (R3.2a - winget manifest).
"""

import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

ROOT = Path(__file__).parent.parent
WINGET = ROOT / "installer" / "winget"
PKG_ID = "Blood-Dawn.SVCS"

VERSION_MANIFEST = WINGET / "Blood-Dawn.SVCS.yaml"
INSTALLER_MANIFEST = WINGET / "Blood-Dawn.SVCS.installer.yaml"
LOCALE_MANIFEST = WINGET / "Blood-Dawn.SVCS.locale.en-US.yaml"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pyproject_version():
    data = ROOT / "pyproject.toml"
    if tomllib is not None:
        return tomllib.loads(data.read_text(encoding="utf-8"))["project"]["version"]
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', data.read_text(encoding="utf-8"))
    return m.group(1)


def test_all_three_manifests_exist():
    for p in (VERSION_MANIFEST, INSTALLER_MANIFEST, LOCALE_MANIFEST):
        assert p.is_file(), f"missing winget manifest: {p}"


def test_version_manifest_keys():
    m = _load(VERSION_MANIFEST)
    assert m["PackageIdentifier"] == PKG_ID
    assert m["DefaultLocale"] == "en-US"
    assert m["ManifestType"] == "version"
    assert m["ManifestVersion"]


def test_locale_manifest_keys():
    m = _load(LOCALE_MANIFEST)
    assert m["PackageIdentifier"] == PKG_ID
    assert m["PackageLocale"] == "en-US"
    assert m["ManifestType"] == "defaultLocale"
    # winget requires these for the default-locale manifest.
    for key in ("Publisher", "PackageName", "License", "ShortDescription"):
        assert m.get(key), f"missing required locale key: {key}"


def test_installer_manifest_keys_and_installer_entry():
    m = _load(INSTALLER_MANIFEST)
    assert m["PackageIdentifier"] == PKG_ID
    assert m["ManifestType"] == "installer"
    assert m["InstallerType"] == "inno"
    installers = m["Installers"]
    assert isinstance(installers, list) and installers, "Installers[] must be non-empty"
    one = installers[0]
    assert one["Architecture"] == "x64"
    url = one["InstallerUrl"]
    assert url.startswith("https://") and url.endswith(".exe")
    # The asset name carries the version.
    assert f"SVCS-Setup-{m['PackageVersion']}.exe" in url
    sha = one["InstallerSha256"]
    assert re.fullmatch(r"[0-9A-Fa-f]{64}", sha), "InstallerSha256 must be 64 hex chars"


def test_silent_switches_present():
    m = _load(INSTALLER_MANIFEST)
    sw = m.get("InstallerSwitches", {})
    assert "/VERYSILENT" in sw.get("Silent", "")
    assert "/SUPPRESSMSGBOXES" in sw.get("Silent", "")


def test_version_matches_pyproject_across_all_three():
    want = _pyproject_version()
    for p in (VERSION_MANIFEST, INSTALLER_MANIFEST, LOCALE_MANIFEST):
        assert str(_load(p)["PackageVersion"]) == want, f"{p.name} version != pyproject"


def test_no_unicode_dashes_in_manifests():
    em, en = chr(0x2014), chr(0x2013)  # avoid literal dashes in this source file
    for p in (VERSION_MANIFEST, INSTALLER_MANIFEST, LOCALE_MANIFEST):
        text = p.read_text(encoding="utf-8")
        assert em not in text and en not in text, f"dash in {p.name}"

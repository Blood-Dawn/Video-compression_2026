"""
tests/test_install_script.py

Structural tests for the WinUtil-style bootstrap installer/Install-SVCS.ps1
(R3.2b).

A PowerShell WPF GUI cannot be unit-tested (see the R3.2 honesty note); these
tests only assert the script exists, exposes the -DryRun / -WhatIf safety path,
carries the SVCS palette, offers the documented components, and is dash-free. If
PowerShell is available the script is also parse-checked (skipped otherwise).

Author: Bloodawn (KheivenD), 2026-06-21 (R3.2b - terminal installer).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "installer" / "Install-SVCS.ps1"


@pytest.fixture(scope="module")
def text():
    return SCRIPT.read_text(encoding="utf-8")


def test_script_exists():
    assert SCRIPT.is_file(), "installer/Install-SVCS.ps1 is missing"


def test_has_dryrun_and_whatif_alias(text):
    assert "[switch]$DryRun" in text, "no -DryRun switch"
    assert "WhatIf" in text, "no -WhatIf alias for -DryRun"
    # The dry-run actually guards real work (prints WOULD ... lines).
    assert "WOULD" in text


def test_has_nogui_fallback(text):
    assert "[switch]$NoGui" in text
    assert "Show-ConsoleMenu" in text


def test_contains_svcs_palette(text):
    assert "#0a0e14" in text, "missing SVCS dark background hex"
    assert "#ffb900" in text, "missing SVCS amber accent hex"


def test_offers_documented_components(text):
    for key in ("core", "plates", "mediamtx", "samples"):
        assert f"'{key}'" in text, f"component {key!r} not offered"


def test_targets_winget_and_release(text):
    assert "Blood-Dawn.SVCS" in text          # winget id
    assert "releases/download" in text          # GitHub Release fallback
    assert "/VERYSILENT" in text                # silent Inno install


def test_is_dash_free():
    t = SCRIPT.read_text(encoding="utf-8")
    assert chr(0x2014) not in t and chr(0x2013) not in t, "em/en dash in the script"


@pytest.mark.skipif(shutil.which("pwsh") is None and shutil.which("powershell") is None,
                    reason="PowerShell not available to parse-check the script")
def test_powershell_parses_the_script():
    exe = shutil.which("pwsh") or shutil.which("powershell")
    code = (
        "$e=$null;$t=$null;"
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT.as_posix()}',[ref]$t,[ref]$e);"
        "if($e.Count -gt 0){$e|ForEach-Object{$_.Message};exit 1}else{exit 0}"
    )
    r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", code],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"PowerShell parse errors:\n{r.stdout}\n{r.stderr}"

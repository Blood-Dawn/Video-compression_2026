"""
tests/test_android_theme_sync.py

Keeps the Android Compose theme in step with the imported design tokens.

The Android module cannot be compiled or tested in this repo's CI (no JDK, no
Android SDK, no Gradle), so almost nothing about it can be verified here. This
is the exception: Color.kt is GENERATED from mobile/design/tokens/colors.css,
and whether the two agree is a pure text comparison that Python can make.

Without this, the most likely way the app diverges from the design is the most
boring one: someone tweaks a hex in the design project, re-imports the CSS, and
nobody regenerates the Kotlin. This fails loudly at that moment.

Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "mobile" / "design" / "tokens" / "colors.css"
KT = (ROOT / "mobile" / "android" / "app" / "src" / "main" / "java" / "org" /
      "svcs" / "mobile" / "ui" / "theme" / "Color.kt")

pytestmark = pytest.mark.skipif(
    not KT.is_file(), reason="Android module not present")


def _css_hex_tokens():
    """{token-name: '#RRGGBB'} for every literal hex in the token file."""
    text = CSS.read_text(encoding="utf-8")
    return {m.group(1): m.group(2).upper()
            for m in re.finditer(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", text)}


def _css_rgba_tokens():
    """{token-name: (r, g, b, a)} for every rgba() token."""
    text = CSS.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"--([a-z0-9-]+):\s*rgba\(([^)]+)\)\s*;", text):
        parts = [p.strip() for p in m.group(2).split(",")]
        out[m.group(1)] = (int(parts[0]), int(parts[1]), int(parts[2]),
                           float(parts[3]))
    return out


def _kt_colors():
    """{KotlinName: 'AARRGGBB'} for every Color(0x...) in the generated file."""
    text = KT.read_text(encoding="utf-8")
    return {m.group(1): m.group(2).upper()
            for m in re.finditer(r"val\s+(\w+)\s*=\s*Color\(0x([0-9A-Fa-f]{8})\)",
                                 text)}


def _kt_name(css_name: str) -> str:
    return "Svcs" + "".join(p.capitalize() for p in css_name.split("-"))


def test_generated_file_exists_and_is_marked_generated():
    text = KT.read_text(encoding="utf-8")
    assert "GENERATED" in text, (
        "Color.kt must say it is generated, or someone will hand-edit it")
    assert "colors.css" in text, "Color.kt must name its source"


@pytest.mark.parametrize("token", sorted(_css_hex_tokens()))
def test_every_opaque_token_matches_the_design(token):
    """Each literal hex token appears in the Kotlin with alpha FF."""
    css = _css_hex_tokens()[token]
    kt = _kt_colors()
    name = _kt_name(token)
    if name not in kt:
        pytest.skip(f"{token} is not carried into the Android theme")
    assert kt[name] == "FF" + css[1:], (
        f"{token} is {css} in the design but 0x{kt[name]} in Color.kt; "
        "regenerate the theme from the tokens")


@pytest.mark.parametrize("token", sorted(_css_rgba_tokens()))
def test_every_translucent_token_matches_the_design(token):
    """rgba() tokens carry their alpha into the Kotlin ARGB literal."""
    r, g, b, a = _css_rgba_tokens()[token]
    kt = _kt_colors()
    name = _kt_name(token)
    if name not in kt:
        pytest.skip(f"{token} is not carried into the Android theme")
    expected = f"{round(a * 255):02X}{r:02X}{g:02X}{b:02X}"
    assert kt[name] == expected, (
        f"{token} is rgba({r},{g},{b},{a}) in the design but 0x{kt[name]} in "
        "Color.kt; regenerate the theme from the tokens")


def test_the_signature_accent_survived_the_transcription():
    """Amber is the one color the whole design language hangs on."""
    assert _kt_colors()["SvcsAmber"] == "FFFFB900"


def test_no_kotlin_color_is_invented():
    """Every color in the Kotlin traces back to a design token.

    Guards the other direction: a hand-added color would drift the app away
    from the design system silently.
    """
    known = {_kt_name(t) for t in _css_hex_tokens()}
    known |= {_kt_name(t) for t in _css_rgba_tokens()}
    invented = set(_kt_colors()) - known
    assert not invented, (
        f"Color.kt defines colors with no design token: {sorted(invented)}")


def test_android_module_does_not_reference_the_font_cdn():
    """The CDN @import must not reach the app.

    It is a cloud call in an offline product, it would not resolve on a LAN
    with no internet route, and it would fail F-Droid inclusion.
    """
    android = ROOT / "mobile" / "android"
    for path in android.rglob("*"):
        if path.is_file() and path.suffix in {".kt", ".xml", ".kts", ".toml"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "fonts.googleapis.com" not in text, (
                f"{path.relative_to(ROOT)} pulls fonts from a CDN")
            assert "fonts.gstatic.com" not in text, (
                f"{path.relative_to(ROOT)} pulls fonts from a CDN")

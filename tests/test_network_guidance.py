"""
tests/test_network_guidance.py

M0.8: the app must not recommend the worst way to reach a surveillance server.

The dashboard help told users to "Forward TCP port 5000 on your router, or use a
tool like ngrok", with no caveat, and DEV.md expanded the ngrok path and
suggested Cloudflare Tunnel as the persistent option.

Both are wrong for this product specifically. It serves recorded video of real
people over plain HTTP, so a forwarded port publishes that footage and replays
the password in cleartext on every request. A public tunnel additionally routes
it through a third party, which contradicts an offline, self-hosted,
no-cloud-calls design.

This matters more now that a phone is meant to connect: "Server Address" is
exactly the field that tempts a user to port-forward.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.8).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.auth import bind_exposure_warning, is_private_bind      # noqa: E402

_TEMPLATE = SRC / "gui" / "templates" / "index.html"
_DEV = ROOT / "DEV.md"


# ── the guidance itself ───────────────────────────────────────────────────────

def test_dashboard_help_no_longer_recommends_ngrok():
    assert "ngrok" not in _TEMPLATE.read_text(encoding="utf-8").lower()


def test_dashboard_help_no_longer_tells_users_to_port_forward():
    html = _TEMPLATE.read_text(encoding="utf-8")
    assert "Forward TCP port 5000 on your router" not in html


def test_dashboard_help_recommends_a_vpn():
    html = _TEMPLATE.read_text(encoding="utf-8")
    assert "WireGuard" in html or "Tailscale" in html


def test_dashboard_help_warns_against_port_forwarding():
    """Removing the bad advice is not enough; users reach for it anyway."""
    html = _TEMPLATE.read_text(encoding="utf-8")
    assert "Do not port-forward" in html or "do not forward" in html.lower()


def test_dev_docs_only_mention_tunnels_to_warn_against_them():
    """DEV.md may name ngrok, but only inside the warning."""
    text = _DEV.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "ngrok" in line.lower():
            assert "do not" in line.lower() or "not use" in line.lower(), (
                f"DEV.md still presents a tunnel as an option: {line.strip()!r}")


def test_dev_docs_recommend_a_vpn_first():
    text = _DEV.read_text(encoding="utf-8")
    assert "WireGuard" in text and "Tailscale" in text


# ── the bind classifier ───────────────────────────────────────────────────────

@pytest.mark.parametrize("host", [
    "127.0.0.1", "localhost", "::1", "",
    "192.168.1.42", "10.0.0.5", "172.16.3.9",       # RFC1918
    "169.254.1.1",                                   # link-local
    "fd00::1",                                       # RFC4193 unique-local
    "100.64.0.1", "100.101.102.103",                 # RFC6598 CGNAT: Tailscale
])
def test_private_binds_are_recognized(host):
    assert is_private_bind(host) is True
    assert bind_exposure_warning(host) is None


def test_tailscale_addresses_are_not_warned_about():
    """Tailscale is the option this project RECOMMENDS, so warning about it
    would train users to ignore the warning.

    Worth an explicit test because Python's ipaddress reports 100.64.0.0/10 as
    neither is_private nor is_global, so the obvious implementation gets this
    wrong. This caught exactly that bug.
    """
    assert is_private_bind("100.64.0.1") is True
    assert bind_exposure_warning("100.115.92.4") is None


@pytest.mark.parametrize("host", [
    "0.0.0.0",          # every interface: public if the host has a public IP
    "::",
    "8.8.8.8",
    "1.1.1.1",
])
def test_exposing_binds_are_warned_about(host):
    assert is_private_bind(host) is False
    warning = bind_exposure_warning(host)
    assert warning, f"no warning for {host!r}"
    assert "VPN" in warning
    assert "forward" in warning.lower()


def test_documentation_ranges_are_treated_as_private():
    """RFC5737 TEST-NET blocks are not globally routable, and Python's
    ipaddress reports them as private. Recorded so the behavior is deliberate
    rather than a surprise to the next reader picking a test address.
    """
    assert is_private_bind("203.0.113.5") is True     # TEST-NET-3
    assert is_private_bind("192.0.2.1") is True       # TEST-NET-1


def test_unspecified_bind_is_not_treated_as_private():
    """0.0.0.0 is the SHIPPING default and the one that actually exposes.

    It is easy to mistake for "local" because it is not a routable address, but
    it binds every interface, so on a machine with a public IP the dashboard is
    on the public internet.
    """
    assert is_private_bind("0.0.0.0") is False
    assert bind_exposure_warning("0.0.0.0") is not None


def test_a_hostname_warns_rather_than_staying_silent():
    """Cannot classify without DNS, and a false warning is far cheaper than
    silently publishing surveillance footage."""
    assert bind_exposure_warning("my-nas.example.com") is not None


def test_warning_names_the_host():
    assert "8.8.8.8" in bind_exposure_warning("8.8.8.8")


def test_run_gui_prints_the_warning():
    src = (ROOT / "run_gui.py").read_text(encoding="utf-8")
    assert "bind_exposure_warning" in src, (
        "run_gui does not surface the exposure warning at startup")

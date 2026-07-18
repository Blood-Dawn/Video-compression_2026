"""
tests/security/test_auth_throttle.py

M0.2: failed-authentication throttling and logging.

Before this the auth guard had no counter, no delay, no lockout, and no record
of a failed attempt. run_gui defaults --host to 0.0.0.0 and the Dockerfile
passes it explicitly, so an unthrottled credential endpoint was the SHIPPING
configuration rather than a hypothetical. Adding device tokens (M0.10) raised
the stakes, because a token is a bearer secret guessable in principle without
knowing any username.

The most important test in this file is the one asserting that nothing the
client sent appears in the log. A throttle that logs the attempted password
turns the log file into the place credentials are written down, which is worse
than the problem it solves.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.2).
"""

import base64
import logging
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import auth as auth_mod                         # noqa: E402
from gui.auth import install_basic_auth                  # noqa: E402


@pytest.fixture(autouse=True)
def clean_throttle():
    """Each test starts with an empty throttle table."""
    auth_mod._reset_throttle()
    yield
    auth_mod._reset_throttle()


@pytest.fixture()
def client():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "ok"

    install_basic_auth(app, "admin", "secret")
    return app.test_client()


def _basic(user, pw):
    blob = base64.b64encode(f"{user}:{pw}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {blob}"}


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── the lockout ───────────────────────────────────────────────────────────────

def test_repeated_failures_eventually_lock_out(client):
    seen_429 = False
    for _ in range(auth_mod._FAIL_MAX + 2):
        r = client.get("/", headers=_basic("admin", "wrong"))
        if r.status_code == 429:
            seen_429 = True
            break
    assert seen_429, (
        f"{auth_mod._FAIL_MAX + 2} wrong passwords never produced a 429; "
        "the credential endpoint is unthrottled")


def test_lockout_returns_retry_after(client):
    for _ in range(auth_mod._FAIL_MAX + 2):
        r = client.get("/", headers=_basic("admin", "wrong"))
        if r.status_code == 429:
            assert r.headers.get("Retry-After"), "429 without Retry-After"
            assert int(r.headers["Retry-After"]) > 0
            return
    pytest.fail("never locked out")


def test_lockout_blocks_even_the_correct_password(client):
    """Otherwise an attacker who finally guesses right walks straight in."""
    for _ in range(auth_mod._FAIL_MAX + 2):
        client.get("/", headers=_basic("admin", "wrong"))
    r = client.get("/", headers=_basic("admin", "secret"))
    assert r.status_code == 429, (
        "a locked-out address was let in with correct credentials")


def test_lockout_expires(client, monkeypatch):
    for _ in range(auth_mod._FAIL_MAX + 2):
        client.get("/", headers=_basic("admin", "wrong"))
    assert client.get("/", headers=_basic("admin", "secret")).status_code == 429

    # Jump past the lockout window.
    real = auth_mod.time.monotonic
    monkeypatch.setattr(auth_mod.time, "monotonic",
                        lambda: real() + auth_mod._LOCKOUT_S + 1)
    assert client.get("/", headers=_basic("admin", "secret")).status_code == 200, (
        "the lockout never expired")


def test_a_few_failures_do_not_lock_out(client):
    """A user fat-fingering their password twice must not be locked out."""
    for _ in range(3):
        assert client.get("/", headers=_basic("admin", "wrong")).status_code == 401
    assert client.get("/", headers=_basic("admin", "secret")).status_code == 200


def test_success_clears_the_failure_history(client):
    """Otherwise failures accumulate across a long session and lock out a
    legitimate user who mistypes occasionally over days."""
    for _ in range(auth_mod._FAIL_MAX - 1):
        client.get("/", headers=_basic("admin", "wrong"))
    assert client.get("/", headers=_basic("admin", "secret")).status_code == 200
    # History cleared, so the next batch starts from zero.
    for _ in range(auth_mod._FAIL_MAX - 1):
        assert client.get("/", headers=_basic("admin", "wrong")).status_code == 401


def test_credential_less_requests_are_not_counted(client):
    """Browsers fire one unauthenticated request and retry after the 401.

    Counting those would lock out ordinary users on their first page load.
    """
    for _ in range(auth_mod._FAIL_MAX * 3):
        assert client.get("/").status_code == 401
    assert client.get("/", headers=_basic("admin", "secret")).status_code == 200


def test_bad_bearer_tokens_are_also_throttled(client, tmp_path, monkeypatch):
    """A token is a bearer secret, so it needs the throttle more than a
    password does: there is no username to guess alongside it."""
    from gui import device_tokens
    monkeypatch.setattr(device_tokens, "token_path",
                        lambda: tmp_path / "device_tokens.json")
    seen_429 = False
    for _ in range(auth_mod._FAIL_MAX + 2):
        r = client.get("/", headers=_bearer("svcs_guess"))
        if r.status_code == 429:
            seen_429 = True
            break
    assert seen_429, "token guessing is unthrottled"


# ── logging: the part that must not leak ──────────────────────────────────────

def test_failed_attempt_is_logged_with_the_source_address(client, caplog):
    with caplog.at_level(logging.WARNING, logger="gui.auth"):
        client.get("/", headers=_basic("admin", "wrong"))
    assert any("failed attempt" in r.message.lower() for r in caplog.records), (
        "a failed auth attempt left no trace in the log")


def test_lockout_is_logged(client, caplog):
    with caplog.at_level(logging.WARNING, logger="gui.auth"):
        for _ in range(auth_mod._FAIL_MAX + 2):
            client.get("/", headers=_basic("admin", "wrong"))
    assert any("locking out" in r.message.lower() for r in caplog.records)


@pytest.mark.parametrize("user,pw", [
    ("admin", "hunter2-SECRET-pw"),
    ("root", "correct horse battery staple"),
    ("admin", "passwörd"),
])
def test_no_attempted_credential_reaches_the_log(client, caplog, user, pw):
    """The throttle must not turn the log into a credential store."""
    with caplog.at_level(logging.DEBUG):
        for _ in range(auth_mod._FAIL_MAX + 2):
            client.get("/", headers=_basic(user, pw))
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert pw not in blob, f"attempted PASSWORD {pw!r} was written to the log"
    if user not in ("admin", "root"):
        assert user not in blob, f"attempted username {user!r} was logged"


def test_no_bearer_token_reaches_the_log(client, caplog, tmp_path, monkeypatch):
    from gui import device_tokens
    monkeypatch.setattr(device_tokens, "token_path",
                        lambda: tmp_path / "device_tokens.json")
    secret = "svcs_super-secret-token-value-xyz"
    with caplog.at_level(logging.DEBUG):
        for _ in range(auth_mod._FAIL_MAX + 2):
            client.get("/", headers=_bearer(secret))
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in blob, "a presented bearer token was written to the log"


def test_configured_password_never_reaches_the_log(client, caplog):
    """Not just the attempted one: the real credential must not leak either."""
    with caplog.at_level(logging.DEBUG):
        for _ in range(auth_mod._FAIL_MAX + 2):
            client.get("/", headers=_basic("admin", "wrong"))
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "secret" not in blob, "the CONFIGURED password appeared in the log"


# ── the throttle table itself ─────────────────────────────────────────────────

def test_forwarded_headers_are_not_trusted():
    """X-Forwarded-For is attacker-controlled here: nothing sets up ProxyFix.

    Honoring it would let one attacker spread attempts across unlimited fake
    identities and never trip the limit.
    """
    src = (SRC / "gui" / "auth.py").read_text(encoding="utf-8")
    assert "X-Forwarded-For" not in src or "not trusted" in src.lower() \
        or "deliberately NOT trusted" in src, \
        "auth.py appears to read X-Forwarded-For without justification"
    assert "remote_addr" in src


def test_tracking_table_is_bounded():
    """A spoofed-source flood must not grow the table without limit."""
    auth_mod._reset_throttle()
    for i in range(auth_mod._MAX_TRACKED_IPS + 50):
        auth_mod._record_failure(f"10.0.{i // 256}.{i % 256}")
    assert len(auth_mod._fail_times) <= auth_mod._MAX_TRACKED_IPS, (
        "the failure table grew past its bound")


def test_one_address_lockout_does_not_affect_another():
    """Locking out an attacker must not lock out the legitimate operator."""
    auth_mod._reset_throttle()
    for _ in range(auth_mod._FAIL_MAX):
        auth_mod._record_failure("10.0.0.9")
    assert auth_mod._is_locked_out("10.0.0.9")
    assert not auth_mod._is_locked_out("10.0.0.10")

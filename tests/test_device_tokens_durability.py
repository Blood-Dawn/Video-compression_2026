"""
tests/test_device_tokens_durability.py

Pairing one device must never unpair the others.

_read_all() returns [] on any read error. That is the right answer for
VERIFICATION - deny rather than admit - but mint_token and revoke_token use it
as the base of a read-modify-write, so a single transient read failure turned
into a write containing only the new token and silently unpaired every other
device. No revocation, no error on the server, no error on the phones; the
tokens simply stopped existing.

On Windows the everyday cause is a sharing violation: an antivirus scanner or
a sync client holding the file open for the instant the mint reads it.

Found for real while re-pairing a phone for M3: a token minted minutes earlier
was gone from the store, with only the most recently minted one left.

Author: Bloodawn (KheivenD), 2026-07-19 (M3).
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import device_tokens as dt                      # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the token store at a temp file."""
    p = tmp_path / "device_tokens.json"
    monkeypatch.setattr(dt, "token_path", lambda: p)
    return p


def _fail_read_once(monkeypatch, target: pathlib.Path):
    """Make the next read of ``target`` raise, then behave normally."""
    real = pathlib.Path.read_text
    state = {"failed": False}

    def flaky(self, *a, **k):
        if self == target and not state["failed"]:
            state["failed"] = True
            raise OSError(13, "The process cannot access the file")
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", flaky)


class TestMintDoesNotDestroyExistingTokens:

    def test_a_failed_read_during_mint_does_not_unpair_other_devices(
            self, store, monkeypatch):
        secret_a, _ = dt.mint_token("phone-a")
        secret_b, _ = dt.mint_token("phone-b")

        _fail_read_once(monkeypatch, store)
        with pytest.raises(dt.StoreUnreadable):
            dt.mint_token("phone-c")

        # Both originals must still authenticate.
        assert dt.verify_token(secret_a) is not None, "phone-a was unpaired"
        assert dt.verify_token(secret_b) is not None, "phone-b was unpaired"
        assert {t.label for t in dt.list_tokens()} == {"phone-a", "phone-b"}

    def test_a_failed_read_during_revoke_does_not_unpair_other_devices(
            self, store, monkeypatch):
        secret_a, _ = dt.mint_token("phone-a")
        _, rec_b = dt.mint_token("phone-b")

        _fail_read_once(monkeypatch, store)
        with pytest.raises(dt.StoreUnreadable):
            dt.revoke_token(rec_b.id)

        assert dt.verify_token(secret_a) is not None, "phone-a was unpaired"
        assert len(dt.list_tokens()) == 2

    def test_a_corrupt_record_is_not_silently_dropped_on_the_next_write(
            self, store):
        """One bad record must not delete itself the next time we write.

        The lenient reader skips records it cannot parse. Appending to that
        result and writing it back is what turns "one corrupt entry" into
        "that device is gone".
        """
        secret_a, _ = dt.mint_token("phone-a")
        raw = json.loads(store.read_text(encoding="utf-8"))
        raw["tokens"].append({"id": "broken", "not": "a valid record"})
        store.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(dt.StoreUnreadable):
            dt.mint_token("phone-c")

        # The good record is untouched and the bad one is still on disk for
        # the operator to look at.
        after = json.loads(store.read_text(encoding="utf-8"))
        assert len(after["tokens"]) == 2
        assert dt.verify_token(secret_a) is not None

    def test_one_corrupt_record_does_not_lock_out_the_other_devices(self, store):
        """The property the original lenient reader was written to protect.

        Refusing to WRITE on a corrupt record is right. Refusing to
        AUTHENTICATE would turn one bad entry into a total outage for every
        paired device, which is worse than the problem being avoided.
        """
        secret_a, _ = dt.mint_token("phone-a")
        secret_b, _ = dt.mint_token("phone-b")
        raw = json.loads(store.read_text(encoding="utf-8"))
        raw["tokens"].append({"id": "broken", "not": "a valid record"})
        store.write_text(json.dumps(raw), encoding="utf-8")

        assert dt.verify_token(secret_a) is not None, \
            "a corrupt third record locked out phone-a"
        assert dt.verify_token(secret_b) is not None, \
            "a corrupt third record locked out phone-b"

    def test_verifying_against_a_partly_corrupt_store_does_not_rewrite_it(
            self, store):
        """The last_used_at touch must not delete the record it cannot parse."""
        secret_a, _ = dt.mint_token("phone-a")
        raw = json.loads(store.read_text(encoding="utf-8"))
        raw["tokens"].append({"id": "broken", "not": "a valid record"})
        store.write_text(json.dumps(raw), encoding="utf-8")
        before = store.read_text(encoding="utf-8")

        assert dt.verify_token(secret_a, touch=True) is not None
        assert store.read_text(encoding="utf-8") == before, \
            "verification rewrote the store and dropped the corrupt record"


class TestVerificationStillFailsClosed:

    def test_an_unreadable_store_denies_rather_than_admits(
            self, store, monkeypatch):
        secret, _ = dt.mint_token("phone-a")
        _fail_read_once(monkeypatch, store)
        assert dt.verify_token(secret) is None, \
            "an unreadable store must deny, not admit"

    def test_a_missing_store_is_empty_not_an_error(self, store):
        """A first run has no file, and that is not a failure."""
        assert not store.exists()
        assert dt.list_tokens() == []
        assert dt._read_all_strict() == []
        # And minting on a fresh install still works.
        secret, _ = dt.mint_token("first-device")
        assert dt.verify_token(secret) is not None


class TestRoutesReportRatherThanCorrupt:

    def test_mint_returns_503_when_the_store_cannot_be_read(
            self, store, monkeypatch):
        """The route must report the refusal, not 500 and not a false success.

        Raises from mint_token directly rather than by breaking the file: the
        route runs an auth check first, which also reads the store, so failing
        a read by file path would be consumed before the mint even runs. What
        is under test here is the route's handling.
        """
        from gui.app import app
        from gui.routes import tokens_bp as tb

        def boom(*a, **k):
            raise dt.StoreUnreadable("simulated unreadable store")
        monkeypatch.setattr(tb.device_tokens, "mint_token", boom)

        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.post("/api/auth/tokens", json={"label": "phone-c"})
        assert resp.status_code == 503
        assert "unpaired" in resp.get_json()["error"].lower()

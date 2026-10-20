"""Behavior guard for the parsed-store cache in gui.device_tokens.

verify_token runs on every authenticated request, so the store parse is cached
by (path, mtime_ns, size). These tests prove the cache never serves stale data.
"""

import json

import pytest

from src.gui import device_tokens as dt


@pytest.fixture()
def store(tmp_path, monkeypatch):
    path = tmp_path / "device_tokens.json"
    monkeypatch.setattr(dt, "token_path", lambda: path)
    monkeypatch.setattr(dt, "_parsed_cache", None)
    return path


def test_revoke_is_seen_by_next_verify(store):
    secret, rec = dt.mint_token("phone")
    assert dt.verify_token(secret) is not None
    assert dt.revoke_token(rec.id)
    assert dt.verify_token(secret) is None


def test_out_of_band_rewrite_is_seen(store):
    secret, _ = dt.mint_token("phone")
    assert dt.verify_token(secret) is not None
    store.write_text(json.dumps({"version": 1, "tokens": []}), encoding="utf-8")
    assert dt.verify_token(secret) is None


def test_deleted_store_denies(store):
    secret, _ = dt.mint_token("phone")
    assert dt.verify_token(secret) is not None
    store.unlink()
    assert dt.verify_token(secret) is None


def test_corrupt_store_is_not_cached_as_good(store):
    secret, _ = dt.mint_token("phone")
    assert dt.verify_token(secret) is not None
    store.write_text("{not json", encoding="utf-8")
    assert dt.verify_token(secret) is None
    with pytest.raises(dt.StoreUnreadable):
        dt.mint_token("another")

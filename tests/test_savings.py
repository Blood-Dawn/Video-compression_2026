"""
tests/test_savings.py

M2.3: GET /api/savings.

Nothing server-side recorded a savings figure, so the desktop derives its
headline ratio in JavaScript as duration * width * height * 3 * fps, which is
the clip as RAW UNCOMPRESSED RGB. That is where the mockup's "277.8x smaller"
comes from.

The arithmetic is right and the number is misleading: a camera never delivers
raw RGB, it delivers H.264 already, so most of that ratio is "video compression
exists" rather than "SVCS shrank your files". An operator reading it on a
dashboard will credit SVCS with all of it.

Most tests here therefore guard HONESTY rather than mechanics:

  * measured savings only counts pairs where BOTH sizes are genuinely known;
  * a compressed output the user has since deleted saves nothing and is excluded;
  * the recording total carries NO ratio, because a live capture has no source
    file and the denominator would have to be invented.

Author: Bloodawn (KheivenD), 2026-07-19 (M2.3).
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app                                   # noqa: E402
from gui.routes import savings_bp as sav                  # noqa: E402
from utils import compressed_index as cidx                # noqa: E402


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def fake_index(tmp_path, monkeypatch):
    """Point compressed_index at a temp file and return a helper to fill it."""
    idx_path = tmp_path / "compressed_index.json"

    def write(entries):
        idx_path.write_text(json.dumps({"entries": entries}), encoding="utf-8")

    monkeypatch.setattr(cidx, "_load", lambda *a, **k: (
        json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.is_file()
        else {"entries": {}}))
    return write


def _pair(tmp_path, name, source_size, output_size):
    """Build a source/output pair and the index entry describing it."""
    out = tmp_path / f"{name}_out.mp4"
    out.write_bytes(b"x" * output_size)
    src = tmp_path / f"{name}_src.mp4"
    sig = f"{src}|{source_size}|1700000000"
    return sig, {"source": str(src), "signature": sig, "output": str(out)}


# ── the signature carries the source size ────────────────────────────────────

def test_source_size_is_recovered_from_the_signature():
    """No schema change was needed: signatures already encode the source size."""
    assert sav._parse_source_size(r"C:\v\a.mp4|123456|1700000000") == 123456
    assert sav._parse_source_size("/home/v/a.mp4|999|1") == 999


@pytest.mark.parametrize("sig", [
    "",
    None,
    "path-with-no-pipes",
    r"C:\v\a.mp4|0|0",        # the index's fallback for an unstat-able file
    "a.mp4|notanumber|1",
])
def test_unusable_signatures_contribute_nothing(sig):
    """A malformed or fallback signature must count as zero, never guess."""
    assert sav._parse_source_size(sig) == 0


# ── measured savings ─────────────────────────────────────────────────────────

def test_measured_reports_a_real_ratio(tmp_path, fake_index):
    sig, entry = _pair(tmp_path, "clip", source_size=1000, output_size=250)
    fake_index({sig: entry})
    m = sav.measured_savings()
    assert m["files"] == 1
    assert m["source_bytes"] == 1000
    assert m["output_bytes"] == 250
    assert m["saved_bytes"] == 750
    assert m["ratio"] == 4.0
    assert m["saved_pct"] == 75.0


def test_measured_sums_across_files(tmp_path, fake_index):
    s1, e1 = _pair(tmp_path, "a", 1000, 200)
    s2, e2 = _pair(tmp_path, "b", 3000, 800)
    fake_index({s1: e1, s2: e2})
    m = sav.measured_savings()
    assert m["files"] == 2
    assert m["source_bytes"] == 4000
    assert m["output_bytes"] == 1000
    assert m["ratio"] == 4.0


def test_a_deleted_output_saves_nothing(tmp_path, fake_index):
    """Retention purges compressed files. A file that is gone did not save the
    user any space, so counting it would overstate the total forever."""
    s1, e1 = _pair(tmp_path, "kept", 1000, 200)
    s2, e2 = _pair(tmp_path, "purged", 5000, 100)
    Path(e2["output"]).unlink()
    fake_index({s1: e1, s2: e2})
    m = sav.measured_savings()
    assert m["files"] == 1
    assert m["source_bytes"] == 1000


def test_an_unknown_source_size_is_skipped_entirely(tmp_path, fake_index):
    """With a 0 source size the pair cannot be scored. Counting the output alone
    would make the saving look BIGGER than it was."""
    out = tmp_path / "o.mp4"
    out.write_bytes(b"x" * 100)
    sig = f"{tmp_path / 'missing.mp4'}|0|0"
    fake_index({sig: {"source": str(tmp_path / "missing.mp4"),
                      "signature": sig, "output": str(out)}})
    m = sav.measured_savings()
    assert m["files"] == 0
    assert m["saved_bytes"] == 0


def test_an_output_larger_than_its_source_never_reports_negative_savings(
        tmp_path, fake_index):
    """Compression can lose on already-compact input. Report zero saved, not a
    negative number that would read as corruption."""
    sig, entry = _pair(tmp_path, "grew", source_size=100, output_size=400)
    fake_index({sig: entry})
    m = sav.measured_savings()
    assert m["saved_bytes"] == 0
    assert m["ratio"] == 0.25       # honest: it got bigger


def test_empty_index_reports_zeros_not_an_error(fake_index):
    fake_index({})
    m = sav.measured_savings()
    assert m["files"] == 0
    assert m["ratio"] is None
    assert m["saved_pct"] is None


def test_a_broken_index_does_not_500(monkeypatch):
    def boom(*a, **k):
        raise ValueError("corrupt index")
    monkeypatch.setattr(cidx, "_load", boom)
    m = sav.measured_savings()
    assert m["files"] == 0


# ── the recording total carries no ratio ─────────────────────────────────────

def test_recorded_totals_offer_no_ratio(client):
    """The honesty guard. A live camera capture has no source file, so any
    "x smaller" here would need an invented denominator."""
    r = sav.recorded_totals()
    assert "ratio" not in r
    assert "saved_bytes" not in r
    assert "saved_pct" not in r
    assert set(r) == {"segments", "output_bytes", "duration_hours"}


def test_endpoint_keeps_measured_and_recorded_separate(client):
    d = client.get("/api/savings").get_json()
    assert "measured" in d and "recorded" in d
    # No top-level ratio: a client must choose which question it is answering.
    assert "ratio" not in d
    assert "note" in d, "the payload should say what each half means"


def test_endpoint_returns_200_on_a_clean_install(client):
    """First run has no compressed files and possibly no DB at all."""
    r = client.get("/api/savings")
    assert r.status_code == 200
    d = r.get_json()
    assert d["measured"]["files"] >= 0
    assert d["recorded"]["segments"] >= 0

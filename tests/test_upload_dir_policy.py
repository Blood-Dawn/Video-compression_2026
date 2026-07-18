"""
tests/test_upload_dir_policy.py

M0.7: uploads must never auto-select a cloud sync root.
M0.9: /api/open_folder must be confined and must not be an existence oracle.

M0.7 is a REGRESSION test in the literal sense. FIX 1 (2026-06-03) established
the policy, stated verbatim in gui/services/cloud_detection.py:

    "The app NEVER falls through to a OneDrive / Google Drive / iCloud root on
     its own. Cloud roots are only OFFERED in the Setup page."

_default_output_dir() honored it and is covered by tests/test_default_output_dir.
_upload_dir() did not, and had zero coverage, so it silently kept preferring a
detected cloud root. That is the worst place to get this wrong: uploads are
surveillance footage of real people, so the old behavior copied video of
identifiable people into a third party's cloud with no opt-in and no way to
decline, contradicting the product's own promise to the user.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.7 / M0.9).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import src.gui.app as gui_module                                  # noqa: E402
from src.gui.routes import files_bp as files_mod                  # noqa: E402


@pytest.fixture()
def client():
    gui_module.app.config["TESTING"] = True
    return gui_module.app.test_client()


@pytest.fixture()
def no_persisted_output(monkeypatch):
    """Simulate a user who has not chosen a destination."""
    monkeypatch.setitem(gui_module._status, "config", {})
    yield


# ── M0.7: never auto-select a cloud root ──────────────────────────────────────

def test_upload_dir_is_local_when_no_destination_chosen(no_persisted_output, monkeypatch, tmp_path):
    """With no explicit choice, uploads go to the LOCAL folder."""
    monkeypatch.setattr(files_mod, "_UPLOAD_DIR_LOCAL", tmp_path / "data" / "uploads")
    d = files_mod._upload_dir()
    assert d == tmp_path / "data" / "uploads"
    assert not files_mod._is_cloud_path(d)


def test_upload_dir_ignores_a_detected_cloud_root(no_persisted_output, monkeypatch, tmp_path):
    """The regression itself: a detected OneDrive/Drive root must be ignored.

    Before M0.7 the presence of a cloud root was enough to redirect uploads
    into it, with no opt-in.
    """
    fake_cloud = tmp_path / "OneDrive"
    fake_cloud.mkdir()
    monkeypatch.setattr(files_mod, "_detect_cloud_root",
                        lambda: (fake_cloud, "OneDrive", None))
    monkeypatch.setattr(files_mod, "_UPLOAD_DIR_LOCAL", tmp_path / "data" / "uploads")
    d = files_mod._upload_dir()
    assert not files_mod._is_cloud_path(d), (
        f"uploads were auto-routed into a cloud root: {d}")
    assert d == tmp_path / "data" / "uploads"


def test_upload_dir_honors_an_explicit_cloud_choice(monkeypatch, tmp_path):
    """A cloud destination IS allowed when the user chose it in Setup.

    The policy forbids falling through to a cloud root on the app's own
    initiative, not honoring the user's own decision.
    """
    chosen = tmp_path / "OneDrive" / "SVCS"
    chosen.mkdir(parents=True)
    monkeypatch.setitem(gui_module._status, "config", {"output_dir": str(chosen)})
    d = files_mod._upload_dir()
    assert d == chosen / "uploads"
    assert files_mod._is_cloud_path(d)


def test_upload_dir_is_created(no_persisted_output, monkeypatch, tmp_path):
    monkeypatch.setattr(files_mod, "_UPLOAD_DIR_LOCAL", tmp_path / "u")
    assert files_mod._upload_dir().is_dir()


def test_relative_persisted_path_falls_back_to_local(monkeypatch, tmp_path):
    """A non-absolute persisted value must not produce a surprise location."""
    monkeypatch.setitem(gui_module._status, "config", {"output_dir": "some/relative"})
    monkeypatch.setattr(files_mod, "_UPLOAD_DIR_LOCAL", tmp_path / "data" / "uploads")
    assert files_mod._upload_dir() == tmp_path / "data" / "uploads"


@pytest.mark.parametrize("p,expected", [
    (r"C:\Users\x\OneDrive\SVCS\uploads", True),
    (r"C:\Users\x\Google Drive\SVCS", True),
    (r"C:\Users\x\My Drive\SVCS", True),
    ("/home/x/Dropbox/SVCS", True),
    ("/home/x/iCloud Drive/SVCS", True),
    (r"C:\Users\x\Videos\SVCS", False),
    ("/home/x/videos/svcs", False),
])
def test_cloud_path_detection_covers_more_than_google(p, expected):
    """The old in_drive check matched only Google Drive, so a OneDrive
    destination reported false and a client could not detect the condition."""
    assert files_mod._is_cloud_path(Path(p)) is expected


def test_policy_docstring_still_states_the_rule():
    """Guard the stated policy so a future edit cannot quietly drop it."""
    src = (SRC / "gui" / "services" / "cloud_detection.py").read_text(encoding="utf-8")
    assert "NEVER falls through" in src


# ── M0.9: open_folder confinement ─────────────────────────────────────────────

def test_open_folder_rejects_a_path_outside_the_roots(client):
    """It spawns a process on the SERVER host, so it must be confined."""
    r = client.post("/api/open_folder", json={"path": str(ROOT / "src" / "gui")})
    assert r.status_code == 403, (
        f"an out-of-roots path was accepted ({r.status_code}); this route "
        "spawns explorer/open/xdg-open on the host")


def test_open_folder_is_not_an_existence_oracle(client, tmp_path):
    """Outside the roots, existing and non-existing paths must be identical.

    Otherwise an authenticated but untrusted caller maps the host filesystem
    one probe at a time, which is the oracle SEC-015 closed on /api/media_debug.
    """
    real = tmp_path / "definitely_exists"
    real.mkdir()
    fake = tmp_path / "definitely_does_not_exist_xyz"

    r_real = client.post("/api/open_folder", json={"path": str(real)})
    r_fake = client.post("/api/open_folder", json={"path": str(fake)})

    assert r_real.status_code == r_fake.status_code == 403
    assert r_real.get_data(as_text=True) == r_fake.get_data(as_text=True), (
        "the response distinguishes an existing path from a missing one "
        "outside the allowed roots")


def test_open_folder_still_rejects_an_empty_path(client):
    assert client.post("/api/open_folder", json={"path": "  "}).status_code == 400


def test_open_folder_still_works_for_an_allowed_output_folder(client, monkeypatch):
    """The confinement must not break the feature it is protecting.

    The dashboard's only caller is the demo's "Open Folder" action, which
    passes an output folder. That lives inside allowed_media_roots(), so it
    must still succeed. Popen is stubbed so the test does not actually open a
    file explorer window.
    """
    from src.gui.services import path_safety as ps
    roots = [r for r in ps.allowed_media_roots() if Path(r).is_dir()]
    if not roots:
        pytest.skip("no allowed media root exists on this host")

    spawned = []
    monkeypatch.setattr(files_mod.subprocess, "Popen",
                        lambda *a, **kw: spawned.append(a) or object())

    r = client.post("/api/open_folder", json={"path": str(roots[0])})
    assert r.status_code == 200, (
        f"a legitimate output folder was rejected: {r.get_data(as_text=True)}")
    assert spawned, "the file explorer was never invoked"


def test_open_folder_docstring_no_longer_claims_unenforced_localhost():
    """The old docstring asserted a localhost restriction nothing implemented,
    which is worse than no comment: it tells a reviewer the route is safe."""
    src = (SRC / "gui" / "routes" / "files_bp.py").read_text(encoding="utf-8")
    assert "Runs on localhost only." not in src

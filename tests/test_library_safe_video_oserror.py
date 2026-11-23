"""An over long path is a refusal, not a 500 (pentest finding PT-03)."""

from pathlib import Path

from gui.routes import library_bp


def test_is_file_oserror_returns_none(monkeypatch, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")

    def boom(self):
        raise OSError(36, "File name too long")

    monkeypatch.setattr(Path, "is_file", boom)
    assert library_bp._safe_video(str(video)) is None


def test_a_very_long_name_is_none_not_an_exception():
    assert library_bp._safe_video("a" * 5000 + ".mp4") is None

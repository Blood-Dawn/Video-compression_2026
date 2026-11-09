"""Archive extraction for the MediaMTX download refuses unsafe members."""

import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import rtsp_server as rs  # noqa: E402


def _tar(path, members):
    """members: list of (name, bytes_or_None, type) ; type default regular file."""
    with tarfile.open(path, "w:gz") as t:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "sym":
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                t.addfile(info)
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                t.addfile(info)
            else:
                data = data or b""
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))


def _zip(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, b"x")


def test_normal_tar_extracts(tmp_path):
    arc = tmp_path / "m.tar.gz"
    _tar(arc, [("LICENSE", b"l", None), ("./mediamtx", b"bin", None), ("mediamtx.yml", b"y", None)])
    dest = tmp_path / "out"
    rs._safe_extract(arc, dest)
    assert (dest / "mediamtx").read_bytes() == b"bin"
    assert (dest / "LICENSE").exists()


def test_normal_zip_extracts(tmp_path):
    arc = tmp_path / "m.zip"
    _zip(arc, ["mediamtx.exe", "mediamtx.yml", "docs/readme.txt"])
    dest = tmp_path / "out"
    rs._safe_extract(arc, dest)
    assert (dest / "mediamtx.exe").exists() and (dest / "docs" / "readme.txt").exists()


@pytest.mark.parametrize("bad", ["../evil.txt", "a/../../evil.txt", "/abs/evil.txt",
                                 "C:/evil.txt", r"..\evil.txt", r"a\..\..\evil.txt"])
def test_tar_traversal_names_are_refused_and_nothing_is_written(tmp_path, bad):
    arc = tmp_path / "m.tar.gz"
    _tar(arc, [("good.txt", b"g", None), (bad, b"e", None)])
    dest = tmp_path / "out"
    with pytest.raises(rs.UnsafeArchiveError):
        rs._safe_extract(arc, dest)
    assert not (dest / "good.txt").exists()
    assert not (tmp_path / "evil.txt").exists()


@pytest.mark.parametrize("bad", ["../evil.txt", "/abs/evil.txt", "C:/evil.txt", r"..\evil.txt"])
def test_zip_traversal_names_are_refused_and_nothing_is_written(tmp_path, bad):
    arc = tmp_path / "m.zip"
    _zip(arc, ["good.txt", bad])
    dest = tmp_path / "out"
    with pytest.raises(rs.UnsafeArchiveError):
        rs._safe_extract(arc, dest)
    assert not (dest / "good.txt").exists()
    assert not (tmp_path / "evil.txt").exists()


def test_tar_symlink_member_is_refused(tmp_path):
    arc = tmp_path / "m.tar.gz"
    _tar(arc, [("link", None, "sym")])
    with pytest.raises(rs.UnsafeArchiveError):
        rs._safe_extract(arc, tmp_path / "out")

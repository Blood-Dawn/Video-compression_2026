"""Pins the helpers taken out of cloud_detection._detect_gdrive_root."""

import sys
import types
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import cloud_detection as cd  # noqa: E402

KEY_A = r"Software\Google\DriveFS\PerAccountPreferences"
KEY_B = r"Software\Google\Drive\PerAccountPreferences"


class _Key:
    def __init__(self, tree):
        self.tree = tree

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_winreg(tree):
    """tree: {key_path: {account: {value_name: data}}}"""
    def open_key(root, path):
        if root == "HKCU":
            if path not in tree:
                raise FileNotFoundError(path)
            return _Key(("root", path))
        return _Key(("sub", root.tree[1], path))

    def enum_key(key, i):
        subs = list(tree[key.tree[1]])
        if i >= len(subs):
            raise OSError("no more")
        return subs[i]

    def query(sub, name):
        vals = tree[sub.tree[1]][sub.tree[2]]
        if name not in vals:
            raise FileNotFoundError(name)
        return vals[name], 1

    return types.SimpleNamespace(HKEY_CURRENT_USER="HKCU", OpenKey=open_key, EnumKey=enum_key, QueryValueEx=query)


@pytest.fixture()
def registry(monkeypatch):
    def install(tree):
        monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(tree) if tree != "absent" else None)
    return install


def test_registry_mount_with_my_drive_prefers_the_my_drive_folder(tmp_path, registry):
    (tmp_path / "My Drive").mkdir()
    registry({KEY_A: {"acct": {"mount_point_path": str(tmp_path)}}})
    assert cd._gdrive_from_registry() == tmp_path / "My Drive"


def test_registry_mount_without_my_drive_uses_the_mount_itself(tmp_path, registry):
    registry({KEY_B: {"acct": {"MountPointPath": str(tmp_path)}}})
    assert cd._gdrive_from_registry() == tmp_path


def test_registry_skips_stale_accounts(tmp_path, registry):
    good = tmp_path / "good"
    good.mkdir()
    registry({KEY_A: {"old": {"mount_point_path": str(tmp_path / "gone")}, "new": {"mount_point_path": str(good)}}})
    assert cd._gdrive_from_registry() == good


@pytest.mark.parametrize("tree", ["absent", {}, {KEY_A: {}}, {KEY_A: {"a": {"other": "x"}}}])
def test_registry_with_nothing_usable_gives_none(registry, tree):
    registry(tree)
    assert cd._gdrive_from_registry() is None


def test_home_folders_in_priority_order(tmp_path):
    (tmp_path / "My Drive").mkdir()
    assert cd._gdrive_from_home_folders(tmp_path) == tmp_path / "My Drive"
    (tmp_path / "Google Drive").mkdir()
    assert cd._gdrive_from_home_folders(tmp_path) == tmp_path / "Google Drive"
    (tmp_path / "Google Drive" / "My Drive").mkdir()
    assert cd._gdrive_from_home_folders(tmp_path) == tmp_path / "Google Drive" / "My Drive"


def test_no_home_folder_gives_none(tmp_path):
    assert cd._gdrive_from_home_folders(tmp_path) is None


def test_macos_cloud_storage_is_found_by_glob(tmp_path):
    mount = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-me@example.com" / "My Drive"
    mount.mkdir(parents=True)
    assert cd._gdrive_from_macos_cloud_storage(tmp_path) == mount
    assert cd._gdrive_from_macos_cloud_storage(tmp_path / "elsewhere") is None


class _FakePath:
    """A stand-in for Path that treats chosen drive paths as directories."""
    dirs: set = set()
    exists_: set = set()

    def __init__(self, s):
        self.s = str(s)

    @property
    def parent(self):
        head = self.s.rstrip("\\").rsplit("\\", 1)[0]
        return _FakePath(head + "\\")

    def __truediv__(self, other):
        return _FakePath(self.s.rstrip("\\") + "\\" + other)

    def is_dir(self):
        return self.s in self.dirs

    def exists(self):
        return self.s in self.exists_

    def __eq__(self, other):
        return isinstance(other, _FakePath) and other.s == self.s


@pytest.fixture()
def letters(monkeypatch):
    monkeypatch.setattr(cd, "Path", _FakePath)
    monkeypatch.setattr(cd, "string", types.SimpleNamespace(ascii_uppercase="GH"))
    _FakePath.dirs, _FakePath.exists_ = set(), set()
    return _FakePath


def test_a_my_drive_folder_on_a_letter_is_google_drive(letters):
    letters.dirs = {"G:\\My Drive"}
    assert cd._gdrive_from_drive_letters() == _FakePath("G:\\My Drive")


def test_a_bare_drive_needs_the_shared_drives_sibling(letters):
    letters.dirs = {"H:\\"}
    assert cd._gdrive_from_drive_letters() is None
    letters.exists_ = {"H:\\My Drive", "H:\\Shared drives"}
    assert cd._gdrive_from_drive_letters() == _FakePath("H:\\My Drive")


def test_no_matching_letter_gives_none(letters):
    assert cd._gdrive_from_drive_letters() is None


def test_detect_returns_the_first_source_that_finds_something(monkeypatch):
    calls = []

    def src(name, result):
        def f(*a):
            calls.append(name)
            return result
        return f

    monkeypatch.setattr(cd, "_gdrive_from_registry", src("registry", None))
    monkeypatch.setattr(cd, "_gdrive_from_drive_letters", src("letters", Path("L")))
    monkeypatch.setattr(cd, "_gdrive_from_home_folders", src("home", Path("H")))
    monkeypatch.setattr(cd, "_gdrive_from_macos_cloud_storage", src("mac", Path("M")))
    assert cd._detect_gdrive_root() == Path("L")
    assert calls == ["registry", "letters"]


def test_detect_gives_none_when_every_source_is_empty(monkeypatch):
    for name in ("_gdrive_from_registry", "_gdrive_from_drive_letters"):
        monkeypatch.setattr(cd, name, lambda: None)
    for name in ("_gdrive_from_home_folders", "_gdrive_from_macos_cloud_storage"):
        monkeypatch.setattr(cd, name, lambda home: None)
    assert cd._detect_gdrive_root() is None

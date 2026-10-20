"""stamp_release_version.py keeps the three version files in step (issue #20)."""

import importlib.util
import shutil
from pathlib import Path

import pytest

from utils.version import is_newer

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "stamp_release_version", ROOT / "scripts" / "stamp_release_version.py"
)
stamp_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp_mod)


@pytest.fixture
def tree(tmp_path):
    for rel in ("pyproject.toml", "installer/svcs.iss", "src/utils/version.py"):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    return tmp_path


def test_spellings_for_beta_tag():
    assert stamp_mod.spellings("v2.2.4-beta") == {"tag": "2.2.4-beta", "pep440": "2.2.4b0"}


def test_spellings_for_dev_and_final():
    assert stamp_mod.spellings("2.2.5.dev0") == {"tag": "2.2.5.dev0", "pep440": "2.2.5.dev0"}
    assert stamp_mod.spellings("v3.0.0") == {"tag": "3.0.0", "pep440": "3.0.0"}


def test_rejects_unknown_shape():
    with pytest.raises(ValueError):
        stamp_mod.spellings("release-candidate-final")


def test_stamp_rewrites_all_three_files(tree):
    changed = stamp_mod.stamp("v9.8.7-beta", root=tree)
    assert sorted(changed) == [
        "installer/svcs.iss",
        "pyproject.toml",
        "src/utils/version.py",
    ]
    assert 'version = "9.8.7b0"' in (tree / "pyproject.toml").read_text(encoding="utf-8")
    assert '"9.8.7-beta"' in (tree / "installer/svcs.iss").read_text(encoding="utf-8")
    assert 'APP_VERSION = "9.8.7-beta"' in (tree / "src/utils/version.py").read_text(encoding="utf-8")


def test_check_mode_changes_nothing(tree):
    before = (tree / "pyproject.toml").read_bytes()
    assert stamp_mod.stamp("v9.8.7-beta", root=tree, check=True)
    assert (tree / "pyproject.toml").read_bytes() == before


def test_stamping_is_idempotent(tree):
    stamp_mod.stamp("v9.8.7-beta", root=tree)
    assert stamp_mod.stamp("v9.8.7-beta", root=tree) == []


def test_stamped_build_does_not_offer_its_own_tag():
    """The bug in #20: a build stamped with its tag must not see that tag as newer."""
    assert not is_newer("v2.2.4-beta", current="2.2.4-beta")
    assert is_newer("v2.2.4-beta", current="2.2.4.dev0")

"""Pure-logic tests for scripts/complexity_ratchet.py (radon is not needed)."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "complexity_ratchet", Path(__file__).resolve().parent.parent / "scripts" / "complexity_ratchet.py"
)
ratchet = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ratchet)


def test_new_function_is_worse():
    worse, improved, gone = ratchet.compare({"a.py::f": 20}, {})
    assert worse == [("a.py::f", 20, None)]
    assert improved == [] and gone == []


def test_higher_than_baseline_is_worse():
    worse, _, _ = ratchet.compare({"a.py::f": 31}, {"a.py::f": 30})
    assert [w[0] for w in worse] == ["a.py::f"]


def test_equal_or_lower_passes():
    worse, improved, gone = ratchet.compare({"a.py::f": 25, "a.py::g": 18}, {"a.py::f": 25, "a.py::g": 22})
    assert worse == []
    assert improved == [("a.py::g", 18, 22)]
    assert gone == []


def test_removed_function_reported_as_gone():
    worse, _, gone = ratchet.compare({}, {"a.py::f": 25})
    assert worse == [] and gone == [("a.py::f", None, 25)]


def test_baseline_file_is_valid_and_above_threshold():
    import json

    data = json.loads(ratchet.BASELINE.read_text(encoding="utf-8"))
    assert data and all(isinstance(v, int) and v > ratchet.THRESHOLD for v in data.values())

"""The OFFLINE pill and hero label say what offline means (issue #21)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
GUI = ROOT / "src" / "gui"


def _read(rel):
    return (GUI / rel).read_text(encoding="utf-8")


def test_header_pill_has_tooltip_in_markup():
    html = _read("templates/index.html")
    assert 'id="status-pill" class="pill offline" title="' in html
    assert "nothing is compressing right now" in html


def test_hero_label_has_tooltip_in_markup():
    html = _read("templates/index.html")
    assert 'id="home-hero-label" title="' in html


def test_status_js_sets_a_title_for_every_hero_state():
    js = _read("static/js/status.js")
    for state in ("LIVE", "ERROR", "OFFLINE"):
        block = js.split(f"label.textContent = '{state}';")[1].split("}")[0]
        assert "label.title" in block, state


def test_set_pipeline_running_updates_pill_title():
    js = _read("static/js/ui.js")
    assert "pill.title = running" in js


def test_idle_hint_is_visible_text_not_only_a_tooltip():
    html = _read("templates/index.html")
    js = _read("static/js/status.js")
    assert "Idle, press Start to begin" in html
    assert "Idle, press Start to begin" in js

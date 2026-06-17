"""Regression tests for the pose colour-swatch button stylesheet.

Guards against the f-string concatenation bug where a stray ``}}`` in a
plain (non-f) string literal produced an unparseable Qt stylesheet and the
runtime warning ``Could not parse stylesheet of object _ColorSwatchButton``.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.conftest import MockShape  # noqa: F401  (keep conftest importable)


def _assert_stylesheet_valid(sheet: str) -> None:
    """A Qt stylesheet must have balanced braces and no escaped-brace
    artifacts (``{{`` / ``}}``) left over from mis-built f-strings."""
    open_count = sheet.count("{")
    close_count = sheet.count("}")
    assert "{{" not in sheet, "stray '{{' artifact in stylesheet: " + sheet
    assert "}}" not in sheet, "stray '}}' artifact in stylesheet: " + sheet
    assert open_count == close_count, (
        "unbalanced braces in stylesheet: " + sheet
    )


def test_color_swatch_stylesheet_is_valid(qapp):
    """A freshly built swatch must produce a parseable stylesheet."""
    from anylabeling.views.labeling.widgets.pose_label.pose_color_panel import (
        _ColorSwatchButton,
    )

    btn = _ColorSwatchButton("#00ff88")
    _assert_stylesheet_valid(btn.styleSheet())


def test_color_swatch_stylesheet_stays_valid_after_set_color(qapp):
    """set_color must also keep the stylesheet parseable (regression for
    the _update_icon re-entry that re-ran the broken f-string)."""
    from anylabeling.views.labeling.widgets.pose_label.pose_color_panel import (
        _ColorSwatchButton,
    )

    btn = _ColorSwatchButton("#000000")
    for hex_color in ("#ff0000", "#00ff00", "#89b4fa", "#3a3a52"):
        btn.set_color(hex_color)
        sheet = btn.styleSheet()
        _assert_stylesheet_valid(sheet)
        assert hex_color in sheet

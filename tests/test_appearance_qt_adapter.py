"""Qt adapter tests for annotation visual styles."""

from PyQt6 import QtCore

from anylabeling.views.labeling.widgets.appearance.types import VisualStyle
from anylabeling.views.labeling.widgets.appearance_qt import (
    QtAppearanceAdapter,
)


def _style():
    """Return a representative immutable visual style."""
    return VisualStyle(
        base_color=(1, 2, 3),
        outer_color=(250, 250, 250),
        outline_width=2.0,
        semantic_width=1.0,
        fill_opacity=28,
        object_opacity=0.5,
        label_badge="person",
        gid_badge="7",
    )


def test_adapter_preserves_alpha_and_screen_stable_width():
    """Pens and brushes carry style opacity and scale-aware widths."""
    style = _style()
    pen = QtAppearanceAdapter.semantic_pen(style, 2.0)
    outer = QtAppearanceAdapter.contrast_pen(style, 0.5)
    brush = QtAppearanceAdapter.fill_brush(style)
    assert pen.width() == 1
    assert outer.width() == 4
    assert pen.color().alpha() == 128
    assert brush.color().alpha() == 28


def test_adapter_badge_and_no_brush_helpers():
    """Identity text remains available independently from color."""
    assert QtAppearanceAdapter.badge_text(_style()) == "person #7"
    assert (
        QtAppearanceAdapter.no_brush().style() == QtCore.Qt.BrushStyle.NoBrush
    )

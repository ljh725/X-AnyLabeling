"""Canvas-side application of the dense-review display table.

The pure decision table is covered by ``test_display_policy``; these tests
prove the canvas *applies* it: the paint gate and the hit gate come from the
same entry, the edit handles follow the role, and leaving review restores the
ordinary painting (DP-01, DP-02, DP-03, DP-07, DP-15, DP-18).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.services.dense_review.display import (
    ROLE_BATCH,
    ROLE_CURRENT,
    ROLE_OTHER,
    RoleStyle,
    ShapeDisplay,
    default_role_styles,
)
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas


@pytest.fixture
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        []
    )
    application.setQuitOnLastWindowClosed(False)
    return application


def _rectangle(shape_id, label, x, y, w=40, h=40):
    shape = Shape(
        label=label,
        shape_type="rectangle",
        group_id=0,
        shape_id=shape_id,
    )
    shape.add_point(QtCore.QPointF(x, y))
    shape.add_point(QtCore.QPointF(x + w, y))
    shape.add_point(QtCore.QPointF(x + w, y + h))
    shape.add_point(QtCore.QPointF(x, y + h))
    shape.close()
    return shape


def _point(shape_id, label, x, y, group_id=0):
    shape = Shape(
        label=label,
        shape_type="point",
        group_id=group_id,
        shape_id=shape_id,
    )
    shape.add_point(QtCore.QPointF(x, y))
    return shape


def _display(shape_id, role, *, drawable=True, hittable=True, style=None):
    return ShapeDisplay(
        shape_id=shape_id,
        role=role,
        style=style or default_role_styles()[role],
        drawable=drawable,
        hittable=hittable,
        label_visible=drawable,
    )


def _canvas_with(shapes):
    canvas = Canvas(parent=None)
    canvas.pixmap = QtGui.QPixmap(400, 400)
    canvas.pixmap.fill(QtGui.QColor("black"))
    canvas.resize(400, 400)
    canvas.scale = 1.0
    canvas.load_shapes(shapes)
    canvas.setEnabled(True)
    return canvas


def test_overlay_is_inactive_by_default(app):
    keypoint = _point("kp1", "nose", 100, 100)
    canvas = _canvas_with([keypoint])
    # Ordinary labelling must behave exactly as before (DP-18).
    assert canvas.dense_review_active is False
    assert canvas.dense_review_drawable(keypoint) is True
    assert canvas.dense_review_hittable(keypoint) is True
    assert canvas.dense_review_paint_style(keypoint) is None


def test_installed_overlay_gates_paint_and_hit_together(app):
    current = _rectangle("id1", "person", 50, 50)
    hidden = _rectangle("id2", "person", 150, 50)
    canvas = _canvas_with([current, hidden])
    canvas.set_dense_review_display(
        {
            "id1": _display("id1", ROLE_CURRENT),
            "id2": _display("id2", ROLE_OTHER, drawable=False, hittable=False),
        }
    )
    assert canvas.dense_review_active is True
    assert canvas.dense_review_drawable(current) is True
    assert canvas.dense_review_hittable(current) is True
    # A non-drawable object cannot be hit either (DP-02).
    assert canvas.dense_review_drawable(hidden) is False
    assert canvas.dense_review_hittable(hidden) is False

    # Hit candidates follow the same gate.
    candidates = canvas._shape_hit_candidates(QtCore.QPointF(170, 70))
    assert hidden not in candidates


def test_handles_follow_role_while_formal_points_stay(app):
    batch = _rectangle("id1", "person", 50, 50)
    current = _rectangle("id2", "person", 200, 50)
    keypoint = _point("kp1", "nose", 120, 120)
    canvas = _canvas_with([batch, current, keypoint])
    canvas.select_shapes([current])
    styles = default_role_styles()
    canvas.set_dense_review_display(
        {
            "id1": _display("id1", ROLE_BATCH),
            "id2": _display("id2", ROLE_CURRENT),
            "kp1": _display("kp1", ROLE_BATCH),
        }
    )
    batch_style = canvas.dense_review_paint_style(batch)
    current_style = canvas.dense_review_paint_style(current)
    keypoint_style = canvas.dense_review_paint_style(keypoint)
    # Only the edit target keeps handles; the non-current rectangle does not
    # (DP-03).
    assert batch_style.handles_visible is False
    assert current_style.handles_visible is True
    # The formal keypoint keeps a visible symbol even without handles.
    assert keypoint_style.handles_visible is False
    assert keypoint_style.points_opacity > 0.0
    assert styles[ROLE_CURRENT].handles > 0.0


def test_zero_strength_role_paints_nothing(app):
    zero = RoleStyle(
        fill=0.0,
        outline=0.0,
        outline_width=1.0,
        points=0.0,
        handles=0.0,
        text=0.0,
        text_plate=0.0,
        attributes=0.0,
        linking=0.0,
        mask=0.0,
    )
    other = _rectangle("id9", "car", 50, 50)
    canvas = _canvas_with([other])
    canvas.set_dense_review_display(
        {
            "id9": _display(
                "id9", ROLE_OTHER, drawable=False, hittable=False, style=zero
            )
        }
    )
    assert canvas.dense_review_drawable(other) is False
    assert canvas.dense_review_hittable(other) is False
    assert canvas._shape_hit_candidates(QtCore.QPointF(60, 60)) == []


def test_clearing_the_overlay_restores_normal_mode(app):
    shape = _rectangle("id1", "person", 50, 50)
    canvas = _canvas_with([shape])
    canvas.set_dense_review_display(
        {"id1": _display("id1", ROLE_CURRENT, drawable=False, hittable=False)}
    )
    assert canvas.dense_review_drawable(shape) is False
    canvas.clear_dense_review_display()
    assert canvas.dense_review_active is False
    assert canvas.dense_review_drawable(shape) is True
    assert canvas.dense_review_hittable(shape) is True


def test_unknown_shape_stays_interactive_until_resync(app):
    shape = _rectangle("brand-new", "person", 50, 50)
    canvas = _canvas_with([shape])
    canvas.set_dense_review_display(
        {"id1": _display("id1", ROLE_CURRENT, drawable=False, hittable=False)}
    )
    # A shape created after the table was built must not silently vanish.
    assert canvas.dense_review_drawable(shape) is True
    assert canvas.dense_review_hittable(shape) is True


def test_painting_with_a_display_style_does_not_raise(app):
    shape = _rectangle("id1", "person", 50, 50)
    shape.selected = True
    image = QtGui.QImage(400, 400, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("#ffffff"))
    painter = QtGui.QPainter(image)
    try:
        shape.paint(
            painter,
            1.0,
            display_style=canvas_style(ROLE_CURRENT),
        )
        shape.paint(painter, 1.0, display_style=canvas_style(ROLE_OTHER))
    finally:
        painter.end()
    # The zero-strength role still leaves the source image untouched.
    assert image.pixelColor(5, 5).name() == "#ffffff"


def canvas_style(role, **overrides):
    from anylabeling.services.dense_review.display import PaintStyle

    style = default_role_styles()[role]
    if overrides:
        style = RoleStyle(**{**style.to_dict(), **overrides}).normalized()
    return PaintStyle.from_role_style(style)


def test_other_role_style_paints_no_fill(app):
    shape = _rectangle("id1", "person", 50, 50)
    shape.fill = True
    image = QtGui.QImage(400, 400, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("#ffffff"))
    painter = QtGui.QPainter(image)
    try:
        shape.paint(painter, 1.0, display_style=canvas_style(ROLE_OTHER))
    finally:
        painter.end()
    # Fill defaults to zero, so the interior stays the source image (DP-01).
    assert image.pixelColor(70, 70).name() == "#ffffff"


def test_paint_event_applies_the_table(app):
    """An excluded object leaves the source pixels untouched."""
    canvas = _canvas_with([])
    current = _rectangle("id1", "person", 50, 50, 100, 100)
    excluded = _rectangle("id2", "person", 200, 50, 100, 100)
    canvas.load_shapes([current, excluded])
    canvas.show_masks = True
    canvas.show_labels = False
    canvas.show_attributes = False
    canvas.show_linking = False
    canvas.show_groups = False
    canvas.show_degrees = False
    canvas.set_dense_review_display(
        {
            "id1": _display("id1", ROLE_CURRENT),
            "id2": _display("id2", ROLE_OTHER, drawable=False, hittable=False),
        }
    )
    image = QtGui.QImage(400, 400, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("#ffffff"))
    canvas.render(image)
    # The source pixmap is black; the current rectangle adds an outline on
    # top of it, the excluded one leaves the bare source pixel.
    background = image.pixelColor(390, 390).name()
    assert image.pixelColor(100, 50).name() != background
    assert image.pixelColor(250, 50).name() == background

"""Stage 6 review fix — AC-058 edit gates.

While the refine mode is ACTIVE, only rectangle edge-drag is a permitted
member edit (§22.2).  Whole-shape edits must be blocked:
    * mouse whole-shape drag
    * keyboard arrow move (Up/Down/Left/Right)
    * keyboard rotation (Z/X/C/V → rotate_by_keyboard)

These tests prove the gates fire on the real Canvas once a workgroup is
ACTIVE, and lift again on exit.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anylabeling.config as _cfgmod  # noqa: E402

_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "anylabeling",
    "configs",
    "xanylabeling_config.yaml",
)
_cfgmod.current_config_file = _CFG_PATH

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.views.labeling.label_wrapper import (  # noqa: E402
    LabelingWrapper,
)
from anylabeling.views.labeling.rect_refine_types import (  # noqa: E402
    RectRefineState,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402

pytest.importorskip("PIL")
from PIL import Image as _PIL_Image  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def widget(qapp, tmp_path):
    p = tmp_path / "img.png"
    _PIL_Image.new("RGB", (300, 300), (255, 255, 255)).save(p)
    mw = QtWidgets.QMainWindow()
    wrapper = LabelingWrapper(mw)
    w = wrapper.view
    assert w.load_file(str(p)) is True
    yield w
    mw.close()


def _rect(label, x, y, w, h):
    s = Shape(label=label, shape_type="rectangle")
    s.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + w, y),
        QtCore.QPointF(x + w, y + h),
        QtCore.QPointF(x, y + h),
    ]
    return s


def _enter_active(widget, person, head):
    wf = widget._ensure_rect_refine_workflow()
    widget.load_shapes([person, head], replace=True, store_backup=False)
    token = widget._rect_refine_image_token
    views = [
        widget._rect_refine_view_builder.build_view(s, i, token)
        for i, s in enumerate(widget.canvas.shapes)
    ]
    wf.enable(token, views)
    widget.canvas.select_shapes([person], source="canvas")
    return wf


# ---------------------------------------------------------------------------
# Gate presence / absence
# ---------------------------------------------------------------------------


def test_blocker_absent_when_mode_off(widget):
    assert widget.canvas.is_whole_shape_edit_blocked() is False


def test_blocker_active_when_workgroup_active(widget):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    widget._toggle_rect_refine_mode(True)
    _enter_active(widget, person, head)
    assert widget.canvas.is_whole_shape_edit_blocked() is True
    # Exiting clears the blocker.
    widget._toggle_rect_refine_mode(False)
    assert widget.canvas.is_whole_shape_edit_blocked() is False


# ---------------------------------------------------------------------------
# AC-058: keyboard arrow move blocked while ACTIVE
# ---------------------------------------------------------------------------


def test_ac058_keyboard_arrow_move_blocked(widget):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    widget._toggle_rect_refine_mode(True)
    _enter_active(widget, person, head)
    widget.canvas.select_shapes([head], source="canvas")
    head_points_before = [(p.x(), p.y()) for p in head.points]

    # Drive an arrow key through the real Canvas keyPressEvent.
    widget.canvas.set_editing(True)
    for key in (
        QtCore.Qt.Key.Key_Up,
        QtCore.Qt.Key.Key_Down,
        QtCore.Qt.Key.Key_Left,
        QtCore.Qt.Key.Key_Right,
    ):
        ev = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress,
            key,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        widget.canvas.keyPressEvent(ev)

    # Member points untouched — arrow move was blocked.
    assert [(p.x(), p.y()) for p in head.points] == head_points_before


# ---------------------------------------------------------------------------
# AC-058: keyboard rotation blocked while ACTIVE
# ---------------------------------------------------------------------------


def test_ac058_keyboard_rotation_blocked(widget):
    # Rotation only applies to 'rotation' shape_type; use one to ensure the
    # blocked path would otherwise rotate.  Use a person+head workgroup plus
    # a rotation shape as a non-member — but rotation only acts on selected,
    # so select the rotation shape.  The gate blocks before any rotation.
    rot = Shape(label="rot", shape_type="rotation")
    rot.points = [
        QtCore.QPointF(10, 10),
        QtCore.QPointF(60, 10),
        QtCore.QPointF(60, 60),
        QtCore.QPointF(10, 60),
    ]
    person = _rect("person", 100, 100, 80, 160)
    head = _rect("head", 120, 110, 40, 50)
    widget._toggle_rect_refine_mode(True)
    wf = widget._ensure_rect_refine_workflow()
    widget.load_shapes([person, head, rot], replace=True, store_backup=False)
    token = widget._rect_refine_image_token
    views = [
        widget._rect_refine_view_builder.build_view(s, i, token)
        for i, s in enumerate(widget.canvas.shapes)
    ]
    wf.enable(token, views)
    widget.canvas.select_shapes([person], source="canvas")
    assert widget.canvas.is_whole_shape_edit_blocked() is True

    widget.canvas.select_shapes([rot], source="canvas")
    rot_points_before = [(p.x(), p.y()) for p in rot.points]
    # Direct call to rotate_by_keyboard must be a no-op while blocked.
    widget.canvas.rotate_by_keyboard(0.5)
    assert [(p.x(), p.y()) for p in rot.points] == rot_points_before


# ---------------------------------------------------------------------------
# AC-058: non-ACTIVE keeps original behaviour (regression guard)
# ---------------------------------------------------------------------------


def test_non_active_arrow_move_not_blocked(widget):
    """Without a workgroup, the blocker must be inert so arrow keys still
    drive the existing whole-shape move (regression guard)."""
    assert widget.canvas.is_whole_shape_edit_blocked() is False
    # _editing_arrow_dispatch returns True for arrow keys regardless of block
    # only when consumed; verify it still returns True (consumed as a move)
    # and the blocker predicate is the only difference.
    widget.canvas.set_editing(True)
    consumed = widget.canvas._editing_arrow_dispatch(
        QtCore.Qt.Key.Key_Up, QtCore.Qt.KeyboardModifier.NoModifier
    )
    assert consumed is True

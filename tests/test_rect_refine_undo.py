"""Stage 6 — undo_floor real-path gate + workgroup-limited undo (TDD).

These tests target audit risk #5: Ctrl+Z must not cross ``undo_floor`` and
must never trigger ``canvas.restore_shape()`` / ``set_dirty()`` while a
workgroup is ACTIVE (which would break member ``id(shape)`` identity and
leak geometry to auto-save).

Written first (failing), then made green by wiring the workflow guard into
``LabelingWidget.undo_shape_edit()`` and adding the workgroup points stack.
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

from PyQt6 import QtCore, QtWidgets  # noqa: E402

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
def make_png(tmp_path):
    def _make(name="img.png"):
        p = tmp_path / name
        _PIL_Image.new("RGB", (300, 300), (255, 255, 255)).save(p)
        return str(p)

    return _make


@pytest.fixture
def widget(qapp, make_png):
    png = make_png()
    mw = QtWidgets.QMainWindow()
    wrapper = LabelingWrapper(mw)
    w = wrapper.view
    assert w.load_file(png) is True
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
# AC-067: ACTIVE + at undo_floor + Ctrl+Z must not cross into pre-group history
# ---------------------------------------------------------------------------


def test_active_undo_at_floor_does_not_cross(widget, monkeypatch):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    wf = _enter_active(widget, person, head)
    assert wf.state == RectRefineState.ACTIVE
    floor = wf.undo_floor

    # Drive the canvas backup count down to the floor (no workgroup edits
    # pushed yet) so an undo would cross into pre-group history.
    widget.canvas.shapes_backups = widget.canvas.shapes_backups[
        : max(0, floor)
    ]
    # Sanity: we are at or below the floor.
    assert widget.canvas.shapes_backups.__len__() <= floor

    restore_calls = []
    save_calls = []
    monkeypatch.setattr(
        widget.canvas,
        "restore_shape",
        lambda: restore_calls.append(1),
    )
    monkeypatch.setattr(
        widget, "save_labels", lambda fn: save_calls.append(fn) or True
    )

    # Member points must be untouched by the blocked undo.
    head_points_before = [(p.x(), p.y()) for p in head.points]
    widget.undo_shape_edit()

    # Core: never called canvas.restore_shape (which would replace shapes).
    assert restore_calls == []
    # Core: never wrote to disk.
    assert save_calls == []
    # Workgroup stays ACTIVE (undo consumed + blocked, not released).
    assert wf.state == RectRefineState.ACTIVE
    assert wf.has_active_workgroup
    # Member identity preserved (no shapes-list replacement).
    assert head in widget.canvas.shapes
    assert [(p.x(), p.y()) for p in head.points] == head_points_before


# ---------------------------------------------------------------------------
# AC-066: ACTIVE + one workgroup edit + Ctrl+Z restores that step in place,
# no disk write, member identity preserved
# ---------------------------------------------------------------------------


def test_active_undo_one_step_restores_points_no_save(widget, monkeypatch):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    wf = _enter_active(widget, person, head)
    head_points_at_build = [(p.x(), p.y()) for p in head.points]

    # Simulate one committed edge-drag on the head: mutate points, then emit
    # shape_moved (the 4A dirty-wrapper routes this to note_geometry_changed
    # + commit_member_points).
    head.points[0] = QtCore.QPointF(41.0, 20.0)
    widget.canvas.shapes_backups.append(
        [s.copy() for s in widget.canvas.shapes]
    )
    widget.canvas.shape_moved.emit()
    assert wf.workgroup_geometry_dirty is True
    head_points_after_edit = [(p.x(), p.y()) for p in head.points]
    assert head_points_after_edit != head_points_at_build

    restore_calls = []
    save_calls = []
    monkeypatch.setattr(
        widget.canvas,
        "restore_shape",
        lambda: restore_calls.append(1),
    )
    monkeypatch.setattr(
        widget, "save_labels", lambda fn: save_calls.append(fn) or True
    )

    widget.undo_shape_edit()

    # Core: in-place restore, no canvas.restore_shape, no save.
    assert restore_calls == []
    assert save_calls == []
    # Member identity preserved.
    assert head in widget.canvas.shapes
    # Points restored to the build-time snapshot (one step back).
    assert [(p.x(), p.y()) for p in head.points] == head_points_at_build
    # Workgroup geometry-dirty flag reflects the rollback.
    assert wf.workgroup_geometry_dirty is False

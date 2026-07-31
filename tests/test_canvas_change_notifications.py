"""Tests for Canvas-wide generic shape change notifications."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtTest

from anylabeling.views.labeling.rectangle_size import RectangleSizeRule
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.labeling.widgets.rectangle_size_monitor import (
    RectangleSizeMonitor,
)
from anylabeling.views.labeling.shape import Shape


def _rectangle(
    label: str = "person",
    *,
    width: float = 20.0,
    height: float = 20.0,
) -> Shape:
    """Return a closed four-point rectangle shape."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(10.0, 10.0),
        QtCore.QPointF(10.0 + width, 10.0),
        QtCore.QPointF(10.0 + width, 10.0 + height),
        QtCore.QPointF(10.0, 10.0 + height),
    ]
    shape.close()
    return shape


def test_incremental_helper_only_emits_for_current_identity(canvas) -> None:
    """A stale equal-looking shape must not leak into current observers."""
    current = _rectangle()
    stale = _rectangle()
    received = []
    canvas.shape_changed.connect(received.append)
    canvas.load_shapes([current], store_backup=False)

    canvas.notify_shape_changed(stale)
    canvas.notify_shape_changed(current)

    assert received == [current]


def test_load_replace_and_append_publish_immutable_snapshots(canvas) -> None:
    """List replacement and extension should each emit one full snapshot."""
    first = _rectangle("person")
    second = _rectangle("head")
    snapshots = []
    canvas.shapes_changed.connect(snapshots.append)

    canvas.load_shapes([first], store_backup=False)
    canvas.load_shapes([second], replace=False, store_backup=False)

    assert snapshots == [(first,), (first, second)]
    assert all(isinstance(snapshot, tuple) for snapshot in snapshots)


def test_delete_and_reset_publish_current_empty_snapshot(canvas) -> None:
    """Removal and image reset must not leave observers with stale shapes."""
    first = _rectangle()
    second = _rectangle("head")
    snapshots = []
    canvas.load_shapes([first, second], store_backup=False)
    canvas.shapes_changed.connect(snapshots.append)

    canvas.delete_shape(first)
    canvas.reset_state()

    assert snapshots == [(second,), ()]
    assert canvas.shapes == []


def test_load_pixmap_clear_shapes_publishes_empty_snapshot(canvas) -> None:
    """Changing images with clear_shapes should synchronously clear observers."""
    canvas.load_shapes([_rectangle()], store_backup=False)
    snapshots = []
    canvas.shapes_changed.connect(snapshots.append)

    canvas.load_pixmap(QtGui.QPixmap(100, 100), clear_shapes=True)

    assert snapshots == [()]
    assert canvas.shapes == []


def test_live_vertex_move_emits_incremental_without_legacy_commit_signal(
    canvas,
) -> None:
    """Live geometry notification must remain separate from dirty semantics."""
    shape = _rectangle()
    canvas.load_pixmap(QtGui.QPixmap(100, 100), clear_shapes=True)
    canvas.load_shapes([shape], store_backup=False)
    changed = []
    moved = []
    canvas.shape_changed.connect(changed.append)
    canvas.shape_moved.connect(lambda: moved.append(True))
    canvas.h_hape = shape
    canvas.h_vertex = 0

    canvas.bounded_move_vertex(QtCore.QPointF(5.0, 5.0))

    assert changed == [shape]
    assert moved == []


def test_visibility_and_global_predicate_use_incremental_and_full_signals(
    canvas,
) -> None:
    """Local visibility changes are incremental; bulk policy changes are full."""
    shape = _rectangle()
    canvas.load_shapes([shape], store_backup=False)
    changed = []
    snapshots = []
    canvas.shape_changed.connect(changed.append)
    canvas.shapes_changed.connect(snapshots.append)

    canvas.set_shape_visible(shape, False)
    canvas.set_main_visibility_predicate(lambda _shape: True)

    assert changed == [shape]
    assert snapshots == [(shape,)]


def test_committed_label_change_emits_incremental_notification(canvas) -> None:
    """Assigning the final label should expose the completed shape metadata."""
    shape = _rectangle(label="")
    canvas.load_shapes([shape])
    changed = []
    canvas.shape_changed.connect(changed.append)

    returned = canvas.set_last_label("person", {}, None)

    assert returned is shape
    assert shape.label == "person"
    assert changed == [shape]


def test_notification_contract_drives_monitor_without_canvas_coupling(
    qapp,
    canvas,
) -> None:
    """Generic signals should satisfy the monitor's public adapter contract."""
    shape = _rectangle(width=20.0, height=20.0)
    monitor = RectangleSizeMonitor(
        [
            RectangleSizeRule(
                label="person",
                min_width_px=36.0,
                min_height_px=36.0,
                trigger_mode="any",
            )
        ],
        enabled=True,
        debounce_ms=5,
        is_shape_interactive=canvas.is_shape_interactive,
    )
    canvas.shapes_changed.connect(monitor.replace_shapes)
    canvas.shape_changed.connect(monitor.invalidate_shape)

    canvas.load_shapes([shape], store_backup=False)
    assert len(monitor.issues) == 1

    shape.label = "head"
    canvas.notify_shape_changed(shape)
    QtTest.QTest.qWait(30)
    qapp.processEvents()

    assert monitor.issues == ()

    shape.label = "person"
    canvas.notify_shape_changed(shape)
    QtTest.QTest.qWait(30)
    qapp.processEvents()
    assert len(monitor.issues) == 1

    canvas.set_main_visibility_predicate(lambda _shape: False)

    assert monitor.issues == ()

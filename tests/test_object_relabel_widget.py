"""Cross-image object marking UI tests (PyQt offscreen).

Canvas gesture-level tests drive real mouse events; widget-level tests
use the light SimpleNamespace stand-in pattern also used by the behavior
analytics widget tests.
"""

import json
import os.path as osp
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.views.labeling import (
    label_widget as label_widget_module,
)  # noqa: E402
from anylabeling.views.labeling.dataset_index import (  # noqa: E402
    DatasetThumbnailRef,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402
from anylabeling.views.labeling.widgets.canvas import Canvas  # noqa: E402
from anylabeling.views.labeling.widgets.object_relabel import (  # noqa: E402
    MarkedObjectRef,
    MarkedObjectStore,
    ObjectMutationResult,
    ObjectRelabelResult,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    STATUS_CANCELLED,
)
from anylabeling.views.labeling.widgets.object_relabel_dialog import (  # noqa: E402
    _preflight_message,
)


def _rect_shape(label="person", x=10, y=10, w=40, h=40):
    """Build a closed rectangle shape with a stable identity."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + w, y),
        QtCore.QPointF(x + w, y + h),
        QtCore.QPointF(x, y + h),
    ]
    shape.close()
    return shape


def _mouse_event(event_type, x, y, button=QtCore.Qt.MouseButton.LeftButton):
    """Fabricate one mouse event at widget position (x, y)."""
    point = QtCore.QPointF(x, y)
    return QtGui.QMouseEvent(
        event_type,
        point,
        point,
        point,
        button,
        button,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


class _CanvasSpy:
    """Minimal canvas stand-in capturing marked id updates."""

    def __init__(self):
        """Start with no marked ids."""
        self.marked_ids = []
        self.mode = False

    def set_marked_shape_ids(self, shape_ids):
        """Record the latest marked identity set."""
        self.marked_ids = list(shape_ids)

    def set_batch_mark_mode(self, enabled):
        """Record the latest gesture mode."""
        self.mode = bool(enabled)


class _Actions:
    """Recorder for the three object-mark actions."""

    def __init__(self):
        """Start with default action state."""
        self.texts = []
        self.enabled = []
        self.clear_enabled = []

    @property
    def relabel_marked_objects(self):
        """Expose a nested recorder matching the attribute access."""
        return self

    @property
    def clear_batch_marks(self):
        """Expose a nested recorder matching the attribute access."""
        return SimpleNamespace(
            setEnabled=self._record_clear,
            setText=self._noop,
        )

    def setText(self, text):
        """Record one action text refresh."""
        self.texts.append(text)

    def setEnabled(self, enabled):
        """Record one enabled refresh."""
        self.enabled.append(enabled)

    def _record_clear(self, enabled):
        """Record clear-action enabled refresh."""
        self.clear_enabled.append(enabled)

    def _noop(self, _text):
        """Accept text updates without recording."""


def _widget(tmp_path, filename="a.png", output_dir=None):
    """Build a light LabelingWidget stand-in over a real mark store."""
    widget = SimpleNamespace()
    widget.marked_object_store = MarkedObjectStore()
    widget._object_relabel_running = False
    widget._object_relabel_thread = None
    widget.filename = str(tmp_path / filename)
    widget.output_dir = output_dir
    widget.canvas = _CanvasSpy()
    widget.canvas.shapes = []
    widget.object_mark_actions = _Actions()
    widget.tr = lambda text: text
    index_refreshes = []
    widget.index_refreshes = index_refreshes
    widget.dataset_review_dataset_root = lambda: str(tmp_path)
    widget._dataset_index_controller = SimpleNamespace(
        label_saved=lambda image_path: index_refreshes.append(image_path)
    )
    widget._marked_project_id = lambda: osp.normcase(
        osp.abspath(str(tmp_path))
    )
    widget._batch_write_root = lambda: osp.abspath(str(tmp_path))
    widget._annotation_path_for_image = (
        lambda image_id: osp.splitext(str(image_id))[0] + ".json"
    )
    widget._sync_marked_object_ui = (
        lambda: label_widget_module.LabelingWidget._sync_marked_object_ui(
            widget
        )
    )
    widget._candidate_target_labels = lambda: sorted(
        {s.label for s in widget.canvas.shapes if s.label}
    ) or [""]
    widget.dataset_review_resolve_dirty = lambda: "save"
    widget.error_message = lambda *args, **kwargs: None
    widget.status = lambda *args, **kwargs: None
    widget.load_file = lambda *args, **kwargs: None
    widget.unique_label_list = SimpleNamespace(count=lambda: 0)
    return widget


# ------------------------------------------------------------ canvas


def test_canvas_plain_object_click_toggles_mark(qapp):
    """A still click on a hovered shape emits exactly one toggle request."""
    canvas = Canvas()
    shape = _rect_shape()
    canvas.shapes = [shape]
    canvas.h_hape = shape
    canvas.set_batch_mark_mode(True)
    emitted = []
    canvas.batch_mark_toggle_requested.connect(emitted.append)
    canvas.mousePressEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonPress, 30, 30)
    )
    canvas.mouseReleaseEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonRelease, 30, 30)
    )
    assert emitted == [shape]


def test_canvas_drag_vertex_edge_and_blank_do_not_toggle(qapp):
    """Drags, vertex/edge presses, and blank clicks never toggle marks."""
    canvas = Canvas()
    shape = _rect_shape()
    canvas.shapes = [shape]
    canvas.set_batch_mark_mode(True)
    emitted = []
    canvas.batch_mark_toggle_requested.connect(emitted.append)

    # Drag: release far from the press position.
    canvas.h_hape = shape
    canvas.mousePressEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonPress, 30, 30)
    )
    canvas.mouseReleaseEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonRelease, 300, 300)
    )
    assert emitted == []

    # Vertex press: hover targets a vertex, not the body.
    canvas.h_hape = shape
    canvas.h_vertex = 0
    canvas.mousePressEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonPress, 10, 10)
    )
    canvas.mouseReleaseEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonRelease, 10, 10)
    )
    canvas.h_vertex = None
    assert emitted == []

    # Active edge press.
    canvas.h_hape = shape
    canvas.h_edge = 0
    canvas.mousePressEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonPress, 30, 10)
    )
    canvas.mouseReleaseEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonRelease, 30, 10)
    )
    canvas.h_edge = None
    assert emitted == []

    # Blank click.
    canvas.h_hape = None
    canvas.mousePressEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonPress, 5, 5)
    )
    canvas.mouseReleaseEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonRelease, 5, 5)
    )
    assert emitted == []


def test_canvas_moving_shape_release_does_not_toggle(qapp):
    """A release that completed a geometric move keeps the mark set."""
    canvas = Canvas()
    shape = _rect_shape()
    canvas.shapes = [shape]
    canvas.set_batch_mark_mode(True)
    emitted = []
    canvas.batch_mark_toggle_requested.connect(emitted.append)
    canvas.h_hape = shape
    canvas.mousePressEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonPress, 30, 30)
    )
    canvas.moving_shape = True
    canvas.mouseReleaseEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonRelease, 31, 31)
    )
    assert emitted == []
    assert canvas.moving_shape is False


def test_pausing_mark_mode_keeps_marked_ids_and_gesture_silent(qapp):
    """Pausing stops new toggles but keeps the current image marks."""
    canvas = Canvas()
    shape = _rect_shape()
    canvas.shapes = [shape]
    canvas.set_marked_shape_ids([shape.xanylabeling_shape_id])
    canvas.set_batch_mark_mode(False)
    assert canvas.marked_shape_ids == {shape.xanylabeling_shape_id}
    emitted = []
    canvas.batch_mark_toggle_requested.connect(emitted.append)
    canvas.h_hape = shape
    canvas.mousePressEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonPress, 30, 30)
    )
    canvas.mouseReleaseEvent(
        _mouse_event(QtCore.QEvent.Type.MouseButtonRelease, 30, 30)
    )
    assert emitted == []


def test_mark_overlay_follows_identity_not_label_or_geometry(qapp):
    """Renaming or moving a marked shape keeps it marked by identity."""
    canvas = Canvas()
    shape = _rect_shape()
    canvas.set_marked_shape_ids([shape.xanylabeling_shape_id])
    shape.label = "renamed"
    shape.points = [
        QtCore.QPointF(100, 100),
        QtCore.QPointF(140, 100),
        QtCore.QPointF(140, 140),
        QtCore.QPointF(100, 140),
    ]
    assert shape.xanylabeling_shape_id in canvas.marked_shape_ids


def test_mark_overlay_repaint_does_not_expand_cached_bounds(qapp):
    """Repeated overlay paints never mutate Shape's cached rectangle."""

    class _Painter:
        """Record rectangles drawn by the overlay."""

        def __init__(self):
            """Start without recorded rectangles."""
            self.rects = []

        def save(self):
            """Accept painter state save."""

        def setPen(self, _pen):
            """Accept the overlay pen."""

        def drawRect(self, rect):
            """Copy each rectangle so later mutations are observable."""
            self.rects.append(QtCore.QRectF(rect))

        def restore(self):
            """Accept painter state restore."""

    canvas = Canvas()
    shape = _rect_shape()
    canvas.shapes = [shape]
    canvas.is_visible = lambda _shape: True
    canvas.set_marked_shape_ids([shape.xanylabeling_shape_id])
    original = QtCore.QRectF(shape.bounding_rect())
    painter = _Painter()

    for _ in range(25):
        canvas._draw_batch_mark_overlay(painter)

    assert shape.bounding_rect() == original
    assert painter.rects
    assert all(rect == painter.rects[0] for rect in painter.rects)


# ------------------------------------------------------------ widget


def test_toggle_and_image_switch_recovers_marks(tmp_path):
    """Marks survive image switches and only reappear on their image."""
    widget = _widget(tmp_path)
    shape = _rect_shape()
    label_widget_module.LabelingWidget.toggle_marked_object(widget, shape)
    assert widget.marked_object_store.counts() == {
        "objects": 1,
        "files": 1,
    }
    assert widget.canvas.marked_ids == [shape.xanylabeling_shape_id]

    other = _widget(tmp_path, filename="b.png")
    other.marked_object_store = widget.marked_object_store
    other.canvas = widget.canvas
    label_widget_module.LabelingWidget._sync_marked_object_ui(other)
    assert widget.canvas.marked_ids == []

    label_widget_module.LabelingWidget._sync_marked_object_ui(widget)
    assert widget.canvas.marked_ids == [shape.xanylabeling_shape_id]


def test_delete_selected_removes_marks_of_deleted_shapes(tmp_path):
    """Deleting a shape removes exactly its mark."""
    widget = _widget(tmp_path)
    kept = _rect_shape()
    deleted = _rect_shape()
    for shape in (kept, deleted):
        label_widget_module.LabelingWidget.toggle_marked_object(widget, shape)
    label_widget_module.LabelingWidget._remove_marks_for_shapes(
        widget, [deleted]
    )
    store = widget.marked_object_store
    assert store.contains(
        (
            widget._marked_project_id(),
            osp.abspath(widget.filename),
            kept.xanylabeling_shape_id,
        )
    )
    assert not store.contains(
        (
            widget._marked_project_id(),
            osp.abspath(widget.filename),
            deleted.xanylabeling_shape_id,
        )
    )


def test_empty_marks_entry_shows_hint_without_starting_flow(
    tmp_path, monkeypatch
):
    """The main entry with no marks informs instead of writing."""
    widget = _widget(tmp_path)
    shown = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda *args, **kwargs: shown.append(args),
    )
    started = []
    monkeypatch.setattr(
        label_widget_module,
        "run_object_relabel_flow",
        lambda *args, **kwargs: started.append(args),
    )
    label_widget_module.LabelingWidget.relabel_marked_objects(widget)
    assert shown and not started


def test_cancelled_target_label_keeps_marks_and_skips_transaction(
    tmp_path, monkeypatch
):
    """Cancelling label selection creates no transaction and keeps marks."""
    widget = _widget(tmp_path)
    label_widget_module.LabelingWidget.toggle_marked_object(
        widget, _rect_shape()
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getItem",
        staticmethod(lambda *args, **kwargs: ("", False)),
    )
    started = []
    monkeypatch.setattr(
        label_widget_module,
        "run_object_relabel_flow",
        lambda *args, **kwargs: started.append(args),
    )
    label_widget_module.LabelingWidget.relabel_marked_objects(widget)
    assert not started
    assert widget.marked_object_store.counts()["objects"] == 1
    assert not (tmp_path / "transactions").exists()


def test_dirty_cancel_aborts_before_label_selection(tmp_path, monkeypatch):
    """A cancelled dirty prompt aborts with no dialog or transaction."""
    widget = _widget(tmp_path)
    label_widget_module.LabelingWidget.toggle_marked_object(
        widget, _rect_shape()
    )
    widget.dataset_review_resolve_dirty = lambda: "cancel"
    asked = []
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getItem",
        staticmethod(
            lambda *args, **kwargs: asked.append(args) or ("", False)
        ),
    )
    started = []
    monkeypatch.setattr(
        label_widget_module,
        "run_object_relabel_flow",
        lambda *args, **kwargs: started.append(args),
    )
    label_widget_module.LabelingWidget.relabel_marked_objects(widget)
    assert not asked and not started
    assert widget.marked_object_store.counts()["objects"] == 1


def test_dirty_save_failure_aborts_with_error_and_keeps_marks(
    tmp_path, monkeypatch
):
    """A failed save aborts relabeling and keeps every mark."""
    widget = _widget(tmp_path)
    label_widget_module.LabelingWidget.toggle_marked_object(
        widget, _rect_shape()
    )
    widget.dataset_review_resolve_dirty = lambda: "save_failed"
    errors = []
    widget.error_message = lambda *args, **kwargs: errors.append(args)
    started = []
    monkeypatch.setattr(
        label_widget_module,
        "run_object_relabel_flow",
        lambda *args, **kwargs: started.append(args),
    )
    label_widget_module.LabelingWidget.relabel_marked_objects(widget)
    assert errors and not started
    assert widget.marked_object_store.counts()["objects"] == 1


def test_apply_result_partial_failure_keeps_marks_without_reload(tmp_path):
    """Failed objects keep marks; uncommitted current file is not reloaded."""
    widget = _widget(tmp_path)
    shape = _rect_shape()
    label_widget_module.LabelingWidget.toggle_marked_object(widget, shape)
    reloads = []
    widget.load_file = lambda *args, **kwargs: reloads.append(args)
    project_id = widget._marked_project_id()
    image_id = osp.abspath(widget.filename)
    result = ObjectRelabelResult(
        transaction_id="t",
        phase="committed",
        cancelled=False,
        manifest_path=None,
        objects=(
            ObjectMutationResult(
                key=(project_id, image_id, shape.xanylabeling_shape_id),
                status=STATUS_FAILED,
            ),
        ),
        files=(),
    )
    label_widget_module.LabelingWidget._apply_object_relabel_result(
        widget, result
    )
    assert not reloads
    assert widget.marked_object_store.counts()["objects"] == 1


def test_apply_result_reloads_only_when_current_file_committed(tmp_path):
    """A committed current file is reloaded from disk."""
    widget = _widget(tmp_path)
    shape = _rect_shape()
    label_widget_module.LabelingWidget.toggle_marked_object(widget, shape)
    reloads = []
    widget.load_file = lambda *args, **kwargs: reloads.append(args)
    project_id = widget._marked_project_id()
    image_id = osp.abspath(widget.filename)
    annotation = osp.abspath(
        label_widget_module.LabelingWidget._annotation_path_for_image(
            widget, image_id
        )
    )
    result = ObjectRelabelResult(
        transaction_id="t",
        phase="committed",
        cancelled=False,
        manifest_path=None,
        objects=(
            ObjectMutationResult(
                key=(project_id, image_id, shape.xanylabeling_shape_id),
                status=STATUS_SUCCEEDED,
            ),
        ),
        files=(
            SimpleNamespace(source_path=annotation, status=STATUS_SUCCEEDED),
        ),
    )
    label_widget_module.LabelingWidget._apply_object_relabel_result(
        widget, result
    )
    assert reloads
    assert widget.marked_object_store.counts()["objects"] == 0
    widget._sync_marked_object_ui()
    assert widget.canvas.marked_ids == []


def test_worker_abort_before_commit_returns_cancelled_and_keeps_marks(
    tmp_path, qapp
):
    """Aborting before confirmation yields a cancelled result per object."""
    from anylabeling.views.labeling.widgets.object_relabel import (
        ObjectRelabelEngine,
        build_object_relabel_plan,
    )
    from anylabeling.views.labeling.widgets.object_relabel_dialog import (
        ObjectRelabelThread,
    )

    source = tmp_path / "a.json"
    source.write_text(
        '{"shapes": [{"xanylabeling_shape_id": "sid-1", '
        '"label": "person", "points": [[1, 2]]}]}',
        encoding="utf-8",
    )
    from anylabeling.views.labeling.widgets.object_relabel import (
        MarkedObjectRef,
    )

    plan = build_object_relabel_plan(
        [MarkedObjectRef("proj", str(tmp_path / "a.png"), "sid-1")],
        "proj",
        "face",
        str(tmp_path),
        lambda image_id: str(source),
    )
    engine = ObjectRelabelEngine(str(tmp_path / "transactions"))
    thread = ObjectRelabelThread(engine, plan, str(tmp_path))
    results = []
    thread.finished_result.connect(results.append)
    thread.request_abort()
    thread.run()
    assert results and results[0].cancelled
    assert results[0].counts[STATUS_CANCELLED] == 1
    store = MarkedObjectStore()
    store.toggle(MarkedObjectRef("proj", str(tmp_path / "a.png"), "sid-1"))
    store.apply_relabel_result(results[0])
    assert store.counts()["objects"] == 1
    assert source.read_text(encoding="utf-8").find('"person"') >= 0


def test_worker_error_emits_failed_callback_message(tmp_path, qapp):
    """A worker exception surfaces through the failed signal, not recursion."""

    class _BrokenEngine:
        """Engine whose preflight always raises."""

        def preflight(self, *args, **kwargs):
            """Raise a representative domain error."""
            raise RuntimeError("boom")

    from anylabeling.views.labeling.widgets.object_relabel import (
        MarkedObjectRef,
    )
    from anylabeling.views.labeling.widgets.object_relabel_dialog import (
        ObjectRelabelThread,
    )

    plan = SimpleNamespace()
    thread = ObjectRelabelThread(_BrokenEngine(), plan, str(tmp_path))
    errors = []
    thread.failed.connect(errors.append)
    thread.run()
    assert errors == ["RuntimeError: boom"]


def test_relabel_flow_closes_progress_and_reports_result_once(
    tmp_path, qapp, monkeypatch
):
    """A terminal result closes progress and remains idempotent."""
    from anylabeling.views.labeling.widgets import object_relabel_dialog

    class _FakeThread(QtCore.QObject):
        """Signal-compatible worker controlled directly by the test."""

        progress = QtCore.pyqtSignal(str, int, int, str)
        preflight_ready = QtCore.pyqtSignal(object)
        committing_started = QtCore.pyqtSignal()
        finished_result = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, _engine, _plan, _commit_root, parent=None):
            """Initialize the controllable worker."""
            super().__init__(parent)
            self.wait_calls = 0

        def start(self):
            """Leave execution under test control."""

        def wait(self):
            """Record terminal draining."""
            self.wait_calls += 1
            return True

        def confirm_commit(self):
            """Accept confirmation."""

        def request_abort(self):
            """Accept cancellation."""

    releases = []
    monkeypatch.setattr(
        object_relabel_dialog.BatchWriteGate,
        "try_acquire",
        lambda _root, _owner: True,
    )
    monkeypatch.setattr(
        object_relabel_dialog.BatchWriteGate,
        "release",
        lambda root, owner: releases.append((root, owner)),
    )
    monkeypatch.setattr(
        object_relabel_dialog,
        "ObjectRelabelEngine",
        lambda _root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        object_relabel_dialog,
        "ObjectRelabelThread",
        _FakeThread,
    )
    messages = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda *args, **kwargs: messages.append(args),
    )
    parent = QtWidgets.QWidget()
    finished = []
    result = ObjectRelabelResult(
        transaction_id="t",
        phase="committed",
        cancelled=False,
        manifest_path=None,
        objects=(),
        files=(),
    )

    assert object_relabel_dialog.run_object_relabel_flow(
        parent,
        SimpleNamespace(),
        str(tmp_path / "transactions"),
        str(tmp_path),
        finished.append,
        pytest.fail,
    )
    thread = parent._object_relabel_thread
    dialog = parent.findChild(QtWidgets.QProgressDialog)
    thread.progress.emit("preflight", 1, 3, "a.json")
    assert dialog.maximum() == 3
    assert dialog.value() == 1

    thread.finished_result.emit(result)
    assert not dialog.isVisible()
    assert parent._object_relabel_thread is None
    assert thread.wait_calls == 1
    assert finished == [result]
    assert len(messages) == 1
    assert len(releases) == 1

    thread.finished_result.emit(result)
    assert finished == [result]
    assert len(messages) == 1
    assert len(releases) == 1


# ------------------------------------------------ audit-fix regressions


def test_apply_result_refreshes_index_only_for_committed_files(tmp_path):
    """label_saved fires once per committed image and never for skips."""
    widget = _widget(tmp_path)
    shape = _rect_shape()
    label_widget_module.LabelingWidget.toggle_marked_object(widget, shape)
    project_id = widget._marked_project_id()
    image_id = osp.abspath(widget.filename)
    other_image = osp.abspath(str(tmp_path / "b.png"))
    annotation = osp.abspath(
        label_widget_module.LabelingWidget._annotation_path_for_image(
            widget, image_id
        )
    )
    other_annotation = osp.abspath(
        label_widget_module.LabelingWidget._annotation_path_for_image(
            widget, other_image
        )
    )
    result = ObjectRelabelResult(
        transaction_id="t",
        phase="committed",
        cancelled=False,
        manifest_path=None,
        objects=(
            ObjectMutationResult(
                key=(project_id, image_id, shape.xanylabeling_shape_id),
                status=STATUS_SUCCEEDED,
            ),
            ObjectMutationResult(
                key=(project_id, other_image, "sid-x"),
                status=STATUS_FAILED,
            ),
        ),
        files=(
            SimpleNamespace(source_path=annotation, status=STATUS_SUCCEEDED),
            SimpleNamespace(source_path=other_annotation, status="failed"),
        ),
    )
    label_widget_module.LabelingWidget._apply_object_relabel_result(
        widget, result
    )
    assert widget.index_refreshes == [image_id]


def test_union_selection_cleans_marks_of_merged_shapes():
    """The union merge path removes marks of the shapes it deletes."""
    import inspect

    source = inspect.getsource(
        label_widget_module.LabelingWidget.union_selection
    )
    assert "_remove_marks_for_shapes" in source
    assert source.index("_remove_marks_for_shapes") < source.index(
        "remove_labels("
    )


def test_entry_recovers_when_flow_refuses_to_start(tmp_path, monkeypatch):
    """A refused flow start restores the entry action immediately."""
    widget = _widget(tmp_path)
    label_widget_module.LabelingWidget.toggle_marked_object(
        widget, _rect_shape()
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getItem",
        staticmethod(lambda *args, **kwargs: ("face", True)),
    )
    monkeypatch.setattr(
        label_widget_module,
        "run_object_relabel_flow",
        lambda *args, **kwargs: False,
    )
    label_widget_module.LabelingWidget.relabel_marked_objects(widget)
    assert widget._object_relabel_running is False
    assert widget.object_mark_actions.enabled[-1] is True


def test_entry_uses_project_scoped_counts(tmp_path, monkeypatch):
    """Foreign-project marks stay out of the entry counts and snapshot."""
    widget = _widget(tmp_path)
    label_widget_module.LabelingWidget.toggle_marked_object(
        widget, _rect_shape()
    )
    widget.marked_object_store.toggle(
        MarkedObjectRef(
            project_id="foreign",
            image_id=str(tmp_path / "f.png"),
            shape_id="sid-f",
        )
    )
    captured = {}
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getItem",
        staticmethod(
            lambda parent, title, label, *a, **k: captured.update(prompt=label)
            or ("", False)
        ),
    )
    started = []
    monkeypatch.setattr(
        label_widget_module,
        "run_object_relabel_flow",
        lambda *args, **kwargs: started.append(args) or True,
    )
    label_widget_module.LabelingWidget.relabel_marked_objects(widget)
    assert "1 marked object(s) in 1 file(s)" in captured["prompt"]
    assert not started


def test_preflight_confirmation_warns_about_immediate_non_undoable_write():
    """Confirmation states the immediate-write and normal-undo boundary."""
    summary = SimpleNamespace(
        target_label="face",
        snapshot_objects=2,
        candidate_files=1,
        changeable=2,
        unchanged=0,
        deleted=0,
        conflict=0,
        failed=0,
    )

    message = _preflight_message(summary).lower()

    assert "immediately" in message
    assert "normal undo stack" in message


def test_restore_entry_and_close_guard_are_wired():
    """The manifest restore action and close-time abort exist."""
    import inspect

    assert hasattr(
        label_widget_module.LabelingWidget,
        "restore_object_relabel_from_manifest",
    )
    init_source = inspect.getsource(
        label_widget_module.LabelingWidget.__init__
    )
    assert "restore_object_relabel_from_manifest" in init_source
    close_source = inspect.getsource(
        label_widget_module.LabelingWidget.closeEvent
    )
    assert "_object_relabel_thread" in close_source
    assert "request_abort" in close_source
    assert "if not relabel_thread.wait(2000)" in close_source
    restore_source = inspect.getsource(
        label_widget_module.LabelingWidget.restore_object_relabel_manifest
    )
    assert "dataset_review_resolve_dirty" in restore_source
    assert "BatchWriteGate" in restore_source
    assert "label_saved" in restore_source


def test_restore_picker_accepts_json_from_batch_root(tmp_path, monkeypatch):
    """Recovery picker starts at the batch root and accepts JSON manifests."""
    widget = _widget(tmp_path)
    picked = tmp_path / "transaction-id" / "manifest.json"
    captured = {}
    restored = []
    widget.restore_object_relabel_manifest = restored.append
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        staticmethod(
            lambda *args: captured.update(
                parent=args[0], directory=args[2], file_filter=args[3]
            )
            or (str(picked), "JSON")
        ),
    )

    label_widget_module.LabelingWidget.restore_object_relabel_from_manifest(
        widget
    )

    assert captured["directory"] == osp.abspath(str(tmp_path))
    assert "*.json" in captured["file_filter"]
    assert restored == [str(picked)]


def test_dataset_root_uses_import_root_for_nested_images(tmp_path):
    """Nested image folders share the imported dataset root."""
    root = tmp_path / "dataset"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    widget = SimpleNamespace(
        last_open_dir=str(root),
        image_list=[str(root / "a" / "one.png"), str(root / "b" / "two.png")],
        filename=str(root / "a" / "one.png"),
    )
    assert label_widget_module.LabelingWidget.dataset_review_dataset_root(
        widget
    ) == osp.abspath(str(root))


def test_prune_missing_marked_objects_cleans_shape_manager_deletions(tmp_path):
    """Shape-manager deletions remove only missing persisted identities."""
    widget = _widget(tmp_path)
    existing = _rect_shape()
    missing = _rect_shape()
    widget.marked_object_store.toggle(
        MarkedObjectRef(
            widget._marked_project_id(),
            str(tmp_path / "a.png"),
            existing.xanylabeling_shape_id,
        )
    )
    widget.marked_object_store.toggle(
        MarkedObjectRef(
            widget._marked_project_id(),
            str(tmp_path / "b.png"),
            missing.xanylabeling_shape_id,
        )
    )
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "shapes": [
                    {"xanylabeling_shape_id": existing.xanylabeling_shape_id}
                ]
            }
        ),
        encoding="utf-8",
    )
    label_widget_module.LabelingWidget._prune_missing_marked_objects(widget)
    assert widget.marked_object_store.contains(
        (
            widget._marked_project_id(),
            str(tmp_path / "a.png"),
            existing.xanylabeling_shape_id,
        )
    )
    assert not widget.marked_object_store.contains(
        (
            widget._marked_project_id(),
            str(tmp_path / "b.png"),
            missing.xanylabeling_shape_id,
        )
    )


def test_thumbnail_navigation_honors_dirty_guard_and_selects_permanent_id(
    tmp_path,
):
    """Thumbnail activation saves/discards first, then loads and centers by ID."""
    current = tmp_path / "current.png"
    target = tmp_path / "target.png"
    current.write_bytes(b"current")
    target.write_bytes(b"target")
    shape = SimpleNamespace(xanylabeling_shape_id="shape-id")
    selected = []
    centered = []
    statuses = []
    widget = SimpleNamespace(
        filename=str(current),
        canvas=SimpleNamespace(
            shapes=[shape],
            select_shapes=lambda shapes, source=None: selected.append(
                (list(shapes), source)
            ),
        ),
        _thumbnail_navigation_active=False,
        may_continue=lambda: True,
        status=lambda *args: statuses.append(args),
        tr=lambda text: text,
        _center_on_shape=centered.append,
    )
    widget.load_file = lambda filename: setattr(widget, "filename", filename)
    ref = DatasetThumbnailRef(
        str(target),
        str(tmp_path / "target.json"),
        0,
        0,
        "shape-id",
        "person",
        (0.0, 0.0, 1.0, 1.0),
    )

    label_widget_module.LabelingWidget._navigate_from_thumbnail(widget, ref)

    assert osp.normcase(widget.filename) == osp.normcase(str(target))
    assert selected == [([shape], "inspector")]
    assert centered == [shape]
    assert not widget._thumbnail_navigation_active

    selected.clear()
    centered.clear()
    label_widget_module.LabelingWidget._navigate_from_thumbnail(widget, ref)
    assert selected == [([shape], "inspector")]
    assert centered == [shape]

    widget.filename = str(current)
    widget.may_continue = lambda: False
    selected.clear()
    label_widget_module.LabelingWidget._navigate_from_thumbnail(widget, ref)
    assert widget.filename == str(current)
    assert selected == []

    widget.filename = str(target)
    widget.may_continue = lambda: True
    widget.canvas.shapes = []
    label_widget_module.LabelingWidget._navigate_from_thumbnail(widget, ref)
    assert statuses and "shape-id" in statuses[-1][0]


def test_main_selection_reveals_thumbnail_without_navigation_feedback():
    """A single canvas selection focuses the browser without loading a file."""
    focused = []
    window = SimpleNamespace(
        isVisible=lambda: True,
        focus_object=lambda image, shape_id: (
            focused.append((image, shape_id)),
            True,
        )[1],
    )
    shape = SimpleNamespace(xanylabeling_shape_id="shape-id")
    widget = SimpleNamespace(
        _dataset_thumbnail_window=window,
        _thumbnail_navigation_active=False,
        _thumbnail_last_synced_identity=None,
        filename="image.png",
    )

    label_widget_module.LabelingWidget._sync_dataset_thumbnail_selection(
        widget, [shape]
    )
    assert focused == [("image.png", "shape-id")]

    label_widget_module.LabelingWidget._sync_dataset_thumbnail_selection(
        widget, [shape]
    )
    assert len(focused) == 1

    widget._thumbnail_navigation_active = True
    label_widget_module.LabelingWidget._sync_dataset_thumbnail_selection(
        widget, [shape]
    )
    assert len(focused) == 1

    widget._thumbnail_navigation_active = False
    widget._virtual_review_active = True
    widget._thumbnail_last_synced_identity = None
    label_widget_module.LabelingWidget._sync_dataset_thumbnail_selection(
        widget, [shape]
    )
    assert len(focused) == 1


def test_thumbnail_digit_mapping_and_dataset_lifecycle_are_wired():
    """The browser reuses rename bindings and closes at all dataset exits."""
    import inspect

    window = SimpleNamespace(close_calls=0)
    window.close = lambda: setattr(
        window, "close_calls", window.close_calls + 1
    )
    widget = SimpleNamespace(
        _dataset_thumbnail_window=window,
        _dataset_thumbnail_auto_refresh_paused=True,
        _dataset_index_controller=SimpleNamespace(
            resume_pending_auto_refresh=lambda lease: resumed.append(lease)
        ),
        _thumbnail_last_synced_identity=("image.png", "shape-id"),
        digit_rename_manager=SimpleNamespace(
            rename_shortcuts={3: {"label": "vehicle"}}
        ),
    )
    resumed = []

    assert (
        label_widget_module.LabelingWidget._thumbnail_digit_label(widget, 3)
        == "vehicle"
    )
    assert (
        label_widget_module.LabelingWidget._thumbnail_digit_label(widget, 4)
        is None
    )
    label_widget_module.LabelingWidget._close_dataset_thumbnail_window(widget)
    assert window.close_calls == 1
    assert widget._dataset_thumbnail_window is None
    label_widget_module.LabelingWidget._on_dataset_thumbnail_closed(widget)
    assert resumed == [True]
    assert not widget._dataset_thumbnail_auto_refresh_paused

    for method in (
        label_widget_module.LabelingWidget.import_image_folder,
        label_widget_module.LabelingWidget.close_file,
        label_widget_module.LabelingWidget.closeEvent,
    ):
        assert "_close_dataset_thumbnail_window" in inspect.getsource(method)
    selection_source = inspect.getsource(
        label_widget_module.LabelingWidget.shape_selection_changed
    )
    assert "_sync_dataset_thumbnail_selection" in selection_source
    open_source = inspect.getsource(
        label_widget_module.LabelingWidget.open_dataset_label_thumbnails
    )
    assert "pause_pending_auto_refresh()" in open_source

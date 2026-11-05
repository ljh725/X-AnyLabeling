"""Execution evidence for the 2026-11-04 review (DR-01..DR-09).

These GUI tests cover cross-batch navigation, direct cold/warm batch
switches, card virtualization and bounded resources, collapsible auxiliary
panels, asynchronous side-by-side comparison, spatial cursor restoration and
the major operations that must keep working after the workspace closes.
"""

import copy
import json
import os
import time
import uuid
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.dense_review.config import save_config
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow

from .conftest import make_config


def _rectangle(label, shape_id, x, y, width=60, height=80):
    return {
        "label": label,
        "shape_type": "rectangle",
        "points": [
            [x, y],
            [x + width, y],
            [x + width, y + height],
            [x, y + height],
        ],
        "xanylabeling_shape_id": shape_id,
    }


def _polygon(label, shape_id, points):
    return {
        "label": label,
        "shape_type": "polygon",
        "points": points,
        "xanylabeling_shape_id": shape_id,
    }


def _grid_shapes(count, labels=("A", "B")):
    shapes = []
    for index in range(count):
        column = index % 5
        row = index // 5
        shapes.append(
            _rectangle(
                labels[index % len(labels)],
                f"id{index}",
                20 + column * 110,
                20 + row * 70,
                80,
                50,
            )
        )
    return shapes


def _wait_until(app, predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _png_bytes(color="#cc3333"):
    image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor(color))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class _FakeFuture:
    def __init__(self):
        self._callbacks = []
        self._result = None
        self._exception = None

    def add_done_callback(self, callback):
        self._callbacks.append(callback)

    def result(self):
        if self._exception is not None:
            raise self._exception
        return self._result

    def finish(self, result):
        self._result = result
        for callback in list(self._callbacks):
            callback(self)

    def fail(self, error):
        self._exception = error
        for callback in list(self._callbacks):
            callback(self)


class _FakeExecutor:
    def __init__(self):
        self.requests = []
        self.futures = []

    def submit(self, _function, request):
        self.requests.append(request)
        future = _FakeFuture()
        self.futures.append(future)
        return future

    def shutdown(self, wait=False, cancel_futures=False):
        pass


@pytest.fixture
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        []
    )
    application.setQuitOnLastWindowClosed(False)
    return application


@pytest.fixture
def open_window(app, tmp_path, monkeypatch):
    windows = []

    def _open(shapes, batches=None, rules=(), auto_save=False):
        monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
        config_file = tmp_path / "config.yaml"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            app_config, "current_config_file", str(config_file)
        )
        image_path = tmp_path / "image.png"
        Image.new("RGB", (640, 480), color=(210, 210, 210)).save(image_path)
        annotation = {
            "version": "4.2.1",
            "imageWidth": 640,
            "imageHeight": 480,
            "imagePath": "image.png",
            "imageData": None,
            "shapes": shapes,
        }
        (tmp_path / "image.json").write_text(
            json.dumps(annotation), encoding="utf-8"
        )
        if batches is not None:
            save_config(
                str(tmp_path),
                make_config(batches=batches, rules=rules),
            )
        config = copy.deepcopy(load_template_config())
        config.update(auto_save=auto_save)
        session_target = os.path.abspath(
            os.path.join(
                ".tmp",
                f"dense-evidence-{os.getpid()}-{uuid.uuid4().hex}.yaml",
            )
        )
        user_config.begin_session(
            target_path=session_target,
            origin="file",
            template=copy.deepcopy(config),
            effective=copy.deepcopy(config),
            ensure_created=True,
            normalizer=normalize_user_config,
        )
        window = MainWindow(app, config=config)
        window.resize(1500, 960)
        window.show()
        app.processEvents()
        widget = window.labeling_widget.view
        assert widget.load_file(str(image_path))
        widget.open_dense_review()
        app.processEvents()
        windows.append(window)
        return window

    yield _open

    for window in windows:
        widget = window.labeling_widget.view
        workspace = getattr(widget, "dense_review_workspace", None)
        if workspace is not None:
            workspace.close()
            workspace.shutdown()
        widget.dirty = False
        window.close()
        app.removeEventFilter(widget)
        window.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _label_rules(labels):
    return tuple((label, "visible", "") for label in labels)


@pytest.mark.parametrize("navigation", ["batch", "object", "skip"])
def test_cross_batch_completion_keeps_views_in_sync(
    app, open_window, navigation
):
    window = open_window(
        [
            _rectangle("A", "id1", 20, 20),
            _rectangle("A", "id2", 120, 20),
            _rectangle("B", "id3", 220, 20),
            _rectangle("B", "id4", 320, 20),
            _rectangle("C", "id5", 20, 160),
            _rectangle("C", "id6", 120, 160),
        ],
        batches=(("A/B", ("A", "B")), ("C", ("C",))),
        rules=_label_rules("ABC"),
    )
    app.processEvents()
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    assert len(session.state.batches) == 2
    first_batch, second_batch = (
        batch.batch_id for batch in session.state.batches
    )
    assert session.state.current_batch == first_batch

    if navigation == "batch":
        workspace._complete_batch()
    else:
        workspace.per_object_checkbox.setChecked(True)
        for _ in session.state.member_ids(first_batch):
            if navigation == "object":
                workspace._complete_current_object()
            else:
                workspace._skip_current()
    app.processEvents()
    target = second_batch
    assert session.state.current_batch == target
    assert session.state.current_object
    current_item = workspace.batch_list.currentItem()
    assert current_item is not None
    assert current_item.data(QtCore.Qt.ItemDataRole.UserRole) == target
    assert workspace._current_batch_id() == target
    assert list(workspace._card_model.shape_ids()) == list(
        session.state.member_ids(target)
    )
    assert session.state.current_object in workspace._selected_shape_ids()
    scope = workspace._scope()
    assert scope is not None and scope.batch_id == target
    assert workspace.complete_batch_button.text().startswith(
        "完成本批并进入下一批"
    )
    assert session.object("id1").confirmed_both() == (navigation != "skip")
    assert not session.object("id5").confirmed("category")
    selected = widget.canvas.selected_shapes
    assert selected
    assert selected[0].xanylabeling_shape_id == session.state.current_object


def test_direct_batch_click_schedules_visible_thumbnails(app, open_window):
    window = open_window(
        [
            _rectangle("A", "id1", 20, 20),
            _rectangle("A", "id2", 120, 20),
            _rectangle("B", "id3", 220, 20),
            _rectangle("B", "id4", 320, 20),
        ],
        batches=(("A", ("A",)), ("B", ("B",))),
        rules=_label_rules("AB"),
    )
    app.processEvents()
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    provider = workspace.thumbnails
    provider._cache.clear()
    workspace._card_request_keys.clear()
    requested = []
    original_request = provider.request

    def _spy(*args, **kwargs):
        requested.append(args[0])
        return original_request(*args, **kwargs)

    with patch.object(provider, "request", side_effect=_spy):
        workspace.batch_list.setCurrentRow(1)
        app.processEvents()
        assert _wait_until(
            app, lambda: bool(requested), timeout=3.0
        ), "a direct batch click must schedule current card thumbnails"
    assert session.state.current_batch == session.state.batches[1].batch_id
    assert set(requested) <= set(
        session.state.member_ids(session.state.batches[1].batch_id)
    )
    assert set(requested)


def test_card_view_virtualizes_and_bounds_resources(app, open_window):
    window = open_window(
        _grid_shapes(60),
        batches=(("A/B", ("A", "B")),),
        rules=_label_rules("AB"),
    )
    app.processEvents()
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    provider = workspace.thumbnails
    model = workspace._card_model
    assert model.rowCount() == 60
    assert model.icon_count() <= 48

    provider._cache.clear()
    provider._pending.clear()
    workspace._card_request_keys.clear()
    calls = []
    original_request = provider.request

    def _spy(*args, **kwargs):
        calls.append(args[0])
        return original_request(*args, **kwargs)

    with patch.object(provider, "request", side_effect=_spy):
        workspace._request_visible_thumbnails()
        app.processEvents()
    assert calls
    assert len(calls) <= 35, "requests must be limited to visible/prefetch"
    last_id = model.shape_ids()[-1]
    assert model.icon_for(last_id) is None
    assert last_id not in workspace._failed_ids

    workspace.card_list.scrollToBottom()
    app.processEvents()
    workspace._request_visible_thumbnails()
    assert _wait_until(
        app,
        lambda: model.icon_for(last_id) is not None
        or last_id in workspace._failed_ids,
    )
    assert model.icon_count() <= 48
    stats = workspace.card_resource_stats()
    assert set(stats) == {
        "rows",
        "icons",
        "provider_cache",
        "pending_requests",
        "queued_results",
        "compare_dialogs",
    }
    assert stats["rows"] == 60
    assert stats["icons"] <= 48

    # A text-only state change must not re-crop source pixels.
    calls.clear()
    with patch.object(provider, "request", side_effect=_spy):
        session = widget.dense_review_session
        session.mark_skipped(session.state.current_object)
        workspace.refresh_all()
        app.processEvents()
    assert calls == []
    assert "暂跳" in model.data(
        model.index(model.row_for(session.state.current_object), 0),
        QtCore.Qt.ItemDataRole.DisplayRole,
    )


def test_small_window_can_collapse_each_auxiliary_panel(app, open_window):
    window = open_window(
        [
            _rectangle("A", "id1", 20, 20),
            _rectangle("B", "id2", 120, 20),
        ],
        batches=(("A/B", ("A", "B")),),
        rules=_label_rules("AB"),
    )
    app.processEvents()
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    workspace.resize(720, 600)
    app.processEvents()
    current = session.state.current_object
    dirty = widget.dirty
    hidden_before = set(widget._manually_hidden_shapes)
    assert workspace.object_splitter.childrenCollapsible() is True

    workspace.set_batches_visible(False)
    app.processEvents()
    assert workspace.batches_panel.isVisible() is False
    assert workspace.compact_batch_combo.isVisible() is True
    assert workspace.summary_label.isVisible() is True
    assert workspace.complete_batch_button.isVisible() is True
    assert workspace.batches_toggle_button.text() == "显示类别批次栏"
    assert session.state.current_object == current
    assert widget.dirty == dirty
    assert set(widget._manually_hidden_shapes) == hidden_before

    workspace.set_batches_visible(True)
    workspace.set_cards_visible(False)
    app.processEvents()
    assert workspace.cards_panel.isVisible() is False
    assert workspace.complete_batch_button.isVisible() is True
    assert workspace.summary_label.isVisible() is True
    assert workspace.cards_toggle_button.text() == "显示对象卡片栏"
    assert session.state.current_object == current
    assert widget.dirty == dirty

    workspace.set_cards_visible(True)
    app.processEvents()
    assert workspace.cards_panel.isVisible() is True
    assert workspace.card_list.isVisible() is True
    assert session.state.current_object == current


def test_compare_cold_cache_requests_updates_and_failures(app, open_window):
    window = open_window(
        [
            _rectangle("A", "id1", 20, 20),
            _rectangle("B", "id2", 120, 20),
        ]
    )
    app.processEvents()
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    provider = workspace.thumbnails
    provider._executor.shutdown(wait=False, cancel_futures=True)
    executor = _FakeExecutor()
    provider._executor = executor
    provider.start_generation(provider.generation + 1)
    provider._drain()
    workspace._failed_ids.clear()
    workspace._card_request_keys.clear()
    workspace._compare_request_keys.clear()

    dialog = workspace._open_compare(["id1", "id2"])
    app.processEvents()
    assert [request.shape_id for request in executor.requests] == [
        "id1",
        "id2",
    ]
    assert dialog._image_labels["id1"].text() == "图块准备中…"

    first = executor.requests[0]
    executor.futures[0].finish(
        (first.shape_id, first.generation, _png_bytes())
    )
    provider._drain()
    app.processEvents()
    assert dialog._image_labels["id1"].pixmap() is not None

    executor.futures[1].fail(RuntimeError("crop failed"))
    provider._drain()
    app.processEvents()
    assert "crop failed" in dialog._status_labels["id2"].text()

    workspace.retry_compare("id2", dialog)
    app.processEvents()
    assert len(executor.requests) == 3
    retried = executor.requests[2]
    executor.futures[2].finish(
        (retried.shape_id, retried.generation, _png_bytes("#3333cc"))
    )
    provider._drain()
    app.processEvents()
    assert dialog._image_labels["id2"].pixmap() is not None

    dialog.close()
    app.processEvents()
    assert dialog not in workspace._compare_dialogs
    image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB32)
    workspace._on_thumbnail_ready("id1", image)
    assert dialog not in workspace._compare_dialogs


def test_spatial_region_state_restores_after_save_and_reopen(app, open_window):
    window = open_window(
        [
            _rectangle("A", "id1", 20, 20),
            _rectangle("B", "id2", 120, 20),
        ],
        batches=(("A/B", ("A", "B")),),
        rules=_label_rules("AB"),
    )
    app.processEvents()
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    workspace.tabs.setCurrentIndex(1)
    app.processEvents()
    plan = session.state.coverage
    assert plan is not None

    workspace._complete_current_region()
    app.processEvents()
    difficult_id = session.state.coverage.current_region
    workspace._set_current_region_state("difficult", True)
    app.processEvents()
    workspace._complete_current_region()
    app.processEvents()
    skipped_id = session.state.coverage.current_region
    workspace._set_current_region_state("skipped", True)
    app.processEvents()
    saved_cursor = session.state.coverage.current_region
    completed_before = {
        region.region_id
        for region in session.state.coverage.regions
        if region.completed
    }
    assert completed_before

    assert widget._save_file(widget.get_label_file()) is True
    assert widget.dirty is False
    workspace.close()
    app.processEvents()
    assert widget.load_file(widget.filename)
    app.processEvents()
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    restored = widget.dense_review_session
    workspace.tabs.setCurrentIndex(1)
    app.processEvents()
    coverage = restored.state.coverage
    assert coverage is not None
    assert coverage.current_region == saved_cursor
    assert coverage.region(difficult_id).difficult is True
    assert coverage.region(skipped_id).skipped is True
    assert {
        region.region_id for region in coverage.regions if region.completed
    } == completed_before
    current_item = workspace.region_list.currentItem()
    assert current_item is not None
    assert current_item.data(QtCore.Qt.ItemDataRole.UserRole) == saved_cursor
    region = coverage.region(saved_cursor)
    assert widget.canvas.dense_review_region == region.rect
    assert widget.canvas.dense_review_region_label
    assert widget.zoom_widget.value() > 0


def test_workspace_closed_keeps_editing_navigation_and_save(app, open_window):
    window = open_window(
        [
            _rectangle("A", "id1", 20, 20),
            _rectangle("B", "id2", 120, 20),
            _rectangle("A", "id3", 220, 20),
            _polygon(
                "B",
                "id4",
                [[20, 200], [110, 200], [110, 290], [20, 290]],
            ),
        ],
        batches=(("A/B", ("A", "B")),),
        rules=_label_rules("AB"),
    )
    app.processEvents()
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    workspace.close()
    app.processEvents()
    assert widget.canvas.hide_backround is False
    shapes = {
        shape.xanylabeling_shape_id: shape for shape in widget.canvas.shapes
    }
    assert widget.actions.digit_shortcut_1.isEnabled()

    widget.drawing_digit_shortcuts = {1: {"label": "C", "mode": "rectangle"}}
    widget.canvas.select_shapes([shapes["id1"]])
    app.processEvents()
    widget.actions.digit_shortcut_1.trigger()
    app.processEvents()
    assert shapes["id1"].label == "C"
    assert widget.dirty is True
    assert widget.actions.undo.isEnabled() is True

    before = shapes["id1"].bounding_rect()
    shapes["id1"].move_by(QtCore.QPointF(12, 8))
    widget.canvas.store_shapes()
    widget.canvas.shape_moved.emit()
    app.processEvents()
    assert shapes["id1"].bounding_rect() != before

    polygon = shapes["id4"]
    widget.canvas.prev_h_shape = polygon
    widget.canvas.prev_h_edge = 0
    edge_a = polygon.points[0]
    edge_b = polygon.points[1]
    widget.canvas.prev_move_point = QtCore.QPointF(
        (edge_a.x() + edge_b.x()) / 2.0,
        (edge_a.y() + edge_b.y()) / 2.0,
    )
    widget.canvas.add_point_to_edge()
    app.processEvents()
    assert len(polygon.points) > 4
    widget.canvas._pending_edge_point = None
    widget.canvas.moving_shape = False

    before_width = shapes["id3"].bounding_rect().width()
    widget.canvas._adjust_rectangle_edge(
        shapes["id3"],
        QtCore.QPointF(
            shapes["id3"].bounding_rect().right() + 6,
            shapes["id3"].bounding_rect().center().y(),
        ),
        True,
    )
    app.processEvents()
    assert shapes["id3"].bounding_rect().width() > before_width

    widget.canvas.select_shapes([shapes["id2"]])

    # Navigation with unsaved edits must exercise the real Cancel path,
    # rather than leave an unattended modal dialog in the test process.
    def cancel_navigation():
        for box in app.topLevelWidgets():
            if isinstance(box, QtWidgets.QMessageBox) and box.isVisible():
                button = box.button(
                    QtWidgets.QMessageBox.StandardButton.Cancel
                )
                if button is not None:
                    button.click()

    QtCore.QTimer.singleShot(0, cancel_navigation)
    widget.open_next_image()
    app.processEvents()
    assert widget.filename

    label_path = os.path.splitext(widget.image_path)[0] + ".json"
    assert widget._save_file(label_path) is True
    with open(label_path, encoding="utf-8") as handle:
        saved = json.load(handle)
    assert len(saved["shapes"]) == 4
    assert widget.dirty is False

    widget.undo_shape_edit()
    app.processEvents()
    assert widget.actions.redo.isEnabled() is True


@pytest.mark.parametrize("choice", ["cancel", "reload", "save"])
def test_external_conflict_from_save_entry(app, open_window, choice):
    window = open_window([_rectangle("A", "id1", 20, 20)])
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    workspace._complete_batch()
    session = widget.dense_review_session
    path = os.path.splitext(widget.image_path)[0] + ".json"
    with open(path, encoding="utf-8") as handle:
        external = json.load(handle)
    external["shapes"][0]["label"] = "EXTERNAL"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(external, handle)
    original_bytes = open(path, "rb").read()
    clicked = []
    roles = QtWidgets.QMessageBox.ButtonRole
    role = {
        "cancel": roles.RejectRole,
        "reload": roles.AcceptRole,
        "save": roles.DestructiveRole,
    }[choice]

    def choose():
        for box in app.topLevelWidgets():
            if isinstance(box, QtWidgets.QMessageBox) and box.isVisible():
                for button in box.buttons():
                    if box.buttonRole(button) == role:
                        clicked.append(button.text())
                        button.click()
                        return

    QtCore.QTimer.singleShot(0, choose)
    result = widget._save_file(path)
    assert clicked, "the actual save-conflict dialog must be handled"
    if choice == "save":
        assert result is True
        assert widget.dirty is False
        with open(path, encoding="utf-8") as handle:
            assert json.load(handle)["shapes"][0]["label"] == "A"
    else:
        assert result is False
        assert open(path, "rb").read() == original_bytes
        if choice == "cancel":
            assert widget.dirty is True
            assert widget.dense_review_session is session
            assert session.object("id1").confirmed_both()
        else:
            restored = widget.dense_review_session
            assert restored.object("id1").label == "EXTERNAL"
            assert not restored.object("id1").confirmed_both()


def test_autosave_writes_at_edit_and_confirmation_boundaries(
    app, open_window, monkeypatch
):
    from anylabeling.views.labeling.label_file import LabelFile

    window = open_window([_rectangle("A", "id1", 20, 20)], auto_save=True)
    widget = window.labeling_widget.view
    workspace = widget.dense_review_workspace
    canvas = widget.canvas
    saved = []
    original = LabelFile.save

    def record_save(self, *args, **kwargs):
        saved.append(args[0] if args else kwargs.get("filename"))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(LabelFile, "save", record_save)
    workspace.refresh_all()
    app.processEvents()
    assert not saved, "read-only refresh must not save"
    shape = canvas.selected_shapes[0]
    point = shape.bounding_rect().center() + canvas.offset_to_center()
    point *= canvas.scale

    def mouse_event(kind, position, button, buttons):
        return QtGui.QMouseEvent(
            kind,
            position,
            position,
            button,
            buttons,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    left = QtCore.Qt.MouseButton.LeftButton
    none = QtCore.Qt.MouseButton.NoButton
    canvas.mousePressEvent(
        mouse_event(QtCore.QEvent.Type.MouseButtonPress, point, left, left)
    )
    before = shape.bounding_rect()
    for index in range(1, 6):
        position = point + QtCore.QPointF(index * 3, index * 3)
        canvas.mouseMoveEvent(
            mouse_event(QtCore.QEvent.Type.MouseMove, position, none, left)
        )
        app.processEvents()
        assert not saved, "drag frames must not write the annotation"
    canvas.mouseReleaseEvent(
        mouse_event(
            QtCore.QEvent.Type.MouseButtonRelease, position, left, none
        )
    )
    app.processEvents()
    assert shape.bounding_rect() != before
    assert len(saved) == 1
    assert widget.dirty is False
    workspace._complete_batch()
    app.processEvents()
    assert len(saved) == 2, "one batch action adds one autosave"
    assert widget.dirty is False


@pytest.mark.parametrize("inward", [False, True])
def test_closed_workspace_keeps_shift_fit_target_and_undo(
    app, open_window, inward
):
    window = open_window(
        [
            _rectangle("A", "id1", 100, 100, 100, 100),
            _rectangle("B", "id2", 100, 100, 100, 100),
        ]
    )
    widget = window.labeling_widget.view
    widget.dense_review_workspace.close()
    app.processEvents()
    canvas = widget.canvas
    target, neighbour = canvas.shapes
    before = target.bounding_rect()
    neighbour_before = neighbour.bounding_rect()
    canvas.select_shapes([target])
    point = (
        QtCore.QPointF(180, 120) + canvas.offset_to_center()
    ) * canvas.scale
    modifiers = QtCore.Qt.KeyboardModifier.ShiftModifier
    if inward:
        modifiers |= QtCore.Qt.KeyboardModifier.AltModifier
    none = QtCore.Qt.MouseButton.NoButton
    left = QtCore.Qt.MouseButton.LeftButton
    for kind, button, buttons in [
        (QtCore.QEvent.Type.MouseMove, none, none),
        (QtCore.QEvent.Type.MouseButtonPress, left, left),
        (QtCore.QEvent.Type.MouseButtonRelease, left, none),
    ]:
        event = QtGui.QMouseEvent(
            kind, point, point, button, buttons, modifiers
        )
        app.sendEvent(canvas, event)
        app.processEvents()
    fitted = target.bounding_rect()
    assert fitted != before
    assert neighbour.bounding_rect() == neighbour_before
    assert widget.dirty is True
    assert not widget.dense_review_session.object("id1").confirmed_both()
    widget.undo_shape_edit()
    assert canvas.shapes[0].bounding_rect() == before
    widget.actions.redo.trigger()
    assert canvas.shapes[0].bounding_rect() == fitted

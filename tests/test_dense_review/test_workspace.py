import copy
import json
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtTest import QTest

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.dense_review.config import save_config
from anylabeling.services.dense_review.session import DenseReviewSession
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow
from PIL import Image

from .conftest import make_config


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    config = copy.deepcopy(load_template_config())
    config.update(auto_save=False)
    # The shared fixture rejects configuration writes outside .tmp; use a
    # dedicated target there instead of the system temp_path.
    session_target = os.path.abspath(
        os.path.join(
            ".tmp", f"dense-review-config-{os.getpid()}-{id(tmp_path)}.yaml"
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
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    yield window
    view = window.labeling_widget.view
    workspace = getattr(view, "dense_review_workspace", None)
    if workspace is not None:
        workspace.close()
        workspace.shutdown()
    view.dirty = False
    window.close()
    app.removeEventFilter(view)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _prepare_image(tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 200), color=(220, 220, 220)).save(image_path)
    annotation = {
        "version": "4.2.1",
        "imageWidth": 200,
        "imageHeight": 200,
        "imagePath": "image.png",
        "imageData": None,
        "shapes": [
            {
                "label": "A",
                "shape_type": "rectangle",
                "points": [[10, 10], [50, 10], [50, 50], [10, 50]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "B",
                "shape_type": "rectangle",
                "points": [[70, 10], [110, 10], [110, 50], [70, 50]],
                "xanylabeling_shape_id": "id2",
            },
            {
                "label": "C",
                "shape_type": "polygon",
                "points": [[10, 100], [50, 100], [50, 140], [10, 140]],
                "xanylabeling_shape_id": "id3",
            },
        ],
    }
    (tmp_path / "image.json").write_text(
        json.dumps(annotation), encoding="utf-8"
    )
    return str(image_path)


def _wait_until(app, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_open_confirm_and_save_round_trip(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    assert widget.actions.open_dense_review is not None
    assert any(
        action.text() == "Dense Review"
        for action in widget.menus.workflow.actions()
    )
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    assert workspace.isVisible()
    assert session is not None
    assert session.counts()["total"] == 3
    assert session.counts()["unsupported"] == 1
    assert widget.dirty is False

    dialog = workspace
    assert dialog.batch_list.count() == 1
    dialog._complete_batch()
    app.processEvents()
    assert session.object("id1").confirmed_both()
    assert session.object("id2").confirmed_both()
    assert not session.object("id3").supported
    assert widget.dirty is True

    widget.save_file()
    assert widget.dirty is False
    payload = json.loads((tmp_path / "image.json").read_text(encoding="utf-8"))
    assert payload["xanylabeling_dense_review"]["version"] == 1
    assert payload["checked"] is False

    assert widget.load_file(image_path)
    app.processEvents()
    restored = widget.dense_review_session
    assert restored is not None
    assert restored.object("id1").confirmed_both()
    assert restored.object("id2").confirmed_both()
    assert not restored.completion_status().complete


def test_batch_confirmation_is_one_undo_without_touching_labels(
    window, tmp_path
):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    widget.dense_review_workspace._complete_batch()
    app.processEvents()
    session = widget.dense_review_session
    assert session.object("id1").confirmed_both()
    assert widget.actions.undo.isEnabled() is True
    before = [
        (shape.label, shape.xanylabeling_shape_id)
        for shape in widget.canvas.shapes
    ]
    widget.undo_shape_edit()
    app.processEvents()
    assert not session.object("id1").confirmed_both()
    after = [
        (shape.label, shape.xanylabeling_shape_id)
        for shape in widget.canvas.shapes
    ]
    assert after == before


def test_batch_confirmation_redo_restores_progress(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    widget.dense_review_workspace._complete_batch()
    app.processEvents()
    session = widget.dense_review_session
    confirmed = copy.deepcopy(session.to_payload())
    assert widget.actions.undo.isEnabled() is True
    assert widget.actions.redo.isEnabled() is False

    widget.undo_shape_edit()
    app.processEvents()
    assert not session.object("id1").confirmed_both()
    assert widget.actions.redo.isEnabled() is True

    widget.redo_shape_edit()
    app.processEvents()
    assert session.object("id1").confirmed_both()
    assert session.to_payload() == confirmed
    assert widget.actions.redo.isEnabled() is False


def test_canvas_edit_redo_restores_bounds_and_review_state(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    widget.dense_review_workspace._complete_batch()
    app.processEvents()
    session = widget.dense_review_session
    shape = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    initial_left = shape.bounding_rect().left()
    shape.move_by(QtCore.QPointF(10, 0))
    widget.canvas.store_shapes()
    widget.canvas.shape_moved.emit()
    app.processEvents()
    assert session.object("id1").confirmed("geometry") is False

    widget.undo_shape_edit()
    app.processEvents()
    restored = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    assert restored.bounding_rect().left() == initial_left
    assert session.object("id1").confirmed_both()
    assert widget.actions.redo.isEnabled() is True

    widget.redo_shape_edit()
    app.processEvents()
    redone = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    assert redone.bounding_rect().left() == initial_left + 10
    # A real geometry change retracts both dimensions again.
    assert session.object("id1").confirmed("geometry") is False
    assert session.object("id1").confirmed("category") is False
    assert widget.actions.redo.isEnabled() is False


def test_new_edit_clears_redo(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    widget.dense_review_workspace._complete_batch()
    app.processEvents()
    shape = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    shape.move_by(QtCore.QPointF(10, 0))
    widget.canvas.store_shapes()
    widget.canvas.shape_moved.emit()
    app.processEvents()
    widget.undo_shape_edit()
    app.processEvents()
    assert widget.actions.redo.isEnabled() is True

    shape.move_by(QtCore.QPointF(20, 0))
    widget.canvas.store_shapes()
    widget.canvas.shape_moved.emit()
    app.processEvents()
    assert widget.actions.redo.isEnabled() is False


def test_relabel_move_and_undo_invalidate_progress(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    workspace._complete_batch()
    app.processEvents()
    session = widget.dense_review_session
    assert session.object("id1").confirmed_both()

    shapes = {
        shape.xanylabeling_shape_id: shape for shape in widget.canvas.shapes
    }
    shapes["id1"].label = "B"
    widget.set_dirty()
    app.processEvents()
    assert not session.object("id1").confirmed("category")
    assert session.object("id1").confirmed("geometry") is False

    widget.canvas.select_shapes([shapes["id1"]])
    shapes["id1"].move_by(QtCore.QPointF(30, 30))
    widget.canvas.store_shapes()
    widget.canvas.shape_moved.emit()
    app.processEvents()
    assert not session.object("id1").confirmed_both()

    widget.undo_shape_edit()
    app.processEvents()
    assert session.object("id1").confirmed_both()


def test_spatial_review_requires_explicit_region_completion(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    workspace._complete_batch()
    app.processEvents()
    session = widget.dense_review_session
    workspace.tabs.setCurrentIndex(1)
    app.processEvents()
    assert session.state.coverage is not None
    assert session.completion_status().coverage_complete is False

    while True:
        plan = session.state.coverage
        if all(region.completed for region in plan.regions):
            break
        workspace._complete_current_region()
        app.processEvents()
    assert session.completion_status().coverage_complete is True
    assert session.completion_status().complete is False
    assert session.completion_status().supported is False


def test_dense_shortcuts_are_window_scoped(window, tmp_path):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    assert workspace._shortcuts
    for shortcut in workspace._shortcuts:
        assert shortcut.context() == (QtCore.Qt.ShortcutContext.WindowShortcut)
    assert "Ctrl+Return" in workspace.complete_batch_button.toolTip()
    assert "Alt+Return" in workspace.complete_object_button.toolTip()
    for button in (
        workspace.start_button,
        workspace.complete_batch_button,
        workspace.complete_object_button,
        workspace.full_image_button,
    ):
        assert not button.icon().isNull()
        assert button.iconSize().width() == 15


def test_coverage_grid_click_selects_matching_region(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    workspace._complete_batch()
    workspace.tabs.setCurrentIndex(1)
    app.processEvents()
    plan = workspace.session.state.coverage
    assert plan is not None and plan.regions
    grid = workspace.coverage_grid
    target = plan.regions[-1]
    cell = grid._cell_rect(target, grid._content_rect())
    QTest.mouseClick(
        grid,
        QtCore.Qt.MouseButton.LeftButton,
        pos=QtCore.QPoint(int(cell.center().x()), int(cell.center().y())),
    )
    app.processEvents()
    assert workspace.session.state.coverage.current_region == target.region_id
    current = workspace.region_list.currentItem()
    assert current is not None
    assert current.data(QtCore.Qt.ItemDataRole.UserRole) == target.region_id


def test_external_change_is_detected_before_save(window, tmp_path):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    widget.dense_review_workspace._complete_batch()
    annotation_path = tmp_path / "image.json"
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    payload["description"] = "external"
    annotation_path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(annotation_path, None)
    assert widget._dense_review_external_conflict() is True


def test_configured_batches_keep_membership_after_relabel(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    config = make_config(
        batches=(("A/B", ("A", "B")),),
        rules=(
            ("A", "visible", ""),
            ("B", "visible", ""),
            ("C", "visible", ""),
        ),
    )
    save_config(str(tmp_path), config)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    assert session.state.batches[0].member_ids == ["id1", "id2"]
    workspace._complete_batch()
    app.processEvents()
    assert session.object("id1").confirmed_both()

    shape = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    widget._apply_field_patch([shape], {"label": "C"}, {"label"})
    app.processEvents()
    assert session.state.batches[0].member_ids[0] == "id1"
    assert session.state.current_object == "id1"
    assert not session.object("id1").confirmed("category")
    assert session.object("id1").confirmed("geometry")


def test_new_copy_enters_pending_without_inheriting(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    workspace._complete_batch()
    app.processEvents()
    shape = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    widget.canvas.select_shapes([shape])
    widget.duplicate_selected_shape()
    app.processEvents()
    new_ids = [
        item.xanylabeling_shape_id
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id not in {"id1", "id2", "id3"}
    ]
    assert len(new_ids) == 1
    new_id = new_ids[0]
    assert session.state.new_pending == [new_id]
    assert not session.object(new_id).confirmed_both()
    target_batch = session.state.batches[0].batch_id
    assert session.add_to_batch(new_id, target_batch)
    widget.dense_review_after_progress_change()
    app.processEvents()
    assert new_id in session.state.batches[0].member_ids
    assert session.state.new_pending == []


def test_hidden_and_filtered_objects_are_excluded_but_focus_is_not(
    window, tmp_path
):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    shape = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id2"
    )
    widget._manually_hidden_shapes.add(shape)
    manual, filtered = widget.dense_review_exclusion_ids()
    assert "id2" in manual
    workspace._refresh_cards(force=True)
    scope = workspace._scope()
    assert scope.excluded["id2"] == "manual_hidden"
    assert "id2" not in scope.candidate_ids

    widget._manually_hidden_shapes.clear()
    widget.set_label_visibility("B", False)
    manual, filtered = widget.dense_review_exclusion_ids()
    assert "id2" in filtered
    assert not manual

    widget.set_label_visibility("B", True)
    widget.dense_review_set_display_mode("focus")
    manual, filtered = widget.dense_review_exclusion_ids()
    assert not manual
    assert not filtered
    assert widget.canvas.hide_backround is True


def test_main_window_undo_reverts_latest_move_after_manual_roundtrip(
    window, tmp_path
):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    before_confirmation = widget.dense_review_session.to_payload()
    widget.dense_review_workspace._complete_batch()
    app.processEvents()
    session = widget.dense_review_session
    shape = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    initial_left = shape.bounding_rect().left()
    shape.move_by(QtCore.QPointF(10, 0))
    widget.canvas.store_shapes()
    widget.canvas.shape_moved.emit()
    app.processEvents()
    shape.move_by(QtCore.QPointF(-10, 0))
    widget.canvas.store_shapes()
    widget.canvas.shape_moved.emit()
    app.processEvents()
    assert shape.bounding_rect().left() == initial_left
    assert session.next_undo_kind() == "canvas"
    assert widget.actions.undo.isEnabled() is True

    widget.undo_shape_edit()
    app.processEvents()
    restored = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    assert restored.bounding_rect().left() == initial_left + 10
    assert not session.object("id1").confirmed_both()
    assert session.next_undo_kind() == "canvas"

    widget.undo_shape_edit()
    app.processEvents()
    restored = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id1"
    )
    assert restored.bounding_rect().left() == initial_left
    assert session.object("id1").confirmed_both()
    assert session.next_undo_kind() == "progress"

    widget.undo_shape_edit()
    app.processEvents()
    assert not session.object("id1").confirmed_both()
    assert session.to_payload() == before_confirmation


def test_changed_bounds_request_fresh_card(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    shape_id = session.current_object().shape_id
    item = session.object(shape_id)
    provider = workspace.thumbnails
    margin = workspace.context_spin.value() / 100.0
    target = (360, 240)
    source_version = widget.dense_review_image_info()[0]
    old_key = provider.request_key(
        shape_id,
        provider.generation,
        item.bounds,
        margin,
        target,
        source_version,
    )
    old_image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGB32)
    old_image.fill(QtGui.QColor("red"))
    provider._cache[old_key] = old_image
    provider._latest_requests[shape_id] = old_key
    workspace._card_request_keys[shape_id] = old_key

    with patch.object(provider, "request", return_value=None) as request_spy:
        workspace._request_visible_thumbnails()
        assert not any(
            call.args[0] == shape_id for call in request_spy.call_args_list
        )

    shape = next(
        value
        for value in widget.canvas.shapes
        if value.xanylabeling_shape_id == shape_id
    )
    with patch.object(provider, "request", return_value=None) as request_spy:
        workspace._failed_ids.add(shape_id)
        shape.move_by(QtCore.QPointF(40, 40))
        widget.canvas.store_shapes()
        widget.canvas.shape_moved.emit()
        app.processEvents()
        workspace._request_visible_thumbnails()
        calls = [
            call
            for call in request_spy.call_args_list
            if call.args[0] == shape_id
        ]
        assert calls
        assert tuple(calls[-1].args[1]) == tuple(
            session.object(shape_id).bounds
        )
        assert shape_id not in workspace._failed_ids
    assert old_key not in provider._cache


def test_full_image_roundtrip_restores_user_zoom(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    widget.set_zoom(175)
    app.processEvents()
    assert widget.zoom_widget.value() == 175
    workspace._toggle_full_image()
    app.processEvents()
    assert workspace._full_image is True
    workspace._toggle_full_image()
    app.processEvents()
    assert workspace._full_image is False
    assert widget.zoom_widget.value() == 175


def test_quick_difficult_shortcut_marks_without_dialog(window, tmp_path):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    workspace._mark_current_difficult_quick()
    current = session.current_object()
    assert current is not None
    assert current.difficult is True
    assert current.difficulty_reason == ""


def test_closing_workspace_restores_canvas_and_writes_nothing(
    window, tmp_path
):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    before = (tmp_path / "image.json").read_text(encoding="utf-8")
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    widget.dense_review_set_display_mode("original")
    assert widget.canvas.dense_review_region is None
    workspace.close()
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    assert widget.canvas.hide_backround is False
    assert all(
        widget.canvas.visible.get(shape, True)
        for shape in widget.canvas.shapes
    )
    assert widget.dirty is False
    assert (tmp_path / "image.json").read_text(encoding="utf-8") == before


def test_display_modes_and_full_image_restore(window, tmp_path):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    workspace = widget.dense_review_workspace
    widget.dense_review_set_display_mode("focus")
    assert widget.canvas.hide_backround is True
    assert all(
        widget.canvas.visible.get(shape, True)
        for shape in widget.canvas.shapes
    )
    assert not widget._manually_hidden_shapes

    widget.dense_review_set_display_mode("original")
    assert all(
        widget.canvas.visible.get(shape) is False
        for shape in widget.canvas.shapes
    )
    assert all(shape.visible for shape in widget.canvas.shapes)
    widget.dense_review_set_display_mode("all")
    assert all(
        widget.canvas.visible.get(shape, True)
        for shape in widget.canvas.shapes
    )

    saved_zoom = widget.zoom_widget.value()
    assert widget.dense_review_toggle_full_image() is True
    assert widget._dense_review_full_view is not None
    assert widget.dense_review_toggle_full_image() is False
    assert widget._dense_review_full_view is None
    assert abs(widget.zoom_widget.value() - saved_zoom) <= 1
    workspace.close()


def test_output_directory_keeps_independent_progress(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    fingerprint, width, height = widget.dense_review_image_info()
    seed = DenseReviewSession.from_shapes(
        make_config(batches=()),
        widget.dense_review_shapes(),
        fingerprint,
        width,
        height,
    )
    seed.confirm_batch("__other__", ("category", "geometry"))
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    annotation = {
        "version": "4.2.1",
        "imageWidth": 200,
        "imageHeight": 200,
        "imagePath": "image.png",
        "imageData": None,
        "shapes": [
            {
                "label": "A",
                "shape_type": "rectangle",
                "points": [[10, 10], [50, 10], [50, 50], [10, 50]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "B",
                "shape_type": "rectangle",
                "points": [[70, 10], [110, 10], [110, 50], [70, 50]],
                "xanylabeling_shape_id": "id2",
            },
        ],
        "xanylabeling_dense_review": seed.to_payload(),
    }
    (output_dir / "image.json").write_text(
        json.dumps(annotation), encoding="utf-8"
    )
    widget.output_dir = str(output_dir)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    restored = widget.dense_review_session
    assert restored is not None
    assert restored.object("id1").confirmed_both()

    widget.output_dir = ""
    assert widget.load_file(image_path)
    app.processEvents()
    fresh = widget.dense_review_session
    assert fresh is not None
    assert not fresh.object("id1").confirmed_both()


def test_unknown_progress_is_preserved_until_explicit_rebuild(
    window, tmp_path
):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    annotation_path = tmp_path / "image.json"
    original = json.loads(annotation_path.read_text(encoding="utf-8"))
    original["xanylabeling_dense_review"] = {
        "version": 99,
        "objects": {},
    }
    annotation_path.write_text(json.dumps(original), encoding="utf-8")
    assert widget.load_file(image_path)
    widget.open_dense_review()
    assert widget.dense_review_session is None
    assert "未知" in widget.dense_review_workspace.status_label.text()
    saved = json.loads(annotation_path.read_text(encoding="utf-8"))
    assert saved["xanylabeling_dense_review"]["version"] == 99

    ok, _message = widget.dense_review_start_round(force_new=True)
    assert ok is True
    assert widget.dense_review_session is not None
    assert widget.dirty is True
    assert widget.other_data["xanylabeling_dense_review"]["version"] == 1
    widget.save_file()
    saved = json.loads(annotation_path.read_text(encoding="utf-8"))
    assert saved["xanylabeling_dense_review"]["version"] == 1


def test_save_failure_keeps_memory_progress(window, tmp_path):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    widget.dense_review_workspace._complete_batch()
    assert widget.dense_review_session.object("id1").confirmed_both()
    before = (tmp_path / "image.json").read_text(encoding="utf-8")
    with (
        patch(
            "anylabeling.views.labeling.label_file.os.replace",
            side_effect=PermissionError("injected atomic replacement failure"),
        ),
        patch.object(widget, "error_message"),
    ):
        widget.save_file()
    assert widget.dirty is True
    assert widget.dense_review_session is not None
    assert widget.dense_review_session.object("id1").confirmed_both()
    assert (tmp_path / "image.json").read_text(encoding="utf-8") == before

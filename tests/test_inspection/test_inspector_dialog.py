import copy
import json
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

from anylabeling import config as app_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.inspection.candidates import Candidate
from anylabeling.services.inspection.models import Decision
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow
from PIL import Image


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore,
        "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    config = copy.deepcopy(load_template_config())
    config.update(auto_save=False)
    window = MainWindow(app, config=config)
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    yield window
    view = window.labeling_widget.view
    dialog = getattr(view, "inspector_dialog", None)
    if dialog is not None:
        dialog.close()
    view.dirty = False
    window.close()
    app.removeEventFilter(view)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _prepare_image(tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (64, 64)).save(image_path)
    annotation = {
        "version": "4.2.1",
        "imageWidth": 64,
        "imageHeight": 64,
        "imagePath": "image.png",
        "imageData": None,
        "shapes": [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[4, 4], [30, 30]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[4, 4], [30, 30]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    }
    (tmp_path / "image.json").write_text(
        json.dumps(annotation), encoding="utf-8"
    )
    return str(image_path)


def _wait_until(app, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_inspector_entry_and_current_image_run(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    assert widget.actions.open_inspector is not None
    assert any(
        action.text() == "Inspector"
        for action in widget.menus.workflow.actions()
    )

    widget.open_inspector()
    dialog = widget.inspector_dialog
    assert dialog is not None
    assert dialog.profile_combo.count() >= 3
    index = dialog.profile_combo.findData("generic")
    assert index >= 0
    dialog.profile_combo.setCurrentIndex(index)
    assert dialog.scope_combo.currentData() == "current_image"

    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    assert dialog.report is not None
    assert dialog.issue_table.rowCount() == 1
    assert dialog.storage is not None
    reports = dialog.storage.reports.list_reports()
    assert reports
    assert dialog.storage.reports.load_manifest(
        reports[0]["run_id"]
    ).file_count == 1
    dialog.report = None
    dialog._resume_last()
    assert dialog.report is not None
    assert dialog.issue_table.rowCount() == 1


def test_feedback_and_navigation_keep_states_separate(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    assert dialog.issue_table.rowCount() == 1
    dialog.issue_table.selectRow(0)
    app.processEvents()
    dialog._set_decision(Decision.FALSE_POSITIVE)
    app.processEvents()

    issue = dialog.report.issues[0]
    assert issue.decision is Decision.FALSE_POSITIVE
    snapshot = dialog.storage.feedback.load()
    assert snapshot.records[issue.family_key].decision is Decision.FALSE_POSITIVE
    assert dialog._session is not None

    dialog._locate_selected()
    app.processEvents()
    selected_ids = {
        shape.xanylabeling_shape_id
        for shape in widget.canvas.selected_shapes
    }
    assert selected_ids == {"id1", "id2"}
    widget.canvas.shape_moved.emit()
    app.processEvents()
    assert all(
        issue.verification.value == "pending_recheck"
        for issue in dialog.report.issues
    )


def test_delete_only_removes_canvas_selected_issue_object(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    dialog.issue_table.selectRow(0)
    app.processEvents()
    shapes = {
        shape.xanylabeling_shape_id: shape
        for shape in widget.canvas.shapes
    }
    widget.canvas.select_shapes([shapes["id1"]])
    app.processEvents()
    assert dialog.delete_button.isEnabled() is True
    with patch.object(
        QtWidgets.QMessageBox,
        "question",
        return_value=QtWidgets.QMessageBox.StandardButton.Yes,
    ):
        dialog._delete_selected()
    app.processEvents()
    remaining = {
        shape.xanylabeling_shape_id for shape in widget.canvas.shapes
    }
    assert remaining == {"id2"}


def test_resume_marks_changed_annotation_as_stale(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog.scope_combo.setCurrentIndex(
        dialog.scope_combo.findData("dataset")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    dialog.issue_table.selectRow(0)
    app.processEvents()
    dialog._set_decision(Decision.FALSE_POSITIVE)
    annotation_path = tmp_path / "image.json"
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    payload["shapes"][0]["points"] = [[5, 5], [31, 31]]
    annotation_path.write_text(json.dumps(payload), encoding="utf-8")
    dialog.report = None
    dialog._resume_last()
    app.processEvents()
    assert dialog.report is not None
    assert dialog._verification_current is False
    assert dialog._verification_reasons
    issue = dialog.report.issues[0]
    assert issue.decision is Decision.FALSE_POSITIVE
    assert issue.verification.value == "stale"
    dialog.issue_table.selectRow(0)
    app.processEvents()
    with patch.object(dialog, "_show_error") as show_error:
        dialog._set_decision(Decision.ACCEPTABLE)
        show_error.assert_called_once()
    assert dialog.report.issues[0].verification.value == "stale"


def test_resume_keeps_unsaved_canvas_edit_pending(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog.scope_combo.setCurrentIndex(
        dialog.scope_combo.findData("dataset")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    dialog.issue_table.selectRow(0)
    app.processEvents()
    shape = next(
        shape
        for shape in widget.canvas.shapes
        if shape.xanylabeling_shape_id == "id1"
    )
    shape.move_by(QtCore.QPointF(2, 2))
    widget.canvas.shape_moved.emit()
    app.processEvents()
    assert widget.dirty is True
    assert dialog.report.issues[0].verification.value == "pending_recheck"
    dialog.report = None
    dialog._resume_last()
    app.processEvents()
    assert dialog._verification_current is False
    assert dialog.report.issues[0].verification.value == "pending_recheck"


def test_run_respects_profile_selected_after_binding(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    first_run = dialog.report.run_id
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("screen_corners")
    )
    dialog._start_run()
    assert dialog._active_profile.profile_id == "screen_corners"
    assert _wait_until(
        app,
        lambda: (
            dialog.report is not None
            and dialog.report.run_id != first_run
            and not dialog.controller.is_running()
        ),
    )


def test_dataset_run_delete_and_recheck_marks_not_detected(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    second_image = tmp_path / "second.png"
    Image.new("RGB", (64, 64)).save(second_image)
    (tmp_path / "second.json").write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": 64,
                "imageHeight": 64,
                "imagePath": "second.png",
                "imageData": None,
                "shapes": [
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[8, 8], [24, 24]],
                        "xanylabeling_shape_id": "other",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    widget._full_image_dir = str(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.scope_combo.setCurrentIndex(
        dialog.scope_combo.findData("dataset")
    )
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    assert dialog.report.requested_files == 2
    assert dialog.issue_table.rowCount() == 1
    old_run_id = dialog.report.run_id
    old_family = dialog.report.issues[0].family_key
    dialog.issue_table.selectRow(0)
    app.processEvents()
    ok, reason = widget.inspection_delete_shapes(["id2"])
    assert ok, reason
    dialog._on_canvas_edit()
    dialog._recheck_selected()
    assert _wait_until(
        app,
        lambda: (
            dialog.report is not None
            and dialog.report.run_id != old_run_id
            and not dialog.controller.is_running()
        ),
    )
    assert any(
        issue.family_key == old_family
        and issue.verification.value == "not_detected_on_successful_recheck"
        for issue in dialog.report.issues
    )
    saved_run = dialog.report.run_id
    dialog.report = None
    dialog._resume_last()
    assert dialog.report.run_id == saved_run
    assert dialog._verification_current is False
    assert any(
        issue.family_key == old_family
        and issue.verification.value == "pending_recheck"
        for issue in dialog.report.issues
    )


def test_candidate_accept_uses_formal_shape_identity(window, tmp_path):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    candidate = Candidate(
        candidate_id="candidate-1",
        source="model",
        source_version="1",
        relative_path="image.png",
        image_path=image_path,
        label="person",
        region=(10, 10, 20, 20),
        image_width=64,
        image_height=64,
        score=0.9,
    )
    before = len(widget.canvas.shapes)
    ok, shape_id = widget.inspection_accept_candidate(
        candidate, "candidate-shape-id"
    )
    assert ok is True
    assert shape_id == "candidate-shape-id"
    assert len(widget.canvas.shapes) == before + 1
    accepted = next(
        shape
        for shape in widget.canvas.shapes
        if shape.xanylabeling_shape_id == shape_id
    )
    assert (
        accepted.attributes["inspection_candidate_id"] == "candidate-1"
    )
    assert accepted.label == "person"

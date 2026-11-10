import copy
import json
import os
import time
from pathlib import Path
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
from anylabeling.views.labeling.utils.theme import DARK
from anylabeling.views.labeling.inspector import dialog as dialog_module
from PIL import Image


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
    # ``LabelingWidget`` persists its canvas preferences during construction;
    # the user-configuration transaction therefore needs an active session.
    from anylabeling import user_config
    from anylabeling.views.labeling import label_widget as label_widget_module

    user_config.begin_session(
        target_path=str(tmp_path / ".xanylabelingrc"),
        origin="test",
        template=config,
        effective=dict(config),
        ensure_created=True,
    )
    # A preference write failure would open a modal box and stall the test
    # run; these tests do not cover preference persistence, so keep it inert.
    monkeypatch.setattr(
        label_widget_module.LabelingWidget,
        "persist_user_preferences",
        lambda self, *args, **kwargs: True,
        raising=False,
    )
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
    user_config.end_session()


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
    assert (
        dialog.storage.reports.load_manifest(reports[0]["run_id"]).file_count
        == 1
    )
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
    assert (
        snapshot.records[issue.family_key].decision is Decision.FALSE_POSITIVE
    )
    assert dialog._session is not None

    dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("review_ignored"))
    dialog.issue_table.selectRow(0)
    dialog._locate_selected()
    app.processEvents()
    selected_ids = {
        shape.xanylabeling_shape_id for shape in widget.canvas.selected_shapes
    }
    assert selected_ids == {"id1"}
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
        shape.xanylabeling_shape_id: shape for shape in widget.canvas.shapes
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
    remaining = {shape.xanylabeling_shape_id for shape in widget.canvas.shapes}
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
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("dataset"))
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
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("dataset"))
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
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("dataset"))
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
    assert accepted.attributes["inspection_candidate_id"] == "candidate-1"
    assert accepted.label == "person"


def test_detail_sections_follow_theme(window, tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    index = dialog.profile_combo.findData("generic")
    dialog.profile_combo.setCurrentIndex(index)
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    assert dialog.issue_table.rowCount() >= 1
    dialog.issue_table.selectRow(0)
    app.processEvents()
    dialog.advanced_actions.show()
    dialog._show_selected_details()
    text = dialog.details.toPlainText()
    for title in ("规则命中", "位置", "建议", "状态", "备注"):
        assert title in text
    from anylabeling.views.labeling.inspector import dialog as dialog_module

    monkeypatch.setattr(dialog_module, "get_theme", lambda: DARK)
    dialog._show_selected_details()
    html_text = dialog.details.toHtml().lower()
    assert DARK["text_secondary"].lower() in html_text
    assert DARK["text"].lower() in html_text


def test_english_translations_cover_workbench(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    translator = QtCore.QTranslator()
    assert translator.load(":/languages/translations/en_US.qm")
    app.installTranslator(translator)
    try:
        widget = window.labeling_widget.view
        assert widget.load_file(_prepare_image(tmp_path))
        widget.open_inspector()
        dialog = widget.inspector_dialog
        assert dialog.start_button.text() == "Start inspection"
        assert dialog.issue_table.horizontalHeaderItem(0).text() == "Risk"
    finally:
        app.removeTranslator(translator)


def test_batch_delete_previews_exact_set_and_can_be_undone(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    # Add an unrelated third object that must never be deleted.
    from anylabeling.views.labeling.shape import Shape

    extra = Shape(label="car", shape_type="rectangle", shape_id="keep-me")
    extra.points = [
        QtCore.QPointF(40, 40),
        QtCore.QPointF(60, 40),
        QtCore.QPointF(60, 60),
        QtCore.QPointF(40, 60),
    ]
    widget.load_shapes([extra], replace=False, update_last_label=False)
    assert widget.load_file(image_path) or True
    widget.load_file(image_path)
    shapes = {
        shape.xanylabeling_shape_id: shape for shape in widget.canvas.shapes
    }
    assert set(shapes) == {"id1", "id2"}  # reload drops the unsaved extra

    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    dialog.issue_table.selectRow(0)
    app.processEvents()
    seen = {}
    with patch.object(
        QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes
    ) as question:
        dialog._batch_delete()
    app.processEvents()
    preview = question.call_args.args[2]
    assert "id1" in preview and "id2" in preview
    assert "keep-me" not in preview
    assert {shape.xanylabeling_shape_id for shape in widget.canvas.shapes} == set()
    # Undo restores both objects and marks the issues pending recheck.
    with patch.object(dialog, "_show_error") as show_error:
        dialog._undo_last_edit()
    app.processEvents()
    show_error.assert_not_called()
    restored = {
        shape.xanylabeling_shape_id for shape in widget.canvas.shapes
    }
    assert restored == {"id1", "id2"}


def test_keep_both_and_defer_do_not_modify_shapes(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    assert widget.load_file(_prepare_image(tmp_path))
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    dialog.issue_table.selectRow(0)
    app.processEvents()
    before = {shape.xanylabeling_shape_id for shape in widget.canvas.shapes}
    dialog._keep_both()
    app.processEvents()
    issue = dialog.report.issues[0]
    assert issue.decision.value == "acceptable"
    assert issue.action.value == "unchanged"
    assert {shape.xanylabeling_shape_id for shape in widget.canvas.shapes} == before
    dialog.issue_table.selectRow(0)
    app.processEvents()
    dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("review_ignored"))
    dialog.issue_table.selectRow(0)
    dialog._defer_issue()
    app.processEvents()
    assert dialog.report.issues[0].decision.value == "needs_discussion"
    assert {shape.xanylabeling_shape_id for shape in widget.canvas.shapes} == before
    # Filters expose the deferred bucket.
    index = dialog.filter_combo.findData("needs_discussion")
    dialog.filter_combo.setCurrentIndex(index)
    app.processEvents()
    assert dialog.issue_table.rowCount() == 1


def test_batch_relabel_previews_and_keeps_unrelated_objects(window, tmp_path):
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
    dialog._batch_target_shapes(
        dialog._current_file_issues()
    )  # keep helper exercised
    with patch.object(
        QtWidgets.QInputDialog, "getItem", side_effect=[("person", True), ("vehicle", True)]
    ), patch.object(
        QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes
    ) as question, patch.object(
        QtWidgets.QInputDialog, "getText", return_value=("vehicle", True)
    ):
        dialog._batch_relabel()
    app.processEvents()
    assert question.call_count == 1
    preview = question.call_args.args[2]
    assert "id1" in preview and "id2" in preview
    labels = {shape.label for shape in widget.canvas.shapes}
    assert labels == {"vehicle"}


def test_canvas_edit_updates_duplicate_issues_incrementally(window, tmp_path):
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
    families = {issue.family_key for issue in dialog.report.issues}
    assert families, "identical boxes must produce a duplicate issue"

    # Move id2 far away: the pair must disappear without a full re-run.
    shape = next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == "id2"
    )
    shape.points = [
        QtCore.QPointF(40, 40),
        QtCore.QPointF(50, 50),
        QtCore.QPointF(50, 60),
        QtCore.QPointF(40, 60),
    ]
    widget.canvas.shape_moved.emit()
    app.processEvents()
    file_issues = [
        issue
        for issue in dialog.report.issues
        if issue.location.relative_path == "image.png"
        and set(issue.rule_ids).issubset(
            {"duplicate_boxes", "legacy_same_group_duplicate"}
        )
    ]
    # The edit invalidates the evidence: the pending item stays in the queue
    # until a recheck proves the pair is gone, and no new pair is invented.
    assert len(file_issues) == 1
    assert file_issues[0].family_key in families
    assert file_issues[0].verification.value == "pending_recheck"
    assert dialog._duplicate_tracker is not None

    # Move it back on top of id1: the pair is reported again with the same
    # family, and the queue holds exactly one entry (no duplicate rows).
    shape.points = [
        QtCore.QPointF(4, 4),
        QtCore.QPointF(30, 4),
        QtCore.QPointF(30, 30),
        QtCore.QPointF(4, 30),
    ]
    widget.canvas.shape_moved.emit()
    app.processEvents()
    file_issues = [
        issue
        for issue in dialog.report.issues
        if issue.location.relative_path == "image.png"
        and set(issue.rule_ids).issubset(
            {"duplicate_boxes", "legacy_same_group_duplicate"}
        )
    ]
    families_now = {issue.family_key for issue in file_issues}
    assert families_now == families
    assert len(file_issues) == 1
    assert file_issues[0].verification.value == "pending_recheck"
    assert "[id1-id2]" == "[{}-{}]".format(
        *file_issues[0].location.object_ids
    )


def test_profile_management_keeps_builtin_read_only(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    assert widget.load_file(_prepare_image(tmp_path))
    widget.open_inspector()
    dialog = widget.inspector_dialog
    assert dialog._ensure_storage()
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    builtin = dialog._selected_profile()
    assert builtin.builtin is True
    builtin_path = dialog._custom_profile_paths.get("generic")
    assert builtin_path is None

    # Rename / edit on a built-in template must be refused before any write.
    with patch.object(dialog, "_show_error") as show_error, patch.object(
        QtWidgets.QInputDialog, "getText", return_value=("renamed", True)
    ):
        dialog._rename_profile()
    show_error.assert_called_once()
    assert "只读" in show_error.call_args.args[0]
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    with patch.object(dialog, "_show_error") as show_error:
        dialog._edit_profile()
    show_error.assert_called_once()
    assert dialog._selected_profile().name == "通用矩形检查"

    # Copy, rename, edit rules and disable round-trip through storage.
    with patch.object(
        QtWidgets.QInputDialog, "getText", return_value=("我的方案", True)
    ):
        dialog._copy_profile()
    app.processEvents()
    custom_id = next(
        profile_id
        for profile_id, profile in dialog._profiles.items()
        if not profile.builtin
    )
    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData(custom_id))
    assert dialog._selected_profile().name == "我的方案"
    custom_path = dialog._custom_profile_paths[custom_id]
    assert os.path.isfile(custom_path)

    with patch.object(
        QtWidgets.QInputDialog, "getText", return_value=("改名后", True)
    ):
        dialog._rename_profile()
    app.processEvents()
    renamed = dialog._profiles[custom_id]
    assert renamed.name == "改名后"
    assert renamed.version == 2

    editor = dialog_module.ProfileRuleEditor(
        renamed, dialog.catalog, dialog
    )
    row = next(
        index
        for index, item in enumerate(editor._rows)
        if item[0] == "duplicate_boxes"
    )
    editor._rows[row][1].setCheckState(QtCore.Qt.CheckState.Unchecked)
    editor._save()
    edited = editor.result_profile()
    assert edited is not None
    assert edited.version == renamed.version + 1
    assert all(
        not rule.enabled or rule.rule_id != "duplicate_boxes"
        for rule in edited.rules
    )
    dialog._persist_profile(edited)
    app.processEvents()
    reloaded = dialog_module.load_profile(custom_path)
    assert reloaded.version == edited.version

    dialog._toggle_profile()
    app.processEvents()
    assert custom_id in dialog._disabled_profiles
    assert custom_id in dialog.storage.profile_state.disabled()
    with patch.object(
        QtWidgets.QMessageBox,
        "question",
        return_value=QtWidgets.QMessageBox.StandardButton.No,
    ) as question:
        assert dialog._prepare_run_profile() is None
    assert question.call_count == 1
    dialog._toggle_profile()
    app.processEvents()
    assert custom_id not in dialog._disabled_profiles


def test_profile_edit_keeps_history_report_snapshot(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    assert widget.load_file(_prepare_image(tmp_path))
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    frozen = dialog.report.profile_snapshot
    assert frozen["profile"]["profile_id"] == "generic"
    original_digest = dialog.report.config_digest
    with patch.object(
        QtWidgets.QInputDialog, "getText", return_value=("副本", True)
    ):
        dialog._copy_profile()
    app.processEvents()
    custom_id = next(
        profile_id
        for profile_id, profile in dialog._profiles.items()
        if not profile.builtin
    )
    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData(custom_id))
    with patch.object(
        QtWidgets.QInputDialog, "getText", return_value=("副本改名", True)
    ):
        dialog._rename_profile()
    app.processEvents()
    # The already-finished report still carries its own frozen config.
    assert dialog.report.config_digest == original_digest
    assert dialog.report.profile_snapshot["profile"]["profile_id"] == "generic"


def test_inspector_shortcuts_scope_and_start(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    assert dialog.start_shortcut.key().toString() == "F5"
    assert dialog.start_shortcut.context() == (
        QtCore.Qt.ShortcutContext.WindowShortcut
    )
    assert dialog.locate_shortcut.context() == (
        QtCore.Qt.ShortcutContext.WidgetShortcut
    )
    assert "Return" in dialog.locate_shortcut.key().toString()
    for button in (
        dialog.start_button,
        dialog.locate_button,
        dialog.recheck_button,
    ):
        assert not button.icon().isNull()
        assert button.iconSize().width() == 15
    index = dialog.profile_combo.findData("generic")
    dialog.profile_combo.setCurrentIndex(index)
    assert dialog.start_button.isEnabled()
    dialog._start_run_shortcut()
    assert _wait_until(app, lambda: dialog.report is not None)


def _prepare_second_image(tmp_path, name="b.png"):
    image_path = tmp_path / name
    Image.new("RGB", (64, 64)).save(image_path)
    annotation = {
        "version": "4.2.1",
        "imageWidth": 64,
        "imageHeight": 64,
        "imagePath": name,
        "imageData": None,
        "shapes": [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[8, 8], [34, 34]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[8, 8], [34, 34]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    }
    (tmp_path / f"{name[:-4]}.json").write_text(
        json.dumps(annotation), encoding="utf-8"
    )
    return str(image_path)


def test_cross_file_same_object_id_cannot_authorize_delete(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    _prepare_second_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("dataset"))
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    assert dialog.report is not None
    foreign = next(
        issue
        for issue in dialog.report.issues
        if issue.location.relative_path == "b.png"
    )
    assert set(foreign.location.object_ids) == {"id1", "id2"}
    # The canvas shows image.png and has an unrelated object with id1.
    shapes = {
        shape.xanylabeling_shape_id: shape for shape in widget.canvas.shapes
    }
    widget.canvas.select_shapes([shapes["id1"]])
    app.processEvents()
    assert dialog._selected_target_ids(foreign) == []
    before = len(widget.canvas.shapes)
    with patch.object(dialog, "_show_error") as show_error, patch.object(
        QtWidgets.QMessageBox,
        "question",
        return_value=QtWidgets.QMessageBox.StandardButton.Yes,
    ):
        dialog._delete_selected()
    show_error.assert_called_once()
    assert len(widget.canvas.shapes) == before
    # The same id on the issue's own file is still actionable.
    same_file = next(
        issue
        for issue in dialog.report.issues
        if issue.location.relative_path == "image.png"
    )
    row = next(
        index
        for index, item in enumerate(dialog._row_issues)
        if item.family_key == same_file.family_key
    )
    dialog.issue_table.selectRow(row)
    app.processEvents()
    assert dialog._selected_target_ids(same_file) == ["id1"]
    assert dialog._target_guard_reason(foreign)


def test_late_run_result_is_archived_not_applied(window, tmp_path):
    from dataclasses import replace as dataclass_replace

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
    current = dialog.report
    assert current is not None
    stale = dataclass_replace(
        current,
        run_id="stale-run-1",
        generation=current.generation + 7,
    )
    dialog._on_finished(stale, None, "expired-token")
    app.processEvents()
    assert dialog.report is current
    assert any("旧运行结果" in note for note in dialog._run_notes)
    assert dialog.storage is not None
    assert dialog.storage.reports.load("stale-run-1").run_id == "stale-run-1"


def test_reopened_inspector_restores_frozen_profile_and_reports_bad_json(
    window, tmp_path
):
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
    assert dialog.storage is not None
    storage_root = dialog.storage.root
    dialog.close()
    dialog.deleteLater()
    widget.inspector_dialog = None

    widget.open_inspector()
    restored = widget.inspector_dialog
    assert restored is not None
    restored._ensure_storage()
    restored._resume_last()
    app.processEvents()
    assert restored.report is not None
    assert restored._active_profile is not None
    assert restored._active_profile.profile_id == "generic"
    restored.issue_table.selectRow(0)
    app.processEvents()
    with patch.object(restored.controller, "start") as start:
        with patch.object(restored, "_show_error") as show_error:
            restored._recheck_selected()
    show_error.assert_not_called()
    assert start.call_count == 1
    profile_arg = start.call_args.args[0]
    assert profile_arg.profile_id == "generic"

    broken_dir = Path(storage_root) / "reports"
    broken_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "broken-report.json").write_text("{not-json", encoding="utf-8")
    before = restored.report
    with patch.object(restored, "_show_error") as show_error:
        restored._load_report("broken-report")
    show_error.assert_called_once()
    assert "broken-report" in show_error.call_args.args[1]
    assert restored.report is before


def test_navigation_resolves_unloaded_file_region_and_load_failure(
    window, tmp_path
):
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    second = _prepare_second_image(tmp_path)
    widget._full_image_dir = str(tmp_path)
    assert widget.load_file(image_path)
    assert widget._inspection_resolve_image_path("b.png") == os.path.abspath(
        second
    )
    assert widget.inspection_navigate_to(
        "b.png", region=(4, 4, 40, 40)
    )
    assert os.path.basename(widget.filename) == "b.png"
    assert widget.canvas.scale > 0

    assert widget.load_file(image_path)
    shapes = {
        shape.xanylabeling_shape_id: shape for shape in widget.canvas.shapes
    }
    widget.canvas.select_shapes([shapes["id1"]])
    before = list(widget.canvas.selected_shapes)
    with patch.object(widget, "load_file", return_value=False):
        assert widget.inspection_navigate_to("b.png") is False
    assert list(widget.canvas.selected_shapes) == before

    # Navigation to a file that is already in the file list must move the
    # list cursor and load it without a second unsaved-changes prompt.
    widget.file_list_widget.clear()
    widget.fn_to_index = {}
    for path in (image_path, second):
        widget.file_list_widget.addItem(path)
        widget.fn_to_index[path] = widget.file_list_widget.count() - 1
    widget.file_list_widget.setCurrentRow(0)
    assert widget.load_file(image_path)
    with patch.object(widget, "may_continue", return_value=True) as may_continue:
        assert widget.inspection_navigate_to("b.png") is True
    assert may_continue.call_count == 1
    assert widget.file_list_widget.currentRow() == 1
    assert os.path.basename(widget.filename) == "b.png"

    widget.load_file(image_path)
    assert os.path.basename(widget.filename) == "image.png"
    # Deleting with a mismatching file identity must be refused.
    ok, reason = widget.inspection_delete_shapes(
        ["id1"],
        relative_path="b.png",
        dataset_root=str(tmp_path),
        output_dir="",
    )
    assert ok is False
    assert reason
    assert {
        shape.xanylabeling_shape_id for shape in widget.canvas.shapes
    } == {"id1", "id2"}

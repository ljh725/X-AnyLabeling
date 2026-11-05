"""Visible scan progress and direct access to configured inspection rules."""

from unittest.mock import patch

from PyQt6 import QtCore, QtWidgets

from anylabeling.services.inspection.manifest import build_manifest
from anylabeling.services.inspection.models import RunScope
from anylabeling.services.inspection.profiles import default_profiles
from anylabeling.views.labeling.inspector.controller import (
    InspectionController,
)
from anylabeling.views.labeling.inspector.dialog import ProfileRuleEditor
from tests.test_inspection.test_inspector_dialog import (
    _prepare_image,
    _wait_until,
    window,  # noqa: F401
)


def test_scan_progress_covers_success_and_read_failure(tmp_path):
    good = _prepare_image(tmp_path)
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    bad.with_suffix(".json").write_text("{bad json", encoding="utf-8")
    events = []
    manifest = build_manifest(
        str(tmp_path),
        image_paths=[good, str(bad)],
        progress=lambda *event: events.append(event),
    )
    assert len(manifest.files) == 2
    assert (
        next(
            file
            for file in manifest.files
            if file.relative_path == "broken.png"
        ).annotation_state
        == "error"
    )
    assert events == [
        (0, 2, "image.png"),
        (1, 2, "image.png"),
        (1, 2, "broken.png"),
        (2, 2, "broken.png"),
    ]


def test_cancelled_scan_never_claims_all_files_read(tmp_path):
    image = _prepare_image(tmp_path)
    events = []
    cancelled = False

    def progress(*event):
        nonlocal cancelled
        events.append(event)
        cancelled = True

    manifest = build_manifest(
        str(tmp_path),
        progress=progress,
        should_cancel=lambda: cancelled,
    )
    assert not manifest.complete
    assert not manifest.files
    assert events == [(1, 0, "image.png")]


def test_controller_delivers_scan_and_check_as_distinct_phases(tmp_path):
    _prepare_image(tmp_path)
    app = QtWidgets.QApplication.instance()
    controller = InspectionController()
    scans, checks, finished = [], [], []
    controller.scan_progress.connect(lambda *args: scans.append(args))
    controller.progress.connect(lambda *args: checks.append(args))
    controller.finished.connect(lambda *args: finished.append(args))
    controller.start(
        default_profiles()[0], RunScope.DATASET, dataset_root=str(tmp_path)
    )
    assert _wait_until(app, lambda: bool(finished))
    token = controller.active_context.token
    assert scans[-1] == (token, 1, 1, "image.png")
    assert checks[-1] == (token, 1, 1, "image.png")


def test_rules_visible_and_preview_cannot_save_builtin(window, tmp_path):
    widget = window.labeling_widget.view
    widget.load_file(_prepare_image(tmp_path))
    widget.open_inspector()
    dialog = widget.inspector_dialog
    assert dialog.info_frame.isVisibleTo(dialog)
    assert dialog.rule_summary.text()
    for button in (
        dialog.view_rules_button,
        dialog.copy_profile_button,
        dialog.edit_profile_button,
    ):
        assert button.isVisibleTo(dialog)
    dialog._toggle_notes()
    dialog._toggle_notes()
    assert dialog.info_frame.isVisibleTo(dialog)
    with patch.object(ProfileRuleEditor, "exec", return_value=0) as show:
        dialog.view_rules_button.click()
    show.assert_called_once()
    editor = ProfileRuleEditor(
        dialog._selected_profile(), dialog.catalog, read_only=True
    )
    assert editor.table.rowCount() >= 6
    for row in range(editor.table.rowCount()):
        assert (
            not editor.table.item(row, 0).flags()
            & QtCore.Qt.ItemFlag.ItemIsUserCheckable
        )
        assert (
            not editor.table.item(row, 2).flags()
            & QtCore.Qt.ItemFlag.ItemIsEditable
        )
    editor._save()
    assert editor.result_profile() is None


def test_progress_is_legible_and_stale_scan_is_ignored(window, tmp_path):
    widget = window.labeling_widget.view
    widget.load_file(_prepare_image(tmp_path))
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog._run_token = "active"
    dialog._on_scan_progress("active", 3, 10, "folder/image.png")
    assert dialog.progress.isTextVisible()
    assert dialog.progress.height() >= 20
    assert (dialog.progress.value(), dialog.progress.maximum()) == (3, 10)
    assert "folder/image.png" in dialog.status_label.text()
    dialog._on_scan_progress("old-run", 10, 10, "stale.png")
    assert dialog.progress.value() == 3
    dialog._on_progress("active", 4, 10, "folder/next.png")
    assert "4/10" in dialog.status_label.text()

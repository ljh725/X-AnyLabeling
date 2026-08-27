"""Offscreen tests for the marked-object field editor dialog."""

import os.path as osp
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6 import QtWidgets  # noqa: E402

from anylabeling.views.labeling.widgets.object_field_edit_dialog import (  # noqa: E402
    ObjectFieldEditDialog,
    ObjectFieldEditThread,
    _preflight_message,
)
from anylabeling.views.labeling.widgets.object_field_edit import (  # noqa: E402
    FieldAssignment,
    ObjectFieldEditEngine,
    ObjectFieldPreflightSummary,
    ObjectFieldEditResult,
    ObjectFieldResult,
)
from anylabeling.views.labeling.widgets.label_batch import (  # noqa: E402
    FileOperationResult,
)
from anylabeling.views.labeling.widgets.object_relabel import (  # noqa: E402
    MarkedObjectRef,
    MarkedObjectStore,
    STATUS_CONFLICT,
    STATUS_SUCCEEDED,
)
from anylabeling.views.labeling import (
    label_widget as label_widget_module,
)  # noqa: E402


def test_dialog_exposes_mark_summary_and_field_completion_boundary(qapp):
    """The dialog states counts and that unselected fields are untouched."""
    dialog = ObjectFieldEditDialog(3, 2)
    assert "3" in dialog.findChildren(QtWidgets.QLabel)[0].text()
    labels = [item.text() for item in dialog.findChildren(QtWidgets.QLabel)]
    assert any("not completed" in item for item in labels)
    dialog.close()


def test_dialog_validates_typed_assignment_and_nested_key(qapp):
    """Rows produce typed assignments, including a nested flags key."""
    dialog = ObjectFieldEditDialog(1, 1)
    row = dialog.rows[0]
    row.field_combo.setCurrentIndex(5)
    row.key_edit.setText("orphan_head")
    row.bool_edit.setCurrentIndex(1)
    assignments = dialog.assignments()
    assert assignments[0].path == ("flags", "orphan_head")
    assert assignments[0].value is False
    dialog.close()


def test_dialog_rejects_duplicate_field_paths(qapp):
    """Duplicate rows are rejected before a worker can be started."""
    dialog = ObjectFieldEditDialog(1, 1)
    first = dialog.rows[0]
    first.value_edit.setText("new-label")
    dialog.add_row()
    second = dialog.rows[1]
    second.value_edit.setText("other-label")
    with pytest.raises(ValueError, match="duplicate"):
        dialog.assignments()
    dialog.close()


def test_field_result_sync_removes_only_successful_marks(tmp_path):
    """Success removes marks while conflicts and outside marks remain."""
    project = osp.normcase(osp.abspath(str(tmp_path)))
    current = osp.abspath(str(tmp_path / "a.png"))
    other = osp.abspath(str(tmp_path / "b.png"))
    store = MarkedObjectStore()
    refs = [
        MarkedObjectRef(project, current, "a"),
        MarkedObjectRef(project, other, "b"),
        MarkedObjectRef(project, current, "outside"),
    ]
    for ref in refs:
        store.toggle(ref)
    loaded = []
    refreshed = []
    widget = SimpleNamespace(
        marked_object_store=store,
        filename=current,
        _dataset_index_controller=SimpleNamespace(
            label_saved=lambda image: refreshed.append(image)
        ),
        _annotation_path_for_image=lambda image: osp.splitext(str(image))[0]
        + ".json",
        load_file=lambda image: loaded.append(image),
        _sync_marked_object_ui=lambda: None,
    )
    result = ObjectFieldEditResult(
        transaction_id="tx",
        phase="committed",
        cancelled=False,
        objects=(
            ObjectFieldResult(refs[0].object_key, STATUS_SUCCEEDED),
            ObjectFieldResult(refs[1].object_key, STATUS_CONFLICT),
        ),
        files=(
            FileOperationResult(
                osp.splitext(current)[0] + ".json", STATUS_SUCCEEDED
            ),
        ),
    )
    label_widget_module.LabelingWidget._apply_object_field_edit_result(
        widget, result
    )
    assert not store.contains(refs[0].object_key)
    assert store.contains(refs[1].object_key)
    assert store.contains(refs[2].object_key)
    assert loaded == [current]
    assert refreshed == [current]


def test_preflight_message_includes_counts_and_alias_warning():
    """The confirmation copy exposes field counters and legacy warnings."""
    summary = ObjectFieldPreflightSummary(
        assignments=(FieldAssignment("difficult", False),),
        snapshot_objects=2,
        candidate_files=1,
        created=1,
        updated=1,
        unchanged=0,
        warnings=("legacy flags.difficult is present",),
    )
    message = _preflight_message(summary)
    assert "Created: 1" in message
    assert "Updated: 1" in message
    assert "legacy flags.difficult" in message


def test_worker_abort_before_preflight_emits_cancelled_result(tmp_path):
    """Cancelling before confirmation never stages or commits a file."""
    source = tmp_path / "a.json"
    source.write_text('{"shapes": []}', encoding="utf-8")
    from anylabeling.views.labeling.widgets.object_relabel import (
        MarkedObjectRef,
    )
    from anylabeling.views.labeling.widgets.object_field_edit import (
        build_object_field_edit_plan,
    )

    project = str(tmp_path)
    ref = MarkedObjectRef(project, str(tmp_path / "a.png"), "missing")
    plan = build_object_field_edit_plan(
        [ref],
        project,
        [FieldAssignment("difficult", False)],
        project,
        lambda image: str(source),
    )
    thread = ObjectFieldEditThread(
        ObjectFieldEditEngine(str(tmp_path / "transactions")),
        plan,
        project,
    )
    results = []
    thread.finished_result.connect(results.append)
    thread.request_abort()
    thread.run()
    assert results and results[0].cancelled

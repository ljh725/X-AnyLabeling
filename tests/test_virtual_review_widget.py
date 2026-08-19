"""Qt integration tests for the virtual review controls and focus layer."""

from anylabeling.views.labeling.widgets.inspector.virtual_review_widget import (
    VirtualReviewWidget,
)
from anylabeling.views.labeling.virtual_review import PackingMode


def test_virtual_review_widget_emits_valid_criteria(qapp):
    widget = VirtualReviewWidget()
    widget.set_labels({"person", "head"})
    widget.label_box.setCurrentIndex(widget.label_box.findData("person"))
    widget.min_width_edit.setText("80")
    widget.max_height_edit.setText("600")
    received = []
    widget.start_requested.connect(received.append)

    widget._emit_start()

    criteria = received[0]["criteria"]
    packing = received[0]["packing"]
    assert criteria["labels"] == frozenset({"person"})
    assert criteria["min_width"] == 80.0
    assert criteria["max_height"] == 600.0
    assert packing["mode"] is PackingMode.BALANCED
    assert packing["max_tasks_per_page"] == 2
    assert packing["min_projected_anchor_px"] == 160.0
    assert packing["min_projected_gap_px"] == 48.0
    widget.deleteLater()


def test_virtual_review_widget_rejects_invalid_range(qapp):
    widget = VirtualReviewWidget()
    widget.min_width_edit.setText("not-a-number")

    widget._emit_start()

    assert "条件无效" in widget.progress_label.text()
    widget.deleteLater()


def test_preset_modes_populate_explicit_controls(qapp):
    widget = VirtualReviewWidget()

    widget.mode_box.setCurrentIndex(
        widget.mode_box.findData(PackingMode.SINGLE)
    )
    assert widget.max_tasks_spin.value() == 1
    assert not widget.max_tasks_spin.isEnabled()

    widget.mode_box.setCurrentIndex(
        widget.mode_box.findData(PackingMode.DENSE)
    )
    assert widget.max_tasks_spin.isEnabled()
    assert widget.max_tasks_spin.value() == 3
    assert widget.min_anchor_spin.value() == 120.0
    assert widget.min_gap_spin.value() == 32.0

    widget.mode_box.setCurrentIndex(
        widget.mode_box.findData(PackingMode.BALANCED)
    )
    assert widget.max_tasks_spin.value() == 2
    assert widget.min_anchor_spin.value() == 160.0
    assert widget.min_gap_spin.value() == 48.0
    widget.deleteLater()


def test_effective_thresholds_remain_editable(qapp):
    widget = VirtualReviewWidget()

    widget.max_tasks_spin.setValue(3)
    widget.min_anchor_spin.setValue(240.5)
    widget.min_gap_spin.setValue(64.0)
    payload = widget.packing_payload()

    assert payload["max_tasks_per_page"] == 3
    assert payload["min_projected_anchor_px"] == 240.5
    assert payload["min_projected_gap_px"] == 64.0
    widget.deleteLater()


def test_single_mode_forces_one_task_page_limit(qapp):
    widget = VirtualReviewWidget()
    widget.max_tasks_spin.setValue(3)
    widget.mode_box.setCurrentIndex(
        widget.mode_box.findData(PackingMode.SINGLE)
    )

    payload = widget.packing_payload()

    assert payload["max_tasks_per_page"] == 1
    assert payload["mode"] is PackingMode.SINGLE
    widget.deleteLater()


def test_progress_and_packing_summary_text(qapp):
    widget = VirtualReviewWidget()

    widget.set_packing_stats(atomic_tasks=8, pages=5, fallback=1)
    widget.set_progress(0, 5, 2)
    text = widget.progress_label.text()

    assert "1/5" in text
    assert "2" in text
    assert "8" in text
    assert "5" in text
    assert "1" in text

    widget.set_progress(-1, 0)
    assert widget.progress_label.text() == "未生成任务"
    widget.deleteLater()


def test_canvas_virtual_focus_preserves_base_visibility(canvas):
    from tests.conftest import MockShape

    current = MockShape(group_id=1)
    context = MockShape(group_id=2)
    hidden = MockShape(visible=False, group_id=3)
    canvas.shapes = [current, context, hidden]
    canvas.visible = {current: True, context: True, hidden: True}

    canvas.set_virtual_review_visibility_predicate(
        lambda shape: shape is current
    )

    assert canvas.main_visible(current)
    assert not canvas.main_visible(context)
    assert canvas._virtual_review_context_visible(context)
    assert not canvas.base_visible(hidden)
    assert not canvas.is_shape_interactive(context)

    canvas.clear_virtual_review_visibility_predicate()
    assert canvas.main_visible(context)


def test_runtime_identity_survives_shape_copy_without_serialization(qapp):
    from PyQt6 import QtCore

    from anylabeling.views.labeling.shape import Shape

    shape = Shape(label="person", shape_type="rectangle", group_id=4)
    shape.points = [QtCore.QPointF(1, 2), QtCore.QPointF(20, 30)]
    shape._virtual_review_id = "vr:test"

    copied = shape.copy()

    assert copied._virtual_review_id == "vr:test"
    assert "_virtual_review_id" not in copied.to_dict()


def test_undo_deepcopy_preserves_runtime_identity(qapp):
    """Undo restores shapes via deepcopy; page membership must survive."""
    import copy

    from PyQt6 import QtCore

    from anylabeling.views.labeling.shape import Shape

    shape = Shape(label="person", shape_type="rectangle", group_id=4)
    shape.points = [QtCore.QPointF(1, 2), QtCore.QPointF(20, 30)]
    shape._virtual_review_id = "vr:undo"

    restored = copy.deepcopy(shape)

    assert restored._virtual_review_id == "vr:undo"


def test_annotation_serialization_has_no_page_or_packing_fields(qapp):
    from PyQt6 import QtCore

    from anylabeling.views.labeling.shape import Shape

    shape = Shape(label="person", shape_type="rectangle", group_id=4)
    shape.points = [QtCore.QPointF(1, 2), QtCore.QPointF(20, 30)]
    shape._virtual_review_id = "vr:page-member"

    data = shape.to_dict()

    assert "_virtual_review_id" not in data
    assert not any(
        "page" in key or "packing" in key or "virtual" in key for key in data
    )

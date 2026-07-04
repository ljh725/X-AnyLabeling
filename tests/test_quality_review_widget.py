"""Quality review widget UI tests (task G6).

Covers navigation signal emission (shape_index >= 0 and -1) and review
state updates via the action buttons.  Uses the shared ``qapp`` fixture
from ``tests/conftest.py``.

Run: pytest tests/test_quality_review_widget.py -v
"""

import os.path as osp
import sys

import pytest

sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

from PyQt6.QtCore import Qt  # noqa: E402

from anylabeling.views.labeling.widgets.inspector.quality.quality_review_queue import (  # noqa: E402
    QualityReviewItem,
)
from anylabeling.views.labeling.widgets.inspector.quality_review_widget import (  # noqa: E402
    QualityReviewWidget,
)

pytest.importorskip("PyQt6")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _seed_queue(widget, items):
    """Populate the widget's queue with ``items`` and refresh the tree."""
    for it in items:
        widget.queue._items[it.issue_id] = it
    widget.populate()


def _make_item(
    issue_id,
    file_path,
    shape_index,
    severity="warning",
    rule_id="L2-01",
    rule_name="face_matched_head_candidate",
):
    return QualityReviewItem(
        issue_id=issue_id,
        run_id="run",
        file_path=file_path,
        shape_index=shape_index,
        rule_id=rule_id,
        rule_name=rule_name,
        severity=severity,
        message=f"issue {issue_id}",
        primary_metric_name="face_head_match_gap",
        primary_metric_value=0.7,
    )


@pytest.fixture
def widget(qapp):
    w = QualityReviewWidget()
    yield w
    w.deleteLater()


def _leaf_items(widget):
    """Yield (tree_item, role_data) for every issue leaf in the tree."""
    role = Qt.ItemDataRole.UserRole
    for i in range(widget.tree.topLevelItemCount()):
        top = widget.tree.topLevelItem(i)
        for j in range(top.childCount()):
            child = top.child(j)
            data = child.data(0, role) or {}
            if data.get("type") == "issue":
                yield child, data


# ---------------------------------------------------------------------------
# G6 — navigation signals
# ---------------------------------------------------------------------------


class TestNavigation:
    def test_click_issue_emits_file_and_shape(self, widget):
        _seed_queue(
            widget,
            [_make_item("id1", "/abs/file.json", 3)],
        )
        emitted = []
        widget.issue_clicked.connect(lambda *a: emitted.append(a))
        leaf, _ = next(_leaf_items(widget))
        widget.tree.setCurrentItem(leaf)
        widget._on_item_clicked(leaf, 0)
        assert emitted == [("/abs/file.json", 3)]

    def test_file_level_issue_emits_minus_one(self, widget):
        # shape_index == -1 → only navigate to file, no shape selection
        _seed_queue(
            widget,
            [_make_item("id1", "/abs/file.json", -1)],
        )
        emitted = []
        widget.issue_clicked.connect(lambda *a: emitted.append(a))
        leaf, _ = next(_leaf_items(widget))
        widget._on_item_clicked(leaf, 0)
        assert emitted == [("/abs/file.json", -1)]

    def test_group_row_does_not_navigate(self, widget):
        _seed_queue(
            widget,
            [_make_item("id1", "/f.json", 0)],
        )
        emitted = []
        widget.issue_clicked.connect(lambda *a: emitted.append(a))
        # click the top-level group row
        top = widget.tree.topLevelItem(0)
        widget._on_item_clicked(top, 0)
        assert emitted == [], "group rows must not navigate"


# ---------------------------------------------------------------------------
# review action updates queue state
# ---------------------------------------------------------------------------


class TestReviewActions:
    def test_false_positive_button_updates_status(self, widget):
        _seed_queue(
            widget,
            [_make_item("id1", "/f.json", 0)],
        )
        leaf, _ = next(_leaf_items(widget))
        widget.tree.setCurrentItem(leaf)

        recorded = []
        widget.review_changed.connect(lambda: recorded.append(True))
        widget._apply_status("false_positive")

        item = widget.queue.get("id1")
        assert item.status == "false_positive"
        assert item.decision == "false_positive"
        assert item.final_action == "ignored"
        assert recorded, "review_changed should fire"

    def test_fixed_button_updates_status(self, widget):
        _seed_queue(
            widget,
            [_make_item("id1", "/f.json", 0)],
        )
        leaf, _ = next(_leaf_items(widget))
        widget.tree.setCurrentItem(leaf)
        widget._apply_status("fixed")
        item = widget.queue.get("id1")
        assert item.status == "fixed"
        assert item.decision == "fixed"
        assert item.final_action == "fixed_box"

    def test_fixed_button_uses_selected_final_action(self, widget):
        _seed_queue(
            widget,
            [_make_item("id1", "/f.json", 0)],
        )
        leaf, _ = next(_leaf_items(widget))
        widget.tree.setCurrentItem(leaf)
        idx = widget.fixed_action_combo.findData("fixed_label")
        widget.fixed_action_combo.setCurrentIndex(idx)
        widget._apply_status("fixed")
        assert widget.queue.get("id1").final_action == "fixed_label"

    def test_confirm_error_button(self, widget):
        _seed_queue(
            widget,
            [_make_item("id1", "/f.json", 0)],
        )
        leaf, _ = next(_leaf_items(widget))
        widget.tree.setCurrentItem(leaf)
        widget._apply_status("confirmed_error")
        item = widget.queue.get("id1")
        assert item.status == "confirmed_error"
        assert item.decision == "confirmed_error"
        assert item.final_action == "none"

    def test_clear_resets_to_pending(self, widget):
        # first mark false_positive, then clear
        _seed_queue(
            widget,
            [_make_item("id1", "/f.json", 0)],
        )
        leaf, _ = next(_leaf_items(widget))
        widget.tree.setCurrentItem(leaf)
        widget._apply_status("false_positive")
        assert widget.queue.get("id1").status == "false_positive"
        widget._apply_status("pending")
        item = widget.queue.get("id1")
        assert item.status == "pending"
        assert item.decision == ""

    def test_note_edit_updates_item(self, widget):
        _seed_queue(
            widget,
            [_make_item("id1", "/f.json", 0)],
        )
        leaf, _ = next(_leaf_items(widget))
        widget.tree.setCurrentItem(leaf)
        widget.note_edit.setText("borderline case")
        widget._on_note_committed()
        assert widget.queue.get("id1").note == "borderline case"

    def test_auto_advance_stays_in_current_rule_group(self, widget):
        _seed_queue(
            widget,
            [
                _make_item("a1", "/f.json", 0, rule_id="L2-01"),
                _make_item("a2", "/f.json", 1, rule_id="L2-01"),
                _make_item(
                    "b1",
                    "/f.json",
                    2,
                    rule_id="L2-02",
                    rule_name="face_inside_matched_head",
                ),
            ],
        )
        leaf, data = next(_leaf_items(widget))
        assert data["issue_id"] == "a1"
        widget.tree.setCurrentItem(leaf)
        widget._apply_status("fixed")
        assert widget.get_selected_item().issue_id == "a2"

    def test_auto_advance_stays_in_rule_name_when_rule_id_empty(self, widget):
        _seed_queue(
            widget,
            [
                _make_item(
                    "a1",
                    "/f.json",
                    0,
                    rule_id="",
                    rule_name="face_head_center_alignment",
                ),
                _make_item(
                    "a2",
                    "/f.json",
                    1,
                    rule_id="",
                    rule_name="face_head_center_alignment",
                ),
                _make_item(
                    "b1",
                    "/f.json",
                    2,
                    rule_id="",
                    rule_name="cross_class_size_order",
                ),
                _make_item(
                    "c1",
                    "/f.json",
                    3,
                    rule_id="",
                    rule_name="image_level_class_density",
                ),
            ],
        )
        leaf, data = next(_leaf_items(widget))
        assert data["issue_id"] == "a1"
        widget.tree.setCurrentItem(leaf)
        widget._apply_status("fixed")
        assert widget.get_selected_item().issue_id == "a2"


# ---------------------------------------------------------------------------
# filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    def test_current_file_filter(self, widget):
        _seed_queue(
            widget,
            [
                _make_item("a", "/labels/file_one.json", 0),
                _make_item("b", "/file_two.json", 1),
            ],
        )
        widget.set_current_file("/images/file_one.jpg")
        widget.current_file_chk.setChecked(True)
        widget._repopulate()
        # only file_one's issue should be visible as a leaf
        visible_ids = [d["issue_id"] for _, d in _leaf_items(widget)]
        assert visible_ids == ["a"]

    def test_suggestion_disabled_without_report(self, widget):
        _seed_queue(
            widget,
            [_make_item("id1", "/f.json", 0)],
        )
        widget._update_action_state()
        assert not widget.suggest_btn.isEnabled()

    def test_severity_filter(self, widget):
        _seed_queue(
            widget,
            [
                _make_item("a", "/f.json", 0, severity="error"),
                _make_item("b", "/f.json", 1, severity="warning"),
            ],
        )
        idx = widget.severity_filter.findData("error")
        widget.severity_filter.setCurrentIndex(idx)
        widget._repopulate()
        visible_ids = [d["issue_id"] for _, d in _leaf_items(widget)]
        assert visible_ids == ["a"]


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_counts_after_review(self, widget):
        _seed_queue(
            widget,
            [
                _make_item("a", "/f.json", 0),
                _make_item("b", "/f.json", 1),
            ],
        )
        # mark one false_positive directly through the queue
        widget.queue.update_review("a", status="false_positive")
        widget._update_summary(2)
        text = widget.summary_label.text()
        assert "误报 1" in text
        assert "总 2" in text

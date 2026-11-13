"""Off-screen Qt coverage for 7.2 field completeness, 5.5 review entry and 7.5 focus.

The review and completeness cases drive the real controller against a scratch
SQLite database; the focus and narrow-width cases use the panel directly so
they do not depend on the host window's activation behaviour.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - real console
        pass

from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from anylabeling.views.labeling.correction_metrics import i18n
from anylabeling.views.labeling.correction_metrics.panel import (
    CorrectionMetricsPanel,
)

IMAGE = str(
    Path(__file__).resolve().parents[2] / "anylabeling" / "resources" / "images" / "icon.png"
)


def rect(sid, label, x):
    return {
        "xanylabeling_shape_id": sid,
        "label": label,
        "shape_type": "rectangle",
        "points": [[x, 0], [x + 10, 10]],
    }


class Canvas(QWidget):
    """Minimal stand-in for the labeling canvas."""

    def __init__(self, shapes, parent=None):
        super().__init__(parent)
        self.shapes = list(shapes)
        self.selected_shapes = []
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_selected(self, shapes):
        self.selected_shapes = list(shapes)


class Host(QWidget):
    def __init__(self, shapes, parent=None):
        super().__init__(parent)
        self.filename = IMAGE
        self.output_dir = ""
        self.canvas = Canvas(shapes, self)
        self.canvas.resize(200, 120)


@pytest.fixture
def host(tmp_path):
    widget = Host([rect("a" * 32, "person", 0)])
    widget.resize(640, 480)
    widget.show()
    widget.canvas.show()
    QApplication.processEvents()
    yield widget
    widget.hide()
    widget.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def controller(host, tmp_path):
    # Imported here so the focus/narrow/i18n cases still run while a teammate
    # is editing controller.py; only the real-controller cases need it.
    from anylabeling.views.labeling.correction_metrics.controller import (
        CorrectionMetricsController,
    )

    instance = CorrectionMetricsController(
        host, language="en_US", storage_root=tmp_path / "metrics"
    )
    assert instance.start_scope(os.path.dirname(IMAGE)) is True
    assert instance.enter_image() is True
    yield instance
    instance.stop()


def panel_of(controller):
    assert controller.show_panel() is True
    panel = controller.panel
    QApplication.processEvents()
    return panel


def test_panel_shows_every_required_field(controller, host):
    """7.2: source, round, timing, counts, nets, completion and integrity."""
    panel = panel_of(controller)
    row = controller.current_row(draft=True)
    assert row is not None

    required = (
        "origin",
        "round",
        "phase",
        "timer_state",
        "time",
        "model_runtime",
        "blocking_time",
        "baseline_count",
        "current_count",
        "transactions",
        "unique_objects",
        "touches",
        "completed",
        "comparable",
        "issues",
        "quality",
    )
    for field in required:
        assert field in panel._fields, field
        assert panel.field_text(field) != "", field

    for field in (
        "added",
        "deleted",
        "geometry_changed",
        "class_changed",
        "modified_original",
        "modified_rate",
    ):
        for prefix in ("draft", "saved"):
            key = "%s_%s" % (prefix, field)
            assert key in panel._fields, key
            assert panel.field_text(key) != "", key

    # Draft and saved stay separate, and a real edit marks the draft unsaved.
    assert panel.field_text("draft_added") == "0"
    assert panel.field_text("saved_added") == "0"
    assert panel.unsaved_badge.isHidden() is True

    host.canvas.shapes.append(rect("c" * 32, "car", 40))
    controller.edit("create", source="manual", changed=[host.canvas.shapes[-1]])
    controller.refresh_panel()
    assert panel.field_text("draft_added") == "1"
    assert panel.field_text("saved_added") == "0"
    assert panel.unsaved_badge.isHidden() is False
    assert panel.field_text("transactions") == "1"
    assert panel.field_text("touches") == "1"


def test_dataset_scope_is_visible(controller):
    """7.1: the enabled dataset scope is visible in the panel header area."""
    panel = panel_of(controller)
    assert panel.field_text("dataset") != ""
    assert controller.scope_label
    assert panel.field_text("dataset") == controller.scope_label

    class Scoped:
        available = True
        language = "en_US"
        scope_label = "images"

        def current_row(self, draft=True):
            return None

        def state(self):
            return {"state": "inactive", "seconds": 0.0, "idle_waiting": False}

        def pause(self, value):
            pass

        def finish_round(self):
            return True

        def start_review(self):
            return True

        def degraded_reason(self):
            return None

    widget = CorrectionMetricsPanel(Scoped())
    widget.show()
    try:
        assert widget.field_text("dataset") == "images"
    finally:
        widget.hide()
        widget.deleteLater()
        QApplication.processEvents()

    class Unscoped:
        available = True
        language = "en_US"
        scope_label = None

        def current_row(self, draft=True):
            return None

        def state(self):
            return None

    blank = CorrectionMetricsPanel(Unscoped())
    blank.show()
    try:
        assert blank.field_text("dataset") == "N/A"
    finally:
        blank.hide()
        blank.deleteLater()
        QApplication.processEvents()


def test_timer_state_covers_every_state_and_seconds(controller):
    panel = panel_of(controller)
    row = controller.current_row(draft=True)
    for state in ("working", "paused", "inactive", "closed", "not_ready"):
        panel.refresh_with(row, {"state": state, "seconds": 42.0, "idle_waiting": False})
        assert panel.field_text("timer_state") == i18n.tr(state, language="en_US")
        assert panel.field_text("time") == i18n.tr("seconds", seconds=42)
    # Missing seconds is N/A, not a fake zero.
    panel.refresh_with(row, {"state": "paused", "seconds": None})
    assert panel.field_text("time") == "N/A"


def test_start_review_opens_a_separate_review_round(controller):
    """5.5: the review entry creates a review-phase round and keeps history."""
    panel = panel_of(controller)
    correction_row = controller.current_row(draft=True)
    assert correction_row["phase"] == "correction"
    assert panel.review_button.isVisible() is True
    assert panel.review_button.isEnabled() is True
    assert panel.review_button.text() == i18n.tr("review", language="en_US")

    panel.review_button.click()
    QApplication.processEvents()

    review_row = controller.current_row(draft=True)
    assert review_row is not None
    assert review_row["phase"] == "review"
    assert review_row["round_id"] != correction_row["round_id"]

    # The correction round stays queryable, together with the review round.
    rounds = controller.rows()
    phases = {
        row.get("phase") for row in rounds
        if row.get("round_id") in (correction_row["round_id"], review_row["round_id"])
    }
    assert phases == {"correction", "review"}
    assert controller.count() >= 2

    # The panel shows the review stage and its own completion wording.
    controller.refresh_panel()
    assert panel.field_text("phase") == i18n.tr("phase_review", language="en_US")
    assert panel.phase_tag.isHidden() is False
    assert panel.phase_tag.text() == i18n.tr("review_tag", language="en_US")
    assert panel.finish_button.text() == i18n.tr("finish_review", language="en_US")
    # A second review round is not offered from inside the review round.
    assert panel.review_button.isEnabled() is False
    assert panel.review_button.toolTip() == i18n.tr(
        "already_in_review", language="en_US"
    )


def test_panel_and_children_never_take_focus(controller):
    """7.5: read-only panel with no focusable children."""
    panel = panel_of(controller)
    assert panel.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert panel.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
    assert panel.isWindow() is False

    for widget in panel.findChildren(QWidget):
        assert widget.focusPolicy() == Qt.FocusPolicy.NoFocus, widget.objectName()


def test_standalone_panel_is_a_tool_window_that_does_not_activate():
    """7.5: a top-level panel is a Tool window; a sidebar panel stays a child."""
    standalone = CorrectionMetricsPanel(None)
    try:
        assert standalone.windowFlags() & Qt.WindowType.Tool
        assert standalone.isWindow() is True
        assert (
            standalone.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            is True
        )
    finally:
        standalone.hide()
        standalone.deleteLater()
        QApplication.processEvents()


def test_opening_the_panel_keeps_focus_and_selection(controller, host):
    """7.5: showing the panel must not steal the canvas focus or its selection."""
    host.canvas.setFocus()
    QApplication.processEvents()
    before_focus = QApplication.focusWidget()
    host.canvas.set_selected([host.canvas.shapes[0]])
    before_selection = list(host.canvas.selected_shapes)

    panel = panel_of(controller)
    QApplication.processEvents()

    after_focus = QApplication.focusWidget()
    assert after_focus is before_focus
    if after_focus is not None:
        assert after_focus is not panel
        assert not panel.isAncestorOf(after_focus)
    assert host.canvas.selected_shapes == before_selection
    assert panel.isVisible() is True


def test_review_controls_fit_a_narrow_sidebar():
    """7.5: the review button and stage tag fit 240 and 320 px without overlap."""
    row = {
        "round_id": "0123456789abcdef0123456789abcdef",
        "origin": "unknown-existing",
        "phase": "review",
        "revision": "rev-1",
        "completed": False,
        "completion": None,
        "quality": "not-assessed",
        "checked": None,
        "baseline_count": 5,
        "final_count": 5,
        "added": 0,
        "deleted": 0,
        "geometry_changed": 1,
        "class_changed": 0,
        "modified_original": 1,
        "modified_rate": 0.2,
        "transactions": 3,
        "touches": 4,
        "unique_objects": 2,
        "issues": [],
        "comparable": True,
        "is_draft": False,
        "time": {"working": 60.0, "adjusted_working": 60.0},
    }

    class Controller:
        available = True
        language = "en_US"

        def current_row(self, draft=True):
            return dict(row)

        def state(self):
            return {"state": "working", "seconds": 60.0, "idle_waiting": False}

        def pause(self, value):
            pass

        def finish_round(self):
            return True

        def start_review(self):
            return True

        def resume_round(self):
            return True

        def confirm_idle(self, exclude):
            return {}

        def degraded_reason(self):
            return None

    panel = CorrectionMetricsPanel(Controller())
    panel.show()
    try:
        assert panel.phase_tag.isHidden() is False
        assert panel.review_button.isHidden() is False
        assert panel.minimumSizeHint().width() <= 240

        leaves = (QLabel, QPushButton, QToolButton)
        for width in (240, 320):
            panel.resize(width, panel.sizeHint().height())
            QApplication.processEvents()
            panel_width = panel.width()
            rectangles = []
            for child in panel.findChildren(QWidget):
                if not isinstance(child, leaves) or not child.isVisible():
                    continue
                rect_ = QRect(child.mapTo(panel, QPoint(0, 0)), child.size())
                assert rect_.left() >= 0, (width, child.objectName(), rect_)
                assert rect_.right() <= panel_width, (width, child.objectName(), rect_)
                rectangles.append((child.objectName() or repr(child), rect_))
            for index, (name, rect_) in enumerate(rectangles):
                for other_name, other in rectangles[index + 1:]:
                    assert not rect_.intersects(other), (width, name, other_name)
    finally:
        panel.hide()
        panel.deleteLater()
        QApplication.processEvents()


def test_review_keys_exist_in_all_four_languages():
    for key in (
        "review",
        "review_tag",
        "finish_review",
        "already_in_review",
        "phase_review",
    ):
        for language in i18n.LANGUAGES:
            text = i18n.tr(key, language=language)
            assert text, (language, key)
            assert text != key, (language, key)
    for key in ("review_tag", "finish_review", "already_in_review"):
        english = i18n.tr(key, language="en_US")
        for language in ("zh_CN", "ja_JP", "ko_KR"):
            assert i18n.tr(key, language=language) != english, (language, key)


# ---------------------------------------------------------------------------
# Tasks 6.5 / 3.3 -- model runtime apart from work time; recovery entry
# ---------------------------------------------------------------------------
def test_model_runtime_and_blocking_wait_are_shown_apart_from_work_time(
    controller,
):
    """6.5：面板并列显示模型运行与阻塞等待，处理时间不被相加。"""
    panel = panel_of(controller)
    row = dict(controller.current_row(draft=True))
    row["inference_seconds"] = 20.0
    row["time"] = dict(row.get("time") or {}, working=20.0, blocking_wait=7.0)
    panel.refresh_with(row, controller.state())

    assert "20" in panel.field_text("model_runtime")
    assert "7" in panel.field_text("blocking_time")
    assert panel.field_text("time") != panel.field_text("model_runtime")
    for field in ("model_runtime", "blocking_time"):
        assert field in panel._fields
        assert panel.field_text(field) != ""


def test_retry_button_appears_only_for_a_recording_problem(controller):
    """3.3：记录异常时提供重试入口；正常状态不占用动作区。"""
    panel = panel_of(controller)
    assert panel.retry_button.isHidden() is True

    panel.refresh_with(
        controller.current_row(draft=True),
        {**controller.state(), "degraded": "storage: disk full"},
    )
    assert panel.retry_button.isHidden() is False
    assert panel.retry_button.text() != ""

    panel.refresh_with(controller.current_row(draft=True), controller.state())
    assert panel.retry_button.isHidden() is True

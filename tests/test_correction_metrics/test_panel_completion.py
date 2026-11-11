"""Off-screen Qt coverage for idle confirmation, completion and quality display.

Covers task 6.4 (non-blocking idle confirmation), 5.5 (completed round display,
resume, browse-only reopening) and 5.6 (quality status that never claims a
round completion is a quality approval).
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - real console
        pass

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton, QWidget

from anylabeling.views.labeling.correction_metrics import i18n
from anylabeling.views.labeling.correction_metrics.panel import (
    CorrectionMetricsPanel,
)


ROUND_ID = "0123456789abcdef0123456789abcdef"
COMPLETION_ID = "fedcba9876543210fedcba9876543210"


def make_row(**overrides):
    row = {
        "round_id": ROUND_ID,
        "origin": "replacement",
        "phase": "correction",
        "revision": "rev-1",
        "completed": False,
        "completion": None,
        "quality": "not-assessed",
        "checked": None,
        "baseline_count": 5,
        "final_count": 6,
        "added": 2,
        "deleted": 1,
        "geometry_changed": 1,
        "class_changed": 0,
        "modified_original": 2,
        "modified_rate": 0.4,
        "transactions": 7,
        "touches": 12,
        "unique_objects": 5,
        "issues": [],
        "comparable": True,
        "is_draft": False,
        "time": {"working": 123.4, "paused": 0.0},
    }
    row.update(overrides)
    return row


class FakeController:
    """Controller stand-in with the idle/completion surface of the real one."""

    def __init__(self, row=None, saved=None, state=None, language="en_US"):
        self.row = row
        self.saved = saved
        self.state_value = (
            {
                "state": "working",
                "seconds": 12.0,
                "paused": False,
                "idle_waiting": False,
            }
            if state is None
            else dict(state)
        )
        self.language = language
        self.confirm_calls = []
        self.resume_calls = 0
        self.available = True

    @property
    def enabled(self):
        return True

    @property
    def degraded_reason(self):
        return None

    def state(self):
        return dict(self.state_value)

    def current_row(self, draft=True):
        row = self.row if draft else self.saved
        return None if row is None else dict(row)

    def pause(self, value):
        self.state_value["state"] = "paused" if value else "working"

    def finish_round(self):
        return True

    def resume_round(self):
        self.resume_calls += 1
        if self.row is not None:
            self.row["completed"] = False
        return True

    def confirm_idle(self, exclude):
        self.confirm_calls.append(bool(exclude))
        self.state_value["idle_waiting"] = False
        return dict(self.state_value)


class StickyIdleController(FakeController):
    """Keeps reporting pending idle time: the panel must not re-prompt twice."""

    def confirm_idle(self, exclude):
        self.confirm_calls.append(bool(exclude))
        return dict(self.state_value)


@pytest.fixture
def build_panel():
    panels = []

    def build(controller=None, **kwargs):
        widget = CorrectionMetricsPanel(controller, **kwargs)
        widget.show()
        QApplication.processEvents()
        panels.append(widget)
        return widget

    yield build
    for widget in panels:
        widget.hide()
        widget.deleteLater()
    QApplication.processEvents()


def test_idle_prompt_appears_and_include_counts_as_work(build_panel):
    controller = FakeController(
        row=make_row(),
        state={"state": "working", "seconds": 130.0, "idle_waiting": True},
    )
    widget = build_panel(controller)
    assert widget.idle_bar.isVisible() is True
    assert widget.idle_question.text() == i18n.tr("idle_question", language="en_US")
    assert widget.idle_include_button.text() == i18n.tr(
        "idle_include_button", language="en_US"
    )

    widget.idle_include_button.click()
    assert controller.confirm_calls == [False]
    assert widget.idle_bar.isVisible() is False


def test_idle_prompt_exclude_excludes_the_idle_time(build_panel):
    controller = FakeController(
        row=make_row(),
        state={"state": "working", "seconds": 130.0, "idle_waiting": True},
    )
    widget = build_panel(controller)
    assert widget.idle_exclude_button.text() == i18n.tr(
        "idle_exclude_button", language="en_US"
    )

    widget.idle_exclude_button.click()
    assert controller.confirm_calls == [True]
    assert widget.idle_bar.isVisible() is False


def test_idle_prompt_is_hidden_without_pending_idle_and_never_repeats(build_panel):
    quiet = FakeController(row=make_row(), state={"state": "working", "seconds": 5.0})
    assert build_panel(quiet).idle_bar.isVisible() is False

    sticky = StickyIdleController(
        row=make_row(),
        state={"state": "working", "seconds": 130.0, "idle_waiting": True},
    )
    widget = build_panel(sticky)
    assert widget.idle_bar.isVisible() is True
    widget.idle_include_button.click()
    assert sticky.confirm_calls == [False]
    # Same segment: refreshing again must not re-prompt.
    widget.refresh()
    assert widget.idle_bar.isVisible() is False

    # A new pending-idle segment prompts again.
    sticky.state_value["idle_waiting"] = False
    widget.refresh()
    sticky.state_value["idle_waiting"] = True
    widget.refresh()
    assert widget.idle_bar.isVisible() is True


def test_completed_round_disables_finish_and_offers_resume(build_panel):
    row = make_row(completed=True, completion={"id": COMPLETION_ID})
    controller = FakeController(row=row, saved=make_row(completed=True))
    widget = build_panel(controller)

    assert widget.finish_button.isEnabled() is False
    assert widget.finish_button.toolTip() == i18n.tr(
        "already_completed", language="en_US"
    )
    assert widget.resume_button.isVisible() is True
    assert widget.resume_button.isEnabled() is True
    assert widget.resume_button.text() == i18n.tr("continue", language="en_US")

    # The host wiring in controller._build_panel connects exactly this signal.
    seen = []
    widget.resume_requested.connect(lambda: seen.append("resume"))
    widget.resume_requested.connect(controller.resume_round)
    widget.resume_button.click()
    assert seen == ["resume"]
    assert controller.resume_calls == 1
    # The panel re-read the controller and now allows finishing again.
    widget.refresh()
    assert widget.finish_button.isEnabled() is True
    assert widget.resume_button.isVisible() is False


def test_unwired_actions_fall_back_to_the_controller(build_panel):
    """Without host wiring the panel still drives the controller, exactly once."""
    row = make_row(completed=True, completion={"id": COMPLETION_ID})
    controller = FakeController(row=row, saved=make_row(completed=True))
    widget = build_panel(controller)

    # No host wiring exists here, so the panel drives the controller itself.
    assert widget.receivers(widget.resume_requested) == 0
    widget.resume_button.click()
    assert controller.resume_calls == 1
    widget.refresh()
    assert widget.resume_button.isVisible() is False


def test_completed_round_freezes_time_and_shows_completion_record(build_panel):
    row = make_row(completed=True, completion={"id": COMPLETION_ID})
    widget = build_panel(FakeController(row=row, saved=make_row(completed=True)))

    assert widget.label_text("time") == i18n.tr("frozen_time", language="en_US")
    assert widget.field_text("time") == i18n.tr("seconds", seconds=123)
    assert widget.field_text("completion_record") == COMPLETION_ID[:8]
    assert widget.field_text("completed") == i18n.tr("completed", language="en_US")

    running = build_panel(FakeController(row=make_row(), saved=make_row()))
    assert running.label_text("time") == i18n.tr("time", language="en_US")
    assert running.field_text("completion_record") == "N/A"


def test_reopened_completed_image_says_browsing_only(build_panel):
    row = make_row(completed=True, completion={"id": COMPLETION_ID})
    closed = FakeController(
        row=row, saved=make_row(completed=True), state={"state": "closed", "seconds": 123.0}
    )
    widget = build_panel(closed)
    assert widget.browse_label.isVisible() is True
    assert widget.browse_label.text() == i18n.tr("browse_only", language="en_US")

    working = build_panel(
        FakeController(
            row=make_row(completed=True, completion={"id": COMPLETION_ID}),
            saved=make_row(completed=True),
            state={"state": "working", "seconds": 12.0},
        )
    )
    assert working.browse_label.isVisible() is False


def test_quality_needs_assessment_and_never_claims_approval(build_panel):
    widget = build_panel(FakeController(row=make_row(), saved=make_row()))
    assert widget.field_text("quality") == i18n.tr("not-assessed", language="en_US")
    assert widget.quality_note_label.isVisible() is True
    assert widget.quality_note_label.text() == i18n.tr(
        "quality_note", language="en_US"
    )
    note = widget.quality_note_label.text().lower()
    assert "approved" not in note
    assert "pass" not in note
    # A round may be complete while its quality stays not assessed.
    assert widget.field_text("completed") == i18n.tr("unfinished", language="en_US")

    marked = build_panel(
        FakeController(row=make_row(quality="checked", checked=True), saved=make_row())
    )
    assert marked.field_text("quality") == "checked"
    assert marked.field_text("checked_marker") == i18n.tr("yes", language="en_US")

    blank = build_panel(FakeController(row=make_row(quality=None), saved=None))
    assert blank.field_text("quality") == "N/A"
    assert blank.field_text("checked_marker") == "N/A"


def test_new_strings_exist_in_all_four_languages():
    keys = (
        "idle_question",
        "idle_keep",
        "idle_exclude",
        "idle_include_button",
        "idle_exclude_button",
        "browse_only",
        "quality_note",
        "checked_marker",
        "completion_record",
        "frozen_time",
        "continue",
        "not-assessed",
        "already_completed",
    )
    for language in i18n.LANGUAGES:
        for key in keys:
            text = i18n.tr(key, language=language)
            assert text, (language, key)
            assert text != key, (language, key)

    for key in (
        "idle_question",
        "browse_only",
        "quality_note",
        "checked_marker",
        "completion_record",
        "frozen_time",
    ):
        english = i18n.tr(key, language="en_US")
        for language in ("zh_CN", "ja_JP", "ko_KR"):
            assert i18n.tr(key, language=language) != english, (language, key)


def test_excluded_idle_lowers_the_displayed_work_time(build_panel):
    """An excluded idle segment must not keep showing raw working seconds."""
    row = make_row(
        time={
            "working": 130.0,
            "pending_idle": 0.0,
            "excluded_idle": 130.0,
            "adjusted_working": 0.0,
        }
    )
    widget = build_panel(FakeController(row=row, saved=make_row()))
    assert widget.field_text("time") == i18n.tr("seconds", seconds=0)
    assert i18n.tr("idle_excluded_note", seconds=130) in widget._fields["time"].toolTip()

    kept = make_row(
        time={"working": 130.0, "pending_idle": 0.0, "excluded_idle": 0.0,
              "adjusted_working": 130.0}
    )
    widget = build_panel(
        FakeController(
            row=kept,
            saved=make_row(),
            state={"state": "working", "seconds": 130.0, "idle_waiting": False},
        )
    )
    assert widget.field_text("time") == i18n.tr("seconds", seconds=130)


def test_idle_bar_fits_a_narrow_sidebar(build_panel):
    controller = FakeController(
        row=make_row(completed=True, completion={"id": COMPLETION_ID}),
        saved=make_row(completed=True),
        state={"state": "closed", "seconds": 130.0, "idle_waiting": True},
    )
    widget = build_panel(controller)
    assert widget.minimumSizeHint().width() <= 240

    leaves = (QLabel, QPushButton, QToolButton)
    widget.resize(240, widget.sizeHint().height())
    QApplication.processEvents()
    panel_width = widget.width()
    rectangles = []
    for child in widget.findChildren(QWidget):
        if not isinstance(child, leaves) or not child.isVisible():
            continue
        rect = QRect(child.mapTo(widget, QPoint(0, 0)), child.size())
        assert rect.left() >= 0, (child.objectName(), rect)
        assert rect.right() <= panel_width, (child.objectName(), rect)
        rectangles.append((child.objectName() or repr(child), rect))
    for index, (name, rect) in enumerate(rectangles):
        for other_name, other in rectangles[index + 1:]:
            assert not rect.intersects(other), (name, other_name)

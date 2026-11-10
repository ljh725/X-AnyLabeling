"""Off-screen Qt coverage for the collapsible current-image cost panel.

The panel is a pure view over a controller: these cases pin the display
contract from design D7 (source / round / stage, timing, box counts,
transactions and unique touches, draft versus saved net result with an
explicit unsaved marker, completion, integrity reasons, N/A instead of a fake
zero) and the three actions.  Nothing here imports the statistics service.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The sandbox console may decode as ASCII; keep assertion dumps readable.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - real console
        pass

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from anylabeling.views.labeling.correction_metrics import i18n
from anylabeling.views.labeling.correction_metrics import panel as panel_module
from anylabeling.views.labeling.correction_metrics.hooks import (
    metrics_pending_message,
)
from anylabeling.views.labeling.correction_metrics.panel import (
    CorrectionMetricsPanel,
)


ROUND_ID = "0123456789abcdef0123456789abcdef"

#: Message keys the panel renders; every catalogue must cover all of them.
PANEL_KEYS = (
    "title",
    "current_image",
    "origin",
    "round",
    "phase",
    "correction",
    "phase_review",
    "baseline_count",
    "current",
    "timing",
    "time",
    "working",
    "paused",
    "inactive",
    "blocking_wait",
    "not_ready",
    "closed",
    "seconds",
    "operations",
    "transactions",
    "unique_objects",
    "touches",
    "draft",
    "saved",
    "added",
    "deleted",
    "geometry_changed",
    "class_changed",
    "modified_original",
    "modified_rate",
    "integrity",
    "processing",
    "completed",
    "unfinished",
    "comparable",
    "issues",
    "clean",
    "yes",
    "no",
    "complete",
    "pause",
    "resume",
    "start",
    "report",
    "need_image",
    "save_before_complete",
    "already_completed",
    "idle_pending",
    "degraded",
    "collapse",
    "expand",
)


def make_row(**overrides):
    """One saved, comparable row with every field the panel reads."""
    row = {
        "round_id": ROUND_ID,
        "origin": "replacement",
        "phase": "correction",
        "revision": "rev-1",
        "completed": False,
        "baseline_count": 5,
        "final_count": 6,
        "added": 2,
        "deleted": 1,
        "geometry_changed": 1,
        "class_changed": 0,
        "modified_original": 2,
        "unchanged": 3,
        "modified_rate": 0.4,
        "unchanged_rate": 0.6,
        "unsupported_count": 0,
        "scope_changes": 0,
        "transactions": 7,
        "undo_count": 1,
        "touches": 12,
        "unique_objects": 5,
        "ai_count": 3,
        "issues": [],
        "comparable": True,
        "is_draft": False,
        "quality": "not-assessed",
        "image_path": "C:/images/x.png",
    }
    row.update(overrides)
    return row


class FakeController:
    """Duck-typed stand-in exposing exactly the documented public API."""

    def __init__(
        self,
        row=None,
        saved=None,
        state=None,
        available=True,
        enabled=True,
        language="en_US",
        degraded=None,
    ):
        self.row = row
        self.saved = saved
        self.state_value = (
            {"state": "working", "seconds": 12.0, "idle_waiting": False}
            if state is None
            else dict(state)
        )
        self.available_value = available
        self.enabled_value = enabled
        self.language = language
        self.degraded = degraded
        self.calls = []

    @property
    def available(self):
        return self.available_value

    @property
    def enabled(self):
        return self.enabled_value

    @property
    def degraded_reason(self):
        return self.degraded

    def state(self):
        return dict(self.state_value)

    def current_row(self, draft=True):
        row = self.row if draft else self.saved
        return None if row is None else dict(row)

    def pause(self, value):
        self.calls.append(("pause", value))
        self.state_value["state"] = "paused" if value else "working"

    def finish_round(self):
        self.calls.append(("finish_round",))
        return True

    def resume_round(self):
        self.calls.append(("resume_round",))
        return True

    def rows(self, limit=None, offset=0):
        return []

    def count(self):
        return 0 if self.row is None else 1


@pytest.fixture
def build_panel():
    """Create a shown panel and clean it up with the off-screen app."""
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


def test_missing_controller_keeps_controls_visible_but_disabled(build_panel):
    widget = build_panel()

    for button in (widget.pause_button, widget.finish_button, widget.summary_button):
        assert button.isEnabled() is False
        assert button.isVisible() is True

    assert widget.ready is False
    assert widget.banner.isVisible() is True
    assert widget.banner.text() == metrics_pending_message("en_US")
    assert widget.field_text("origin") == "N/A"
    assert widget.field_text("draft_added") == "N/A"
    # Refreshing without data must stay quiet instead of raising.
    widget.refresh_with(None, None)
    assert widget.field_text("timer_state") == "N/A"


def test_unavailable_workspace_disables_controls_with_localised_hint():
    widget = CorrectionMetricsPanel(
        FakeController(available=False, language="zh_CN")
    )
    widget.show()
    try:
        assert widget.ready is False
        assert widget.pause_button.isEnabled() is False
        assert widget.finish_button.isEnabled() is False
        assert widget.summary_button.isEnabled() is False
        assert widget.banner.isVisible() is True
        assert widget.banner.text() == metrics_pending_message("zh_CN")
    finally:
        widget.hide()
        widget.deleteLater()


def test_na_replaces_missing_values_but_zero_stays_zero(build_panel):
    draft = make_row(
        added=0,
        deleted=None,
        geometry_changed=None,
        modified_original=None,
        modified_rate=None,
        baseline_count=0,
    )
    widget = build_panel(FakeController(row=draft, saved=None))

    assert widget.field_text("draft_added") == "0"
    assert widget.field_text("draft_deleted") == "N/A"
    assert widget.field_text("draft_geometry_changed") == "N/A"
    assert widget.field_text("draft_modified_rate") == "N/A"
    assert widget.field_text("saved_added") == "N/A"
    assert widget.field_text("baseline_count") == "0"
    assert widget.field_text("current_count") == "6"


def test_draft_marks_the_result_as_unsaved(build_panel):
    draft = build_panel(
        FakeController(row=make_row(is_draft=True), saved=make_row(is_draft=False))
    )
    assert draft.unsaved_badge.isVisible() is True
    assert draft.unsaved_badge.text() == i18n.tr("unsaved", language="en_US")
    assert draft.unsaved_badge.toolTip() == i18n.tr("unsaved", language="en_US")

    localised = build_panel(
        FakeController(
            row=make_row(is_draft=True),
            saved=make_row(is_draft=False),
            language="zh_CN",
        )
    )
    assert localised.unsaved_badge.isVisible() is True
    assert i18n.tr("unsaved", language="zh_CN") in localised.unsaved_badge.toolTip()

    # A round that was never saved has no revision: still unsaved.
    never_saved = build_panel(
        FakeController(row=make_row(is_draft=False, revision=""), saved=None)
    )
    assert never_saved.unsaved_badge.isVisible() is True

    saved = build_panel(
        FakeController(row=make_row(is_draft=False, revision="rev-2"), saved=None)
    )
    assert saved.unsaved_badge.isVisible() is False


def test_identity_timing_and_counter_rows(build_panel):
    row = make_row(origin="unknown-existing", phase="review")
    widget = build_panel(FakeController(row=row, saved=make_row()))

    assert widget.field_text("origin") == i18n.tr(
        "unknown-existing", language="en_US"
    )
    assert widget.field_text("round") == ROUND_ID[:8]
    assert widget.field_text("phase") == i18n.tr("phase_review", language="en_US")
    assert widget.field_text("timer_state") == i18n.tr("working", language="en_US")
    assert widget.field_text("time") == i18n.tr("seconds", seconds=12)
    assert widget.field_text("transactions") == "7"
    assert widget.field_text("unique_objects") == "5"
    assert widget.field_text("touches") == "12"
    assert widget.field_text("completed") == i18n.tr("unfinished", language="en_US")


def test_action_buttons_emit_signals_and_call_the_controller(build_panel):
    controller = FakeController(row=make_row(), saved=make_row())
    widget = build_panel(controller)
    # The host wiring in controller._build_panel connects exactly these signals.
    widget.pause_requested.connect(controller.pause)
    widget.finish_requested.connect(controller.finish_round)
    seen = []
    widget.pause_requested.connect(lambda value: seen.append(("pause", value)))
    widget.finish_requested.connect(lambda: seen.append(("finish",)))
    widget.summary_requested.connect(lambda: seen.append(("summary",)))

    assert widget.pause_button.text() == i18n.tr("pause", language="en_US")
    widget.pause_button.click()
    assert seen[-1] == ("pause", True)
    assert ("pause", True) in controller.calls
    # The panel re-read the controller after the action, so it now offers resume.
    assert widget.pause_button.text() == i18n.tr("resume", language="en_US")

    widget.pause_button.click()
    assert seen[-1] == ("pause", False)
    assert ("pause", False) in controller.calls

    widget.finish_button.click()
    assert ("finish",) in seen
    assert ("finish_round",) in controller.calls

    widget.summary_button.click()
    assert seen[-1] == ("summary",)


def test_controller_without_action_methods_disables_them(build_panel):
    class MinimalController:
        available = True
        language = "en_US"

        def current_row(self, draft=True):
            return make_row()

        def state(self):
            return {"state": "working", "seconds": 1.0, "idle_waiting": False}

    widget = build_panel(MinimalController())
    assert widget.ready is True
    assert widget.banner.isHidden() is True
    assert widget.pause_button.isEnabled() is False
    assert widget.finish_button.isEnabled() is False
    assert widget.summary_button.isEnabled() is True
    widget.pause_button.click()  # must be a no-op, never an exception


def test_finish_button_disabled_state_explains_itself(build_panel):
    completed = build_panel(
        FakeController(row=make_row(completed=True), saved=make_row(completed=True))
    )
    assert completed.finish_button.isEnabled() is False
    assert completed.finish_button.toolTip() == i18n.tr(
        "already_completed", language="en_US"
    )

    unsaved = build_panel(
        FakeController(row=make_row(is_draft=True), saved=None)
    )
    assert unsaved.finish_button.isEnabled() is False
    assert unsaved.finish_button.toolTip() == i18n.tr(
        "save_before_complete", language="en_US"
    )

    ready = build_panel(FakeController(row=make_row(), saved=make_row()))
    assert ready.finish_button.isEnabled() is True


def test_integrity_reasons_are_short_and_localised(build_panel):
    codes = ("partial-scope", "storage-gap", "unknown-origin")
    row = make_row(issues=list(codes), comparable=False)
    widget = build_panel(
        FakeController(row=row, saved=make_row(), language="zh_CN")
    )
    expected = " · ".join(i18n.tr_issue(code, language="zh_CN") for code in codes)
    assert widget.field_text("issues") == expected
    assert widget.field_text("issues") != " · ".join(codes)
    assert widget.field_text("comparable") == i18n.tr("no", language="zh_CN")

    clean = build_panel(
        FakeController(row=make_row(issues=[]), saved=make_row(), language="zh_CN")
    )
    assert clean.field_text("issues") == i18n.tr("clean", language="zh_CN")


def test_degraded_reason_is_disclosed(build_panel):
    widget = build_panel(
        FakeController(
            row=make_row(), saved=make_row(), degraded="storage-gap: locked"
        )
    )
    assert widget.degraded_label.isVisible() is True
    assert "storage-gap: locked" in widget.degraded_label.full_text()

    healthy = build_panel(FakeController(row=make_row(), saved=make_row()))
    assert healthy.degraded_label.isVisible() is False


def test_every_language_covers_every_panel_string():
    for language in i18n.LANGUAGES:
        for key in PANEL_KEYS:
            text = i18n.tr(key, language=language)
            assert text, (language, key)
            assert text != key, (language, key)

    # Strings newer than the compiled catalogue must not fall back to English.
    for key in (
        "unique_objects",
        "touches",
        "comparable",
        "phase_review",
        "issue_storage_gap",
        "issue_unknown_origin",
    ):
        english = i18n.tr(key, language="en_US")
        for language in ("zh_CN", "ja_JP", "ko_KR"):
            assert i18n.tr(key, language=language) != english, (language, key)

    for code in i18n.ISSUE_KEYS:
        for language in i18n.LANGUAGES:
            assert i18n.tr_issue(code, language=language) != code, (code, language)
    assert i18n.tr_issue("not-a-real-code", language="zh_CN") == "not-a-real-code"


def test_collapse_hides_the_body_and_restores_it(build_panel):
    widget = build_panel(FakeController(row=make_row(), saved=make_row()))
    assert widget.collapsed is False
    assert widget.body.isHidden() is False

    widget.set_collapsed(True)
    assert widget.collapsed is True
    assert widget.body.isHidden() is True
    assert widget.toggle_button.toolTip() == i18n.tr("expand", language="en_US")

    widget.toggle_button.click()
    assert widget.collapsed is False
    assert widget.body.isHidden() is False
    assert widget.toggle_button.toolTip() == i18n.tr("collapse", language="en_US")


def test_narrow_sidebar_never_clips_or_overlaps(build_panel):
    row = make_row(
        origin="unknown-existing",
        phase="review",
        issues=["partial-scope", "storage-gap", "unknown-origin"],
        comparable=False,
        modified_rate=None,
    )
    widget = build_panel(FakeController(row=row, saved=make_row(), language="zh_CN"))
    assert widget.minimumSizeHint().width() <= 240

    leaves = (QLabel, QPushButton, QToolButton)
    for width in (240, 320):
        widget.resize(width, widget.sizeHint().height())
        QApplication.processEvents()
        panel_width = widget.width()
        assert panel_width <= max(width, widget.minimumWidth())

        rectangles = []
        for child in widget.findChildren(QWidget):
            if not isinstance(child, leaves) or not child.isVisible():
                continue
            rect = QRect(child.mapTo(widget, QPoint(0, 0)), child.size())
            assert rect.left() >= 0, (width, child.objectName(), rect)
            assert rect.right() <= panel_width, (width, child.objectName(), rect)
            rectangles.append((child.objectName() or repr(child), rect))

        for index, (name, rect) in enumerate(rectangles):
            for other_name, other in rectangles[index + 1:]:
                assert not rect.intersects(other), (width, name, other_name)


def test_panel_consumes_only_the_controller_api():
    source = Path(panel_module.__file__).read_text(encoding="utf-8")
    assert "anylabeling.services" not in source
    assert "from ..services" not in source
    assert "from ...services" not in source

"""Collapsible sidebar panel with the correction cost of the current image.

The panel is a read-only view over a controller object.  It only calls the
public surface documented for ``controller`` (``available``, ``enabled``,
``degraded_reason``, ``state``, ``current_row``) and never imports the
statistics service, so a missing or half-initialised controller leaves every
control visible but disabled instead of raising.  The three actions are
emitted as signals (``pause_requested``, ``finish_requested``,
``summary_requested``); the host connects them to the controller, which keeps
one owner for every mutation.  A controller without an action method keeps
that button disabled.

Design reference: D7 -- source / round / stage, timer state and seconds,
starting and current rectangle counts, transactions, unique objects and
touches, the draft net result next to the saved one (the draft is explicitly
marked unsaved), completion, and the integrity of the record.  ``None`` is
shown as ``N/A``; a real zero stays ``0``.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .hooks import metrics_pending_message
from .i18n import LANGUAGES, tr, tr_issue


N_A = "N/A"

#: ``controller.state()["state"]`` value -> message key.
STATE_KEYS = {
    "working": "working",
    "paused": "paused",
    "inactive": "inactive",
    "blocking_wait": "blocking_wait",
    "not_ready": "not_ready",
    "closed": "closed",
}
#: States in which the timer is running, so the action pauses it.
RUNNING_STATES = ("working", "inactive", "blocking_wait", "not_ready")
#: ``origin`` values that have a translation.
ORIGIN_KEYS = {
    "unknown-existing": "unknown-existing",
    "replacement": "replacement",
    "additive": "additive",
}
#: ``phase`` values that have a translation.
PHASE_KEYS = {"correction": "correction", "review": "phase_review"}
#: Net-result rows shown for both the draft and the saved version.
NET_FIELDS = (
    ("added", "added"),
    ("deleted", "deleted"),
    ("geometry_changed", "geometry_changed"),
    ("class_changed", "class_changed"),
    ("modified_original", "modified_original"),
    ("modified_rate", "modified_rate"),
)
_UNSET = object()


def format_count(value):
    """Integer counter; ``None`` means "not comparable" and becomes N/A."""
    if value is None:
        return N_A
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return N_A


def format_rate(value):
    """0..1 ratio as a percentage, never a fake zero for a missing ratio."""
    if value is None:
        return N_A
    try:
        text = "%.1f" % (float(value) * 100.0)
    except (TypeError, ValueError):
        return N_A
    if text.endswith(".0"):
        text = text[:-2]
    return text + "%"


class _ElidedLabel(QLabel):
    """Label that shortens with an ellipsis instead of widening the sidebar."""

    def __init__(self, alignment=None, parent=None):
        super().__init__("", parent)
        self._full = ""
        if alignment is not None:
            self.setAlignment(alignment)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def full_text(self):
        return self._full

    def setText(self, text):  # noqa: N802 - Qt naming
        self._full = "" if text is None else str(text)
        self.setToolTip(self._full)
        self._apply()

    def _apply(self):
        width = self.contentsRect().width()
        text = self._full
        if width > 0 and self.fontMetrics().horizontalAdvance(text) > width:
            text = self.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideRight, width
            )
        super().setText(text)

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._apply()

    def minimumSizeHint(self):  # noqa: N802 - Qt naming
        return QSize(0, super().minimumSizeHint().height())


class CorrectionMetricsPanel(QWidget):
    """Current-image correction cost, collapsible for a narrow right sidebar."""

    #: Target value for ``controller.pause(value)``.
    pause_requested = pyqtSignal(bool)
    finish_requested = pyqtSignal()
    summary_requested = pyqtSignal()

    def __init__(self, controller=None, parent=None, *, language=None):
        super().__init__(parent)
        self._controller = None
        self._row = None
        self._saved = None
        self._state = None
        self._language = language if language in LANGUAGES else None
        self._collapsed = False
        self._label_specs = []
        self._fields = {}
        self._build()
        self.setObjectName("CorrectionMetricsPanel")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if controller is not None:
            self.attach(controller)
        else:
            self._render()

    # ------------------------------------------------------------- assembly
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(3)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        self.title_label = _ElidedLabel()
        self.title_label.setObjectName("metrics_title")
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("metrics_toggle_button")
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self._on_toggle_clicked)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.toggle_button, 0)
        root.addLayout(header)

        self.banner = QLabel()
        self.banner.setObjectName("metrics_pending_banner")
        self.banner.setWordWrap(True)
        root.addWidget(self.banner)

        self.body = QWidget()
        self.body.setObjectName("metrics_body")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)

        identity, identity_grid = self._section("current_image")
        self._add_row(identity_grid, "origin", "origin", 0)
        self._add_row(identity_grid, "round", "round", 1)
        self._add_row(identity_grid, "phase", "phase", 2)
        self._add_row(identity_grid, "baseline_count", "baseline_count", 3)
        self._add_row(identity_grid, "current_count", "current", 4)

        timing, timing_grid = self._section("timing")
        self._add_row(timing_grid, "timer_state", "processing", 0)
        self._add_row(timing_grid, "time", "time", 1)
        self.idle_label = _ElidedLabel()
        self.idle_label.setObjectName("metrics_idle_pending")
        self.idle_label.hide()
        timing_grid.addWidget(self.idle_label, 2, 0, 1, 2)

        counters, counters_grid = self._section("operations")
        self._add_row(counters_grid, "transactions", "transactions", 0)
        self._add_row(counters_grid, "unique_objects", "unique_objects", 1)
        self._add_row(counters_grid, "touches", "touches", 2)

        draft, draft_grid = self._section("draft", badge=True)
        for index, (field, key) in enumerate(NET_FIELDS):
            self._add_row(draft_grid, "draft_" + field, key, index)

        saved, saved_grid = self._section("saved")
        for index, (field, key) in enumerate(NET_FIELDS):
            self._add_row(saved_grid, "saved_" + field, key, index)

        integrity, integrity_grid = self._section("integrity")
        self._add_row(integrity_grid, "completed", "processing", 0)
        self._add_row(integrity_grid, "comparable", "comparable", 1)
        self._add_row(integrity_grid, "issues", "issues", 2)
        self.degraded_label = _ElidedLabel()
        self.degraded_label.setObjectName("metrics_degraded")
        self.degraded_label.hide()
        integrity_grid.addWidget(self.degraded_label, 3, 0, 1, 2)

        for frame in (identity, timing, counters, draft, saved, integrity):
            body.addWidget(frame)

        actions = QVBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(3)
        self.pause_button = QPushButton()
        self.pause_button.setObjectName("metrics_pause_button")
        self.pause_button.clicked.connect(self._on_pause_clicked)
        self.finish_button = QPushButton()
        self.finish_button.setObjectName("metrics_finish_button")
        self.finish_button.clicked.connect(self._on_finish_clicked)
        self.summary_button = QPushButton()
        self.summary_button.setObjectName("metrics_summary_button")
        self.summary_button.clicked.connect(self._on_summary_clicked)
        for button in (self.pause_button, self.finish_button, self.summary_button):
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            actions.addWidget(button)
        body.addLayout(actions)

        root.addWidget(self.body)

    def _section(self, message_key, badge=False):
        """Return a titled frame and its two-column grid, registered for i18n."""
        frame = QFrame()
        frame.setObjectName("metrics_section_" + message_key)
        frame.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(1)

        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 0)
        heading_row.setSpacing(4)
        heading = _ElidedLabel()
        heading.setObjectName("metrics_heading_" + message_key)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        heading_row.addWidget(heading, 1)
        self._label_specs.append((heading, message_key))
        if badge:
            self.unsaved_badge = _ElidedLabel()
            self.unsaved_badge.setObjectName("metrics_unsaved_badge")
            self.unsaved_badge.setStyleSheet(
                "color: #b45309; font-weight: 600;"
            )
            heading_row.addWidget(self.unsaved_badge, 0)
        outer.addLayout(heading_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        outer.addLayout(grid)
        return frame, grid

    def _add_row(self, grid, field, label_key, row):
        label = _ElidedLabel()
        label.setObjectName("metrics_label_" + field)
        self._label_specs.append((label, label_key))
        value = _ElidedLabel(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        value.setObjectName("metrics_value_" + field)
        grid.addWidget(label, row, 0)
        grid.addWidget(value, row, 1)
        self._fields[field] = value

    # --------------------------------------------------------------- public
    @property
    def ready(self):
        """True when a controller is attached and its workspace is usable."""
        return self._compute_ready()

    @property
    def collapsed(self):
        return self._collapsed

    def set_collapsed(self, value):
        self._collapsed = bool(value)
        self._apply_collapsed()

    def set_language(self, language):
        self._language = language if language in LANGUAGES else None
        self._render()

    def field_text(self, field):
        """Full (un-elided) text of one value row, for tests and tooltips."""
        widget = self._fields.get(field)
        return "" if widget is None else widget.full_text()

    def attach(self, controller):
        """Bind a controller (or ``None``) and paint its current state."""
        self._controller = controller
        if controller is not None and self._language is None:
            language = getattr(controller, "language", None)
            if language in LANGUAGES:
                self._language = language
        self.refresh()

    def refresh(self):
        """Pull the current row and timer state from the attached controller."""
        row = saved = state = None
        if self._compute_ready():
            row = self._call("current_row", True)
            saved = self._call("current_row", False)
            state = self._call("state")
        self.refresh_with(row, state, saved=saved)

    def refresh_with(self, row=None, state=None, *, saved=_UNSET):
        """Paint one row/state pair; ``None`` means "no data available"."""
        self._row = dict(row) if isinstance(row, dict) else None
        self._state = dict(state) if isinstance(state, dict) else None
        if saved is _UNSET:
            saved = self._call("current_row", False) if self._compute_ready() else None
        self._saved = dict(saved) if isinstance(saved, dict) else None
        self._render()

    def show_panel(self):
        """Host convenience: expand, show and raise the panel."""
        self.set_collapsed(False)
        self.show()
        self.raise_()

    # -------------------------------------------------------------- actions
    def _on_toggle_clicked(self):
        self.set_collapsed(not self._collapsed)

    def _on_pause_clicked(self):
        # Emit only: the host owns the controller call, then we re-read it.
        state = (self._state or {}).get("state")
        self.pause_requested.emit(state != "paused")
        self.refresh()

    def _on_finish_clicked(self):
        self.finish_requested.emit()
        self.refresh()

    def _on_summary_clicked(self):
        self.summary_requested.emit()

    # -------------------------------------------------------------- helpers
    def _ui_language(self):
        if self._language in LANGUAGES:
            return self._language
        controller = self._controller
        if controller is not None:
            language = getattr(controller, "language", None)
            if language in LANGUAGES:
                return language
        return "en_US"

    def _compute_ready(self):
        controller = self._controller
        if controller is None:
            return False
        try:
            available = getattr(controller, "available", True)
        except Exception:  # noqa: BLE001 - a broken property is "not ready"
            return False
        return bool(available)

    def _call(self, name, *args):
        controller = self._controller
        method = getattr(controller, name, None) if controller is not None else None
        if not callable(method):
            return None
        try:
            return method(*args)
        except Exception:  # noqa: BLE001 - the panel never breaks annotation
            return None

    def _degraded_reason(self):
        state = self._state or {}
        if state.get("degraded"):
            return str(state["degraded"])
        controller = self._controller
        if controller is not None:
            try:
                value = controller.degraded_reason
            except Exception:  # noqa: BLE001
                return None
            if value:
                return str(value)
        return None

    def _set(self, field, text, tooltip=None):
        widget = self._fields.get(field)
        if widget is None:
            return
        widget.setText(text)
        if tooltip is not None:
            widget.setToolTip(tooltip)

    def _apply_collapsed(self):
        language = self._ui_language()
        self.body.setVisible(not self._collapsed)
        self.toggle_button.setText("\u25b8" if self._collapsed else "\u25be")
        label = tr("expand" if self._collapsed else "collapse", language=language)
        self.toggle_button.setToolTip(label)
        self.toggle_button.setAccessibleName(label)

    # ---------------------------------------------------------------- paint
    def _render(self):
        language = self._ui_language()
        self.title_label.setText(tr("title", language=language))
        for widget, key in self._label_specs:
            widget.setText(tr(key, language=language))
        self.unsaved_badge.setText(tr("unsaved", language=language))

        if self._compute_ready():
            self.banner.hide()
        else:
            self.banner.setText(metrics_pending_message(language))
            self.banner.show()

        self._render_identity(self._row or {}, language)
        self._render_counters(self._row or {})
        self._render_timing(language)
        self._render_net("draft", self._row, language)
        self._render_net("saved", self._saved, language)
        self._render_integrity(language)
        self._render_actions(language)
        self._apply_collapsed()

    def _render_identity(self, row, language):
        origin = row.get("origin")
        key = ORIGIN_KEYS.get(origin)
        if key is not None:
            self._set("origin", tr(key, language=language))
        else:
            self._set("origin", N_A if not origin else str(origin))

        round_id = row.get("round_id")
        if round_id:
            self._set("round", str(round_id)[:8], tooltip=str(round_id))
        else:
            self._set("round", N_A)

        phase = row.get("phase")
        key = PHASE_KEYS.get(phase)
        if key is not None:
            self._set("phase", tr(key, language=language))
        else:
            self._set("phase", N_A if not phase else str(phase))

        self._set("baseline_count", format_count(row.get("baseline_count")))
        self._set("current_count", format_count(row.get("final_count")))

    def _render_counters(self, row):
        self._set("transactions", format_count(row.get("transactions")))
        self._set("unique_objects", format_count(row.get("unique_objects")))
        self._set("touches", format_count(row.get("touches")))

    def _render_timing(self, language):
        state = self._state or {}
        if not state:
            self._set("timer_state", N_A)
            self._set("time", N_A)
        else:
            code = state.get("state")
            key = STATE_KEYS.get(code)
            self._set(
                "timer_state",
                tr(key, language=language) if key else (N_A if not code else str(code)),
            )
            seconds = state.get("seconds")
            if seconds is None:
                self._set("time", N_A)
            else:
                self._set(
                    "time",
                    tr("seconds", language=language, seconds=int(round(float(seconds)))),
                )
        idle = bool(state.get("idle_waiting"))
        self.idle_label.setVisible(idle)
        if idle:
            self.idle_label.setText(tr("idle_pending", language=language))
            self.idle_label.setToolTip(self.idle_label.full_text())

    def _render_net(self, prefix, row, language):
        data = row or {}
        for field, _ in NET_FIELDS:
            formatter = format_rate if field == "modified_rate" else format_count
            self._set("%s_%s" % (prefix, field), formatter(data.get(field)))
        if prefix == "draft":
            unsaved = bool(data) and (
                bool(data.get("is_draft")) or not str(data.get("revision") or "")
            )
            self.unsaved_badge.setVisible(unsaved)

    def _render_integrity(self, language):
        row = self._row
        if not row:
            self._set("completed", N_A)
            self._set("comparable", N_A)
            self._set("issues", N_A)
        else:
            self._set(
                "completed",
                tr("completed" if row.get("completed") else "unfinished", language=language),
            )
            comparable = row.get("comparable")
            if comparable is None:
                self._set("comparable", N_A)
            else:
                self._set(
                    "comparable", tr("yes" if comparable else "no", language=language)
                )
            issues = [str(code) for code in (row.get("issues") or ()) if str(code)]
            if not issues:
                self._set("issues", tr("clean", language=language))
            else:
                self._set(
                    "issues",
                    " \u00b7 ".join(tr_issue(code, language=language) for code in issues),
                )

        reason = self._degraded_reason()
        self.degraded_label.setVisible(bool(reason))
        if reason:
            self.degraded_label.setText(
                tr("degraded", language=language) + ": " + reason
            )
            self.degraded_label.setToolTip(reason)

    def _render_actions(self, language):
        controller = self._controller
        ready = self._compute_ready()
        state = self._state or {}
        code = state.get("state")
        row = self._row
        unsaved = bool(row) and (
            bool(row.get("is_draft")) or not str(row.get("revision") or "")
        )
        finished = bool(row and row.get("completed"))
        pending = metrics_pending_message(language)

        can_pause = ready and callable(getattr(controller, "pause", None))
        can_finish = ready and callable(getattr(controller, "finish_round", None))

        if code == "paused":
            key = "resume"
        elif code in RUNNING_STATES:
            key = "pause"
        else:
            key = "start"
        self.pause_button.setText(tr(key, language=language))
        self.pause_button.setEnabled(can_pause)
        self.pause_button.setToolTip(
            tr(key, language=language) if can_pause else pending
        )

        reason = None
        if not ready:
            reason = pending
        elif not row:
            reason = tr("need_image", language=language)
        elif finished:
            reason = tr("already_completed", language=language)
        elif unsaved:
            reason = tr("save_before_complete", language=language)
        self.finish_button.setText(tr("complete", language=language))
        self.finish_button.setEnabled(can_finish and bool(row) and not finished and not unsaved)
        self.finish_button.setToolTip(reason or tr("complete", language=language))

        self.summary_button.setText(tr("report", language=language))
        self.summary_button.setEnabled(ready)
        self.summary_button.setToolTip(tr("report", language=language) if ready else pending)

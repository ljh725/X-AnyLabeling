"""Runtime coordinator for proactive rectangle-size validation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Optional

from PyQt6 import QtCore

from .. import rect_edge_alignment
from ..rectangle_size import (
    RectangleCandidate,
    RectangleSizeEvaluator,
    RectangleSizeIssue,
    RectangleSizeRule,
)

CandidateBuilder = Callable[
    [object, int, bool],
    Optional[RectangleCandidate],
]
ShapeReviewPredicate = Callable[[object], bool]

logger = logging.getLogger(__name__)


def is_shape_reviewable_by_attributes(shape: object) -> bool:
    """Return basic visibility state without depending on a Canvas instance.

    Canvas integration should inject ``Canvas.base_visible`` later so
    canvas-specific base visibility rules remain authoritative without
    inheriting temporary editing-focus restrictions.

    Args:
        shape: Live shape-like object.

    Returns:
        True when the shape is visible and is not hidden by a label filter.
    """
    return bool(getattr(shape, "visible", True)) and not bool(
        getattr(shape, "hidden_by_filter", False)
    )


def build_rectangle_candidate(
    shape: object,
    shape_index: int,
    interactive: bool,
) -> Optional[RectangleCandidate]:
    """Adapt one live rectangle shape to an immutable evaluator snapshot.

    Args:
        shape: Live shape-like object accepted by the shared rectangle
            geometry adapter.
        shape_index: Current index in the canvas shape snapshot.
        interactive: Review eligibility supplied by the monitor. The name is
            retained for compatibility with ``RectangleCandidate``.

    Returns:
        A normalized candidate, or ``None`` for incompatible geometry.
    """
    geometry = rect_edge_alignment.geometry_from_shape(shape)
    if geometry is None:
        return None
    label = getattr(shape, "label", "")
    if not isinstance(label, str):
        label = ""
    shape_type = getattr(shape, "shape_type", "")
    if not isinstance(shape_type, str):
        shape_type = ""
    return RectangleCandidate(
        candidate_id=id(shape),
        shape_index=shape_index,
        label=label,
        shape_type=shape_type,
        bbox=(
            geometry.x_min,
            geometry.y_min,
            geometry.x_max,
            geometry.y_max,
        ),
        interactive=interactive,
    )


class RectangleSizeMonitor(QtCore.QObject):
    """Maintain live issues for the current canvas shape snapshot.

    The monitor owns no shapes and never mutates them. Full invalidations and
    per-shape invalidations are coalesced by a single-shot timer. Explicit
    lifecycle transitions such as enabling, changing rules, or replacing the
    current-image shape list scan immediately so stale overlays cannot remain.
    """

    issues_changed = QtCore.pyqtSignal(tuple)

    def __init__(
        self,
        rules: Iterable[RectangleSizeRule] = (),
        *,
        enabled: bool = False,
        debounce_ms: int = 32,
        candidate_builder: CandidateBuilder = build_rectangle_candidate,
        is_shape_reviewable: ShapeReviewPredicate = (
            is_shape_reviewable_by_attributes
        ),
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        """Initialize an isolated current-image monitor.

        Args:
            rules: Initial rectangle-size rules.
            enabled: Whether proactive validation starts enabled.
            debounce_ms: Delay used to coalesce geometry invalidations.
            candidate_builder: Adapter from live shapes to pure candidates.
            is_shape_reviewable: Predicate for rectangle-size review
                eligibility.
            parent: Optional Qt object owner.

        Raises:
            TypeError: If callbacks are not callable or enabled is not bool.
            ValueError: If rules or the debounce interval are invalid.
        """
        super().__init__(parent)
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        if not callable(candidate_builder):
            raise TypeError("candidate_builder must be callable")
        if not callable(is_shape_reviewable):
            raise TypeError("is_shape_reviewable must be callable")
        if isinstance(debounce_ms, bool) or not isinstance(debounce_ms, int):
            raise TypeError("debounce_ms must be an integer")
        if debounce_ms < 0:
            raise ValueError("debounce_ms cannot be negative")

        self._rules = tuple(rules)
        self._evaluator = RectangleSizeEvaluator(self._rules)
        self._enabled = enabled
        self._candidate_builder = candidate_builder
        self._is_shape_reviewable = is_shape_reviewable
        self._shapes: tuple[object, ...] = ()
        self._shape_by_identity: dict[int, object] = {}
        self._shape_index_by_identity: dict[int, int] = {}
        self._candidate_id_by_shape_identity: dict[int, object] = {}
        self._shape_by_candidate_id: dict[object, object] = {}
        self._issues_by_candidate_id: dict[object, RectangleSizeIssue] = {}
        self._issues: tuple[RectangleSizeIssue, ...] = ()
        self._full_scan_pending = False
        self._pending_shape_identities: set[int] = set()
        self._reported_candidate_error_ids: set[int] = set()

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._flush_pending)

    @property
    def enabled(self) -> bool:
        """Return whether proactive validation is enabled."""
        return self._enabled

    @property
    def rules(self) -> tuple[RectangleSizeRule, ...]:
        """Return the currently compiled immutable rule snapshot."""
        return self._rules

    @property
    def shapes(self) -> tuple[object, ...]:
        """Return the current-image shape reference snapshot."""
        return self._shapes

    @property
    def issues(self) -> tuple[RectangleSizeIssue, ...]:
        """Return current issues in canvas shape order."""
        return self._issues

    @property
    def scan_pending(self) -> bool:
        """Return whether a debounced invalidation awaits evaluation."""
        return self._timer.isActive()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable proactive validation.

        Disabling immediately clears issues and cancels pending work while
        preserving the shape snapshot. Re-enabling immediately scans it.

        Args:
            enabled: New proactive-validation state.

        Raises:
            TypeError: If enabled is not a bool.
        """
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self._cancel_pending()
        if enabled:
            self._scan_all()
        else:
            self._clear_issue_state()

    def set_rules(self, rules: Iterable[RectangleSizeRule]) -> None:
        """Atomically replace rules and refresh active issues.

        Args:
            rules: New rules to compile before replacing current state.

        Raises:
            ValueError: If an enabled rule is invalid.
        """
        new_rules = tuple(rules)
        new_evaluator = RectangleSizeEvaluator(new_rules)
        if new_rules == self._rules:
            return
        self._rules = new_rules
        self._evaluator = new_evaluator
        self._cancel_pending()
        if self._enabled:
            self._scan_all()

    def replace_shapes(self, shapes: Iterable[object]) -> None:
        """Replace the current-image shape snapshot.

        Args:
            shapes: Shapes belonging to the newly loaded or refreshed image.

        Raises:
            ValueError: If the same object occurs more than once.
        """
        new_shapes = tuple(shapes)
        shape_by_identity = {id(shape): shape for shape in new_shapes}
        if len(shape_by_identity) != len(new_shapes):
            raise ValueError(
                "Current shape snapshot contains duplicate objects"
            )

        self._shapes = new_shapes
        self._shape_by_identity = shape_by_identity
        self._shape_index_by_identity = {
            id(shape): index for index, shape in enumerate(new_shapes)
        }
        self._reported_candidate_error_ids.clear()
        self._cancel_pending()
        if self._enabled:
            self._scan_all()
        else:
            self._clear_issue_state()

    def invalidate_all(self) -> None:
        """Schedule one debounced full scan of the current shape snapshot."""
        if not self._enabled:
            return
        self._full_scan_pending = True
        self._pending_shape_identities.clear()
        self._timer.start()

    def invalidate_shape(self, shape: object) -> None:
        """Schedule an incremental refresh for one known live shape.

        Args:
            shape: Shape whose geometry, label, or visibility changed.
        """
        if not self._enabled or self._full_scan_pending:
            return
        shape_identity = id(shape)
        if self._shape_by_identity.get(shape_identity) is not shape:
            return
        self._pending_shape_identities.add(shape_identity)
        self._timer.start()

    def rescan_now(self) -> None:
        """Cancel pending work and synchronously rebuild all active issues."""
        self._cancel_pending()
        if self._enabled:
            self._scan_all()
        else:
            self._clear_issue_state()

    def clear_shapes(self) -> None:
        """Drop all current-image references, pending work, and issues."""
        self._shapes = ()
        self._shape_by_identity.clear()
        self._shape_index_by_identity.clear()
        self._reported_candidate_error_ids.clear()
        self._cancel_pending()
        self._clear_issue_state()

    def shape_for_candidate(self, candidate_id: object) -> Optional[object]:
        """Return the live shape associated with a current issue candidate.

        Args:
            candidate_id: Candidate identity copied into an issue.

        Returns:
            Current live shape reference, or ``None`` after replacement/clear.
        """
        return self._shape_by_candidate_id.get(candidate_id)

    def _cancel_pending(self) -> None:
        """Cancel timer work and clear pending invalidation flags."""
        self._timer.stop()
        self._full_scan_pending = False
        self._pending_shape_identities.clear()

    def _flush_pending(self) -> None:
        """Run the coalesced full or incremental scan."""
        if not self._enabled:
            self._cancel_pending()
            return
        if self._full_scan_pending:
            self._full_scan_pending = False
            self._pending_shape_identities.clear()
            self._scan_all()
            return
        identities = tuple(
            sorted(
                self._pending_shape_identities,
                key=self._shape_index_by_identity.__getitem__,
            )
        )
        self._pending_shape_identities.clear()
        self._scan_shape_identities(identities)

    def _scan_all(self) -> None:
        """Rebuild candidates, associations, and issues from all shapes."""
        candidates = []
        candidate_id_by_shape_identity = {}
        shape_by_candidate_id = {}
        for index, shape in enumerate(self._shapes):
            candidate = self._candidate_for_shape(shape, index)
            if candidate is None:
                continue
            if candidate.candidate_id in shape_by_candidate_id:
                self._report_candidate_error(
                    shape,
                    index,
                    "candidate builder returned a duplicate candidate_id",
                )
                continue
            candidates.append(candidate)
            shape_identity = id(shape)
            candidate_id_by_shape_identity[shape_identity] = (
                candidate.candidate_id
            )
            shape_by_candidate_id[candidate.candidate_id] = shape

        issues = self._evaluator.evaluate(candidates)
        self._candidate_id_by_shape_identity = candidate_id_by_shape_identity
        self._shape_by_candidate_id = shape_by_candidate_id
        self._issues_by_candidate_id = {
            issue.candidate_id: issue for issue in issues
        }
        self._replace_issues(issues)

    def _scan_shape_identities(self, identities: Iterable[int]) -> None:
        """Refresh only invalidated shape identities."""
        for shape_identity in identities:
            shape = self._shape_by_identity.get(shape_identity)
            index = self._shape_index_by_identity.get(shape_identity)
            if shape is None or index is None:
                continue

            candidate = self._candidate_for_shape(shape, index)
            issue = (
                self._evaluator.evaluate_candidate(candidate)
                if candidate is not None
                else None
            )
            if candidate is not None:
                existing_shape = self._shape_by_candidate_id.get(
                    candidate.candidate_id
                )
                if existing_shape is not None and existing_shape is not shape:
                    self._report_candidate_error(
                        shape,
                        index,
                        "candidate builder returned a duplicate candidate_id",
                    )
                    candidate = None
                    issue = None

            previous_candidate_id = self._candidate_id_by_shape_identity.pop(
                shape_identity,
                None,
            )
            if previous_candidate_id is not None:
                self._shape_by_candidate_id.pop(
                    previous_candidate_id,
                    None,
                )
                self._issues_by_candidate_id.pop(
                    previous_candidate_id,
                    None,
                )

            if candidate is None:
                continue
            self._candidate_id_by_shape_identity[shape_identity] = (
                candidate.candidate_id
            )
            self._shape_by_candidate_id[candidate.candidate_id] = shape
            if issue is not None:
                self._issues_by_candidate_id[issue.candidate_id] = issue

        issues = tuple(
            sorted(
                self._issues_by_candidate_id.values(),
                key=lambda issue: issue.shape_index,
            )
        )
        self._replace_issues(issues)

    def _candidate_for_shape(
        self,
        shape: object,
        index: int,
    ) -> Optional[RectangleCandidate]:
        """Build one validated candidate without letting one shape abort a scan."""
        try:
            reviewable = bool(self._is_shape_reviewable(shape))
            candidate = self._candidate_builder(shape, index, reviewable)
        except Exception as error:  # noqa: BLE001 - isolate extension failures
            self._report_candidate_error(shape, index, str(error))
            return None
        if candidate is None:
            self._reported_candidate_error_ids.discard(id(shape))
            return None
        if not isinstance(candidate, RectangleCandidate):
            self._report_candidate_error(
                shape,
                index,
                "candidate builder returned an incompatible value",
            )
            return None
        if candidate.shape_index != index:
            self._report_candidate_error(
                shape,
                index,
                "candidate builder returned the wrong shape_index",
            )
            return None
        if not isinstance(candidate.label, str) or not isinstance(
            candidate.shape_type,
            str,
        ):
            self._report_candidate_error(
                shape,
                index,
                "candidate label and shape_type must be strings",
            )
            return None
        try:
            hash(candidate.candidate_id)
        except TypeError:
            self._report_candidate_error(
                shape,
                index,
                "candidate_id must be hashable",
            )
            return None
        self._reported_candidate_error_ids.discard(id(shape))
        return candidate

    def _report_candidate_error(
        self,
        shape: object,
        index: int,
        message: str,
    ) -> None:
        """Log one candidate failure per live shape until it recovers."""
        shape_identity = id(shape)
        if shape_identity in self._reported_candidate_error_ids:
            return
        self._reported_candidate_error_ids.add(shape_identity)
        logger.warning(
            "Skipping rectangle-size candidate at index %d: %s",
            index,
            message or "unknown candidate error",
        )

    def _clear_issue_state(self) -> None:
        """Clear candidate associations and publish an empty issue snapshot."""
        self._candidate_id_by_shape_identity.clear()
        self._shape_by_candidate_id.clear()
        self._issues_by_candidate_id.clear()
        self._replace_issues(())

    def _replace_issues(
        self,
        issues: Iterable[RectangleSizeIssue],
    ) -> None:
        """Publish a changed immutable issue snapshot exactly once."""
        new_issues = tuple(issues)
        if new_issues == self._issues:
            return
        self._issues = new_issues
        self.issues_changed.emit(new_issues)


__all__ = [
    "CandidateBuilder",
    "RectangleSizeMonitor",
    "ShapeReviewPredicate",
    "build_rectangle_candidate",
    "is_shape_reviewable_by_attributes",
]

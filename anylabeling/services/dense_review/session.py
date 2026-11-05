"""Stateful dense-review session shared by the workspace and the canvas."""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from . import coverage as coverage_service
from .ledger import (
    build_object_state,
    create_state,
    next_display_index,
    rebuild_batches,
    reviewable_shapes,
    spatial_order,
)
from .models import (
    NEW_PENDING_BATCH_ID,
    REVIEW_DIMENSIONS,
    SUPPORTED_SHAPE_TYPES,
    BatchConfirmation,
    CandidateScope,
    CompletionStatus,
    CoveragePlan,
    CoverageSettings,
    IncompatibleReviewState,
    ObjectReviewState,
    ReviewConfig,
    ReviewState,
    canonical_json,
    normalize_bounds,
    signature_for,
)
from .signatures import (
    content_hash,
    shape_bounds,
    shape_category_signature,
    shape_geometry_signature,
)


class ReviewConfigError(ValueError):
    """Raised when a review configuration cannot start a stable round."""

    def __init__(self, message: str, issues: Sequence[Any] = ()):
        super().__init__(message)
        self.issues = tuple(issues)


@dataclass
class _HistoryEntry:
    kind: str
    state: ReviewState
    content_hash: str = ""
    before_hash: str = ""
    after_hash: str = ""


@dataclass
class _RedoEntry:
    """One undone transaction, ready to be re-applied by redo."""

    kind: str
    state: ReviewState
    content_hash: str = ""


class DenseReviewSession:
    """Own review progress for one image and output-directory pair."""

    def __init__(
        self,
        config: ReviewConfig,
        image_fingerprint: str,
        image_width: int,
        image_height: int,
    ) -> None:
        self.config = config.normalized()
        self.image_fingerprint = image_fingerprint
        self.image_width = int(image_width)
        self.image_height = int(image_height)
        self.state = ReviewState(
            image_fingerprint=image_fingerprint,
            image_width=int(image_width),
            image_height=int(image_height),
            rules_signature=self.config.rules_signature(),
            batch_signature=self.config.batch_signature(),
        )
        self.dirty = False
        self.has_payload = False
        self._removed: dict[
            str, tuple[ObjectReviewState, Optional[str], int]
        ] = {}
        # Each transaction owns its snapshot, so eviction is atomic and equal
        # content at different points in history can retain different progress.
        self._history: deque[_HistoryEntry] = deque(maxlen=100)
        # Undone transactions, newest last. ``_redo_order`` keeps progress and
        # canvas transactions in one LIFO stream so redo mirrors undo exactly.
        self._redo_progress: deque[_RedoEntry] = deque(maxlen=100)
        self._redo_content: deque[_RedoEntry] = deque(maxlen=100)
        self._redo_order: deque[str] = deque(maxlen=200)
        self._redo_snapshot: Optional[
            tuple[
                tuple[_RedoEntry, ...],
                tuple[_RedoEntry, ...],
                tuple[str, ...],
            ]
        ] = None
        self._last_content_hash = ""
        self._last_action = ""

    @classmethod
    def from_shapes(
        cls,
        config: ReviewConfig,
        shapes: Iterable[Any],
        image_fingerprint: str,
        image_width: int,
        image_height: int,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> "DenseReviewSession":
        """Create a fresh round or restore one persisted payload."""
        issues = config.validate()
        if issues:
            raise ReviewConfigError(
                issues[0].message,
                issues,
            )
        session = cls(
            config,
            image_fingerprint,
            image_width,
            image_height,
        )
        if payload is None:
            session.state = create_state(
                session.config,
                reviewable_shapes(shapes),
                image_fingerprint,
                image_width,
                image_height,
            )
        else:
            session.has_payload = True
            session.state = ReviewState.from_dict(payload)
            session._reconcile_loaded_state(shapes)
        session._after_restore(shapes)
        return session

    def _reconcile_loaded_state(self, shapes: Iterable[Any]) -> None:
        state = self.state
        image_changed = bool(
            state.image_fingerprint
            and state.image_fingerprint != self.image_fingerprint
        )
        if image_changed:
            self._reset_for_image_change()
        state.image_fingerprint = self.image_fingerprint
        state.image_width = self.image_width
        state.image_height = self.image_height
        if state.rules_signature != self.config.rules_signature():
            self._clear_all_confirmations(invalidate_coverage=True)
        state.rules_signature = self.config.rules_signature()
        state.dimensions = (
            tuple(
                dimension
                for dimension in state.dimensions
                if dimension in REVIEW_DIMENSIONS
            )
            or REVIEW_DIMENSIONS
        )
        if image_changed:
            self.dirty = True

    def _reset_for_image_change(self) -> None:
        for item in self.state.objects.values():
            item.clear_confirmation(REVIEW_DIMENSIONS)
            item.difficult = False
            item.difficulty_dimensions = ()
            item.difficulty_reason = ""
            item.skipped = False
        self.state.coverage = None

    def _after_restore(self, shapes: Iterable[Any]) -> None:
        self.sync_shapes(shapes, record_history=False, mark_dirty=False)
        self._validate_cursor()
        current_hash = content_hash(reviewable_shapes(shapes))
        self._last_content_hash = current_hash
        self._history.clear()
        self._clear_redo()
        self._last_action = ""

    def _validate_cursor(self) -> None:
        state = self.state
        if (
            state.current_batch
            not in {batch.batch_id for batch in state.batches}
            and state.current_batch != NEW_PENDING_BATCH_ID
        ):
            state.current_batch = (
                state.batches[0].batch_id if state.batches else ""
            )
        members = state.member_ids(state.current_batch)
        if state.current_object not in members:
            state.current_object = members[0] if members else ""
        if state.coverage is not None:
            if state.coverage.region(state.coverage.current_region) is None:
                state.coverage.current_region = (
                    state.coverage.regions[0].region_id
                    if state.coverage.regions
                    else ""
                )

    # -- content synchronisation -------------------------------------

    def sync_shapes(
        self,
        shapes: Iterable[Any],
        *,
        record_history: bool = True,
        mark_dirty: bool = True,
    ) -> bool:
        """Reconcile live shapes with the ledger and invalidate stale state."""
        current_shapes = {
            str(shape.xanylabeling_shape_id): shape
            for shape in reviewable_shapes(shapes)
        }
        current_hash = content_hash(current_shapes.values())
        if current_hash == self._last_content_hash:
            return False
        before_hash = self._last_content_hash
        before_state = copy.deepcopy(self.state) if record_history else None
        changed_bounds: dict[
            str, tuple[Optional[Sequence[float]], Optional[Sequence[float]]]
        ] = {}
        changed = self._sync_removals(current_shapes, changed_bounds)
        changed = (
            self._sync_additions(current_shapes, changed_bounds) or changed
        )
        changed = (
            self._sync_existing(current_shapes, changed_bounds) or changed
        )
        if changed_bounds and self.state.coverage is not None:
            coverage_service.invalidate_regions(
                self.state.coverage,
                changed_bounds,
                unknown_scope=self._coverage_scope_unknown(changed_bounds),
            )
        if changed:
            self._validate_cursor()
            self.state.batch_signature = self.config.batch_signature()
        if current_hash != self._last_content_hash:
            if record_history:
                self._history.append(
                    _HistoryEntry(
                        kind="content",
                        state=before_state,
                        before_hash=before_hash,
                        after_hash=current_hash,
                    )
                )
                self._clear_redo()
                if changed:
                    self._last_action = "content"
                    if mark_dirty:
                        self.dirty = True
            self._last_content_hash = current_hash
        return changed

    @staticmethod
    def _coverage_scope_unknown(
        changed_bounds: Mapping[str, tuple[Any, Any]],
    ) -> bool:
        for old_bounds, new_bounds in changed_bounds.values():
            if new_bounds is None:
                if old_bounds is None or normalize_bounds(old_bounds) is None:
                    return True
                continue
            if normalize_bounds(new_bounds) is None:
                return True
        return False

    def _sync_removals(
        self,
        current: Mapping[str, Any],
        changed_bounds: dict[str, tuple[Any, Any]],
    ) -> bool:
        removed = [
            shape_id
            for shape_id in self.state.objects
            if shape_id not in current
        ]
        if not removed:
            return False
        for shape_id in removed:
            item = self.state.objects.pop(shape_id)
            batch_id = self.state.batch_for_object(shape_id)
            index = -1
            if batch_id and batch_id != NEW_PENDING_BATCH_ID:
                batch = self.state.batch(batch_id)
                if batch is not None and shape_id in batch.member_ids:
                    index = batch.member_ids.index(shape_id)
                    batch.member_ids.pop(index)
                self._removed[shape_id] = (
                    copy.deepcopy(item),
                    batch_id,
                    index,
                )
            else:
                if shape_id in self.state.new_pending:
                    index = self.state.new_pending.index(shape_id)
                    self.state.new_pending.remove(shape_id)
                self._removed[shape_id] = (
                    copy.deepcopy(item),
                    NEW_PENDING_BATCH_ID,
                    index,
                )
            changed_bounds[shape_id] = (item.bounds, None)
        return True

    def _sync_additions(
        self,
        current: Mapping[str, Any],
        changed_bounds: dict[str, tuple[Any, Any]],
    ) -> bool:
        added = [
            shape_id
            for shape_id in current
            if shape_id not in self.state.objects
        ]
        if not added:
            return False
        for shape_id in added:
            shape = current[shape_id]
            item = self._restore_removed(shape)
            if item is None:
                item = build_object_state(
                    shape,
                    self.config,
                    next_display_index(self.state),
                    added=True,
                )
                self.state.new_pending.append(shape_id)
            self.state.objects[shape_id] = item
            changed_bounds[shape_id] = (None, item.bounds)
        return True

    def _restore_removed(self, shape: Any) -> Optional[ObjectReviewState]:
        shape_id = str(shape.xanylabeling_shape_id)
        restored = self._removed.pop(shape_id, None)
        if restored is None:
            return None
        item, batch_id, index = restored
        geometry = shape_geometry_signature(shape, self.config.rules)
        category = shape_category_signature(shape, self.config.rules, geometry)
        if (
            item.geometry_signature != geometry
            or item.category_signature != category
        ):
            self._removed[shape_id] = restored
            return None
        bounds = shape_bounds(shape)
        if bounds is not None:
            item.bounds = bounds
        if batch_id == NEW_PENDING_BATCH_ID:
            if not item.confirmed_both():
                insert_at = min(max(index, 0), len(self.state.new_pending))
                self.state.new_pending.insert(insert_at, shape_id)
        else:
            batch = self.state.batch(batch_id)
            if batch is not None:
                insert_at = min(max(index, 0), len(batch.member_ids))
                batch.member_ids.insert(insert_at, shape_id)
            else:
                self.state.new_pending.append(shape_id)
        return item

    def _sync_existing(
        self,
        current: Mapping[str, Any],
        changed_bounds: dict[str, tuple[Any, Any]],
    ) -> bool:
        changed = False
        for shape_id, item in self.state.objects.items():
            shape = current.get(shape_id)
            if shape is None:
                continue
            changed = self._sync_one(shape, item, changed_bounds) or changed
        return changed

    def _sync_one(
        self,
        shape: Any,
        item: ObjectReviewState,
        changed_bounds: dict[str, tuple[Any, Any]],
    ) -> bool:
        geometry = shape_geometry_signature(shape, self.config.rules)
        category = shape_category_signature(shape, self.config.rules, geometry)
        bounds = shape_bounds(shape)
        label = str(getattr(shape, "label", "") or "")
        shape_type = str(getattr(shape, "shape_type", "polygon"))
        old_rule = self.config.rules.box_rule(item.label)
        new_rule = self.config.rules.box_rule(label)
        bounds_changed = bounds is not None and tuple(bounds) != tuple(
            item.bounds
        )
        geometry_changed = geometry != item.geometry_signature
        category_changed = category != item.category_signature
        label_changed = label != item.label
        changed = (
            bounds_changed
            or geometry_changed
            or category_changed
            or label_changed
            or shape_type != item.shape_type
        )
        if not changed:
            return False
        if geometry_changed or bounds_changed:
            item.clear_confirmation(REVIEW_DIMENSIONS)
        elif category_changed or label_changed:
            item.category_confirmed = None
            if old_rule != new_rule or new_rule == "unknown":
                item.geometry_confirmed = None
            elif geometry_changed:
                item.geometry_confirmed = None
        if bounds_changed:
            changed_bounds[item.shape_id] = (
                item.bounds,
                bounds,
            )
            item.bounds = bounds or item.bounds
        item.label = label
        item.shape_type = shape_type
        item.category_signature = category
        item.geometry_signature = geometry
        item.supported = shape_type in SUPPORTED_SHAPE_TYPES
        item.load_failed = bounds is None
        if item.load_failed or not item.supported:
            item.clear_confirmation(REVIEW_DIMENSIONS)
        return True

    # -- confirmation -------------------------------------------------

    def candidate_scope(
        self,
        batch_id: str,
        dimensions: Iterable[str],
        *,
        manual_hidden_ids: Iterable[str] = (),
        filtered_ids: Iterable[str] = (),
        failed_ids: Iterable[str] = (),
    ) -> CandidateScope:
        requested = self._normalize_dimensions(dimensions)
        members = self.state.member_ids(batch_id)
        manual_hidden = {str(item) for item in manual_hidden_ids}
        filtered = {str(item) for item in filtered_ids}
        failed = {str(item) for item in failed_ids}
        candidates: list[str] = []
        excluded: dict[str, str] = {}
        for shape_id in members:
            item = self.state.objects.get(shape_id)
            reason = self._exclusion_reason(
                item, manual_hidden, filtered, failed
            )
            if reason is None:
                candidates.append(shape_id)
            else:
                excluded[shape_id] = reason
        fingerprint = signature_for(
            {
                "batch_id": batch_id,
                "dimensions": list(requested),
                "members": members,
                "candidates": [
                    (
                        shape_id,
                        self.state.objects[shape_id].category_signature,
                        self.state.objects[shape_id].geometry_signature,
                    )
                    for shape_id in candidates
                ],
                "excluded": excluded,
            }
        )
        return CandidateScope(
            batch_id=batch_id,
            dimensions=requested,
            candidate_ids=tuple(candidates),
            excluded=excluded,
            fingerprint=fingerprint,
            total=len(members),
        )

    @staticmethod
    def _exclusion_reason(
        item: Optional[ObjectReviewState],
        manual_hidden: set[str],
        filtered: set[str],
        failed: set[str],
    ) -> Optional[str]:
        if item is None:
            return "missing"
        if item.load_failed:
            return "load_failed"
        if not item.supported:
            return "unsupported"
        if item.difficult:
            return "difficult"
        if item.skipped:
            return "skipped"
        if item.shape_id in manual_hidden:
            return "manual_hidden"
        if item.shape_id in filtered:
            return "filtered"
        if item.shape_id in failed:
            return "load_failed"
        return None

    def confirm_batch(
        self,
        batch_id: str,
        dimensions: Iterable[str],
        *,
        expected_fingerprint: str = "",
        manual_hidden_ids: Iterable[str] = (),
        filtered_ids: Iterable[str] = (),
        failed_ids: Iterable[str] = (),
    ) -> BatchConfirmation:
        scope = self.candidate_scope(
            batch_id,
            dimensions,
            manual_hidden_ids=manual_hidden_ids,
            filtered_ids=filtered_ids,
            failed_ids=failed_ids,
        )
        if expected_fingerprint and (
            expected_fingerprint != scope.fingerprint
        ):
            return BatchConfirmation(
                status="conflict",
                excluded=scope.excluded,
                next_batch_id=self.state.current_batch,
                next_object_id=self.state.current_object,
                conflict=True,
            )
        if not scope.candidate_ids:
            return BatchConfirmation(
                status="empty",
                excluded=scope.excluded,
                next_batch_id=self.state.current_batch,
                next_object_id=self.state.current_object,
            )
        self._push_progress_undo()
        confirmed: list[str] = []
        for shape_id in scope.candidate_ids:
            item = self.state.objects.get(shape_id)
            if item is None:
                continue
            item.apply_confirmation(scope.dimensions)
            if all(
                item.confirmed(dimension) for dimension in scope.dimensions
            ):
                confirmed.append(shape_id)
        if batch_id == NEW_PENDING_BATCH_ID:
            self._prune_new_pending()
        self._advance_after_batch(batch_id, scope.dimensions)
        self.dirty = True
        self._last_action = "progress"
        return BatchConfirmation(
            status="confirmed",
            confirmed_ids=tuple(confirmed),
            excluded=scope.excluded,
            next_batch_id=self.state.current_batch,
            next_object_id=self.state.current_object,
        )

    def confirm_object(self, shape_id: str, dimensions: Iterable[str]) -> bool:
        item = self.state.objects.get(shape_id)
        if item is None:
            return False
        requested = self._normalize_dimensions(dimensions)
        self._push_progress_undo()
        changed = item.apply_confirmation(requested)
        if not changed:
            self._discard_last_progress_undo()
            return False
        self._prune_new_pending()
        next_id = self.next_pending_object(
            self.state.current_batch, requested, after=shape_id
        )
        if next_id:
            self.state.current_object = next_id
        self.dirty = True
        self._last_action = "progress"
        return True

    # -- difficult / skipped ------------------------------------------

    def mark_difficult(
        self,
        shape_id: str,
        dimensions: Iterable[str] = REVIEW_DIMENSIONS,
        reason: str = "",
    ) -> bool:
        item = self.state.objects.get(shape_id)
        if item is None:
            return False
        requested = self._normalize_dimensions(dimensions)
        self._push_progress_undo()
        item.difficult = True
        item.difficulty_dimensions = requested
        item.difficulty_reason = str(reason)
        item.skipped = False
        item.clear_confirmation(requested)
        self.dirty = True
        self._last_action = "progress"
        return True

    def clear_difficult(self, shape_id: str) -> bool:
        item = self.state.objects.get(shape_id)
        if item is None or not item.difficult:
            return False
        self._push_progress_undo()
        item.difficult = False
        item.difficulty_dimensions = ()
        item.difficulty_reason = ""
        self.dirty = True
        self._last_action = "progress"
        return True

    def mark_skipped(self, shape_id: str) -> bool:
        item = self.state.objects.get(shape_id)
        if item is None:
            return False
        self._push_progress_undo()
        item.skipped = True
        item.difficult = False
        item.difficulty_dimensions = ()
        item.difficulty_reason = ""
        item.clear_confirmation(REVIEW_DIMENSIONS)
        self.dirty = True
        self._last_action = "progress"
        return True

    def clear_skipped(self, shape_id: str) -> bool:
        item = self.state.objects.get(shape_id)
        if item is None or not item.skipped:
            return False
        self._push_progress_undo()
        item.skipped = False
        self.dirty = True
        self._last_action = "progress"
        return True

    # -- navigation and queue -----------------------------------------

    def set_current(self, batch_id: str, shape_id: str = "") -> None:
        if (
            batch_id not in {batch.batch_id for batch in self.state.batches}
            and batch_id != NEW_PENDING_BATCH_ID
        ):
            return
        self.state.current_batch = batch_id
        members = self.state.member_ids(batch_id)
        if shape_id in members:
            self.state.current_object = shape_id
        elif members:
            self.state.current_object = members[0]
        else:
            self.state.current_object = ""

    def set_dimensions(self, dimensions: Iterable[str]) -> None:
        self.state.dimensions = self._normalize_dimensions(dimensions)

    def set_current_region(self, region_id: str) -> None:
        if self.state.coverage is None:
            return
        if self.state.coverage.region(region_id) is not None:
            self.state.coverage.current_region = region_id

    def add_to_batch(self, shape_id: str, batch_id: str) -> bool:
        batch = self.state.batch(batch_id)
        if batch is None or shape_id not in self.state.new_pending:
            return False
        self._push_progress_undo()
        self.state.new_pending.remove(shape_id)
        if shape_id not in batch.member_ids:
            batch.member_ids.append(shape_id)
        self.state.current_batch = batch_id
        self.state.current_object = shape_id
        self.dirty = True
        self._last_action = "progress"
        return True

    def rebuild_queue(self, shapes: Iterable[Any]) -> None:
        self._push_progress_undo()
        self.sync_shapes(shapes, record_history=False, mark_dirty=False)
        rebuild_batches(self.state, self.config)
        self.dirty = True
        self._last_action = "progress"

    def next_pending_object(
        self,
        batch_id: str,
        dimensions: Iterable[str],
        after: str = "",
    ) -> Optional[str]:
        requested = self._normalize_dimensions(dimensions)
        members = self.state.member_ids(batch_id)
        if not members:
            return None
        start = 0
        if after in members:
            start = members.index(after) + 1
        for offset in range(len(members)):
            shape_id = members[(start + offset) % len(members)]
            item = self.state.objects.get(shape_id)
            if item is None or item.difficult or item.skipped:
                continue
            if item.load_failed or not item.supported:
                continue
            if any(not item.confirmed(dimension) for dimension in requested):
                return shape_id
        return None

    def next_pending_batch(
        self, dimensions: Iterable[str], after: str = ""
    ) -> Optional[str]:
        requested = self._normalize_dimensions(dimensions)
        batch_ids = [batch.batch_id for batch in self.state.batches]
        if self.state.new_pending:
            batch_ids.append(NEW_PENDING_BATCH_ID)
        if not batch_ids:
            return None
        start = 0
        if after in batch_ids:
            start = batch_ids.index(after) + 1
        for offset in range(len(batch_ids)):
            batch_id = batch_ids[(start + offset) % len(batch_ids)]
            if self.next_pending_object(batch_id, requested):
                return batch_id
        return None

    def _advance_after_batch(
        self, batch_id: str, dimensions: Iterable[str]
    ) -> None:
        requested = self._normalize_dimensions(dimensions)
        next_batch = self.next_pending_batch(requested, after=batch_id)
        if next_batch is None:
            next_batch = batch_id
        self.state.current_batch = next_batch
        next_object = self.next_pending_object(next_batch, requested)
        if next_object is None:
            members = self.state.member_ids(next_batch)
            next_object = members[0] if members else ""
        self.state.current_object = next_object

    def _prune_new_pending(self) -> None:
        remaining = []
        for shape_id in self.state.new_pending:
            item = self.state.objects.get(shape_id)
            if item is None:
                continue
            if item.confirmed_both() and not item.difficult:
                continue
            remaining.append(shape_id)
        self.state.new_pending = remaining

    # -- configuration and coverage -----------------------------------

    def apply_config(
        self, config: ReviewConfig, shapes: Iterable[Any]
    ) -> None:
        issues = config.validate()
        if issues:
            raise ReviewConfigError(issues[0].message, issues)
        normalized = config.normalized()
        old_rules = self.config.rules_signature()
        self._push_progress_undo()
        self.config = normalized
        if normalized.rules_signature() != old_rules:
            self._clear_all_confirmations(invalidate_coverage=True)
            self.state.rules_signature = normalized.rules_signature()
            self._recompute_signatures(shapes)
        self.dirty = True
        self._last_action = "progress"

    def _recompute_signatures(self, shapes: Iterable[Any]) -> None:
        for shape in reviewable_shapes(shapes):
            item = self.state.objects.get(str(shape.xanylabeling_shape_id))
            if item is None:
                continue
            geometry = shape_geometry_signature(shape, self.config.rules)
            item.geometry_signature = geometry
            item.category_signature = shape_category_signature(
                shape, self.config.rules, geometry
            )
            bounds = shape_bounds(shape)
            if bounds is not None:
                item.bounds = bounds

    def _clear_all_confirmations(
        self, *, invalidate_coverage: bool = False
    ) -> None:
        for item in self.state.objects.values():
            item.clear_confirmation(REVIEW_DIMENSIONS)
        if invalidate_coverage and self.state.coverage is not None:
            coverage_service.invalidate_all(self.state.coverage)

    def ensure_coverage(self) -> CoveragePlan:
        if self.state.coverage is None:
            self.state.coverage = coverage_service.build_plan(
                self.config.coverage,
                self.state.image_width,
                self.state.image_height,
            )
        return self.state.coverage

    def rebuild_coverage(
        self,
        settings: CoverageSettings,
    ) -> CoveragePlan:
        self._push_progress_undo()
        self.config = ReviewConfig(
            batches=self.config.batches,
            rules=self.config.rules,
            coverage=settings.normalized(),
        )
        self.state.coverage = coverage_service.build_plan(
            settings,
            self.state.image_width,
            self.state.image_height,
        )
        self.dirty = True
        self._last_action = "progress"
        return self.state.coverage

    def complete_region(self, region_id: str) -> bool:
        plan = self.state.coverage
        if plan is None:
            return False
        self._push_progress_undo()
        if not coverage_service.complete_region(
            plan, region_id, self.state.objects
        ):
            self._discard_last_progress_undo()
            return False
        self._advance_region(plan, region_id)
        self.dirty = True
        self._last_action = "progress"
        return True

    def mark_region_difficult(
        self, region_id: str, difficult: bool = True
    ) -> bool:
        plan = self.state.coverage
        if plan is None:
            return False
        self._push_progress_undo()
        if not coverage_service.set_region_difficult(
            plan, region_id, difficult
        ):
            self._discard_last_progress_undo()
            return False
        if difficult:
            self._advance_region(plan, region_id)
        self.dirty = True
        self._last_action = "progress"
        return True

    def mark_region_skipped(
        self, region_id: str, skipped: bool = True
    ) -> bool:
        plan = self.state.coverage
        if plan is None:
            return False
        self._push_progress_undo()
        if not coverage_service.set_region_skipped(plan, region_id, skipped):
            self._discard_last_progress_undo()
            return False
        if skipped:
            self._advance_region(plan, region_id)
        self.dirty = True
        self._last_action = "progress"
        return True

    @staticmethod
    def _advance_region(plan: CoveragePlan, region_id: str) -> None:
        next_region = coverage_service.next_region(plan, start_after=region_id)
        if next_region is None:
            next_region = coverage_service.next_region(
                plan, include_difficult=True
            )
        if next_region is not None:
            plan.current_region = next_region.region_id

    # -- completion and counts ----------------------------------------

    def completion_status(self, translate=str) -> CompletionStatus:
        reasons: list[str] = []
        supported = True
        object_complete = True
        for item in self.state.objects.values():
            values = {"index": item.display_index, "label": item.label}
            if not item.supported:
                supported = False
                object_complete = False
                reasons.append(
                    translate(
                        "对象 #{index}（{label}）为首版不支持的非矩形形状"
                    ).format(**values)
                )
                continue
            if item.load_failed:
                object_complete = False
                reasons.append(
                    translate("对象 #{index}（{label}）无法呈现").format(
                        **values
                    )
                )
                continue
            if item.difficult:
                object_complete = False
                reasons.append(
                    translate("对象 #{index}（{label}）仍为疑难").format(
                        **values
                    )
                )
            if item.skipped:
                object_complete = False
                reasons.append(
                    translate("对象 #{index}（{label}）仍为暂跳").format(
                        **values
                    )
                )
            if not item.confirmed("category"):
                object_complete = False
                reasons.append(
                    translate("对象 #{index}（{label}）类别待审").format(
                        **values
                    )
                )
            if not item.confirmed("geometry"):
                object_complete = False
                reasons.append(
                    translate("对象 #{index}（{label}）框待审").format(
                        **values
                    )
                )
        if self.state.new_pending:
            object_complete = False
            reasons.append(
                translate("新增待处理还有 {count} 个对象").format(
                    count=len(self.state.new_pending)
                )
            )
        coverage_complete = False
        plan = self.state.coverage
        if plan is None:
            reasons.append(translate("空间查漏尚未开始"))
        else:
            counts = coverage_service.coverage_counts(plan)
            coverage_complete = (
                counts["total"] > 0 and counts["completed"] == counts["total"]
            )
            if counts["difficult"]:
                reasons.append(
                    translate("还有 {count} 个查漏区域为疑难").format(
                        count=counts["difficult"]
                    )
                )
            if counts["pending"]:
                reasons.append(
                    translate("还有 {count} 个查漏区域未完成").format(
                        count=counts["pending"]
                    )
                )
        complete = supported and object_complete and coverage_complete
        deduplicated = tuple(dict.fromkeys(reasons))
        return CompletionStatus(
            complete=complete,
            object_complete=object_complete,
            coverage_complete=coverage_complete,
            supported=supported,
            reasons=deduplicated,
        )

    def counts(self) -> dict[str, int]:
        items = list(self.state.objects.values())
        return {
            "total": len(items),
            "category_confirmed": sum(
                1 for item in items if item.confirmed("category")
            ),
            "geometry_confirmed": sum(
                1 for item in items if item.confirmed("geometry")
            ),
            "confirmed_both": sum(
                1 for item in items if item.confirmed_both()
            ),
            "difficult": sum(1 for item in items if item.difficult),
            "skipped": sum(1 for item in items if item.skipped),
            "unsupported": sum(1 for item in items if not item.supported),
            "new_pending": len(self.state.new_pending),
        }

    def label_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.state.objects.values():
            counts[item.label] = counts.get(item.label, 0) + 1
        return dict(sorted(counts.items()))

    def current_object(self) -> Optional[ObjectReviewState]:
        return self.state.objects.get(self.state.current_object)

    def object(self, shape_id: str) -> Optional[ObjectReviewState]:
        return self.state.objects.get(shape_id)

    def batch_counts(self, batch_id: str) -> dict[str, int]:
        members = self.state.member_ids(batch_id)
        items = [
            self.state.objects[shape_id]
            for shape_id in members
            if shape_id in self.state.objects
        ]
        confirmed = sum(1 for item in items if item.confirmed_both())
        return {
            "total": len(items),
            "confirmed": confirmed,
            "pending": len(items) - confirmed,
        }

    def rule_summary(self, label: str, translate=str) -> str:
        rule = self.config.rules.box_rule(label)
        note = self.config.rules.note(label)
        parts = [
            translate("类别：{note}").format(
                note=note or translate("未填写类别规则说明")
            ),
            translate("框：{rule}").format(
                rule=translate(self._box_rule_label(rule))
            ),
        ]
        return translate("；").join(parts)

    @staticmethod
    def _box_rule_label(rule: str) -> str:
        return {
            "visible": "可见框",
            "full": "完整框",
            "unknown": "未知（跨类不保留框确认）",
        }.get(rule, "未知")

    # -- undo ----------------------------------------------------------

    def next_undo_kind(self) -> str:
        """Return ``progress`` or ``canvas`` for the next undo target."""
        if not self._history:
            return "canvas"
        top = self._history[-1]
        if top.kind != "progress":
            return "canvas"
        if top.content_hash != self._last_content_hash:
            return "canvas"
        return "progress"

    def can_undo_progress(self) -> bool:
        return self.next_undo_kind() == "progress"

    def undo_progress(self) -> bool:
        if not self.can_undo_progress():
            return False
        entry = self._history.pop()
        self._redo_progress.append(
            _RedoEntry(
                kind="progress",
                state=copy.deepcopy(self.state),
                content_hash=self._last_content_hash,
            )
        )
        self._redo_order.append("progress")
        self.state = entry.state
        self.dirty = True
        return True

    def undo_after_canvas(self, shapes: Iterable[Any]) -> bool:
        """Restore the snapshot owned by the canvas transaction being undone."""
        current_hash = content_hash(reviewable_shapes(shapes))
        # The canvas owns its own snapshot stack, so every canvas undo is one
        # entry in the shared redo order even when it carries no review change.
        self._redo_order.append("canvas")
        if current_hash == self._last_content_hash:
            # A canvas-only style change must not consume a content transaction.
            return False
        before_state = copy.deepcopy(self.state)
        before_hash = self._last_content_hash
        redo_entry = _RedoEntry(
            kind="content",
            state=before_state,
            content_hash=before_hash,
        )
        popped = False
        while self._history and self._history[-1].kind == "content":
            entry = self._history.pop()
            popped = True
            if entry.before_hash == current_hash:
                self._redo_content.append(redo_entry)
                self.state = entry.state
                self._last_content_hash = current_hash
                self.dirty = True
                self._last_action = ""
                return True
        self._redo_content.append(redo_entry)
        self.sync_shapes(shapes, record_history=False, mark_dirty=True)
        self._last_action = ""
        return popped

    def _clear_redo(self) -> None:
        """Drop the redo stream when a new transaction supersedes it."""
        self._redo_progress.clear()
        self._redo_content.clear()
        self._redo_order.clear()

    def _push_progress_undo(self) -> None:
        # Keep the redo stream so a rejected/no-op action can restore it.
        self._redo_snapshot = (
            tuple(self._redo_progress),
            tuple(self._redo_content),
            tuple(self._redo_order),
        )
        self._clear_redo()
        self._history.append(
            _HistoryEntry(
                kind="progress",
                state=copy.deepcopy(self.state),
                content_hash=self._last_content_hash,
            )
        )

    def _discard_last_progress_undo(self) -> None:
        if self._history and self._history[-1].kind == "progress":
            self._history.pop()
            snapshot = getattr(self, "_redo_snapshot", None)
            if snapshot is not None:
                progress, content, order = snapshot
                self._redo_progress.extend(progress)
                self._redo_content.extend(content)
                self._redo_order.extend(order)
        self._redo_snapshot = None

    # -- redo ----------------------------------------------------------

    def next_redo_kind(self) -> str:
        """Return ``progress`` or ``canvas`` for the next redo target."""
        while self._redo_order:
            kind = self._redo_order[-1]
            if kind == "progress" and self._redo_progress:
                return "progress"
            if kind == "canvas":
                return "canvas"
            self._redo_order.pop()
        return "canvas"

    def can_redo_progress(self) -> bool:
        return self.next_redo_kind() == "progress"

    def has_redo(self) -> bool:
        """Report whether any session-level transaction can be re-applied."""
        return bool(self._redo_order)

    def drop_stale_canvas_redo(self) -> None:
        """Discard a canvas marker whose canvas snapshot no longer exists."""
        if self._redo_order and self._redo_order[-1] == "canvas":
            self._redo_order.pop()

    def redo_progress(self) -> bool:
        if not self.can_redo_progress():
            return False
        entry = self._redo_progress.pop()
        self._redo_order.pop()
        self._history.append(
            _HistoryEntry(
                kind="progress",
                state=copy.deepcopy(self.state),
                content_hash=self._last_content_hash,
            )
        )
        self.state = entry.state
        self.dirty = True
        self._last_action = "progress"
        return True

    def redo_after_canvas(self, shapes: Iterable[Any]) -> bool:
        """Re-apply the review snapshot owned by the canvas redo."""
        if self._redo_order and self._redo_order[-1] == "canvas":
            self._redo_order.pop()
        current_hash = content_hash(reviewable_shapes(shapes))
        if (
            self._redo_content
            and self._redo_content[-1].content_hash == current_hash
        ):
            entry = self._redo_content.pop()
            self.state = entry.state
            self._last_content_hash = current_hash
            self.dirty = True
            self._last_action = ""
            return True
        self.sync_shapes(shapes, record_history=False, mark_dirty=True)
        self._last_action = ""
        return False

    def _normalize_dimensions(
        self, dimensions: Iterable[str]
    ) -> tuple[str, ...]:
        result = tuple(
            dimension
            for dimension in REVIEW_DIMENSIONS
            if dimension in set(dimensions)
        )
        return result or REVIEW_DIMENSIONS

    # -- persistence ---------------------------------------------------

    def to_payload(self) -> dict[str, Any]:
        return self.state.to_dict()

    def mark_saved(self) -> None:
        self.dirty = False
        self.has_payload = True
        self._removed.clear()

    def payload_signature(self) -> str:
        return signature_for(self.state.to_dict())

    def debug_summary(self) -> str:
        return canonical_json(
            {
                "objects": self.counts(),
                "batches": len(self.state.batches),
                "coverage": coverage_service.coverage_counts(
                    self.state.coverage
                ),
                "dirty": self.dirty,
            }
        )

"""Pure in-memory state machine for image viewport lifecycle management.

The module deliberately contains no Qt imports.  It models the state and
the load decision; ``ViewportController`` remains responsible for converting
between Qt scrollbars and image coordinates.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, IntEnum
from types import MappingProxyType


class ViewportZoomMode(IntEnum):
    """Supported zoom modes shared with ``LabelingWidget``."""

    FIT_WINDOW = 0
    FIT_WIDTH = 1
    MANUAL_ZOOM = 2


class ViewportStatus(str, Enum):
    """Derived lifecycle state for one image."""

    UNKNOWN = "unknown"
    CACHED = "cached"
    RESET_PENDING = "reset_pending"


class ViewportSource(str, Enum):
    """Source selected by the deterministic load resolver."""

    FORCE_DEFAULT = "force_default"
    EXACT = "exact"
    PREVIOUS_VIEWPORT = "previous_viewport"
    PREVIOUS_SCALE = "previous_scale"
    DEFAULT = "default"


@dataclass(frozen=True)
class ViewportState:
    """Immutable image-coordinate snapshot of one image's viewport."""

    zoom_mode: int
    zoom_value: int
    center_x: float
    center_y: float

    def __post_init__(self) -> None:
        """Validate state before it enters the state machine."""
        try:
            mode = ViewportZoomMode(self.zoom_mode)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"unsupported viewport zoom mode: {self.zoom_mode}"
            ) from exc
        if int(self.zoom_value) <= 0:
            raise ValueError("viewport zoom value must be positive")
        if not math.isfinite(float(self.center_x)) or not math.isfinite(
            float(self.center_y)
        ):
            raise ValueError("viewport centre coordinates must be finite")
        object.__setattr__(self, "zoom_mode", int(mode))
        object.__setattr__(self, "zoom_value", int(self.zoom_value))
        object.__setattr__(self, "center_x", float(self.center_x))
        object.__setattr__(self, "center_y", float(self.center_y))


@dataclass(frozen=True)
class ViewportLoadPlan:
    """Read-only decision describing how a file should be loaded."""

    file_id: str
    source: ViewportSource
    state: ViewportState | None = None
    zoom_value: int | None = None

    def __post_init__(self) -> None:
        """Validate the payload allowed by the selected source."""
        if (
            self.source
            in (
                ViewportSource.EXACT,
                ViewportSource.PREVIOUS_VIEWPORT,
            )
            and self.state is None
        ):
            raise ValueError(f"{self.source.value} requires a viewport state")
        if self.source is ViewportSource.PREVIOUS_SCALE:
            if self.zoom_value is None or int(self.zoom_value) <= 0:
                raise ValueError(
                    "previous-scale plan requires a positive zoom"
                )
        if (
            self.source not in (ViewportSource.PREVIOUS_SCALE,)
            and self.zoom_value is not None
        ):
            raise ValueError(
                f"{self.source.value} cannot carry a zoom-only value"
            )


@dataclass(frozen=True)
class ViewportResetResult:
    """Summary of a committed reset request."""

    filenames: tuple[str, ...]
    cleared_state_count: int
    marked_default_count: int


@dataclass(frozen=True)
class ViewportStateSnapshot:
    """Small rollback snapshot for a reset transaction."""

    states: Mapping[str, ViewportState | None]
    pending_defaults: frozenset[str]
    active_file_id: str | None
    previous_scale: int | None


class ViewportStateMachine:
    """Manage sparse per-file viewport states within one dataset session."""

    def __init__(self) -> None:
        self._states: dict[str, ViewportState] = {}
        self._reset_pending: set[str] = set()
        self._active_file_id: str | None = None
        self._previous_scale: int | None = None

    @property
    def active_file_id(self) -> str | None:
        """Return the last successfully committed file load."""
        return self._active_file_id

    @property
    def previous_scale(self) -> int | None:
        """Return the last successfully applied zoom value."""
        return self._previous_scale

    @staticmethod
    def normalize_file_id(
        filename: str | os.PathLike[str] | None,
    ) -> str | None:
        """Return a stable absolute, normalized file identity."""
        if filename is None:
            return None
        value = os.fspath(filename)
        if not isinstance(value, str) or not value:
            return None
        value = os.path.abspath(os.path.normpath(os.path.expanduser(value)))
        return os.path.normcase(value)

    def status(
        self, filename: str | os.PathLike[str] | None
    ) -> ViewportStatus:
        """Return the derived three-state status for *filename*."""
        file_id = self.normalize_file_id(filename)
        if file_id is None:
            return ViewportStatus.UNKNOWN
        if file_id in self._reset_pending:
            return ViewportStatus.RESET_PENDING
        if file_id in self._states:
            return ViewportStatus.CACHED
        return ViewportStatus.UNKNOWN

    def get_state(
        self, filename: str | os.PathLike[str] | None
    ) -> ViewportState | None:
        """Return a cached state without exposing the internal mapping."""
        file_id = self.normalize_file_id(filename)
        return self._states.get(file_id) if file_id is not None else None

    def pending_defaults(self) -> frozenset[str]:
        """Return a read-only view of pending default file identities."""
        return frozenset(self._reset_pending)

    def debug_snapshot(self) -> Mapping[str, ViewportState]:
        """Return a read-only copy suitable for diagnostics and tests."""
        return MappingProxyType(dict(self._states))

    def capture(self, filename: str, state: ViewportState) -> str:
        """Commit a valid exact snapshot and transition the file to CACHED."""
        file_id = self._require_file_id(filename)
        if not isinstance(state, ViewportState):
            raise TypeError("state must be a ViewportState")
        self._states[file_id] = state
        self._reset_pending.discard(file_id)
        self._previous_scale = state.zoom_value
        self._assert_invariants()
        return file_id

    def commit_loaded(
        self,
        filename: str,
        plan: ViewportLoadPlan,
        *,
        applied_zoom: int | None = None,
    ) -> str:
        """Commit a successfully applied load plan."""
        file_id = self._require_file_id(filename)
        if plan.file_id != file_id:
            raise ValueError("load plan belongs to a different file")
        if plan.source is ViewportSource.FORCE_DEFAULT:
            self._reset_pending.discard(file_id)
        if plan.state is not None:
            self._previous_scale = plan.state.zoom_value
        elif applied_zoom is not None and int(applied_zoom) > 0:
            self._previous_scale = int(applied_zoom)
        self._active_file_id = file_id
        self._assert_invariants()
        return file_id

    def consume_reset_pending(self, filename: str) -> bool:
        """Consume a pending reset marker after a successful default apply."""
        file_id = self._require_file_id(filename)
        if file_id not in self._reset_pending:
            return False
        self._reset_pending.remove(file_id)
        self._assert_invariants()
        return True

    def resolve_load_plan(
        self,
        filename: str,
        *,
        keep_prev_viewport: bool,
        keep_prev_scale: bool,
    ) -> ViewportLoadPlan:
        """Resolve the five-level load priority without mutating state."""
        file_id = self._require_file_id(filename)
        if file_id in self._reset_pending:
            return ViewportLoadPlan(file_id, ViewportSource.FORCE_DEFAULT)

        exact = self._states.get(file_id)
        if exact is not None:
            return ViewportLoadPlan(file_id, ViewportSource.EXACT, state=exact)

        previous_state = self._states.get(self._active_file_id)
        if keep_prev_viewport and previous_state is not None:
            return ViewportLoadPlan(
                file_id,
                ViewportSource.PREVIOUS_VIEWPORT,
                state=previous_state,
            )

        if keep_prev_scale and self._previous_scale is not None:
            return ViewportLoadPlan(
                file_id,
                ViewportSource.PREVIOUS_SCALE,
                zoom_value=self._previous_scale,
            )

        return ViewportLoadPlan(file_id, ViewportSource.DEFAULT)

    def reset(
        self, filenames: Iterable[str], *, mark_default: bool = True
    ) -> ViewportResetResult:
        """Invalidate a stable, de-duplicated sequence of file identities."""
        unique_ids = self._normalize_filenames(filenames)
        cleared_count = sum(file_id in self._states for file_id in unique_ids)
        for file_id in unique_ids:
            self._states.pop(file_id, None)
            if mark_default:
                self._reset_pending.add(file_id)
            else:
                self._reset_pending.discard(file_id)
        self._assert_invariants()
        return ViewportResetResult(
            filenames=unique_ids,
            cleared_state_count=cleared_count,
            marked_default_count=len(unique_ids) if mark_default else 0,
        )

    def reset_with_rollback(
        self,
        filenames: Iterable[str],
        *,
        mark_default: bool = True,
        after_reset: Callable[[ViewportResetResult], None] | None = None,
    ) -> ViewportResetResult:
        """Commit a reset and restore its snapshot when a callback fails.

        The optional callback is intended for the UI coordinator to perform
        additional cache invalidation while the state machine owns rollback.
        Exceptions are re-raised after restoring the snapshot so callers
        cannot mistake a partial reset for success.
        """
        snapshot = self.snapshot(filenames)
        try:
            result = self.reset(filenames, mark_default=mark_default)
            if after_reset is not None:
                after_reset(result)
        except Exception:
            self.restore(snapshot)
            raise
        return result

    def snapshot(self, filenames: Iterable[str]) -> ViewportStateSnapshot:
        """Capture enough state to roll back a reset transaction."""
        unique_ids = self._normalize_filenames(filenames)
        return ViewportStateSnapshot(
            states={
                file_id: self._states.get(file_id) for file_id in unique_ids
            },
            pending_defaults=frozenset(
                file_id
                for file_id in unique_ids
                if file_id in self._reset_pending
            ),
            active_file_id=self._active_file_id,
            previous_scale=self._previous_scale,
        )

    def restore(self, snapshot: ViewportStateSnapshot) -> None:
        """Restore a snapshot captured before a reset transaction."""
        for file_id, state in snapshot.states.items():
            if state is None:
                self._states.pop(file_id, None)
            else:
                self._states[file_id] = state
        target_ids = set(snapshot.states)
        self._reset_pending.difference_update(target_ids)
        self._reset_pending.update(snapshot.pending_defaults)
        self._active_file_id = snapshot.active_file_id
        self._previous_scale = snapshot.previous_scale
        self._assert_invariants()

    def clear_session(self) -> None:
        """Clear all viewport state at a dataset boundary."""
        self._states.clear()
        self._reset_pending.clear()
        self._active_file_id = None
        self._previous_scale = None

    def clear_file(self, filename: str) -> bool:
        """Remove all state for one file as a lifecycle cleanup operation."""
        file_id = self._require_file_id(filename)
        removed = file_id in self._states or file_id in self._reset_pending
        self._states.pop(file_id, None)
        self._reset_pending.discard(file_id)
        if self._active_file_id == file_id:
            self._active_file_id = None
        self._assert_invariants()
        return removed

    @classmethod
    def _normalize_filenames(
        cls, filenames: Iterable[str] | None
    ) -> tuple[str, ...]:
        """Normalize and de-duplicate valid filenames in stable order."""
        if filenames is None:
            return ()
        result: dict[str, None] = {}
        for filename in filenames:
            file_id = cls.normalize_file_id(filename)
            if file_id is not None:
                result.setdefault(file_id, None)
        return tuple(result)

    @classmethod
    def _require_file_id(cls, filename: str) -> str:
        """Normalize a required filename or raise a useful error."""
        file_id = cls.normalize_file_id(filename)
        if file_id is None:
            raise ValueError("filename must be a non-empty path")
        return file_id

    def _assert_invariants(self) -> None:
        """Assert that exact and pending states remain mutually exclusive."""
        overlap = set(self._states).intersection(self._reset_pending)
        if overlap:
            raise AssertionError(
                f"viewport state invariant violated: {overlap}"
            )

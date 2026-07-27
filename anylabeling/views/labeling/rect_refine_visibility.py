# PyQt-free module — MUST NOT import PyQt6 or any UI widget.
"""Three-layer visibility model for the three-box refine mode.

Implements the §28 visibility split.  The crucial invariant (§28.1,
audit risk #2): the *task* layer must **never** be simulated by overwriting
``shape.visible`` / ``canvas.visible`` / label-list check state.  Those fields
belong to the *base* layer (navigator + restore semantics).  The task layer is
an independent in-memory set of member ids.

Three layers (§28.2):
    base_visible  — user filter / label visibility / per-shape manual visibility
                    (navigator + restore logic)
    task_visible  — the ACTIVE workgroup's member set (main canvas task view)
    main_visible  — OFF/SELECTING/INFERRING → base; ACTIVE/SAVING → task

The base snapshot is a deep copy captured once at mode entry (§24.5, §28.1);
it is restored verbatim on exit (invariant §22.3 #11).  Stage 1+2 captures the
per-shape boolean only; stage 4 will extend the snapshot to the full filter /
label-check / per-shape ``(visible, canvas_visible, hidden_by_filter)`` triple
without changing these method signatures.

References:
    §24.5 WorkgroupSnapshot    §28.2 three visibilities
    §27.3 Visibility interface  §28.5 navigator
    §33.5 visibility acceptance (pure-logic subset)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Sequence, Set

from .rect_refine_types import RectRefineState, ShapeId, ShapeRefineView


@dataclass
class BaseVisibilitySnapshot:
    """Deep-copied base-layer visibility captured at mode entry.

    Stage 1+2 stores only the per-shape boolean.  The fields below are
    reserved for stage 4 (filter state, label check state, per-shape
    ``(visible, canvas_visible, hidden_by_filter)``).  Keeping them here means
    :meth:`RectRefineVisibility.capture_base_state` won't need a signature
    change later — only richer input.
    """

    per_shape: Dict[ShapeId, bool] = field(default_factory=dict)
    #: Reserved for stage 4 — opaque snapshot of the FilterEngine state.
    filter_state: object = None
    #: Reserved for stage 4 — opaque snapshot of label-list check state.
    label_check_state: object = None
    #: Reserved for stage 4 — per-shape (shape.visible, canvas.visible,
    #: hidden_by_filter) triple captured verbatim.
    per_shape_full: Dict[ShapeId, object] = field(default_factory=dict)


class RectRefineVisibility:
    """Owns the base snapshot and the (optional) task-layer member set.

    The task layer is *only* present while a workgroup is ACTIVE/SAVING.  It
    is cleared on workgroup release, rollback, save success or image change
    (§28.4) so SELECTING returns to base-layer display.
    """

    def __init__(self) -> None:
        self._base: Optional[BaseVisibilitySnapshot] = None
        self._task_member_ids: Optional[Set[ShapeId]] = None

    # ------------------------------------------------------------------
    # §27.3 interface
    # ------------------------------------------------------------------

    def capture_base_state(self, views: Sequence[ShapeRefineView]) -> None:
        """Deep-copy each Shape's base visibility (§27.3).

        ``ShapeRefineView.base_visible`` carries the stage-1+2 boolean.  Stage
        4 will populate the richer ``per_shape_full`` / ``filter_state`` /
        ``label_check_state`` fields via an extended adapter; the method
        signature stays stable.
        """
        self._base = BaseVisibilitySnapshot(
            per_shape={v.shape_id: bool(v.base_visible) for v in views}
        )
        self._task_member_ids = None

    def base_visible(self, shape_id: ShapeId) -> bool:
        """Return ``True`` iff the shape is visible on the *base* layer.

        Unknown ids default to ``True`` (mirrors ``Canvas.is_visible``).
        """
        if self._base is None:
            return True
        return self._base.per_shape.get(shape_id, True)

    def set_workgroup_task_layer(self, member_ids: Iterable[ShapeId]) -> None:
        """Install the task layer — main canvas shows only these members."""
        self._task_member_ids = set(member_ids)

    def clear_task_layer(self) -> None:
        """Remove the task layer; base layer is untouched (§27.3)."""
        self._task_member_ids = None

    def task_visible(self, shape_id: ShapeId) -> bool:
        """Return ``True`` iff the shape is a current workgroup member.

        Outside ACTIVE/SAVING the task layer is absent and this returns
        ``False`` for every id.
        """
        if self._task_member_ids is None:
            return False
        return shape_id in self._task_member_ids

    def main_visible(self, shape_id: ShapeId, state: RectRefineState) -> bool:
        """Effective main-canvas visibility for the given workflow state.

        §28.2:
            OFF / SELECTING / INFERRING  → base
            ACTIVE / SAVING              → task

        INFERRING is a synchronous transient (§28.2 last paragraph); the task
        layer is only installed *after* a successful GROUP_READY transition,
        so during INFERRING the main canvas still shows the base layer.
        """
        if state in (RectRefineState.ACTIVE, RectRefineState.SAVING):
            return self.task_visible(shape_id)
        return self.base_visible(shape_id)

    def navigator_visibility(
        self, views: Sequence[ShapeRefineView]
    ) -> Dict[ShapeId, bool]:
        """Per-shape base visibility for the navigator (§28.5).

        The navigator must never read the task layer; it always reflects the
        user's base filter.  This is the core of AC-052.
        """
        return {v.shape_id: self.base_visible(v.shape_id) for v in views}

    def restore_base_state(self) -> None:
        """Drop the task layer; keep the base snapshot for stage-4 restore.

        §27.3: restoring the *full* base UI (filter controls, label checks,
        per-shape flags) is a stage-4 concern that reads this snapshot.  Here
        we only guarantee the task layer is cleared so main_visible returns
        to base.
        """
        self._task_member_ids = None

    # ------------------------------------------------------------------
    # Introspection — used by workflow + tests
    # ------------------------------------------------------------------

    @property
    def has_base_snapshot(self) -> bool:
        return self._base is not None

    @property
    def has_task_layer(self) -> bool:
        return self._task_member_ids is not None

    @property
    def task_member_ids(self) -> Optional[frozenset]:
        if self._task_member_ids is None:
            return None
        return frozenset(self._task_member_ids)

    def base_snapshot(self) -> Optional[BaseVisibilitySnapshot]:
        """Test-only accessor for invariant assertions (AC-053/054)."""
        return self._base


__all__ = ["BaseVisibilitySnapshot", "RectRefineVisibility"]

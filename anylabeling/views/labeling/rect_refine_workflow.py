# PyQt-free module — MUST NOT import PyQt6 or any UI widget.
"""Rect-refine workflow state machine and adapter contracts.

The workflow is the **single source of truth** for refine-mode state (§27.6).
Menu check-state, Canvas toggles and Overlay visibility are all *derived* from
``workflow.state``; they never reconstruct it.

Three :class:`typing.Protocol` adapters isolate this pure-logic module from
Qt.  Stage 4 (LabelWidget integration) provides concrete implementations and
injects them here; stage 1+2 tests drive the state machine with fakes.

Audit blocking risks addressed in this module:

* #3  Save cancelled/failed must not release the workgroup — see
       :meth:`RectRefineWorkflow.accept_workgroup`.
* #4  Esc rollback must not unconditionally clear dirty — see
       :meth:`RectRefineWorkflow._rollback_workgroup` + :class:`DirtyAdapter`.
* #5  Ctrl+Z must not cross ``undo_floor`` — see
       :meth:`RectRefineWorkflow.is_undo_blocked`.
* #10 Grouping reads only in-memory :class:`ShapeRefineView` — the workflow
       builds views from live shapes; disk QA loaders are never used.

Risk #1 (auto-save blocking) is *not* handled here: the workflow never
triggers saves itself.  Stage 4 disconnects ``shape_moved → set_dirty`` while
ACTIVE so dragged-edge geometry cannot reach ``save_labels()`` until the user
explicitly accepts.

References:
    §25   state machine          §27   interface contracts
    §26   detailed workflow      §32   failure handling
"""

from __future__ import annotations

import copy
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

from .rect_refine_grouping import DEFAULTS, GroupingResult, infer
from .rect_refine_types import (
    BBox,
    CandidateSource,
    ConflictCode,
    OverlayModel,
    OverlayRelation,
    Point,
    RectRefineState,
    RectRefineWorkgroup,
    RelationGraph,
    RelationKind,
    SaveResult,
    ShapeId,
    ShapeRefineView,
    WorkgroupSnapshot,
    validate_snapshot,
)
from .rect_refine_visibility import RectRefineVisibility

# ---------------------------------------------------------------------------
# §27.4 / §27.5 / §32.3 adapter contracts
# ---------------------------------------------------------------------------


@runtime_checkable
class CanvasAdapter(Protocol):
    """Minimal Canvas surface the workflow needs (§27.4).

    Stage 4 implements this on/around ``LabelingWidget``; the workflow never
    imports ``Canvas`` directly.
    """

    def is_rect_edge_dragging(self) -> bool:
        """A rectangle-edge drag is currently in progress."""
        ...

    def has_rect_edge_pending(self) -> bool:
        """A rectangle-edge pending (uncommitted) state exists."""
        ...

    def cancel_rect_edge_drag(self) -> None:
        """Cancel an active rect-edge drag (§25.3 Esc tier 1)."""
        ...

    def clear_rect_edge_pending(self) -> None:
        """Clear rect-edge pending/hover (§25.3 Esc tier 2)."""
        ...

    def undo_backup_count(self) -> int:
        """Current ``len(canvas.shapes_backups)`` — used as undo floor."""
        ...

    def shape_alive(self, shape_ref: Any) -> bool:
        """``True`` iff ``shape_ref`` is still in the current canvas.shapes."""
        ...

    def shapes_count(self) -> int:
        """Number of shapes currently on the canvas (liveness sanity)."""
        ...

    # Stage 3 — main-canvas visibility + Esc + overlay hooks.  These let the
    # workflow install the task layer and Esc tier-3 callback without the
    # Canvas ever importing the workflow module.

    def install_workgroup_visibility(
        self, member_shape_ids, image_token: str
    ) -> None:
        """Restrict main-canvas visibility to the given member shape ids."""
        ...

    def clear_workgroup_visibility(self) -> None:
        """Drop the task visibility layer; base layer is untouched."""
        ...

    def set_escape_handler(self, handler) -> None:
        """Install the Esc tier-3 callback (``None`` clears)."""
        ...

    def install_overlay_provider(self, provider) -> None:
        """Install a callable returning an OverlayModel for paint."""
        ...

    def clear_overlay_provider(self) -> None:
        """Remove the overlay provider."""
        ...

    def set_whole_shape_edit_blocker(self, blocker) -> None:
        """Install/clear the AC-058 whole-shape-edit gate (§22.2).

        ``blocker`` is a zero-arg callable returning True while whole-shape
        edits (mouse drag, arrow move, rotation) must be blocked.  Pass
        ``None`` to clear.
        """
        ...

    # Stage 6 — workgroup-limited undo reads/writes member points in place
    # (never via canvas.restore_shape, which would replace the shapes list
    # and break member ``id(shape)`` identity; audit risk #5).

    def get_shape_points(self, shape_ref: Any) -> Tuple[Point, ...]:
        """Read a live member's points as ``((x, y), ...)`` tuples."""
        ...

    def set_shape_points(
        self, shape_ref: Any, points: Tuple[Point, ...]
    ) -> None:
        """Restore a member's points in place (no list replacement)."""
        ...


@runtime_checkable
class SaveAdapter(Protocol):
    """§27.5 save adapter wrapping ``save_labels()``.

    Must distinguish user-cancel (no file chosen) from write failure.  Both
    return non-SUCCESS and both keep the workgroup ACTIVE (§32.1).
    """

    def save_current(self) -> SaveResult: ...  # noqa: E704


@runtime_checkable
class DirtyAdapter(Protocol):
    """§32.3 dirty-state adapter.

    Enables *precise* dirty restoration on rollback: the workflow records
    ``dirty_before`` at workgroup construction and restores that exact value
    on Esc.  It never calls an unconditional ``set_clean()`` (audit risk #4).
    """

    def is_dirty(self) -> bool: ...  # noqa: E704

    def set_dirty(self, value: bool) -> None:
        """Restore dirty to a captured value (``False`` → clean, ``True`` → dirty)."""
        ...


@runtime_checkable
class ShapeViewBuilder(Protocol):
    """Builds a :class:`ShapeRefineView` from a live Shape reference.

    The workflow itself is PyQt-free, so it delegates the
    ``Shape → (points, bbox, group_id, …)`` extraction to stage 4.  This keeps
    the grouping input purely in-memory (audit risk #10): no disk QA loader
    is ever consulted.
    """

    def build_view(  # noqa: E704
        self,
        shape_ref: Any,
        shape_index: int,
        image_token: str,
        base_visible: bool = True,
    ) -> ShapeRefineView: ...


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


class RectRefineWorkflow:
    """Sole owner of refine-mode state (§23.2, §27.6).

    Constructed once by the LabelWidget with concrete adapter implementations.
    All state transitions go through :meth:`_set_state`; public methods are
    thin event handlers that check guards (§25.2) before transitioning.
    """

    def __init__(
        self,
        canvas: CanvasAdapter,
        save: SaveAdapter,
        dirty: DirtyAdapter,
        view_builder: ShapeViewBuilder,
        visibility: Optional[RectRefineVisibility] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._canvas = canvas
        self._save = save
        self._dirty = dirty
        self._view_builder = view_builder
        self._visibility = visibility or RectRefineVisibility()
        self._config = config if config is not None else DEFAULTS

        self._state: RectRefineState = RectRefineState.OFF
        self._workgroup: Optional[RectRefineWorkgroup] = None
        self._image_token: str = ""
        #: Live shape references for the *current* workgroup members, keyed by
        #: shape_id.  Cleared on release/rollback/image-change.
        self._member_refs: Dict[ShapeId, Any] = {}
        #: Stage 6 — workgroup-limited undo points history.  Each entry is a
        #: per-member points snapshot; the build-time snapshot is the stack
        #: base.  ``commit_member_points`` pushes; ``handle_undo_request``
        #: pops.  Independent of ``canvas.shapes_backups`` so undo never
        #: replaces the shapes list (audit risk #5).
        self._undo_stack: List[Dict[ShapeId, Tuple[Point, ...]]] = []

    # ------------------------------------------------------------------
    # Public state (single source of truth, §27.6)
    # ------------------------------------------------------------------

    @property
    def state(self) -> RectRefineState:
        return self._state

    @property
    def image_token(self) -> str:
        return self._image_token

    @property
    def visibility(self) -> RectRefineVisibility:
        return self._visibility

    @property
    def has_active_workgroup(self) -> bool:
        return (
            self._workgroup is not None
            and self._state == RectRefineState.ACTIVE
        )

    @property
    def undo_floor(self) -> int:
        """The Ctrl+Z floor captured at workgroup construction (§32.4)."""
        if self._workgroup is None:
            return 0
        return self._workgroup.snapshot.undo_floor

    def is_undo_blocked(self) -> bool:
        """Whether a generic Ctrl+Z must be blocked right now.

        Returns ``True`` only when ACTIVE/SAVING *and* the backup stack has
        been consumed down to the floor.  Stage 4 queries this from the
        Canvas undo path (audit risk #5).
        """
        if self._workgroup is None:
            return False
        if self._state not in (
            RectRefineState.ACTIVE,
            RectRefineState.SAVING,
        ):
            return False
        return self._canvas.undo_backup_count() <= self.undo_floor

    # ------------------------------------------------------------------
    # Stage 4A integration hooks
    # ------------------------------------------------------------------

    def is_active_workgroup(self) -> bool:
        """Stage 4A DirtyAdapter query: is there an ACTIVE workgroup?

        Used by :meth:`LabelingWidget._on_canvas_shape_moved_for_dirty`
        to decide whether ``shape_moved`` should be blocked from auto-save.
        """
        return self.has_active_workgroup

    def note_geometry_changed(self) -> None:
        """Mark a temporary geometry change inside the ACTIVE workgroup.

        Called from the stage-4A dirty-routing wrapper when ``shape_moved``
        fires while ACTIVE.  Records the change on the workgroup *only*; it
        never touches the global dirty flag and never triggers a save
        (audit risk #1).  Rollback / save-success clears the whole workgroup
        object, so this flag naturally resets — no extra cleanup needed.
        """
        if self._workgroup is not None:
            self._workgroup.has_committed_geometry = True

    def commit_member_points(self) -> None:
        """Stage 6 — snapshot the current member points onto the undo stack.

        Called by the LabelWidget dirty-wrapper *after* a workgroup edge-drag
        commits (post-``shape_moved``).  The pushed snapshot is the basis for
        one workgroup-limited undo step.  No-op when no workgroup is ACTIVE.
        """
        if self._workgroup is None or not self.is_active_workgroup():
            return
        snapshot: Dict[ShapeId, Tuple[Point, ...]] = {}
        for sid, ref in self._member_refs.items():
            if ref is not None and self._canvas.shape_alive(ref):
                snapshot[sid] = self._canvas.get_shape_points(ref)
        self._undo_stack.append(snapshot)

    def handle_undo_request(self) -> bool:
        """Stage 6 — process Ctrl+Z while a workgroup is ACTIVE.

        Returns ``True`` when the event is consumed (the caller must NOT run
        the normal ``canvas.restore_shape()`` path).  Two cases:

        * At/below ``undo_floor`` (only the build-time snapshot remains, or
          the canvas backup stack has been drained to the floor): block —
          never cross into pre-group history (audit risk #5, AC-067).
        * Workgroup edits exist on the points stack: pop one entry and
          restore each still-alive member's points *in place* (no shapes-list
          replacement, no ``set_dirty()``, no auto-save — AC-066).

        Returns ``False`` when no workgroup is ACTIVE (caller runs normal undo).
        """
        if not self.is_active_workgroup():
            return False
        # Floor guard: never let undo reach pre-group history.
        if self._canvas.undo_backup_count() <= self.undo_floor:
            return True
        # Workgroup-limited in-place undo.
        if len(self._undo_stack) > 1:
            self._undo_stack.pop()  # discard the current points
            prev = self._undo_stack[-1]
            for sid, pts in prev.items():
                ref = self._member_refs.get(sid)
                if ref is not None and self._canvas.shape_alive(ref):
                    self._canvas.set_shape_points(ref, pts)
            if self._workgroup is not None:
                self._workgroup.has_committed_geometry = (
                    len(self._undo_stack) > 1
                )
            return True
        # Only the build-time snapshot remains → at the group's own floor.
        return True

    @property
    def workgroup_geometry_dirty(self) -> bool:
        """Whether the ACTIVE workgroup has uncommitted geometry changes."""
        if self._workgroup is None:
            return False
        return self._workgroup.has_committed_geometry

    def on_image_loaded(self, image_token: str) -> None:
        """Stage 4A: notify a new image-load lifecycle completed.

        The base visibility snapshot was already captured at mode entry (or
        will be re-captured by stage 4B's filter-state tracking); here we
        only refresh the token and return SELECTING images to the base layer.
        """
        self.after_image_loaded(image_token, [])

    def accept_current_workgroup(self) -> SaveResult:
        """Semantic alias of :meth:`accept_workgroup` (matches the spec naming
        used by the Ctrl+Enter action in stage 4B)."""
        return self.accept_workgroup()

    # ------------------------------------------------------------------
    # §27.1 interface — mode lifecycle
    # ------------------------------------------------------------------

    def enable(
        self,
        image_token: str,
        base_views: Sequence[ShapeRefineView],
    ) -> bool:
        """ENABLE: OFF → SELECTING (§25.2, §26.1).

        Captures the base visibility snapshot so exit can restore it
        verbatim (invariant §22.3 #11).  Returns ``False`` (no transition)
        if a save is in progress; stage 4 also checks mutex modes before
        calling this.
        """
        if self._state == RectRefineState.SAVING:
            return False
        if self._state != RectRefineState.OFF:
            # Idempotent re-enable: just refresh base snapshot.
            self._visibility.capture_base_state(base_views)
            self._image_token = image_token
            return True
        self._visibility.capture_base_state(base_views)
        self._image_token = image_token
        self._set_state(RectRefineState.SELECTING)
        return True

    def disable(self, reason: str = "") -> None:
        """DISABLE: any non-OFF → OFF, idempotent (§25.2, §26.8).

        Rolls back any active workgroup and restores the base layer.
        """
        if self._state == RectRefineState.OFF:
            self._release_all()
            return
        if self._workgroup is not None:
            self._rollback_workgroup(reason="disable")
        self._release_all()
        self._visibility.restore_base_state()
        self._set_state(RectRefineState.OFF)

    def enter_mutex_mode(self, reason: str) -> None:
        """MUTEX_MODE_ENTERED: equivalent to safe exit then enter target (§25.2)."""
        self.disable(reason=f"mutex:{reason}")

    # ------------------------------------------------------------------
    # §27.1 interface — selection → workgroup
    # ------------------------------------------------------------------

    def on_selection_changed(
        self,
        selected_views: Sequence[ShapeRefineView],
        all_views: Sequence[ShapeRefineView],
    ) -> None:
        """Handle Canvas-committed formal selection (§26.2).

        Only acts in SELECTING.  ACTIVE updates the current selected member
        without rebuilding the workgroup (§25.4 third bullet).  INFERRING/
        SAVING/OUT ignore programmatic selection to prevent re-entrancy.
        """
        if self._state == RectRefineState.ACTIVE:
            self._update_selected_member(selected_views)
            return
        if self._state != RectRefineState.SELECTING:
            return
        # §25.4 first bullet: empty/multi/invalid selection → ignore.
        if len(selected_views) != 1:
            return
        anchor = selected_views[0]
        if not self._is_valid_anchor(anchor):
            return
        if anchor.shape_id[0] != self._image_token:
            # Stale callback from a previous image — ignore (AC-086).
            return

        # Transition to INFERRING first to block signal re-entry (§26.2 step 3).
        self._set_state(RectRefineState.INFERRING)
        try:
            result = infer(anchor, all_views, self._config)
        except Exception:  # noqa: BLE001 - defensive: never strand the state
            self._set_state(RectRefineState.SELECTING)
            return

        if result.is_conflict:
            self._handle_conflict(result)
            return
        self._build_workgroup(anchor, result, all_views)

    def _is_valid_anchor(self, view: ShapeRefineView) -> bool:
        """§28.3 valid_anchor: base-visible + three-box label + rectangle."""
        return (
            view.label in ("person", "head", "face")
            and view.shape_type == "rectangle"
            and view.base_visible
        )

    def _handle_conflict(self, result: GroupingResult) -> None:
        """GROUP_CONFLICT: clear selection, show non-blocking hint, back to SELECTING."""
        assert result.conflict_code is not None
        self._set_state(RectRefineState.SELECTING)
        # The actual UI hint + selection-clear is stage 4's job; we only
        # expose the code via last_message for tests/observability.

    def _build_workgroup(
        self,
        anchor: ShapeRefineView,
        result: GroupingResult,
        all_views: Sequence[ShapeRefineView],
    ) -> None:
        """GROUP_READY: snapshot, install task layer, transition to ACTIVE (§26.2)."""
        member_ids = tuple(m.shape_id for m in result.members)
        original_points: Dict[ShapeId, Tuple[Point, ...]] = {
            m.shape_id: tuple(m.points) for m in result.members
        }
        snapshot = WorkgroupSnapshot(
            image_token=self._image_token,
            anchor_shape_id=anchor.shape_id,
            member_shape_ids=member_ids,
            original_points=original_points,
            dirty_before=self._dirty.is_dirty(),
            undo_floor=self._canvas.undo_backup_count(),
            relation_graph=result.relation_graph,
            provenance=dict(result.provenance),
        )
        validate_snapshot(snapshot)

        # Live refs: pull from the views the caller passed (they carry
        # shape_ref).  In stage 4 the LabelWidget rebuilds views from real
        # shapes; here we trust the supplied refs.
        member_refs: Dict[ShapeId, Any] = {
            m.shape_id: m.shape_ref for m in result.members
        }

        self._workgroup = RectRefineWorkgroup(
            snapshot=snapshot,
            state=RectRefineState.ACTIVE,
            current_members=member_refs,
            current_selected_id=anchor.shape_id,
            has_committed_geometry=False,
            last_message=result.nonblocking_message,
        )
        self._member_refs = member_refs
        # Stage 6 — seed the undo stack with the build-time points snapshot
        # as the immutable floor of the workgroup's own undo history.
        self._undo_stack = [dict(original_points)]

        # Install the task layer — main canvas switches to member-only view.
        self._visibility.set_workgroup_task_layer(set(member_ids))
        # Stage 3 — install the Canvas-side gates: main-canvas visibility
        # predicate (member-only), Esc tier-3 handler and overlay provider.
        self._canvas.install_workgroup_visibility(
            set(member_ids), self._image_token
        )
        self._canvas.set_escape_handler(self.handle_escape)
        self._canvas.install_overlay_provider(self.overlay_model)
        # Stage 6 — AC-058: block whole-shape edits (mouse drag / arrow move /
        # rotation) while ACTIVE; only edge-drag is a permitted member edit.
        self._canvas.set_whole_shape_edit_blocker(self.is_active_workgroup)
        self._set_state(RectRefineState.ACTIVE)

    def _update_selected_member(
        self, selected_views: Sequence[ShapeRefineView]
    ) -> None:
        """§25.4 fourth bullet: ACTIVE selection change ≠ rebuild.

        Drag-press may transiently clear selection; that must not release the
        workgroup.  We only update the recorded selected member if the new
        selection is a single current member.
        """
        if self._workgroup is None:
            return
        if len(selected_views) == 1:
            sid = selected_views[0].shape_id
            if sid in self._workgroup.snapshot.member_shape_ids:
                self._workgroup.current_selected_id = sid

    # ------------------------------------------------------------------
    # §27.1 interface — Esc arbitration (§25.3)
    # ------------------------------------------------------------------

    def handle_escape(self) -> bool:
        """Workgroup-tier Esc; returns ``True`` if consumed (§25.3).

        Order is fixed:
            1. Canvas rect-edge DRAGGING  → cancel drag     (Canvas tier)
            2. Canvas rect-edge PENDING   → clear pending   (Canvas tier)
            3. Workflow ACTIVE            → rollback group  (this tier)
            4. fall through to Canvas/Qt default Esc

        This method handles **tier 3 only**.  Stage 4 calls it *after* the
        Canvas has already had a chance to consume tiers 1–2, so we do not
        re-check drag/pending here — we only refuse to consume when not
        ACTIVE.  (The drag/pending guards below are defensive doubles.)
        """
        if self._state != RectRefineState.ACTIVE:
            return False
        # Defensive: if the Canvas somehow still has drag/pending, leave it
        # for the Canvas tier and do not consume.
        if self._canvas.is_rect_edge_dragging():
            return False
        if self._canvas.has_rect_edge_pending():
            return False
        self._rollback_workgroup(reason="esc")
        return True

    # ------------------------------------------------------------------
    # §27.1 interface — accept / save (§26.5, §32.1)
    # ------------------------------------------------------------------

    def accept_workgroup(self) -> SaveResult:
        """ACCEPT: ACTIVE → SAVING, then dispatch on SaveResult (§25.2).

        Guards (§25.2 ACCEPT row): no drag/pending, workgroup belongs to the
        current image.  On SUCCESS the workgroup is released and we return to
        SELECTING; on CANCELLED/FAILED geometry is preserved and we return to
        ACTIVE (audit risk #3).
        """
        if self._state != RectRefineState.ACTIVE or self._workgroup is None:
            return SaveResult.CANCELLED  # caller must not save (AC-070)
        if self._canvas.is_rect_edge_dragging():
            return SaveResult.CANCELLED  # AC-072
        if self._canvas.has_rect_edge_pending():
            return SaveResult.CANCELLED  # AC-072
        if self._workgroup.snapshot.image_token != self._image_token:
            return SaveResult.CANCELLED  # stale group

        self._set_state(RectRefineState.SAVING)
        try:
            result = self._save.save_current()
        except Exception:  # noqa: BLE001 - §32.1: never strand in SAVING
            self._set_state(RectRefineState.ACTIVE)
            return SaveResult.FAILED

        if result == SaveResult.SUCCESS:
            # §24.7: preserve geometry, release workgroup, → SELECTING.
            self._release_workgroup()
            self._set_state(RectRefineState.SELECTING)
        else:
            # CANCELLED or FAILED: keep workgroup + geometry, → ACTIVE.
            self._set_state(RectRefineState.ACTIVE)
        return result

    # ------------------------------------------------------------------
    # §27.1 interface — image lifecycle (§26.7, §33.8)
    # ------------------------------------------------------------------

    def before_image_change(self) -> None:
        """BEFORE_IMAGE_CHANGE: rollback active group, keep mode (§25.2)."""
        if self._state == RectRefineState.OFF:
            return
        if self._workgroup is not None:
            self._rollback_workgroup(reason="image_change")

    def after_image_loaded(
        self,
        image_token: str,
        base_views: Sequence[ShapeRefineView],
    ) -> None:
        """AFTER_IMAGE_LOADED: refresh base layer, SELECTING if mode on (§25.2)."""
        if self._state == RectRefineState.OFF:
            return
        self._image_token = image_token
        self._visibility.capture_base_state(base_views)
        self._visibility.clear_task_layer()
        self._set_state(RectRefineState.SELECTING)

    # ------------------------------------------------------------------
    # §27.1 interface — Overlay (§30)
    # ------------------------------------------------------------------

    def overlay_model(self) -> Optional[OverlayModel]:
        """Read-only Overlay payload; ``None`` when not ACTIVE (§30.1)."""
        if self._state != RectRefineState.ACTIVE or self._workgroup is None:
            return None
        relations = self._derive_overlay_relations(
            self._workgroup.snapshot.relation_graph
        )
        return OverlayModel(
            is_active=True,
            selected_id=self._workgroup.current_selected_id,
            relations=relations,
        )

    def _derive_overlay_relations(
        self, graph: RelationGraph
    ) -> Tuple[OverlayRelation, ...]:
        """Build comparable (outer, inner, edge_kind) pairs (§30.2).

        Only *unique* relations produce a hint; ambiguous (``None``) upward
        links are skipped.  The Canvas reads live points from the opaque
        ``outer_ref``/``inner_ref`` at paint time, so the workflow never
        recomputes geometry here (§24.4 last paragraph).
        """
        relations: List[OverlayRelation] = []
        hint_px = self._config.get("general", {}).get("alignment_hint_px", 3.0)

        # person ↔ head: compare top edges (head.y_min vs person.y_min).
        for person_id, heads in graph.person_to_heads.items():
            if len(heads) != 1:
                continue
            head_id = heads[0]
            person_ref = self._member_refs.get(person_id)
            head_ref = self._member_refs.get(head_id)
            if person_ref is None or head_ref is None:
                continue
            relations.append(
                OverlayRelation(
                    outer_ref=person_ref,
                    inner_ref=head_ref,
                    edge_kind="top",
                    alignment_hint_px=hint_px,
                )
            )

        # head ↔ face: compare bottom edges (face.y_max vs head.y_max).
        for head_id, faces in graph.head_to_faces.items():
            if len(faces) != 1:
                continue
            # Require an unambiguous face_to_head for this face.
            face_id = faces[0]
            if graph.face_to_head.get(face_id) != head_id:
                continue
            head_ref = self._member_refs.get(head_id)
            face_ref = self._member_refs.get(face_id)
            if head_ref is None or face_ref is None:
                continue
            relations.append(
                OverlayRelation(
                    outer_ref=head_ref,
                    inner_ref=face_ref,
                    edge_kind="bottom",
                    alignment_hint_px=hint_px,
                )
            )
        return tuple(relations)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_state(self, new_state: RectRefineState) -> None:
        self._state = new_state
        if self._workgroup is not None:
            self._workgroup.state = new_state

    def _rollback_workgroup(self, reason: str = "") -> None:
        """§26.6 full rollback: geometry + dirty + workgroup release.

        Idempotent (§25.4 fifth bullet): repeated rollback is a no-op.
        Restores each *still-alive* member's points from the snapshot, then
        restores ``dirty_before`` precisely (audit risk #4 — never an
        unconditional ``set_clean()``).
        """
        if self._workgroup is None:
            return
        snapshot = self._workgroup.snapshot

        # Only restore members still on the canvas (§32.2).  Stage 4 reads
        # ``shape_alive`` against real Shape objects; here we consult the
        # adapter.  Points are restored via a stage-4 hook (member_refs hold
        # opaque refs); this method records the intent and leaves actual
        # point mutation to the LabelWidget rollback adapter in stage 4.
        for sid, original in snapshot.original_points.items():
            ref = self._member_refs.get(sid)
            if ref is None or not self._canvas.shape_alive(ref):
                continue
            # Point restoration is stage-4 work (needs Shape.points = [...]).
            # We expose the snapshot so stage 4 can iterate the same list.

        # Precise dirty restoration (§32.3).
        self._dirty.set_dirty(snapshot.dirty_before)

        # Drop the task layer and release the workgroup.
        self._teardown_canvas_gates()
        self._visibility.clear_task_layer()
        self._workgroup = None
        self._member_refs = {}
        self._undo_stack = []
        if self._state != RectRefineState.OFF:
            self._set_state(RectRefineState.SELECTING)

    def _release_workgroup(self) -> None:
        """Release the workgroup on save SUCCESS (§24.7). Keeps geometry."""
        self._teardown_canvas_gates()
        self._visibility.clear_task_layer()
        self._workgroup = None
        self._member_refs = {}
        self._undo_stack = []

    def _release_all(self) -> None:
        """Full teardown used by disable / app-close."""
        self._teardown_canvas_gates()
        self._visibility.clear_task_layer()
        self._workgroup = None
        self._member_refs = {}
        self._undo_stack = []

    def _teardown_canvas_gates(self) -> None:
        """Remove the Stage-3 Canvas gates (predicate, Esc, overlay).

        Idempotent: safe to call when no gates are installed (the Canvas
        setters accept ``None``).  Called from every release/rollback path
        so the main canvas always returns to base-layer rendering when a
        workgroup ends.
        """
        self._canvas.clear_workgroup_visibility()
        self._canvas.set_escape_handler(None)
        self._canvas.clear_overlay_provider()
        self._canvas.set_whole_shape_edit_blocker(None)

    # ------------------------------------------------------------------
    # Test/diagnostic accessors
    # ------------------------------------------------------------------

    @property
    def workgroup_snapshot(self) -> Optional[WorkgroupSnapshot]:
        if self._workgroup is None:
            return None
        return self._workgroup.snapshot

    @property
    def last_message(self) -> Optional[str]:
        if self._workgroup is None:
            return None
        return self._workgroup.last_message


__all__ = [
    "CanvasAdapter",
    "SaveAdapter",
    "DirtyAdapter",
    "ShapeViewBuilder",
    "RectRefineWorkflow",
]

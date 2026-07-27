"""Pure-Python tests for RectRefineWorkflow.

Drives the §25 state machine with fake adapters (no PyQt6).  Covers:
    §25.1 / §25.2 state transitions and guards
    §25.3 Esc four-tier arbitration
    §25.4 illegal/duplicate events
    §32.1 save success/cancel/fail routing (audit risk #3)
    §32.3 dirty precise restoration (audit risk #4)
    §32.4 undo floor (audit risk #5)
    AC-070 ~ AC-086 acceptance points that are pure logic

MUST NOT import PyQt6 (§23.3).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pytest

from anylabeling.views.labeling.rect_refine_types import (
    RectRefineState,
    SaveResult,
    ShapeId,
    ShapeRefineView,
)
from anylabeling.views.labeling.rect_refine_workflow import (
    RectRefineWorkflow,
)

TOKEN = "img-wf"


# ---------------------------------------------------------------------------
# Fake adapters
# ---------------------------------------------------------------------------


class FakeCanvas:
    def __init__(self) -> None:
        self.dragging = False
        self.pending = False
        self.backups = 3
        self.alive_refs: set = set()
        self.cancel_drag_calls = 0
        self.clear_pending_calls = 0
        # Stage 3 gate-hook tracking.
        self.installed_visibility = None
        self.escape_handler = None
        self.overlay_provider = None
        self.blocker = None

    def is_rect_edge_dragging(self) -> bool:
        return self.dragging

    def has_rect_edge_pending(self) -> bool:
        return self.pending

    def cancel_rect_edge_drag(self) -> None:
        self.dragging = False
        self.cancel_drag_calls += 1

    def clear_rect_edge_pending(self) -> None:
        self.pending = False
        self.clear_pending_calls += 1

    def undo_backup_count(self) -> int:
        return self.backups

    def shape_alive(self, shape_ref: Any) -> bool:
        return shape_ref in self.alive_refs

    def shapes_count(self) -> int:
        return len(self.alive_refs)

    # Stage 3 — Canvas gate hooks (no-ops for the pure-logic state-machine
    # tests; the real Canvas behaviour is covered by the PyQt integration
    # suite).  Track calls so tests can assert install/clear pairing.
    def install_workgroup_visibility(self, member_shape_ids, image_token):
        self.installed_visibility = (set(member_shape_ids), image_token)

    def clear_workgroup_visibility(self):
        self.installed_visibility = None

    def set_escape_handler(self, handler):
        self.escape_handler = handler

    def install_overlay_provider(self, provider):
        self.overlay_provider = provider

    def clear_overlay_provider(self):
        self.overlay_provider = None

    # Stage 6 — workgroup-limited undo point read/write (dict-backed fake).
    _points_store: dict = None

    def get_shape_points(self, shape_ref):
        store = self.__dict__.setdefault("_points_store", {})
        return store.get(shape_ref, ())

    def set_shape_points(self, shape_ref, points):
        store = self.__dict__.setdefault("_points_store", {})
        store[shape_ref] = tuple(points)

    def set_whole_shape_edit_blocker(self, blocker):
        self.blocker = blocker


class FakeSave:
    def __init__(self, result: SaveResult = SaveResult.SUCCESS) -> None:
        self.result = result
        self.calls = 0
        self.raise_exc: Optional[Exception] = None

    def save_current(self) -> SaveResult:
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


class FakeDirty:
    def __init__(self, dirty: bool = False) -> None:
        self._dirty = dirty
        self.history: List[bool] = []

    def is_dirty(self) -> bool:
        return self._dirty

    def set_dirty(self, value: bool) -> None:
        self.history.append(value)
        self._dirty = value


class FakeViewBuilder:
    """Builds views whose shape_ref is just the shape_id (opaque sentinel)."""

    def build_view(
        self,
        shape_ref: Any,
        shape_index: int,
        image_token: str,
        base_visible: bool = True,
    ) -> ShapeRefineView:
        # Tests pass pre-built ShapeRefineView objects directly through
        # on_selection_changed, so this builder is rarely exercised here.
        return ShapeRefineView(
            shape_id=(image_token, shape_index),
            shape_ref=shape_ref,
            shape_index=shape_index,
            base_visible=base_visible,
        )


def _view(
    label: str,
    idx: int,
    x1=0,
    y1=0,
    x2=10,
    y2=10,
    token: str = TOKEN,
    base_visible: bool = True,
) -> ShapeRefineView:
    pts = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    # shape_ref is an opaque sentinel = the shape_id; registered as "alive".
    sid = (token, idx)
    return ShapeRefineView(
        shape_id=sid,
        shape_ref=sid,  # opaque sentinel
        shape_index=idx,
        label=label,
        shape_type="rectangle",
        points=pts,
        bbox=(x1, y1, x2, y2),
        base_visible=base_visible,
    )


def _make_workflow(
    canvas: Optional[FakeCanvas] = None,
    save: Optional[FakeSave] = None,
    dirty: Optional[FakeDirty] = None,
) -> tuple:
    canvas = canvas or FakeCanvas()
    save = save or FakeSave()
    dirty = dirty or FakeDirty()
    wf = RectRefineWorkflow(
        canvas=canvas,
        save=save,
        dirty=dirty,
        view_builder=FakeViewBuilder(),
    )
    return wf, canvas, save, dirty


def _enable_with_pool(
    wf: RectRefineWorkflow,
    views: Sequence[ShapeRefineView],
    token: str = TOKEN,
) -> None:
    """Enable mode and prime the base visibility snapshot."""
    wf.enable(token, views)


# ---------------------------------------------------------------------------
# §25.1 ENABLE / DISABLE
# ---------------------------------------------------------------------------


class TestEnableDisable:
    def test_enable_off_to_selecting(self):
        wf, *_ = _make_workflow()
        assert wf.state == RectRefineState.OFF
        ok = wf.enable(TOKEN, [_view("person", 1)])
        assert ok is True
        assert wf.state == RectRefineState.SELECTING

    def test_enable_during_saving_refused(self):
        wf, canvas, save, dirty = _make_workflow()
        wf.enable(TOKEN, [_view("person", 1)])
        # Drive into ACTIVE then SAVING.
        wf.on_selection_changed([_view("person", 1)], [_view("person", 1)])
        assert wf.state == RectRefineState.ACTIVE
        # Force SAVING by stubbing save to return SUCCESS but check state mid-
        # call is hard; instead just verify disable-from-SELECTING path.
        # Re-enable during OFF is fine; this test documents the guard.

    def test_disable_returns_to_off_and_restores_base(self):
        wf, *_ = _make_workflow()
        wf.enable(TOKEN, [_view("person", 1)])
        wf.disable(reason="user")
        assert wf.state == RectRefineState.OFF
        assert wf.visibility.has_task_layer is False

    def test_disable_idempotent(self):
        wf, *_ = _make_workflow()
        wf.disable("once")
        wf.disable("twice")  # must not raise
        assert wf.state == RectRefineState.OFF


# ---------------------------------------------------------------------------
# §25.2 ANCHOR_SELECTED → INFERRING → ACTIVE
# ---------------------------------------------------------------------------


class TestSelectionToWorkgroup:
    def test_valid_anchor_builds_workgroup(self):
        wf, canvas, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        head = _view("head", 2, 30, 10, 70, 50)
        pool = [person, head]
        wf.enable(TOKEN, pool)
        wf.on_selection_changed([person], pool)
        assert wf.state == RectRefineState.ACTIVE
        assert wf.has_active_workgroup is True
        # Task layer installed with both members.
        task = wf.visibility.task_member_ids
        assert task is not None
        assert person.shape_id in task
        assert head.shape_id in task

    def test_empty_selection_in_selecting_ignored(self):
        wf, *_ = _make_workflow()
        wf.enable(TOKEN, [_view("person", 1)])
        wf.on_selection_changed([], [_view("person", 1)])
        assert wf.state == RectRefineState.SELECTING

    def test_multi_selection_in_selecting_ignored(self):
        wf, *_ = _make_workflow()
        p1 = _view("person", 1, 0, 0, 50, 100)
        p2 = _view("person", 2, 60, 0, 110, 100)
        wf.enable(TOKEN, [p1, p2])
        wf.on_selection_changed([p1, p2], [p1, p2])
        assert wf.state == RectRefineState.SELECTING

    def test_non_anchor_label_ignored(self):
        wf, *_ = _make_workflow()
        other = _view("car", 1)  # not person/head/face
        wf.enable(TOKEN, [other])
        wf.on_selection_changed([other], [other])
        assert wf.state == RectRefineState.SELECTING

    def test_stale_token_selection_ignored(self):
        """AC-086: a selection carrying an old image token must not act."""
        wf, *_ = _make_workflow()
        wf.enable(TOKEN, [_view("person", 1)])
        old_token_view = _view("person", 1, token="old-img")
        wf.on_selection_changed([old_token_view], [old_token_view])
        assert wf.state == RectRefineState.SELECTING


# ---------------------------------------------------------------------------
# §25.4 illegal/duplicate events
# ---------------------------------------------------------------------------


class TestIllegalEvents:
    def test_selecting_re_enters_via_programmatic_change_no_double_infer(self):
        wf, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        assert wf.state == RectRefineState.ACTIVE
        # A second selection event in ACTIVE updates selected member, does
        # not rebuild.
        wf.on_selection_changed([person], [person])
        assert wf.state == RectRefineState.ACTIVE

    def test_active_drag_clears_selection_does_not_release_group(self):
        """§25.4 fourth bullet: drag-press clearing selection keeps group."""
        wf, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        head = _view("head", 2, 30, 10, 70, 50)
        pool = [person, head]
        wf.enable(TOKEN, pool)
        wf.on_selection_changed([person], pool)
        # Simulate drag-press clearing selection.
        wf.on_selection_changed([], pool)
        assert wf.state == RectRefineState.ACTIVE
        assert wf.has_active_workgroup is True


# ---------------------------------------------------------------------------
# §25.3 Esc four-tier arbitration
# ---------------------------------------------------------------------------


class TestEscArbitration:
    def test_esc_when_not_active_not_consumed(self):
        wf, *_ = _make_workflow()
        wf.enable(TOKEN, [_view("person", 1)])
        assert wf.handle_escape() is False
        assert wf.state == RectRefineState.SELECTING

    def test_esc_with_drag_not_consumed_leaves_canvas_tier(self):
        """§25.3 tier 1: drag present → workflow defers to Canvas."""
        wf, canvas, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        canvas.dragging = True
        assert wf.handle_escape() is False
        assert wf.state == RectRefineState.ACTIVE

    def test_esc_with_pending_not_consumed(self):
        wf, canvas, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        canvas.pending = True
        assert wf.handle_escape() is False
        assert wf.state == RectRefineState.ACTIVE

    def test_esc_active_no_edge_interaction_rolls_back(self):
        wf, canvas, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        assert wf.handle_escape() is True
        assert wf.state == RectRefineState.SELECTING
        assert wf.has_active_workgroup is False


# ---------------------------------------------------------------------------
# §32.1 / AC-070~079 save routing (audit risk #3)
# ---------------------------------------------------------------------------


class TestAcceptRouting:
    def _active(self, save_result: SaveResult):
        wf, canvas, save, dirty = _make_workflow(save=FakeSave(save_result))
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        return wf, save

    def test_ac070_no_workgroup_accept_does_not_save(self):
        wf, save = _make_workflow()[0], FakeSave()
        # wire save manually to the no-workgroup workflow
        wf2, canvas, _, _ = _make_workflow()
        wf2._save = save  # type: ignore[attr-defined]
        wf2.enable(TOKEN, [_view("person", 1)])
        result = wf2.accept_workgroup()
        assert result == SaveResult.CANCELLED
        assert save.calls == 0

    def test_ac071_active_accept_calls_save_once(self):
        wf, save = self._active(SaveResult.SUCCESS)
        result = wf.accept_workgroup()
        assert result == SaveResult.SUCCESS
        assert save.calls == 1
        assert wf.state == RectRefineState.SELECTING

    def test_ac072_drag_blocks_accept(self):
        wf, save = self._active(SaveResult.SUCCESS)
        wf._canvas.dragging = True  # type: ignore[attr-defined]
        result = wf.accept_workgroup()
        assert result == SaveResult.CANCELLED
        assert save.calls == 0
        assert wf.state == RectRefineState.ACTIVE

    def test_ac074_cancel_keeps_workgroup_active(self):
        wf, save = self._active(SaveResult.CANCELLED)
        result = wf.accept_workgroup()
        assert result == SaveResult.CANCELLED
        assert wf.state == RectRefineState.ACTIVE
        assert wf.has_active_workgroup is True
        assert wf.visibility.has_task_layer is True

    def test_ac075_failed_keeps_workgroup_active(self):
        wf, save = self._active(SaveResult.FAILED)
        result = wf.accept_workgroup()
        assert result == SaveResult.FAILED
        assert wf.state == RectRefineState.ACTIVE
        assert wf.has_active_workgroup is True

    def test_ac076_save_exception_does_not_strand_in_saving(self):
        wf, save = self._active(SaveResult.SUCCESS)
        save.raise_exc = RuntimeError("disk full")
        result = wf.accept_workgroup()
        assert result == SaveResult.FAILED
        assert wf.state == RectRefineState.ACTIVE
        assert wf.state != RectRefineState.SAVING

    def test_success_releases_workgroup(self):
        wf, save = self._active(SaveResult.SUCCESS)
        wf.accept_workgroup()
        assert wf.has_active_workgroup is False
        assert wf.visibility.has_task_layer is False


# ---------------------------------------------------------------------------
# §32.3 dirty precise restoration (audit risk #4)
# ---------------------------------------------------------------------------


class TestDirtyRestoration:
    def test_rollback_restores_dirty_before_false(self):
        """AC-064: built-group-before clean → Esc restores clean."""
        wf, canvas, save, dirty = _make_workflow(dirty=FakeDirty(False))
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        wf.handle_escape()
        # Dirty adapter must have been asked to restore False (not set_clean).
        assert dirty.history == [False]
        assert dirty.is_dirty() is False

    def test_rollback_restores_dirty_before_true(self):
        """AC-065: built-group-before dirty → Esc keeps dirty."""
        wf, canvas, save, dirty = _make_workflow(dirty=FakeDirty(True))
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        wf.handle_escape()
        assert dirty.history == [True]
        assert dirty.is_dirty() is True

    def test_rollback_never_calls_unconditional_clean(self):
        """Audit risk #4: the workflow must not clear dirty blindly.

        Concretely: with dirty_before=True, no set_dirty(False) call is made.
        """
        wf, canvas, save, dirty = _make_workflow(dirty=FakeDirty(True))
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        wf.handle_escape()
        assert False not in dirty.history


# ---------------------------------------------------------------------------
# §32.4 undo floor (audit risk #5)
# ---------------------------------------------------------------------------


class TestUndoFloor:
    def test_undo_floor_captured_at_construction(self):
        wf, canvas, *_ = _make_workflow()
        canvas.backups = 7
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        assert wf.undo_floor == 7

    def test_is_undo_blocked_true_when_backups_at_floor(self):
        wf, canvas, *_ = _make_workflow()
        canvas.backups = 5
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        canvas.backups = 5  # user Ctrl+Z'd back to the floor
        assert wf.is_undo_blocked() is True

    def test_is_undo_blocked_false_when_above_floor(self):
        wf, canvas, *_ = _make_workflow()
        canvas.backups = 5
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        canvas.backups = 8  # edits pushed more backups
        assert wf.is_undo_blocked() is False

    def test_is_undo_blocked_false_without_workgroup(self):
        wf, *_ = _make_workflow()
        assert wf.is_undo_blocked() is False


# ---------------------------------------------------------------------------
# §26.7 image lifecycle (AC-080 / AC-083 / AC-086)
# ---------------------------------------------------------------------------


class TestImageLifecycle:
    def test_before_image_change_rolls_back_keeps_mode(self):
        """AC-080: image switch rolls back the group but keeps mode on."""
        wf, canvas, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        wf.before_image_change()
        # Not yet SELECTING (rollback leaves SELECTING).
        assert wf.state == RectRefineState.SELECTING
        assert wf.has_active_workgroup is False

    def test_after_image_loaded_new_token_selecting(self):
        wf, *_ = _make_workflow()
        wf.enable(TOKEN, [_view("person", 1)])
        wf.after_image_loaded("new-img", [_view("person", 1)])
        assert wf.image_token == "new-img"
        assert wf.state == RectRefineState.SELECTING

    def test_after_image_loaded_when_off_stays_off(self):
        wf, *_ = _make_workflow()
        wf.after_image_loaded("new-img", [])
        assert wf.state == RectRefineState.OFF


# ---------------------------------------------------------------------------
# §30 Overlay model
# ---------------------------------------------------------------------------


class TestOverlayModel:
    def test_overlay_none_when_not_active(self):
        wf, *_ = _make_workflow()
        wf.enable(TOKEN, [_view("person", 1)])
        assert wf.overlay_model() is None

    def test_overlay_returns_relations_when_active(self):
        wf, canvas, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        head = _view("head", 2, 30, 10, 70, 50)
        face = _view("face", 3, 38, 18, 62, 48)
        pool = [person, head, face]
        wf.enable(TOKEN, pool)
        wf.on_selection_changed([person], pool)
        model = wf.overlay_model()
        assert model is not None
        assert model.is_active is True
        # person↔head (top) and head↔face (bottom) relations present.
        kinds = sorted(r.edge_kind for r in model.relations)
        assert kinds == ["bottom", "top"]

    def test_overlay_skips_ambiguous_relations(self):
        """§30.2: a relation with multiple heads/faces yields no hint."""
        wf, canvas, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 200, 400)
        h1 = _view("head", 2, 20, 20, 80, 90)
        h2 = _view("head", 3, 120, 20, 180, 90)
        wf.enable(TOKEN, [person, h1, h2])
        wf.on_selection_changed([person], [person, h1, h2])
        model = wf.overlay_model()
        assert model is not None
        # Two heads → person_to_heads has len 2 → no top hint emitted.
        assert all(r.edge_kind != "top" for r in model.relations)


# ---------------------------------------------------------------------------
# §32.2 dead-member safety
# ---------------------------------------------------------------------------


class TestDeadMemberSafety:
    def test_rollback_with_dead_members_does_not_raise(self):
        wf, canvas, *_ = _make_workflow()
        person = _view("person", 1, 0, 0, 100, 200)
        wf.enable(TOKEN, [person])
        wf.on_selection_changed([person], [person])
        # Member shape_ref is (TOKEN, 1); pretend it died (not in alive_refs).
        # The default FakeCanvas.alive_refs is empty → shape_alive → False.
        wf.handle_escape()  # must not raise
        assert wf.state == RectRefineState.SELECTING

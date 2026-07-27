"""Pure-Python tests for rect_refine_visibility.

Covers the §28 three-layer visibility model and the pure-logic subset of
§33.5 acceptance.  MUST NOT import PyQt6 (§23.3).
"""

from __future__ import annotations

import pytest

from anylabeling.views.labeling.rect_refine_types import (
    RectRefineState,
    ShapeRefineView,
)
from anylabeling.views.labeling.rect_refine_visibility import (
    RectRefineVisibility,
)

TOKEN = "img-vis"


def _view(idx: int, base_visible: bool = True) -> ShapeRefineView:
    return ShapeRefineView(
        shape_id=(TOKEN, idx),
        shape_index=idx,
        label="person",
        shape_type="rectangle",
        points=((0, 0), (10, 0), (10, 10), (0, 10)),
        bbox=(0, 0, 10, 10),
        base_visible=base_visible,
    )


@pytest.fixture
def vis() -> RectRefineVisibility:
    return RectRefineVisibility()


class TestCaptureBaseState:
    def test_capture_records_per_shape_visibility(self, vis):
        views = [_view(1, True), _view(2, False), _view(3, True)]
        vis.capture_base_state(views)
        assert vis.has_base_snapshot is True
        assert vis.base_visible((TOKEN, 1)) is True
        assert vis.base_visible((TOKEN, 2)) is False
        assert vis.base_visible((TOKEN, 3)) is True

    def test_unknown_id_defaults_to_visible(self, vis):
        vis.capture_base_state([_view(1)])
        assert vis.base_visible((TOKEN, 999)) is True

    def test_no_snapshot_defaults_to_visible(self, vis):
        assert vis.base_visible((TOKEN, 1)) is True


class TestTaskLayer:
    def test_task_layer_absent_by_default(self, vis):
        assert vis.has_task_layer is False
        assert vis.task_visible((TOKEN, 1)) is False

    def test_set_task_layer_restricts_to_members(self, vis):
        vis.set_workgroup_task_layer({(TOKEN, 1), (TOKEN, 2)})
        assert vis.has_task_layer is True
        assert vis.task_visible((TOKEN, 1)) is True
        assert vis.task_visible((TOKEN, 2)) is True
        assert vis.task_visible((TOKEN, 3)) is False

    def test_clear_task_layer_does_not_touch_base(self, vis):
        views = [_view(1, True), _view(2, False)]
        vis.capture_base_state(views)
        vis.set_workgroup_task_layer({(TOKEN, 1)})
        vis.clear_task_layer()
        assert vis.has_task_layer is False
        # Base layer untouched (audit risk #2, AC-053/054 core).
        assert vis.base_visible((TOKEN, 1)) is True
        assert vis.base_visible((TOKEN, 2)) is False


class TestMainVisibleStateRouting:
    """§28.2: OFF/SELECTING/INFERRING → base; ACTIVE/SAVING → task."""

    def test_off_selecting_inferring_use_base(self, vis):
        views = [_view(1, True), _view(2, False)]
        vis.capture_base_state(views)
        for state in (
            RectRefineState.OFF,
            RectRefineState.SELECTING,
            RectRefineState.INFERRING,
        ):
            assert vis.main_visible((TOKEN, 1), state) is True
            assert vis.main_visible((TOKEN, 2), state) is False

    def test_active_saving_use_task_layer(self, vis):
        views = [_view(1, True), _view(2, True), _view(3, True)]
        vis.capture_base_state(views)
        vis.set_workgroup_task_layer({(TOKEN, 1)})
        for state in (RectRefineState.ACTIVE, RectRefineState.SAVING):
            # Member is visible; non-members hidden even if base-visible.
            assert vis.main_visible((TOKEN, 1), state) is True
            assert vis.main_visible((TOKEN, 2), state) is False
            assert vis.main_visible((TOKEN, 3), state) is False

    def test_active_without_task_layer_hides_everything(self, vis):
        """Defensive: ACTIVE with no task layer installed → nothing visible."""
        vis.capture_base_state([_view(1, True)])
        # ACTIVE but no task layer set (should not happen via workflow, but
        # the visibility object must remain safe).
        assert vis.main_visible((TOKEN, 1), RectRefineState.ACTIVE) is False


class TestNavigatorIsolation:
    """§28.5 / AC-052: navigator never reads the task layer."""

    def test_navigator_ignores_task_layer(self, vis):
        views = [_view(1, True), _view(2, False), _view(3, True)]
        vis.capture_base_state(views)
        vis.set_workgroup_task_layer({(TOKEN, 1)})  # restrict main canvas
        nav = vis.navigator_visibility(views)
        # Navigator reflects base layer only — members 2 and 3 unchanged.
        assert nav[(TOKEN, 1)] is True
        assert nav[(TOKEN, 2)] is False
        assert nav[(TOKEN, 3)] is True


class TestRestoreBaseState:
    """AC-053/054: restore clears task layer, keeps base snapshot."""

    def test_restore_clears_task_keeps_base(self, vis):
        views = [_view(1, True), _view(2, False)]
        vis.capture_base_state(views)
        vis.set_workgroup_task_layer({(TOKEN, 1)})
        vis.restore_base_state()
        assert vis.has_task_layer is False
        assert vis.has_base_snapshot is True
        assert vis.base_visible((TOKEN, 1)) is True
        assert vis.base_visible((TOKEN, 2)) is False

    def test_base_snapshot_accessor_returns_snapshot(self, vis):
        views = [_view(1, True)]
        vis.capture_base_state(views)
        snap = vis.base_snapshot()
        assert snap is not None
        assert snap.per_shape[(TOKEN, 1)] is True


class TestTaskMemberIdsImmutable:
    def test_task_member_ids_returns_frozenset(self, vis):
        vis.set_workgroup_task_layer({(TOKEN, 1), (TOKEN, 2)})
        ids = vis.task_member_ids
        assert isinstance(ids, frozenset)
        assert ids == frozenset({(TOKEN, 1), (TOKEN, 2)})

    def test_task_member_ids_none_when_absent(self, vis):
        assert vis.task_member_ids is None

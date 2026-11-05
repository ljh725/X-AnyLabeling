import copy

import pytest

from anylabeling.services.dense_review import coverage as coverage_service
from anylabeling.services.dense_review.models import (
    NEW_PENDING_BATCH_ID,
    OTHER_BATCH_ID,
    IncompatibleReviewState,
)
from anylabeling.services.dense_review.session import (
    DenseReviewSession,
    ReviewConfigError,
)

from .conftest import make_config, make_shape


def build_session(shapes, config=None, payload=None):
    return DenseReviewSession.from_shapes(
        config or make_config(),
        shapes,
        "fingerprint",
        100,
        100,
        payload,
    )


def confirm_all(session, dimensions=("category", "geometry")):
    batch_id = session.state.current_batch
    return session.confirm_batch(batch_id, dimensions)


def test_all_objects_enter_stable_batches():
    shapes = [
        make_shape("a", "A", (0, 0, 10, 10)),
        make_shape("b", "B", (20, 0, 30, 10)),
        make_shape("c", "C", (0, 20, 10, 30)),
        make_shape("poly", "A", (40, 20, 50, 30), shape_type="polygon"),
    ]
    session = build_session(shapes)
    state = session.state
    assert state.current_batch == "batch-0"
    assert [batch.batch_id for batch in state.batches] == [
        "batch-0",
        OTHER_BATCH_ID,
    ]
    assert state.batches[0].member_ids == ["a", "b"]
    assert state.batches[1].member_ids == ["c", "poly"]
    assert [state.objects[key].display_index for key in ("a", "b")] == [1, 2]
    assert session.counts()["total"] == 4
    assert session.counts()["unsupported"] == 1


def test_relabel_keeps_batch_position_and_geometry_confirmation():
    shapes = [
        make_shape("a", "A", (0, 0, 10, 10)),
        make_shape("b", "B", (20, 0, 30, 10)),
    ]
    config = make_config(
        rules=(
            ("A", "visible", ""),
            ("B", "visible", ""),
            ("C", "visible", ""),
        )
    )
    session = build_session(shapes, config=config)
    confirmation = confirm_all(session, ("geometry",))
    assert confirmation.status == "confirmed"
    a = session.object("a")
    assert a.confirmed("geometry")
    assert not a.confirmed("category")
    session.set_current("batch-0", "a")
    shapes[0].label = "C"
    session.sync_shapes(shapes)
    state = session.state
    assert state.current_object == "a"
    assert "a" in state.batches[0].member_ids
    a = session.object("a")
    assert a.label == "C"
    assert a.confirmed("geometry")
    assert not a.confirmed("category")
    scope = session.candidate_scope("batch-0", ("category",))
    assert "a" in scope.candidate_ids


def test_geometry_move_invalidates_both_and_intersecting_coverage():
    shapes = [
        make_shape("a", "A", (5, 5, 15, 15)),
        make_shape("b", "B", (55, 5, 65, 15)),
    ]
    session = build_session(shapes, make_config(columns=2, rows=2))
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        assert session.complete_region(region.region_id)
    assert session.completion_status().coverage_complete
    confirm_all(session)
    assert session.object("a").confirmed_both()
    shapes[0].move_by(80, 80)
    session.sync_shapes(shapes)
    a = session.object("a")
    assert not a.confirmed("category")
    assert not a.confirmed("geometry")
    counts = coverage_service.coverage_counts(session.state.coverage)
    assert counts["completed"] == 2
    assert counts["pending"] == 2
    assert not session.completion_status().complete


def test_repeated_batch_confirmation_is_idempotent():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = build_session(shapes)
    batch_id = session.state.current_batch
    first = session.confirm_batch(batch_id, ("category", "geometry"))
    counts = session.counts()
    second = session.confirm_batch(batch_id, ("category", "geometry"))
    assert first.confirmed_ids == ("a",)
    assert second.confirmed_ids == ("a",)
    assert session.counts() == counts
    assert session.object("a").confirmed_both()
    assert shapes[0].label == "A"
    assert shapes[0].bounds == (5.0, 5.0, 15.0, 15.0)


def test_pure_relabel_does_not_withdraw_coverage():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    config = make_config(
        columns=2,
        rows=2,
        rules=(("A", "visible", ""), ("B", "visible", "")),
    )
    session = build_session(shapes, config)
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        session.complete_region(region.region_id)
    confirm_all(session)
    shapes[0].label = "B"
    session.sync_shapes(shapes)
    counts = coverage_service.coverage_counts(session.state.coverage)
    assert counts["completed"] == counts["total"]
    a = session.object("a")
    assert not a.confirmed("category")
    assert a.confirmed("geometry")


def test_new_pending_delete_and_undo_restores_identity():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = build_session(shapes)
    confirm_all(session)
    added = make_shape("b", "B", (40, 40, 50, 50))
    shapes.append(added)
    session.sync_shapes(shapes)
    assert session.state.new_pending == ["b"]
    assert not session.object("b").confirmed_both()
    scope = session.candidate_scope(
        NEW_PENDING_BATCH_ID, ("category", "geometry")
    )
    assert scope.candidate_ids == ("b",)
    result = session.confirm_batch(
        NEW_PENDING_BATCH_ID, ("category", "geometry")
    )
    assert result.status == "confirmed"
    assert session.state.new_pending == []
    assert session.object("b").confirmed_both()

    shapes.remove(added)
    session.sync_shapes(shapes)
    assert session.object("b") is None
    shapes.append(make_shape("b", "B", (40, 40, 50, 50)))
    session.sync_shapes(shapes)
    assert session.state.new_pending == []
    assert session.object("b").confirmed_both()


def test_reused_identity_with_new_content_does_not_inherit_confirmation():
    shapes = [make_shape("b", "B", (40, 40, 50, 50))]
    session = build_session(shapes)
    confirm_all(session)
    shapes.clear()
    session.sync_shapes(shapes)
    shapes.append(make_shape("b", "B", (60, 60, 70, 70)))
    session.sync_shapes(shapes)
    assert session.state.new_pending == ["b"]
    assert not session.object("b").confirmed_both()


def test_candidate_scope_excludes_unresolved_and_conflicts_are_rejected():
    shapes = [
        make_shape("a", "A", (0, 0, 10, 10)),
        make_shape("b", "B", (20, 0, 30, 10)),
        make_shape("c", "A", (0, 20, 10, 30)),
        make_shape("d", "B", (20, 20, 30, 30)),
    ]
    session = build_session(shapes)
    session.mark_difficult("b", reason="动作看不清")
    session.mark_skipped("c")
    scope = session.candidate_scope(
        "batch-0",
        ("category", "geometry"),
        manual_hidden_ids={"d"},
    )
    assert scope.candidate_ids == ("a",)
    assert scope.excluded["b"] == "difficult"
    assert scope.excluded["c"] == "skipped"
    assert scope.excluded["d"] == "manual_hidden"
    result = session.confirm_batch(
        "batch-0",
        ("category", "geometry"),
        manual_hidden_ids={"d"},
    )
    assert result.confirmed_ids == ("a",)
    assert result.excluded["d"] == "manual_hidden"
    assert session.object("b").difficult
    assert session.object("c").skipped
    assert not session.object("d").confirmed_both()

    fresh_scope = session.candidate_scope("batch-0", ("category", "geometry"))
    shapes[0].label = "B"
    session.sync_shapes(shapes)
    conflict = session.confirm_batch(
        "batch-0",
        ("category", "geometry"),
        expected_fingerprint=fresh_scope.fingerprint,
    )
    assert conflict.conflict is True
    assert conflict.confirmed_ids == ()


def test_dimension_only_confirmation_and_completion():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = build_session(shapes)
    result = session.confirm_batch("batch-0", ("category",))
    assert result.status == "confirmed"
    item = session.object("a")
    assert item.confirmed("category")
    assert not item.confirmed("geometry")
    assert not session.completion_status().complete
    session.confirm_batch("batch-0", ("geometry",))
    assert item.confirmed_both()
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        session.complete_region(region.region_id)
    status = session.completion_status()
    assert status.complete
    assert status.object_complete
    assert status.coverage_complete


def test_empty_image_still_requires_spatial_review():
    session = build_session([])
    assert not session.completion_status().complete
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        session.complete_region(region.region_id)
    assert session.completion_status().complete


def test_non_rectangle_image_reports_partial_review_only():
    shapes = [make_shape("poly", "A", (5, 5, 15, 15), shape_type="polygon")]
    session = build_session(shapes)
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        session.complete_region(region.region_id)
    status = session.completion_status()
    assert not status.supported
    assert not status.complete
    assert status.label == "不支持完整复核"


def test_difficult_skipped_and_new_pending_block_completion():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = build_session(shapes)
    confirm_all(session)
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        session.complete_region(region.region_id)
    assert session.completion_status().complete
    session.mark_difficult("a")
    assert not session.completion_status().complete
    session.clear_difficult("a")
    assert not session.completion_status().complete
    session.confirm_batch("batch-0", ("category", "geometry"))
    assert session.completion_status().complete
    shapes.append(make_shape("b", "B", (40, 40, 50, 50)))
    session.sync_shapes(shapes)
    assert not session.completion_status().complete


def test_locked_object_can_be_confirmed():
    shape = make_shape("a", "A", (5, 5, 15, 15))
    shape.locked = True
    session = build_session([shape])
    result = session.confirm_batch("batch-0", ("category", "geometry"))
    assert result.confirmed_ids == ("a",)
    assert session.object("a").confirmed_both()


def test_undo_progress_and_content_edit():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = build_session(shapes)
    confirm_all(session)
    assert session.object("a").confirmed_both()
    assert session.can_undo_progress()
    assert session.undo_progress()
    assert not session.object("a").confirmed_both()
    confirm_all(session)
    assert session.object("a").confirmed_both()

    shapes[0].label = "C"
    session.sync_shapes(shapes)
    assert session._last_action == "content"
    shapes[0].label = "A"
    restored = session.undo_after_canvas(shapes)
    assert restored
    assert session.object("a").confirmed_both()
    assert session.can_undo_progress()
    assert session.undo_progress()
    assert not session.object("a").confirmed_both()


def test_manual_edit_back_to_same_content_keeps_canvas_undo_first():
    shapes = [make_shape("a", "A", (10, 10, 30, 30))]
    session = DenseReviewSession.from_shapes(
        make_config(),
        shapes,
        "fingerprint",
        100,
        100,
    )
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        assert session.complete_region(region.region_id)
    before_confirmation = copy.deepcopy(session.to_payload())
    assert session.confirm_object("a", ("category", "geometry"))
    confirmed = copy.deepcopy(session.to_payload())
    shapes[0].move_by(10, 0)
    session.sync_shapes(shapes)
    after_first_move = copy.deepcopy(session.to_payload())
    shapes[0].move_by(-10, 0)
    session.sync_shapes(shapes)
    assert session.next_undo_kind() == "canvas"
    assert not session.can_undo_progress()
    assert not session.object("a").confirmed_both()
    assert not session.completion_status().coverage_complete

    shapes[0].move_by(10, 0)
    session.undo_after_canvas(shapes)
    assert session.to_payload() == after_first_move
    assert session.next_undo_kind() == "canvas"
    shapes[0].move_by(-10, 0)
    session.undo_after_canvas(shapes)
    assert session.object("a").confirmed_both()
    assert session.completion_status().complete
    assert session.to_payload() == confirmed
    assert session.next_undo_kind() == "progress"
    assert session.undo_progress()
    assert session.to_payload() == before_confirmation


@pytest.mark.parametrize("changes", [50, 51, 99, 100, 101, 151])
def test_progress_history_limit_keeps_matching_snapshots(changes):
    session = build_session([make_shape("a")])
    snapshots = []
    for index in range(changes):
        snapshots.append(copy.deepcopy(session.to_payload()))
        if index % 2 == 0:
            assert session.mark_difficult("a")
        else:
            assert session.clear_difficult("a")

    # The chronological history retains 100 transactions, each with its state.
    for expected in reversed(snapshots[-100:]):
        assert session.can_undo_progress()
        assert session.undo_progress()
        assert session.to_payload() == expected
    assert not session.can_undo_progress()
    assert not session.undo_progress()


def test_mixed_history_limit_restores_each_transaction_state():
    shape = make_shape("a", bounds=(5, 5, 15, 15))
    session = build_session([shape])
    snapshots = []
    for index in range(65):
        snapshots.append(
            ("progress", shape.bounds, copy.deepcopy(session.to_payload()))
        )
        if index % 2 == 0:
            assert session.mark_difficult("a", reason=str(index))
        else:
            assert session.clear_difficult("a")
        snapshots.append(
            ("canvas", shape.bounds, copy.deepcopy(session.to_payload()))
        )
        shape.move_by(10 if index % 2 == 0 else -10, 0)
        session.sync_shapes([shape])

    for kind, bounds, expected in reversed(snapshots[-100:]):
        assert session.next_undo_kind() == kind
        if kind == "progress":
            assert session.undo_progress()
        else:
            shape.set_bounds(bounds)
            assert session.undo_after_canvas([shape])
        assert session.to_payload() == expected
    assert not session.can_undo_progress()
    assert not session.undo_progress()


def test_canvas_only_undo_keeps_review_content_transaction():
    shape = make_shape("a")
    session = build_session([shape])
    assert session.confirm_object("a", ("category", "geometry"))
    confirmed = copy.deepcopy(session.to_payload())
    shape.move_by(10, 0)
    session.sync_shapes([shape])
    # Undoing a later style-only edit leaves the review content unchanged.
    assert not session.undo_after_canvas([shape])
    assert session.next_undo_kind() == "canvas"
    shape.move_by(-10, 0)
    assert session.undo_after_canvas([shape])
    assert session.to_payload() == confirmed
    assert session.can_undo_progress()


def test_two_progress_commands_can_be_undone_consecutively():
    shapes = [
        make_shape("a", "A", (5, 5, 15, 15)),
        make_shape("b", "B", (25, 5, 35, 15)),
    ]
    session = build_session(shapes)
    assert session.confirm_object("a", ("category", "geometry"))
    assert session.mark_difficult("b", ("category", "geometry"), "看不清")
    assert session.can_undo_progress()
    assert session.undo_progress()
    assert not session.object("b").difficult
    assert session.object("a").confirmed_both()
    assert session.can_undo_progress()
    assert session.undo_progress()
    assert not session.object("a").confirmed_both()
    assert not session.can_undo_progress()


def test_config_rule_change_invalidates_and_batch_change_does_not():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = build_session(shapes)
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        session.complete_region(region.region_id)
    confirm_all(session)
    same_rules_new_batches = make_config(
        batches=(("A/C", ("A", "C")),),
    )
    session.apply_config(same_rules_new_batches, shapes)
    assert session.object("a").confirmed_both()
    session.rebuild_queue(shapes)
    assert session.state.batches[0].member_ids == ["a"]

    changed_rules = make_config(
        batches=(("A/C", ("A", "C")),),
        rules=(("A", "visible", "只标可见部分"),),
    )
    session.apply_config(changed_rules, shapes)
    assert not session.object("a").confirmed_both()
    counts = coverage_service.coverage_counts(session.state.coverage)
    assert counts["completed"] == 0


def test_incompatible_version_and_identity_repair_do_not_inherit():
    payload = {
        "version": 99,
        "objects": {},
    }
    with pytest.raises(IncompatibleReviewState):
        build_session([], payload=payload)

    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = build_session(shapes)
    confirm_all(session)
    payload = copy.deepcopy(session.to_payload())
    repaired = [make_shape("repaired", "A", (5, 5, 15, 15))]
    restored = build_session(repaired, payload=payload)
    assert restored.state.new_pending == ["repaired"]
    assert not restored.object("repaired").confirmed_both()


def test_conflicting_config_cannot_start():
    config = make_config(batches=(("A/B", ("A", "B")), ("A/C", ("A", "C"))))
    with pytest.raises(ReviewConfigError):
        build_session([make_shape("a", "A")], config=config)


def test_redo_progress_restores_confirmation_and_cursor():
    shapes = [
        make_shape("a", "A", (5, 5, 15, 15)),
        make_shape("b", "B", (25, 5, 35, 15)),
    ]
    session = build_session(shapes)
    assert session.confirm_object("a", ("category", "geometry"))
    confirmed = copy.deepcopy(session.to_payload())
    confirmed_cursor = session.state.current_object
    assert session.next_undo_kind() == "progress"
    assert session.undo_progress()
    assert not session.object("a").confirmed_both()
    assert session.next_redo_kind() == "progress"
    assert session.redo_progress()
    assert session.to_payload() == confirmed
    assert session.state.current_object == confirmed_cursor
    assert not session.can_redo_progress()


def test_redo_after_canvas_restores_review_state():
    shape = make_shape("a", "A", (5, 5, 15, 15))
    session = build_session([shape])
    assert session.confirm_object("a", ("category", "geometry"))
    confirmed = copy.deepcopy(session.to_payload())
    shape.move_by(10, 0)
    session.sync_shapes([shape])
    moved = copy.deepcopy(session.to_payload())
    assert not session.object("a").confirmed("geometry")

    shape.move_by(-10, 0)
    assert session.undo_after_canvas([shape])
    assert session.to_payload() == confirmed
    assert session.next_redo_kind() == "canvas"

    shape.move_by(10, 0)
    assert session.redo_after_canvas([shape])
    assert session.to_payload() == moved
    assert not session.object("a").confirmed("geometry")


def test_new_progress_action_clears_redo():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = build_session(shapes)
    assert session.confirm_object("a", ("category", "geometry"))
    assert session.undo_progress()
    assert session.has_redo()
    assert session.mark_difficult("a")
    assert not session.has_redo()
    assert not session.can_redo_progress()


def test_noop_confirm_keeps_redo_stream():
    shapes = [
        make_shape("a", "A", (5, 5, 15, 15)),
        make_shape("b", "B", (25, 5, 35, 15)),
    ]
    session = build_session(shapes)
    assert session.confirm_object("b", ("category", "geometry"))
    assert session.confirm_object("a", ("category", "geometry"))
    assert session.undo_progress()
    assert session.has_redo()
    # Confirming an object that is already confirmed changes nothing and must
    # not throw away the transaction the user just undid.
    assert not session.confirm_object("b", ("category", "geometry"))
    assert session.has_redo()
    assert session.next_redo_kind() == "progress"
    assert session.redo_progress()
    assert session.object("a").confirmed_both()


def test_mixed_undo_then_redo_restores_every_transaction():
    shape = make_shape("a", "A", (5, 5, 15, 15))
    session = build_session([shape])
    kinds = []
    undo_points = []
    redo_points = []
    undo_bounds = []
    redo_bounds = []
    for index in range(4):
        kinds.append("progress")
        undo_points.append(copy.deepcopy(session.to_payload()))
        if index % 2 == 0:
            assert session.mark_difficult("a", reason=str(index))
        else:
            assert session.clear_difficult("a")
        redo_points.append(copy.deepcopy(session.to_payload()))

        kinds.append("canvas")
        undo_points.append(copy.deepcopy(session.to_payload()))
        undo_bounds.append(shape.bounds)
        shape.move_by(10 if index % 2 == 0 else -10, 0)
        redo_bounds.append(shape.bounds)
        session.sync_shapes([shape])
        redo_points.append(copy.deepcopy(session.to_payload()))

    for index in reversed(range(len(kinds))):
        assert session.next_undo_kind() == kinds[index]
        if kinds[index] == "progress":
            assert session.undo_progress()
        else:
            shape.set_bounds(undo_bounds[index // 2])
            assert session.undo_after_canvas([shape])
        assert session.to_payload() == undo_points[index]

    for index in range(len(kinds)):
        assert session.next_redo_kind() == kinds[index]
        if kinds[index] == "progress":
            assert session.redo_progress()
        else:
            shape.set_bounds(redo_bounds[index // 2])
            assert session.redo_after_canvas([shape])
        assert session.to_payload() == redo_points[index]
    assert not session.has_redo()

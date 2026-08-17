"""Pure state-machine tests for the image viewport lifecycle."""

import math

import pytest

from anylabeling.views.labeling.widgets.viewport_state_machine import (
    ViewportSource,
    ViewportState,
    ViewportStateMachine,
    ViewportStatus,
)


def _state(zoom=250, center_x=10.0, center_y=20.0):
    return ViewportState(2, zoom, center_x, center_y)


def test_three_states_are_derived_from_sparse_storage(tmp_path):
    machine = ViewportStateMachine()
    image = tmp_path / "image.png"

    assert machine.status(image) is ViewportStatus.UNKNOWN

    machine.reset([str(image)])
    assert machine.status(image) is ViewportStatus.RESET_PENDING

    machine.commit_loaded(
        str(image),
        machine.resolve_load_plan(
            str(image), keep_prev_viewport=True, keep_prev_scale=True
        ),
        applied_zoom=100,
    )
    assert machine.status(image) is ViewportStatus.UNKNOWN

    machine.capture(str(image), _state())
    assert machine.status(image) is ViewportStatus.CACHED


def test_exact_history_always_wins_over_inheritance(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    machine = ViewportStateMachine()

    machine.capture(str(first), _state(zoom=180))
    machine.commit_loaded(
        str(first),
        machine.resolve_load_plan(
            str(first), keep_prev_viewport=False, keep_prev_scale=False
        ),
    )
    machine.capture(str(second), _state(zoom=320))

    plan = machine.resolve_load_plan(
        str(first), keep_prev_viewport=True, keep_prev_scale=True
    )

    assert plan.source is ViewportSource.EXACT
    assert plan.state.zoom_value == 180


@pytest.mark.parametrize("keep_prev_viewport", [False, True])
def test_unknown_image_uses_full_viewport_only_when_enabled(
    tmp_path, keep_prev_viewport
):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    machine = ViewportStateMachine()
    machine.capture(str(first), _state(zoom=275))
    machine.commit_loaded(
        str(first),
        machine.resolve_load_plan(
            str(first), keep_prev_viewport=False, keep_prev_scale=False
        ),
    )

    plan = machine.resolve_load_plan(
        str(second),
        keep_prev_viewport=keep_prev_viewport,
        keep_prev_scale=False,
    )

    expected = (
        ViewportSource.PREVIOUS_VIEWPORT
        if keep_prev_viewport
        else ViewportSource.DEFAULT
    )
    assert plan.source is expected


def test_keep_previous_scale_is_lower_priority_than_full_viewport(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    machine = ViewportStateMachine()
    machine.capture(str(first), _state(zoom=300))
    machine.commit_loaded(
        str(first),
        machine.resolve_load_plan(
            str(first), keep_prev_viewport=False, keep_prev_scale=False
        ),
    )

    plan = machine.resolve_load_plan(
        str(second), keep_prev_viewport=False, keep_prev_scale=True
    )

    assert plan.source is ViewportSource.PREVIOUS_SCALE
    assert plan.zoom_value == 300


def test_reset_pending_blocks_both_inheritance_policies_until_success(
    tmp_path,
):
    first = tmp_path / "first.png"
    target = tmp_path / "target.png"
    machine = ViewportStateMachine()
    machine.capture(str(first), _state(zoom=280))
    machine.commit_loaded(
        str(first),
        machine.resolve_load_plan(
            str(first), keep_prev_viewport=False, keep_prev_scale=False
        ),
    )
    machine.reset([str(target)])

    pending_plan = machine.resolve_load_plan(
        str(target), keep_prev_viewport=True, keep_prev_scale=True
    )
    assert pending_plan.source is ViewportSource.FORCE_DEFAULT
    assert machine.status(target) is ViewportStatus.RESET_PENDING

    machine.commit_loaded(str(target), pending_plan, applied_zoom=100)
    assert machine.status(target) is ViewportStatus.UNKNOWN

    machine.capture(str(target), _state(zoom=150))
    assert machine.status(target) is ViewportStatus.CACHED


def test_reverse_navigation_does_not_overwrite_other_files(tmp_path):
    paths = [tmp_path / f"image_{index}.png" for index in range(3)]
    machine = ViewportStateMachine()
    for index, path in enumerate(paths):
        machine.capture(str(path), _state(zoom=100 + index * 50))
        machine.commit_loaded(
            str(path),
            machine.resolve_load_plan(
                str(path), keep_prev_viewport=False, keep_prev_scale=False
            ),
        )

    plan = machine.resolve_load_plan(
        str(paths[0]), keep_prev_viewport=True, keep_prev_scale=True
    )

    assert plan.source is ViewportSource.EXACT
    assert plan.state.zoom_value == 100
    assert machine.get_state(paths[2]).zoom_value == 200


def test_file_identity_is_normalized_and_reset_is_rollback_safe(tmp_path):
    image = tmp_path / "image.png"
    alias = tmp_path / "." / "image.png"
    machine = ViewportStateMachine()
    machine.capture(str(image), _state())
    snapshot = machine.snapshot([str(alias)])

    result = machine.reset([str(alias), str(image)])
    assert result.filenames == (machine.normalize_file_id(image),)
    assert machine.status(image) is ViewportStatus.RESET_PENDING

    machine.restore(snapshot)
    assert machine.status(image) is ViewportStatus.CACHED
    assert machine.get_state(alias) == _state()


def test_reset_with_rollback_restores_state_when_follow_up_fails(tmp_path):
    image = tmp_path / "image.png"
    machine = ViewportStateMachine()
    machine.capture(str(image), _state())

    def fail_after_reset(_result):
        raise RuntimeError("injected cache failure")

    with pytest.raises(RuntimeError, match="injected cache failure"):
        machine.reset_with_rollback([str(image)], after_reset=fail_after_reset)

    assert machine.status(image) is ViewportStatus.CACHED
    assert machine.get_state(image) == _state()


def test_large_reset_is_linear_and_does_not_require_image_loading(tmp_path):
    machine = ViewportStateMachine()
    filenames = [tmp_path / f"image_{index}.png" for index in range(5000)]

    result = machine.reset(filenames)

    assert len(result.filenames) == 5000
    assert len(machine.pending_defaults()) == 5000
    assert machine.status(filenames[-1]) is ViewportStatus.RESET_PENDING


def test_reset_scopes_share_one_batch_transition(tmp_path):
    """Current, tail, and all scopes use identical per-file semantics."""
    paths = [tmp_path / f"image_{index}.png" for index in range(3)]
    scopes = (
        [paths[1]],
        [paths[1], paths[2]],
        paths,
    )

    for targets in scopes:
        machine = ViewportStateMachine()
        machine.capture(str(paths[0]), _state())
        result = machine.reset(targets)

        expected = tuple(
            machine.normalize_file_id(path) for path in dict.fromkeys(targets)
        )
        assert result.filenames == expected
        assert all(
            machine.status(path) is ViewportStatus.RESET_PENDING
            for path in targets
        )


def test_invalid_viewport_state_is_rejected():
    with pytest.raises(ValueError):
        ViewportState(99, 100, 0.0, 0.0)
    with pytest.raises(ValueError):
        ViewportState(2, 0, 0.0, 0.0)
    with pytest.raises(ValueError):
        ViewportState(2, 100, math.inf, 0.0)


def test_session_clear_drops_all_sparse_state(tmp_path):
    image = tmp_path / "image.png"
    pending = tmp_path / "pending.png"
    machine = ViewportStateMachine()
    machine.capture(str(image), _state())
    machine.reset([str(pending)])
    machine.commit_loaded(
        str(image),
        machine.resolve_load_plan(
            str(image), keep_prev_viewport=False, keep_prev_scale=False
        ),
    )

    machine.clear_session()

    assert machine.active_file_id is None
    assert machine.previous_scale is None
    assert machine.pending_defaults() == frozenset()
    assert machine.debug_snapshot() == {}

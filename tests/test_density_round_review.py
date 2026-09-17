"""Tests for deterministic density-based review rounds."""

from dataclasses import replace

import pytest

from anylabeling.views.labeling.density_round_review import (
    RectangleSnapshot,
    RoundReviewSession,
    build_round_partition,
)


def snap(shape_id, x, y, index):
    """Build a compact rectangle snapshot for tests."""
    return RectangleSnapshot(shape_id, x, y, index)


def test_landscape_partition_is_spatial_and_balanced():
    """Landscape images sort left-to-right and avoid a tiny final round."""
    items = [snap(str(i), i, 100 - i, i) for i in range(34)]
    partition = build_round_partition(items, (200, 100), limit=10)

    assert partition.axis == "x"
    assert [len(group) for group in partition.rounds] == [9, 9, 8, 8]
    assert partition.rounds[0][0] == "0"
    assert partition.rounds[-1][-1] == "33"


def test_portrait_partition_uses_y_then_x_then_source_order():
    """Portrait ordering uses vertical position with stable tie breakers."""
    items = [
        snap("b", 20, 10, 1),
        snap("a", 10, 10, 0),
        snap("c", 0, 20, 2),
    ]
    partition = build_round_partition(items, (100, 200), limit=10)

    assert partition.axis == "y"
    assert partition.rounds == (("a", "b", "c"),)


def test_exact_limit_creates_equal_rounds():
    """Forty instances at ten per round create four equal rounds."""
    items = [snap(str(i), i, 0, i) for i in range(40)]
    partition = build_round_partition(items, (100, 50), limit=10)
    assert [len(group) for group in partition.rounds] == [10] * 4


def test_zero_instances_keep_one_empty_round():
    """An unlabelled image remains reviewable instead of being skipped."""
    partition = build_round_partition([], (100, 50), limit=10)
    assert partition.rounds == ((),)
    assert partition.boundaries[0].start == 0
    assert partition.boundaries[0].end == 100


def test_limit_must_be_positive():
    """Invalid limits fail before any partition state is built."""
    with pytest.raises(ValueError):
        build_round_partition([], (100, 100), limit=0)


def test_session_freezes_membership_boundary_and_applied_limit():
    """Edits do not rebalance the current image or apply a pending limit."""
    session = RoundReviewSession(default_limit=2)
    session.load_image(
        "one.jpg",
        (100, 50),
        [snap("a", 10, 0, 0), snap("b", 20, 0, 1), snap("c", 90, 0, 2)],
    )
    boundary = session.current_boundary
    session.set_pending_limit(1)
    session.add_to_current("new")
    session.remove("a")

    assert session.applied_limit == 2
    assert session.pending_limit == 1
    assert session.current_boundary == boundary
    assert session.round_count == 2
    assert session.current_members == ("b", "new")


def test_main_creation_uses_frozen_boundary():
    """Main-window creation joins the spatially matching frozen round."""
    session = RoundReviewSession(default_limit=2)
    session.load_image(
        "one.jpg",
        (100, 50),
        [snap("a", 10, 0, 0), snap("b", 20, 0, 1), snap("c", 90, 0, 2)],
    )
    assigned = session.add_by_position(snap("new", 95, 0, 3))
    assert assigned == 1
    assert session.partition.rounds[1] == ("c", "new")


def test_new_image_commits_pending_limit_and_resets_round():
    """Pending limits apply only when another image is loaded."""
    session = RoundReviewSession(default_limit=10)
    session.load_image("one.jpg", (100, 50), [snap("a", 0, 0, 0)])
    session.set_pending_limit(3)
    session.load_image(
        "two.jpg",
        (100, 50),
        [snap(str(i), i, 0, i) for i in range(7)],
    )
    assert session.applied_limit == 3
    assert [len(group) for group in session.partition.rounds] == [3, 2, 2]
    assert session.current_round == 0


def test_deletion_preserves_empty_round():
    """Removing every member never collapses the frozen round list."""
    session = RoundReviewSession(default_limit=1)
    session.load_image(
        "one.jpg",
        (100, 50),
        [snap("a", 10, 0, 0), snap("b", 90, 0, 1)],
    )
    assert session.remove("a")
    assert session.partition.rounds == ((), ("b",))

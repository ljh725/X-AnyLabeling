"""Tests for virtual review criteria and task construction."""

import pytest

from anylabeling.views.labeling.virtual_review import (
    GroupIdMode,
    VirtualShapeView,
    VirtualTaskCriteria,
    build_virtual_tasks,
)


def _shape(
    shape_id,
    label="person",
    shape_type="rectangle",
    group_id=None,
    width=100,
    height=200,
    visible=True,
):
    return VirtualShapeView(
        shape_id=shape_id,
        label=label,
        shape_type=shape_type,
        group_id=group_id,
        width=width,
        height=height,
        bbox=(0, 0, width, height),
        base_visible=visible,
    )


def test_grouped_anchors_are_deduplicated_and_expand_members():
    shapes = (
        _shape("p1", group_id=1),
        _shape("head1", "head", group_id=1, width=20, height=20),
        _shape("p2", group_id=2),
    )

    tasks = build_virtual_tasks(
        shapes,
        VirtualTaskCriteria(labels=frozenset({"person"})),
    )

    assert [task.task_id for task in tasks] == ["group:1", "group:2"]
    assert tasks[0].member_ids == ("p1", "head1")


def test_ungrouped_anchor_is_a_single_shape_task():
    tasks = build_virtual_tasks(
        (_shape("p1"), _shape("p2")),
        VirtualTaskCriteria(labels=frozenset({"person"})),
    )

    assert [task.task_id for task in tasks] == ["shape:p1", "shape:p2"]
    assert tasks[0].member_ids == ("p1",)


def test_label_and_shape_type_are_anded():
    shapes = (
        _shape("person", shape_type="rectangle"),
        _shape("head", label="head", shape_type="rectangle"),
        _shape("polygon", shape_type="polygon"),
    )
    criteria = VirtualTaskCriteria(
        labels=frozenset({"person"}),
        shape_types=frozenset({"rectangle"}),
    )

    tasks = build_virtual_tasks(shapes, criteria)

    assert [task.anchor_id for task in tasks] == ["person"]


@pytest.mark.parametrize(
    "width,expected",
    [(80, True), (100, True), (101, False)],
)
def test_width_bounds_are_inclusive(width, expected):
    tasks = build_virtual_tasks(
        (_shape("p", width=width),),
        VirtualTaskCriteria(min_width=80, max_width=100),
    )

    assert bool(tasks) is expected


def test_group_id_modes_distinguish_valid_missing_and_exact():
    shapes = (_shape("valid", group_id="07"), _shape("missing"))

    valid = build_virtual_tasks(
        shapes,
        VirtualTaskCriteria(group_id_mode=GroupIdMode.VALID),
    )
    missing = build_virtual_tasks(
        shapes,
        VirtualTaskCriteria(group_id_mode=GroupIdMode.MISSING),
    )
    exact = build_virtual_tasks(
        shapes,
        VirtualTaskCriteria(
            group_id_mode=GroupIdMode.EXACT,
            group_id="7",
        ),
    )

    assert [task.anchor_id for task in valid] == ["valid"]
    assert [task.anchor_id for task in missing] == ["missing"]
    assert [task.anchor_id for task in exact] == ["valid"]


def test_hidden_anchor_is_not_eligible_but_hidden_member_is_retained():
    shapes = (
        _shape("p", group_id=1),
        _shape("head", label="head", group_id=1, visible=False),
    )

    tasks = build_virtual_tasks(
        shapes,
        VirtualTaskCriteria(labels=frozenset({"person"})),
    )

    assert tasks[0].member_ids == ("p", "head")
    assert (
        build_virtual_tasks(
            (_shape("hidden", visible=False),), VirtualTaskCriteria()
        )
        == ()
    )


def test_invalid_ranges_are_rejected():
    with pytest.raises(ValueError, match="min_width"):
        VirtualTaskCriteria(min_width=10, max_width=5)

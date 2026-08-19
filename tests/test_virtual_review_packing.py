"""Pure tests for deterministic smart virtual-review packing."""

import pytest

from anylabeling.views.labeling.virtual_review import (
    PackingMode,
    VirtualPackingOptions,
    VirtualTask,
    bbox_gap,
    bboxes_overlap,
    evaluate_page,
    fit_scale,
    pack_virtual_tasks,
    projected_gap,
    projected_short_side,
)


def _task(task_id, left, top=0, width=100, height=100):
    bbox = (left, top, left + width, top + height)
    return VirtualTask(
        task_id=task_id,
        anchor_id=f"anchor:{task_id}",
        member_ids=(f"member:{task_id}",),
        anchor_index=int(task_id),
        bbox=bbox,
        anchor_bbox=bbox,
    )


def test_geometry_helpers_use_projected_screen_space():
    bbox = (0, 0, 100, 50)
    assert bbox_gap(bbox, (150, 0, 250, 50)) == 50
    assert bbox_gap(bbox, (50, 0, 150, 50)) == 0
    assert bboxes_overlap(bbox, (50, 0, 150, 50)) is True
    assert bboxes_overlap(bbox, (100, 0, 200, 50)) is False
    assert fit_scale((0, 0, 200, 100), (800, 600), 2) == 2
    assert projected_short_side(bbox, 2) == 100
    assert projected_gap(bbox, (150, 0, 250, 50), 2) == 100


def test_options_presets_and_validation():
    assert (
        VirtualPackingOptions.preset(PackingMode.SINGLE).max_tasks_per_page
        == 1
    )
    balanced = VirtualPackingOptions.preset("balanced")
    dense = VirtualPackingOptions.preset(PackingMode.DENSE)
    assert balanced.max_tasks_per_page == 2
    assert dense.max_tasks_per_page == 3
    with pytest.raises(ValueError):
        VirtualPackingOptions(max_tasks_per_page=1.5)
    with pytest.raises(ValueError):
        VirtualPackingOptions(min_projected_gap_px=-1)
    with pytest.raises(ValueError):
        VirtualPackingOptions(fit_margin=0)


def test_balanced_mode_combines_compatible_tasks():
    tasks = (_task("0", 0), _task("1", 180))
    result = pack_virtual_tasks(
        tasks, (800, 600), VirtualPackingOptions.preset("balanced")
    )
    assert result.atomic_task_count == 2
    assert result.page_count == 1
    assert result.pages[0].task_ids == ("0", "1")
    assert result.pages[0].member_ids == ("member:0", "member:1")


def test_close_tasks_are_not_combined():
    tasks = (_task("0", 0), _task("1", 105))
    result = pack_virtual_tasks(
        tasks, (800, 600), VirtualPackingOptions.preset("balanced")
    )
    assert [page.task_ids for page in result.pages] == [("0",), ("1",)]


def test_far_tasks_that_become_too_small_are_not_combined():
    tasks = (_task("0", 0), _task("1", 300))
    result = pack_virtual_tasks(
        tasks, (800, 600), VirtualPackingOptions.preset("balanced")
    )
    assert result.page_count == 2


def test_page_limit_and_deterministic_tie_breaking():
    tasks = tuple(_task(str(index), index * 180) for index in range(4))
    options = VirtualPackingOptions(
        mode=PackingMode.DENSE,
        max_tasks_per_page=2,
        min_projected_anchor_px=100,
        min_projected_gap_px=20,
    )
    first = pack_virtual_tasks(tasks, (1200, 800), options)
    second = pack_virtual_tasks(tasks, (1200, 800), options)
    assert first.pages == second.pages
    assert all(page.task_count <= 2 for page in first.pages)


def test_invalid_geometry_falls_back_without_dropping_tasks():
    invalid = VirtualTask(
        task_id="invalid",
        anchor_id="anchor:invalid",
        member_ids=("member:invalid",),
        anchor_index=0,
    )
    valid = _task("1", 0)
    result = pack_virtual_tasks(
        (invalid, valid), (800, 600), VirtualPackingOptions.preset("balanced")
    )
    assert result.atomic_task_count == 2
    assert result.page_count == 2
    assert result.singleton_fallback_count == 1
    assert {task_id for page in result.pages for task_id in page.task_ids} == {
        "invalid",
        "1",
    }


def test_evaluate_page_rejects_over_limit():
    options = VirtualPackingOptions.preset("balanced")
    tasks = (_task("0", 0), _task("1", 180), _task("2", 360))
    evaluation = evaluate_page(tasks, (1200, 800), options)
    assert not evaluation.accepted


def test_geometry_helpers_reject_invalid_inputs():
    invalid_bbox = (10, 10, 10, 40)  # zero width
    assert bbox_gap(invalid_bbox, (0, 0, 1, 1)) is None
    assert bbox_gap(None, (0, 0, 1, 1)) is None
    for bad_viewport in ((0, 600), (800, -1), (float("nan"), 600)):
        assert fit_scale((0, 0, 100, 50), bad_viewport) == 0.0
    assert fit_scale((0, 0, 100, 50), (800, 600), fit_margin=0) == 0.0
    assert projected_short_side((0, 0, 100, 50), 0) is None
    assert projected_short_side(None, 2.0) is None
    assert projected_gap((0, 0, 10, 10), (20, 0, 30, 10), 0.0) is None


def test_overlapping_tasks_are_never_combined():
    first = VirtualTask(
        task_id="0",
        anchor_id="a0",
        member_ids=("m0",),
        anchor_index=0,
        bbox=(0, 0, 200, 100),
        anchor_bbox=(0, 0, 200, 100),
    )
    second = VirtualTask(
        task_id="1",
        anchor_id="a1",
        member_ids=("m1",),
        anchor_index=1,
        bbox=(100, 0, 300, 100),  # overlaps first
        anchor_bbox=(100, 0, 300, 100),
    )
    result = pack_virtual_tasks(
        (first, second), (1600, 900), VirtualPackingOptions.preset("dense")
    )
    assert [page.task_ids for page in result.pages] == [("0",), ("1",)]


def test_overlapping_tasks_are_rejected_when_gap_threshold_is_zero():
    first = _task("0", 0)
    second = _task("1", 50)
    options = VirtualPackingOptions(
        max_tasks_per_page=2,
        min_projected_anchor_px=0,
        min_projected_gap_px=0,
    )

    result = pack_virtual_tasks((first, second), (800, 600), options)

    assert [page.task_ids for page in result.pages] == [("0",), ("1",)]


def test_packing_uses_actual_maximum_review_zoom():
    first = _task("0", 0, width=6, height=6)
    second = _task("1", 16, width=6, height=6)
    options = VirtualPackingOptions.preset("balanced")

    assert fit_scale((0, 0, 22, 6), (800, 600), options.fit_margin) == 10
    result = pack_virtual_tasks((first, second), (800, 600), options)

    assert [page.task_ids for page in result.pages] == [("0",), ("1",)]


def test_single_mode_wraps_every_task_as_singleton_page():
    tasks = tuple(_task(str(index), index * 50) for index in range(4))
    result = pack_virtual_tasks(
        tasks, (800, 600), VirtualPackingOptions.preset("single")
    )
    assert result.page_count == len(tasks)
    assert all(page.task_count == 1 for page in result.pages)
    assert [page.task_ids[0] for page in result.pages] == [
        task.task_id for task in tasks
    ]
    assert result.singleton_fallback_count == 0


def test_invalid_viewport_fails_closed_to_singletons():
    tasks = (_task("0", 0), _task("1", 180))
    for bad_viewport in ((0, 0), (-5, 100), (float("inf"), 20)):
        result = pack_virtual_tasks(
            tasks,
            bad_viewport,
            VirtualPackingOptions.preset("balanced"),
        )
        assert result.page_count == 2
        assert result.singleton_fallback_count == 2


@pytest.mark.parametrize(
    "bad_viewport",
    [None, (None, 600), (800,), (800, 600, 1)],
)
def test_malformed_viewport_fails_closed_to_singletons(bad_viewport):
    tasks = (_task("0", 0), _task("1", 180))

    result = pack_virtual_tasks(
        tasks,
        bad_viewport,
        VirtualPackingOptions.preset("balanced"),
    )

    assert result.page_count == 2
    assert result.singleton_fallback_count == 2


def _packed_membership(pages):
    return [task_id for page in pages for task_id in page.task_ids]


def test_every_task_appears_exactly_once():
    tasks = tuple(_task(str(index), index * 190) for index in range(30))
    result = pack_virtual_tasks(
        tasks, (1920, 1080), VirtualPackingOptions.preset("dense")
    )
    coverage = _packed_membership(result.pages)
    assert len(coverage) == len(tasks)
    assert set(coverage) == {task.task_id for task in tasks}


def test_grouped_task_members_stay_on_one_page():
    grouped = VirtualTask(
        task_id="group:1",
        anchor_id="person",
        member_ids=("person", "face", "hand"),
        group_id="1",
        anchor_index=0,
        bbox=(0, 0, 400, 400),
        anchor_bbox=(0, 0, 400, 400),
    )
    other = _task("9", 600)
    result = pack_virtual_tasks(
        (grouped, other), (1920, 1080), VirtualPackingOptions.preset("dense")
    )
    member_pages = [
        page.page_id for page in result.pages if "person" in page.member_ids
    ]
    assert member_pages == [result.pages[0].page_id]
    assert set(grouped.member_ids) <= set(result.pages[0].member_ids)


def test_packing_30_tasks_is_stable_and_bounded():
    tasks = tuple(_task(str(index), index * 170) for index in range(30))
    options = VirtualPackingOptions.preset("balanced")
    first = pack_virtual_tasks(tasks, (1920, 1080), options)
    assert first.page_count <= 30
    assert all(page.task_count <= 2 for page in first.pages)
    again = pack_virtual_tasks(tasks, (1920, 1080), options)
    assert again.pages == first.pages
    coverage = _packed_membership(first.pages)
    assert len(coverage) == 30
    assert len(set(coverage)) == 30


def test_page_order_follows_first_task_order():
    tasks = tuple(_task(str(index), index * 190) for index in range(8))
    result = pack_virtual_tasks(
        tasks, (1920, 1080), VirtualPackingOptions.preset("dense")
    )
    seeds = [int(page.task_ids[0]) for page in result.pages]
    assert seeds == sorted(seeds)

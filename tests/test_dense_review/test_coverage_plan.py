from anylabeling.services.dense_review import coverage
from anylabeling.services.dense_review.models import (
    CoverageSettings,
    ObjectReviewState,
)


def _object(shape_id, bounds):
    return ObjectReviewState(
        shape_id=shape_id,
        display_index=1,
        label="A",
        shape_type="rectangle",
        bounds=bounds,
        category_signature="cat",
        geometry_signature="geo",
    )


def test_plan_covers_whole_image_and_has_overlap():
    plan = coverage.build_plan(
        CoverageSettings(columns=2, rows=2, overlap=0.2), 100, 80
    )
    assert len(plan.regions) == 4
    assert min(region.rect[0] for region in plan.regions) == 0
    assert min(region.rect[1] for region in plan.regions) == 0
    assert max(region.rect[2] for region in plan.regions) == 100
    assert max(region.rect[3] for region in plan.regions) == 80
    top_left = plan.region("r00-00")
    top_right = plan.region("r00-01")
    assert top_left.rect[2] > 50
    assert top_right.rect[0] < 50
    assert coverage.next_region(plan).region_id == "r00-00"


def test_complete_region_records_baseline():
    plan = coverage.build_plan(CoverageSettings(2, 2, 0.1), 100, 100)
    objects = {"a": _object("a", (5, 5, 15, 15))}
    region = plan.region("r00-00")
    assert coverage.complete_region(plan, region.region_id, objects)
    assert region.completed
    assert "a" in region.baseline


def test_move_invalidates_old_and_new_regions_only():
    plan = coverage.build_plan(CoverageSettings(2, 2, 0.0), 100, 100)
    for region in plan.regions:
        coverage.complete_region(plan, region.region_id, {})
    assert coverage.invalidate_regions(
        plan, {"a": ((5, 5, 15, 15), (85, 85, 95, 95))}
    ) == 2
    assert coverage.coverage_counts(plan)["completed"] == 2


def test_delete_without_old_bounds_withdraws_everything():
    plan = coverage.build_plan(CoverageSettings(2, 2, 0.0), 100, 100)
    for region in plan.regions:
        coverage.complete_region(plan, region.region_id, {})
    assert coverage.invalidate_regions(
        plan, {"a": (None, None)}, unknown_scope=True
    ) == 4
    assert coverage.coverage_counts(plan)["completed"] == 0


def test_region_difficult_and_skipped_are_not_completed():
    plan = coverage.build_plan(CoverageSettings(2, 2, 0.0), 100, 100)
    region_id = "r00-00"
    assert coverage.set_region_difficult(plan, region_id, True)
    assert not coverage.complete_region(plan, region_id, {})
    assert coverage.set_region_skipped(plan, region_id, True)
    assert not coverage.complete_region(plan, region_id, {})
    assert coverage.set_region_skipped(plan, region_id, False)
    assert coverage.complete_region(plan, region_id, {})


def test_different_grid_settings_produce_different_plan_identity():
    first = coverage.build_plan(CoverageSettings(2, 2, 0.1), 100, 100)
    second = coverage.build_plan(CoverageSettings(3, 2, 0.1), 100, 100)
    assert first.plan_id != second.plan_id
    assert len(first.regions) != len(second.regions)

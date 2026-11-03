"""Spatial omission-review plan and conservative coverage invalidation."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from .models import (
    CoveragePlan,
    CoverageRegion,
    CoverageSettings,
    normalize_bounds,
    signature_for,
)
from .signatures import bbox_intersects_bounds, shape_bounds


def plan_id_for(
    settings: CoverageSettings, image_width: int, image_height: int
) -> str:
    normalized = settings.normalized()
    return signature_for(
        {
            "columns": normalized.columns,
            "rows": normalized.rows,
            "overlap": normalized.overlap,
            "width": int(image_width),
            "height": int(image_height),
        }
    )[:16]


def build_plan(
    settings: CoverageSettings,
    image_width: int,
    image_height: int,
) -> CoveragePlan:
    """Build a new plan covering the whole image, including empty areas."""
    normalized = settings.normalized()
    width = max(1, int(image_width))
    height = max(1, int(image_height))
    cell_width = width / normalized.columns
    cell_height = height / normalized.rows
    margin_x = cell_width * normalized.overlap / 2.0
    margin_y = cell_height * normalized.overlap / 2.0
    regions: list[CoverageRegion] = []
    for row in range(normalized.rows):
        for column in range(normalized.columns):
            x0 = max(0.0, column * cell_width - margin_x)
            y0 = max(0.0, row * cell_height - margin_y)
            x1 = min(width, (column + 1) * cell_width + margin_x)
            y1 = min(height, (row + 1) * cell_height + margin_y)
            rect = normalize_bounds((x0, y0, x1, y1))
            if rect is None:
                continue
            region_id = f"r{row:02d}-{column:02d}"
            regions.append(
                CoverageRegion(
                    region_id=region_id,
                    row=row,
                    column=column,
                    rect=rect,
                )
            )
    return CoveragePlan(
        plan_id=plan_id_for(normalized, width, height),
        columns=normalized.columns,
        rows=normalized.rows,
        overlap=normalized.overlap,
        image_width=width,
        image_height=height,
        regions=regions,
        current_region=regions[0].region_id if regions else "",
    )


def region_objects(
    plan: CoveragePlan,
    region: CoverageRegion,
    objects: Mapping[str, Any],
) -> dict[str, tuple[float, float, float, float]]:
    """Return current bounds for alive objects intersecting one region."""
    baseline: dict[str, tuple[float, float, float, float]] = {}
    for shape_id, item in objects.items():
        bounds = normalize_bounds(getattr(item, "bounds", ()))
        if bounds is None:
            continue
        if bbox_intersects_bounds(bounds, region.rect):
            baseline[shape_id] = bounds
    return baseline


def complete_region(
    plan: CoveragePlan,
    region_id: str,
    objects: Mapping[str, Any],
) -> bool:
    """Record one explicit region completion unless it is unresolved."""
    region = plan.region(region_id)
    if region is None or region.difficult or region.skipped:
        return False
    region.completed = True
    region.baseline = region_objects(plan, region, objects)
    plan.current_region = region_id
    return True


def set_region_difficult(
    plan: CoveragePlan, region_id: str, difficult: bool
) -> bool:
    region = plan.region(region_id)
    if region is None:
        return False
    region.difficult = bool(difficult)
    if difficult:
        region.completed = False
        region.skipped = False
        region.baseline = {}
    plan.current_region = region_id
    return True


def set_region_skipped(
    plan: CoveragePlan, region_id: str, skipped: bool
) -> bool:
    region = plan.region(region_id)
    if region is None:
        return False
    region.skipped = bool(skipped)
    if skipped:
        region.completed = False
        region.difficult = False
        region.baseline = {}
    plan.current_region = region_id
    return True


ChangedBounds = Mapping[
    str,
    tuple[Optional[Sequence[float]], Optional[Sequence[float]]],
]


def invalidate_regions(
    plan: CoveragePlan,
    changed_bounds: ChangedBounds,
    *,
    rules_changed: bool = False,
    unknown_scope: bool = False,
) -> int:
    """Invalidate completed regions affected by changed object bounds.

    ``changed_bounds`` maps a shape id to ``(old_bounds, new_bounds)``.  An
    object that fully disappeared has ``new_bounds=None``; a newly added
    object has ``old_bounds=None``.  When the old position or the affected
    scope is unknown, every region is withdrawn conservatively.
    """
    if rules_changed or unknown_scope:
        return invalidate_all(plan)
    invalidated = 0
    for region in plan.regions:
        if not region.completed:
            continue
        affected = False
        for shape_id, (old_bounds, new_bounds) in changed_bounds.items():
            if shape_id in region.baseline:
                affected = True
                break
            for bounds in (old_bounds, new_bounds):
                if bounds is None:
                    continue
                if bbox_intersects_bounds(bounds, region.rect):
                    affected = True
                    break
            if affected:
                break
        if affected:
            region.completed = False
            region.baseline = {}
            invalidated += 1
    return invalidated


def invalidate_all(plan: CoveragePlan) -> int:
    """Withdraw every completed region while keeping the plan identity."""
    invalidated = 0
    for region in plan.regions:
        if region.completed:
            invalidated += 1
        region.completed = False
        region.baseline = {}
    return invalidated


def next_region(
    plan: CoveragePlan,
    start_after: Optional[str] = None,
    *,
    include_difficult: bool = False,
    include_skipped: bool = True,
) -> Optional[CoverageRegion]:
    """Return the next unresolved region in row-major order."""
    if not plan.regions:
        return None
    index = 0
    if start_after:
        for position, region in enumerate(plan.regions):
            if region.region_id == start_after:
                index = position + 1
                break
    count = len(plan.regions)
    for offset in range(count):
        region = plan.regions[(index + offset) % count]
        if region.completed:
            continue
        if region.difficult and not include_difficult:
            continue
        if region.skipped and not include_skipped:
            continue
        return region
    return None


def coverage_counts(plan: Optional[CoveragePlan]) -> dict[str, int]:
    """Return counts used by the workspace and completion checks."""
    if plan is None:
        return {
            "total": 0,
            "completed": 0,
            "difficult": 0,
            "skipped": 0,
            "pending": 0,
        }
    completed = sum(1 for region in plan.regions if region.completed)
    difficult = sum(1 for region in plan.regions if region.difficult)
    skipped = sum(1 for region in plan.regions if region.skipped)
    return {
        "total": len(plan.regions),
        "completed": completed,
        "difficult": difficult,
        "skipped": skipped,
        "pending": len(plan.regions) - completed,
    }


def bounds_for_shapes(shapes: Iterable[Any]) -> dict[str, tuple[float, ...]]:
    """Return bounds for all shapes that can participate in coverage."""
    result: dict[str, tuple[float, ...]] = {}
    for shape in shapes:
        shape_id = str(getattr(shape, "xanylabeling_shape_id", ""))
        bounds = shape_bounds(shape)
        if shape_id and bounds is not None:
            result[shape_id] = bounds
    return result

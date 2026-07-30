"""Tests for loose three-box relative-geometry filtering."""

from __future__ import annotations

import json
from pathlib import Path

from anylabeling.views.labeling.rect_refine_grouping import (
    infer,
    loosely_nested,
)
from anylabeling.views.labeling.rect_refine_types import ShapeRefineView
from scripts.compare_rect_refine_grouping import compare_samples

TOKEN = "image-1"


def _view(
    label: str,
    bbox: tuple[float, float, float, float] | None,
    index: int,
    *,
    shape_type: str = "rectangle",
) -> ShapeRefineView:
    """Build one deterministic grouping view."""
    return ShapeRefineView(
        shape_id=(TOKEN, index),
        shape_index=index,
        label=label,
        shape_type=shape_type,
        bbox=bbox,
    )


def _member_ids(
    anchor: ShapeRefineView,
    pool: list[ShapeRefineView],
) -> set[tuple[str, int]]:
    """Return member identities produced for one anchor."""
    return {member.shape_id for member in infer(anchor, pool).members}


def test_loose_nesting_accepts_slight_overflow() -> None:
    """A true inner box may cross an outer edge by half its own size."""
    head = _view("head", (10, 10, 50, 50), 1)
    face = _view("face", (35, 20, 55, 45), 2)

    assert loosely_nested(face, head) is True


def test_loose_nesting_accepts_small_annotation_gap() -> None:
    """Near-adjacent boxes survive without a fixed pixel threshold."""
    person = _view("person", (10, 20, 100, 200), 1)
    head = _view("head", (35, 0, 65, 25), 2)

    assert loosely_nested(head, person) is True


def test_loose_nesting_rejects_far_or_larger_inner() -> None:
    """Spatially unrelated and inverted-size pairs remain filtered."""
    outer = _view("person", (0, 0, 100, 200), 1)
    far = _view("head", (300, 300, 330, 340), 2)
    larger = _view("head", (-50, -50, 150, 250), 3)

    assert loosely_nested(far, outer) is False
    assert loosely_nested(larger, outer) is False


def test_person_anchor_includes_related_heads_and_faces() -> None:
    """Person selection keeps every loose head and its loose faces."""
    person = _view("person", (0, 0, 100, 200), 1)
    head_a = _view("head", (10, 5, 40, 45), 2)
    head_b = _view("head", (60, 10, 90, 50), 3)
    face = _view("face", (65, 20, 88, 48), 4)
    far_head = _view("head", (300, 300, 330, 340), 5)
    pool = [person, head_a, head_b, face, far_head]

    assert _member_ids(person, pool) == {
        person.shape_id,
        head_a.shape_id,
        head_b.shape_id,
        face.shape_id,
    }


def test_head_anchor_includes_persons_and_faces_without_top_one() -> None:
    """Head selection retains all plausible neighbours, not a scored top-1."""
    person_a = _view("person", (0, 0, 100, 200), 1)
    person_b = _view("person", (30, 0, 130, 200), 2)
    head = _view("head", (40, 10, 70, 50), 3)
    face = _view("face", (45, 20, 68, 48), 4)
    pool = [person_a, person_b, head, face]

    assert _member_ids(head, pool) == {
        person_a.shape_id,
        person_b.shape_id,
        head.shape_id,
        face.shape_id,
    }


def test_face_anchor_builds_head_person_chain() -> None:
    """Face selection walks upward through every loose related head."""
    person = _view("person", (0, 0, 100, 200), 1)
    head = _view("head", (30, 10, 70, 50), 2)
    face = _view("face", (38, 18, 72, 52), 3)
    pool = [person, head, face]

    assert _member_ids(face, pool) == {
        person.shape_id,
        head.shape_id,
        face.shape_id,
    }


def test_invalid_geometry_keeps_anchor_only() -> None:
    """Degenerate anchors fail safely without admitting unrelated Shapes."""
    anchor = _view("person", None, 1)
    head = _view("head", (30, 10, 70, 50), 2)
    result = infer(anchor, [anchor, head])

    assert result.members == (anchor,)
    assert result.nonblocking_message == "anchor_invalid_geometry"


def test_member_order_follows_canvas_order() -> None:
    """Filtering remains deterministic without a score-based sort key."""
    person = _view("person", (0, 0, 100, 200), 3)
    head = _view("head", (30, 10, 70, 50), 1)
    face = _view("face", (38, 18, 62, 48), 2)

    result = infer(person, [person, head, face])

    assert [member.shape_index for member in result.members] == [1, 2, 3]


def test_real_samples_keep_all_reviewed_true_targets() -> None:
    """Captured production samples must retain every reviewed relation."""
    fixture = (
        Path(__file__).parent / "fixtures" / "rect_refine_real_samples.json"
    )
    samples = json.loads(fixture.read_text(encoding="utf-8"))

    report = compare_samples(samples)

    assert report["summary"]["expected_total"] == 46
    assert report["summary"]["expected_hits"] == 46
    assert report["summary"]["expected_recall"] == 1.0
    assert report["summary"]["visibility_reduction"] > 0.80
    assert report["legacy_scoring_baseline"]["expected_hits"] == 36
    assert report["comparison"]["expected_hit_delta"] == 10

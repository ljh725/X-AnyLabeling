import pytest

from anylabeling.services.inspection.duplicate import (
    DuplicateSeverity,
    DuplicateThresholds,
    IncrementalDuplicateDetector,
    RectangleSnapshot,
    evaluate_pair,
    full_scan,
    legacy_same_group_pair,
    pair_metrics,
    rectangle_snapshot_from_points,
    thresholds_from_mapping,
)


def _rect(shape_id, label="person", bbox=(0, 0, 10, 10), group_id=None):
    return RectangleSnapshot(shape_id, label, bbox, group_id)


def test_identical_rectangles_are_high_risk():
    pair = evaluate_pair(
        _rect("a"), _rect("b"), thresholds_from_mapping(
            {
                "red_iou": 0.95,
                "red_containment": 0.97,
                "red_center": 0.04,
                "red_area_ratio": 0.88,
                "yellow_iou": 0.80,
                "yellow_containment": 0.92,
                "yellow_center": 0.13,
                "yellow_area_ratio": 0.65,
                "yellow_aspect_ratio": 0.68,
                "yellow_edge_delta": 0.14,
            }
        )
    )
    assert pair is not None
    assert pair.severity is DuplicateSeverity.HIGH_RISK
    assert pair.key == ("a", "b")
    assert pair.metrics.iou == pytest.approx(1.0)


def test_non_overlapping_rectangles_are_not_candidates():
    pair = evaluate_pair(
        _rect("a", bbox=(0, 0, 10, 10)),
        _rect("b", bbox=(40, 40, 50, 50)),
        thresholds_from_mapping(
            {
                "red_iou": 0.95,
                "red_containment": 0.97,
                "red_center": 0.04,
                "red_area_ratio": 0.88,
                "yellow_iou": 0.80,
                "yellow_containment": 0.92,
                "yellow_center": 0.13,
                "yellow_area_ratio": 0.65,
                "yellow_aspect_ratio": 0.68,
                "yellow_edge_delta": 0.14,
            }
        ),
    )
    assert pair is None


def test_threshold_validation_rejects_inverted_order():
    with pytest.raises(ValueError):
        DuplicateThresholds(
            0.5, 0.9, 0.1, 0.9, 0.6, 0.9, 0.2, 0.8, 0.6, 0.2
        ).validate()


def test_full_scan_cancellation_is_not_an_empty_success():
    result = full_scan(
        [_rect("a"), _rect("b")],
        thresholds_from_mapping(
            {
                "red_iou": 0.95,
                "red_containment": 0.97,
                "red_center": 0.04,
                "red_area_ratio": 0.88,
                "yellow_iou": 0.80,
                "yellow_containment": 0.92,
                "yellow_center": 0.13,
                "yellow_area_ratio": 0.65,
                "yellow_aspect_ratio": 0.68,
                "yellow_edge_delta": 0.14,
            }
        ),
        should_cancel=lambda: True,
    )
    assert result.cancelled is True
    assert result.complete is False


def test_incremental_detector_matches_full_scan():
    thresholds = thresholds_from_mapping(
        {
            "red_iou": 0.95,
            "red_containment": 0.97,
            "red_center": 0.04,
            "red_area_ratio": 0.88,
            "yellow_iou": 0.80,
            "yellow_containment": 0.92,
            "yellow_center": 0.13,
            "yellow_area_ratio": 0.65,
            "yellow_aspect_ratio": 0.68,
            "yellow_edge_delta": 0.14,
        }
    )
    rectangles = [
        _rect("a", bbox=(0, 0, 10, 10)),
        _rect("b", bbox=(0, 0, 10, 10)),
        _rect("c", bbox=(0, 0, 30, 30)),
    ]
    full = full_scan(rectangles, thresholds)
    detector = IncrementalDuplicateDetector(thresholds)
    detector.replace(full, rectangles)
    assert set(detector.pairs) == {pair.key for pair in full.pairs}
    detector.update_geometry(_rect("c", bbox=(0, 0, 10, 10)))
    updated = full_scan(
        [
            _rect("a", bbox=(0, 0, 10, 10)),
            _rect("b", bbox=(0, 0, 10, 10)),
            _rect("c", bbox=(0, 0, 10, 10)),
        ],
        thresholds,
    )
    assert set(detector.pairs) == {pair.key for pair in updated.pairs}
    detector.remove("a")
    assert all("a" not in key for key in detector.pairs)


def test_rectangle_snapshot_rejects_invalid_geometry():
    with pytest.raises(ValueError):
        rectangle_snapshot_from_points("a", "person", [[0, 0], [0, 0]])
    with pytest.raises(ValueError):
        rectangle_snapshot_from_points("a", "person", [[0, 0], [float("nan"), 1]])


def test_legacy_rule_keeps_same_group_edges_only():
    first = _rect("a", group_id=7)
    second = _rect("b", group_id=7)
    assert legacy_same_group_pair(first, second, 2.0) is not None
    assert legacy_same_group_pair(first, _rect("c", group_id=8), 2.0) is None
    assert legacy_same_group_pair(first, _rect("d", "car", group_id=7), 2.0) is None


def test_metrics_are_stable_for_contained_rectangles():
    inner = _rect("a", bbox=(2, 2, 8, 8))
    outer = _rect("b", bbox=(0, 0, 10, 10))
    metrics = pair_metrics(inner, outer)
    assert metrics.smaller_coverage == pytest.approx(1.0)
    assert metrics.area_ratio == pytest.approx(0.36)


def test_chain_overlap_keeps_pairs_without_merging_entities():
    thresholds = thresholds_from_mapping(
        {
            "red_iou": 0.95,
            "red_containment": 0.97,
            "red_center": 0.04,
            "red_area_ratio": 0.88,
            "yellow_iou": 0.80,
            "yellow_containment": 0.92,
            "yellow_center": 0.13,
            "yellow_area_ratio": 0.65,
            "yellow_aspect_ratio": 0.68,
            "yellow_edge_delta": 0.14,
        }
    )
    rectangles = [
        _rect("a", bbox=(0, 0, 10, 10)),
        _rect("b", bbox=(1, 0, 11, 10)),
        _rect("c", bbox=(2, 0, 12, 10)),
    ]
    result = full_scan(rectangles, thresholds)
    keys = {pair.key for pair in result.pairs}
    assert ("a", "b") in keys
    assert ("b", "c") in keys
    assert ("a", "c") not in keys


def test_contained_rectangle_is_a_candidate_not_a_deletion():
    thresholds = thresholds_from_mapping(
        {
            "red_iou": 0.95,
            "red_containment": 0.97,
            "red_center": 0.04,
            "red_area_ratio": 0.88,
            "yellow_iou": 0.80,
            "yellow_containment": 0.92,
            "yellow_center": 0.13,
            "yellow_area_ratio": 0.65,
            "yellow_aspect_ratio": 0.68,
            "yellow_edge_delta": 0.14,
        }
    )
    pair = evaluate_pair(
        _rect("inner", bbox=(0.1, 0.1, 9.9, 9.9)),
        _rect("outer", bbox=(0, 0, 10, 10)),
        thresholds,
    )
    assert pair is not None
    assert pair.severity is DuplicateSeverity.HIGH_RISK

"""Incremental duplicate updates must equal a full scan of the same input."""

from anylabeling.services.inspection.duplicate import (
    PRESETS,
    full_scan,
    rectangle_snapshot_from_points,
)
from anylabeling.services.inspection.incremental import (
    DuplicateTracker,
    rectangles_from_file,
    tracker_from_profile,
)
from anylabeling.services.inspection.manifest import (
    load_file_snapshot,
    memory_file_snapshot,
)
from anylabeling.services.inspection.profiles import default_profiles


def _rect(shape_id, bbox, label="person", group_id=None):
    left, top, right, bottom = bbox
    return rectangle_snapshot_from_points(
        shape_id,
        label,
        [(left, top), (right, bottom)],
        group_id,
    )


def _memory(tmp_path, image_name, shapes):
    return memory_file_snapshot(
        str(tmp_path / image_name),
        image_name,
        shapes,
        image_width=100,
        image_height=100,
    )


def _full_pair_keys(rectangles, thresholds=PRESETS["medium"]):
    result = full_scan(rectangles, thresholds)
    return sorted((pair.key, pair.severity.value) for pair in result.pairs)


def test_incremental_edit_matches_full_scan(tmp_path):
    tracker = DuplicateTracker(PRESETS["medium"])
    first = _memory(
        tmp_path,
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[20, 20], [30, 30]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    )
    tracker.load_file("a.jpg", first)

    # Move id2 on top of id1: incremental result must equal a fresh scan.
    moved = _memory(
        tmp_path,
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    )
    rectangles, _ = rectangles_from_file(moved)
    pairs = tracker.apply_edit("a.jpg", updated=rectangles)
    assert pairs.consistent is True
    assert pairs.incremental_applied is True
    assert [(pair.key, pair.severity.value) for pair in pairs.pairs] == (
        _full_pair_keys(rectangles)
    )

    # Add another overlapping box; again incremental == full scan.
    added = _rect("id3", (1, 1, 11, 11))
    pairs = tracker.apply_edit("a.jpg", added=[added])
    rectangles, _ = rectangles_from_file(moved)
    rectangles.append(added)
    assert pairs.consistent is True
    assert [(pair.key, pair.severity.value) for pair in pairs.pairs] == (
        _full_pair_keys(rectangles)
    )

    # Delete id2: the pair must disappear in both paths.
    pairs = tracker.apply_edit("a.jpg", removed=["id2", "id3"])
    remaining = [item for item in rectangles if item.shape_id == "id1"]
    assert pairs.pairs == ()
    assert _full_pair_keys(remaining) == []

    # Undo the deletion (re-add) restores the pair.
    pairs = tracker.apply_edit(
        "a.jpg", added=[_rect("id2", (0, 0, 10, 10))]
    )
    assert pairs.pairs


def test_cross_image_same_ids_do_not_share_state(tmp_path):
    tracker = DuplicateTracker(PRESETS["medium"])
    a = _memory(
        tmp_path,
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    )
    b = _memory(
        tmp_path,
        "b.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[50, 50], [60, 60]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    )
    assert tracker.load_file("a.jpg", a).pairs
    assert tracker.load_file("b.jpg", b).pairs == ()
    # Editing b.jpg must not touch a.jpg's state even with the same ids.
    moved_b = _memory(
        tmp_path,
        "b.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    )
    rectangles, _ = rectangles_from_file(moved_b)
    pair_state = tracker.apply_edit("b.jpg", updated=rectangles)
    assert pair_state.pairs
    assert tracker.last_pairs["a.jpg"] == _both_equal(PRESETS["medium"], a)


def _both_equal(thresholds, file):
    rectangles, _ = rectangles_from_file(file)
    result = full_scan(rectangles, thresholds)
    return result.pairs


def test_threshold_change_rescans_every_file(tmp_path):
    tracker = DuplicateTracker(PRESETS["medium"])
    low_overlap = _memory(
        tmp_path,
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [100, 100]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[50, 50], [150, 150]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    )
    tracker.load_file("a.jpg", low_overlap)
    strict = DuplicateTracker(PRESETS["high"])
    strict_rects, _ = rectangles_from_file(low_overlap)
    expected_strict = _full_pair_keys(strict_rects, PRESETS["high"])
    touched = tracker.set_thresholds(PRESETS["high"])
    assert touched == ("a.jpg",)
    assert [(pair.key, pair.severity.value)
            for pair in tracker.last_pairs["a.jpg"]] == expected_strict


def test_recheck_file_detects_out_of_band_change(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"image")
    (tmp_path / "a.json").write_text(
        '{"version":"4.2.1","imageWidth":100,"imageHeight":100,'
        '"shapes":[{"label":"person","shape_type":"rectangle",'
        '"points":[[0,0],[10,10]],"xanylabeling_shape_id":"id1"},'
        '{"label":"person","shape_type":"rectangle",'
        '"points":[[20,20],[30,30]],"xanylabeling_shape_id":"id2"}]}',
        encoding="utf-8",
    )
    tracker = DuplicateTracker(PRESETS["medium"])
    snapshot = load_file_snapshot(str(image), str(tmp_path))
    assert tracker.load_file("a.jpg", snapshot).pairs == ()
    # Another process overwrites the annotation with two identical boxes.
    (tmp_path / "a.json").write_text(
        '{"version":"4.2.1","imageWidth":100,"imageHeight":100,'
        '"shapes":[{"label":"person","shape_type":"rectangle",'
        '"points":[[0,0],[10,10]],"xanylabeling_shape_id":"id1"},'
        '{"label":"person","shape_type":"rectangle",'
        '"points":[[0,0],[10,10]],"xanylabeling_shape_id":"id2"}]}',
        encoding="utf-8",
    )
    changed = load_file_snapshot(str(image), str(tmp_path))
    state = tracker.recheck_file("a.jpg", changed)
    assert state.pairs
    assert state.consistent is False


def test_tracker_uses_profile_thresholds():
    tracker = tracker_from_profile(default_profiles()[0])
    assert tracker.thresholds == PRESETS["medium"]
    assert tracker.keys() == ()

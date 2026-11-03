import json
import os

import pytest

from anylabeling.services.dense_review import coverage as coverage_service
from anylabeling.services.dense_review.config import (
    ReviewConfigFileError,
    load_config,
    save_config,
)
from anylabeling.services.dense_review.models import (
    IncompatibleReviewState,
    ReviewConfig,
)
from anylabeling.services.dense_review.session import DenseReviewSession
from anylabeling.services.dense_review.storage import (
    annotation_state,
    image_fingerprint,
    load_payload,
)

from .conftest import make_config, make_shape


def make_session(shapes, config=None, payload=None, fingerprint="fp"):
    return DenseReviewSession.from_shapes(
        config or make_config(),
        shapes,
        fingerprint,
        100,
        100,
        payload,
    )


def test_payload_round_trip_keeps_valid_confirmations():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = make_session(shapes)
    session.confirm_batch("batch-0", ("category", "geometry"))
    session.ensure_coverage()
    for region in list(session.state.coverage.regions):
        session.complete_region(region.region_id)
    payload = session.to_payload()
    assert payload["version"] == 1

    restored = make_session(
        [make_shape("a", "A", (5, 5, 15, 15))],
        payload=payload,
    )
    assert restored.object("a").confirmed_both()
    counts = coverage_service.coverage_counts(restored.state.coverage)
    assert counts["completed"] == counts["total"]
    assert restored.completion_status().complete


def test_equivalent_rectangle_order_keeps_confirmation():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    config = make_config(rules=(("A", "visible", ""),))
    session = make_session(shapes, config)
    session.confirm_batch("batch-0", ("category", "geometry"))
    payload = session.to_payload()
    reordered = make_shape("a", "A", (5, 5, 15, 15))
    reordered.set_points_raw([(15, 15), (5, 15), (5, 5), (15, 5)])
    restored = make_session([reordered], config, payload)
    assert restored.object("a").confirmed_both()


def test_small_coordinate_change_invalidates_after_reload():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = make_session(shapes)
    session.confirm_batch("batch-0", ("category", "geometry"))
    payload = session.to_payload()
    moved = make_shape("a", "A", (5, 5, 15.01, 15))
    restored = make_session([moved], payload=payload)
    assert not restored.object("a").confirmed_both()


def test_image_change_clears_confirmations_and_coverage():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = make_session(shapes)
    session.confirm_batch("batch-0", ("category", "geometry"))
    session.ensure_coverage()
    for region in list(session.state.coverage.regions):
        session.complete_region(region.region_id)
    payload = session.to_payload()
    restored = make_session(
        [make_shape("a", "A", (5, 5, 15, 15))],
        payload=payload,
        fingerprint="different-image",
    )
    assert not restored.object("a").confirmed_both()
    assert restored.state.coverage is None
    assert not restored.completion_status().complete


def test_external_move_invalidates_old_and_new_regions_on_reload():
    shapes = [
        make_shape("a", "A", (5, 5, 15, 15)),
        make_shape("b", "B", (55, 5, 65, 15)),
    ]
    session = make_session(shapes)
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        session.complete_region(region.region_id)
    session.confirm_batch("batch-0", ("category", "geometry"))
    payload = session.to_payload()
    moved = [
        make_shape("a", "A", (85, 85, 95, 95)),
        make_shape("b", "B", (55, 5, 65, 15)),
    ]
    restored = make_session(moved, payload=payload)
    counts = coverage_service.coverage_counts(restored.state.coverage)
    assert counts["completed"] == 2
    assert counts["pending"] == 2
    assert not restored.object("a").confirmed_both()


def test_external_delete_invalidates_only_old_regions():
    shapes = [
        make_shape("a", "A", (5, 5, 15, 15)),
        make_shape("b", "B", (55, 5, 65, 15)),
    ]
    session = make_session(shapes)
    plan = session.ensure_coverage()
    for region in list(plan.regions):
        session.complete_region(region.region_id)
    session.confirm_batch("batch-0", ("category", "geometry"))
    payload = session.to_payload()
    restored = make_session(
        [make_shape("b", "B", (55, 5, 65, 15))], payload=payload
    )
    counts = coverage_service.coverage_counts(restored.state.coverage)
    assert counts["completed"] == 3
    assert restored.object("a") is None
    assert restored.object("b").confirmed_both()


def test_rule_change_on_reload_invalidates():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = make_session(shapes)
    session.confirm_batch("batch-0", ("category", "geometry"))
    payload = session.to_payload()
    changed_config = make_config(
        rules=(("A", "visible", "只标可见部分"),)
    )
    restored = make_session(shapes, changed_config, payload)
    assert not restored.object("a").confirmed_both()


def test_unknown_version_is_rejected():
    with pytest.raises(IncompatibleReviewState):
        make_session([], payload={"version": 2, "objects": {}})


def test_invalid_object_bounds_persist_as_unrenderable_pending():
    shape = make_shape("bad", "A", (5, 5, 15, 15))
    shape.points = []
    shape.bounds = (0.0, 0.0, 0.0, 0.0)
    session = make_session([shape])
    assert session.object("bad").load_failed is True
    payload = session.to_payload()
    restored = make_session([shape], payload=payload)
    assert restored.object("bad").load_failed is True
    assert not restored.completion_status().complete


def test_load_payload_rejects_non_mapping():
    with pytest.raises(IncompatibleReviewState):
        load_payload({"xanylabeling_dense_review": []})


def test_annotation_state_detects_external_edit(tmp_path):
    path = tmp_path / "image.json"
    path.write_text('{"checked": false}', encoding="utf-8")
    first = annotation_state(str(path))
    path.write_text('{"checked": true}', encoding="utf-8")
    os.utime(path, None)
    second = annotation_state(str(path))
    assert second.changed_from(first)
    assert not second.changed_from(second)


def test_config_round_trip_and_atomic_save(tmp_path):
    config = make_config(
        batches=(("A/B", ("A", "B")), ("C/D", ("C", "D"))),
        rules=(("A", "visible", "只标可见部分"),),
    )
    save_config(str(tmp_path), config)
    restored = load_config(str(tmp_path))
    assert restored.normalized() == config.normalized()
    assert (tmp_path / ".xanylabeling/dense_review/config.json").is_file()

    path = tmp_path / ".xanylabeling/dense_review/config.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ReviewConfigFileError):
        load_config(str(tmp_path))


def test_conflicting_config_is_not_saved(tmp_path):
    config = make_config(batches=(("A/B", ("A", "B")), ("A/C", ("A", "C"))))
    with pytest.raises(ReviewConfigFileError):
        save_config(str(tmp_path), config)
    assert not (tmp_path / ".xanylabeling/dense_review/config.json").exists()


def test_image_fingerprint_is_content_based():
    assert image_fingerprint(b"abc") == image_fingerprint(b"abc")
    assert image_fingerprint(b"abc") != image_fingerprint(b"abcd")


def test_payload_uses_versioned_namespace_and_preserves_other_data():
    shapes = [make_shape("a", "A", (5, 5, 15, 15))]
    session = make_session(shapes)
    other_data = {"description": "keep me", "custom": {"x": 1}}
    other_data["xanylabeling_dense_review"] = session.to_payload()
    encoded = json.dumps(other_data)
    restored = json.loads(encoded)
    assert restored["description"] == "keep me"
    assert restored["custom"] == {"x": 1}
    assert restored["xanylabeling_dense_review"]["version"] == 1
    assert isinstance(ReviewConfig.from_dict({}), ReviewConfig)

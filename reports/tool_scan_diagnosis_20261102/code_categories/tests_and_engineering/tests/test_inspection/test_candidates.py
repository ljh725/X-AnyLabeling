import json

import pytest

from anylabeling.services.inspection.candidates import (
    AcceptIntentStore,
    AlreadyAccepted,
    CandidateStore,
    load_candidates,
)
from anylabeling.services.inspection.manifest import build_manifest
from anylabeling.services.inspection.models import CandidateStatus


def _manifest(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": 100,
                "imageHeight": 80,
                "shapes": [],
            }
        ),
        encoding="utf-8",
    )
    return build_manifest(str(tmp_path))


def _candidate(**overrides):
    payload = {
        "relative_path": "a.jpg",
        "label": "person",
        "region": [1, 2, 11, 12],
        "image_width": 100,
        "image_height": 80,
        "source": "model-a",
        "source_version": "1",
        "score": 0.9,
    }
    payload.update(overrides)
    return payload


def test_candidate_import_validates_region_and_label(tmp_path):
    manifest = _manifest(tmp_path)
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            {
                "candidates": [
                    _candidate(),
                    _candidate(region=[0, 0, 200, 10]),
                    _candidate(label=""),
                ]
            }
        ),
        encoding="utf-8",
    )
    result = load_candidates(str(path), manifest=manifest)
    assert len(result.candidates) == 1
    assert len(result.errors) == 2
    assert result.candidates[0].candidate_id


def test_candidate_dimension_mismatch_is_rejected(tmp_path):
    manifest = _manifest(tmp_path)
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps({"candidates": [_candidate(image_width=50)]}),
        encoding="utf-8",
    )
    result = load_candidates(str(path), manifest=manifest)
    assert len(result.candidates) == 0
    assert result.errors


def test_duplicate_basenames_are_ambiguous(tmp_path):
    first = tmp_path / "left"
    second = tmp_path / "right"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        (directory / "a.jpg").write_bytes(b"fake")
        (directory / "a.json").write_text(
            json.dumps(
                {
                    "version": "4.2.1",
                    "imageWidth": 100,
                    "imageHeight": 80,
                    "shapes": [],
                }
            ),
            encoding="utf-8",
        )
    manifest = build_manifest(str(tmp_path))
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps({"candidates": [_candidate()]}),
        encoding="utf-8",
    )
    result = load_candidates(str(path), manifest=manifest)
    assert result.candidates
    assert result.ambiguous


def test_candidate_store_and_accept_intent(tmp_path):
    manifest = _manifest(tmp_path)
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps({"candidates": [_candidate()]}),
        encoding="utf-8",
    )
    result = load_candidates(str(path), manifest=manifest)
    candidate = result.candidates[0]
    store = CandidateStore(str(tmp_path))
    revision, records = store.load()
    assert revision == 0 and records == {}
    records[candidate.candidate_id] = candidate
    assert store.save(records, 0) == 1
    accepted = store.mark(
        candidate, CandidateStatus.ACCEPTED, accepted_shape_id="shape-1"
    )
    assert accepted.status is CandidateStatus.ACCEPTED
    assert accepted.accepted_shape_id == "shape-1"

    intents = AcceptIntentStore(str(tmp_path))
    created = intents.create(candidate.candidate_id, "a.jpg", "shape-1")
    assert created["status"] == "pending"
    assert intents.create(candidate.candidate_id, "a.jpg", "shape-1") == created
    confirmed = intents.confirm(candidate.candidate_id)
    assert confirmed["status"] == "confirmed"
    with pytest.raises(AlreadyAccepted):
        intents.create(candidate.candidate_id, "a.jpg", "shape-2")

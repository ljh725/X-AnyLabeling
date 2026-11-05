"""Validate the synthetic dense-review sample set.

The scenes are regenerated from ``scripts/generate_dense_review_samples.py``
into a temporary directory, then compared with the checked-in fixture
description in ``samples/dense_review/manifest.json``.  Counts, classes and
stable object identifiers are checked there, and every label file is loaded
through the project loader to prove it needs no identity repair.

Byte equality with the committed PNGs is deliberately not asserted: only the
deterministic generator output is compared, which keeps the test stable across
Pillow versions and platforms.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_dense_review_samples.py"
SAMPLES_DIR = REPO_ROOT / "samples" / "dense_review"
APP_LOGGER_NAME = "X-AnyLabeling"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "dense_review_sample_generator", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator():
    return _load_generator()


@pytest.fixture(scope="module")
def regenerated(generator, tmp_path_factory):
    output = tmp_path_factory.mktemp("dense_review_samples")
    manifest = generator.generate(output)
    return output, manifest


@pytest.fixture(scope="module")
def manifest():
    path = SAMPLES_DIR / "manifest.json"
    assert path.is_file(), f"missing checked-in manifest: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


class _LogCollector(logging.Handler):
    """Collect messages emitted by the application logger."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _read_label_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_matches_regenerated_scenes(manifest, regenerated):
    """The checked-in manifest must describe what the generator produces."""
    _output, generated_manifest = regenerated
    assert generated_manifest == manifest
    assert manifest["scenes"], "manifest lists no scenes"
    assert [scene["key"] for scene in manifest["scenes"]] == [
        "dense_30_six_classes",
        "all_correct_12",
        "small_and_occluded",
        "clipped_arm",
        "misclassified_third_batch",
        "empty",
        "mixed_shapes",
    ]


def test_generated_scene_counts_classes_and_ids(manifest, regenerated):
    """Object counts, class distribution and stable IDs match the manifest."""
    output, _manifest = regenerated
    for scene in manifest["scenes"]:
        label_path = output / scene["label"]
        image_path = output / scene["image"]
        assert label_path.is_file(), label_path
        assert image_path.is_file(), image_path

        with Image.open(image_path) as image:
            assert image.size == (scene["image_width"], scene["image_height"])

        payload = _read_label_json(label_path)
        assert payload["imageWidth"] == scene["image_width"]
        assert payload["imageHeight"] == scene["image_height"]
        assert payload["imagePath"] == scene["image"]
        assert payload["imageData"] is None
        shapes = payload["shapes"]
        assert len(shapes) == scene["object_count"]

        identifiers = [shape["xanylabeling_shape_id"] for shape in shapes]
        assert identifiers == [item["id"] for item in scene["objects"]]
        assert len(identifiers) == len(set(identifiers)), "duplicate IDs"
        for identifier in identifiers:
            assert re.fullmatch(r"[a-z0-9]+-\d{3}", identifier), identifier

        assert dict(Counter(shape["label"] for shape in shapes)) == (
            scene["class_distribution"]
        )
        assert dict(Counter(shape["shape_type"] for shape in shapes)) == (
            scene["shape_type_distribution"]
        )
        for shape, item in zip(shapes, scene["objects"]):
            assert shape["label"] == item["label"]
            assert shape["shape_type"] == item["shape_type"]
            points = shape["points"]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            assert [
                min(xs),
                min(ys),
                max(xs),
                max(ys),
            ] == pytest.approx(item["bbox"])


def test_label_files_load_without_identity_repair(manifest, regenerated):
    """Every generated label file loads through the project loader cleanly."""
    from anylabeling.views.labeling.label_file import LabelFile
    from anylabeling.views.labeling.shape_identity import (
        validate_shape_identities,
    )

    output, _manifest = regenerated
    collector = _LogCollector()
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.addHandler(collector)
    try:
        for scene in manifest["scenes"]:
            payload = _read_label_json(output / scene["label"])
            serialized_ids = [
                shape["xanylabeling_shape_id"] for shape in payload["shapes"]
            ]
            assert validate_shape_identities(serialized_ids) == ()

            label_file = LabelFile(str(output / scene["label"]))
            assert len(label_file.shapes) == scene["object_count"]
            assert [
                shape.xanylabeling_shape_id for shape in label_file.shapes
            ] == serialized_ids
            assert [shape.label for shape in label_file.shapes] == [
                item["label"] for item in scene["objects"]
            ]
    finally:
        app_logger.removeHandler(collector)

    problems = "; ".join(collector.messages)
    assert not problems, f"label loading emitted warnings: {problems}"


def test_checked_in_label_files_load(manifest):
    """The committed fixtures load and agree with the checked-in manifest."""
    from anylabeling.views.labeling.label_file import LabelFile

    for scene in manifest["scenes"]:
        label_path = SAMPLES_DIR / scene["label"]
        assert label_path.is_file(), label_path
        assert (SAMPLES_DIR / scene["image"]).is_file()
        label_file = LabelFile(str(label_path))
        loaded_ids = [
            shape.xanylabeling_shape_id for shape in label_file.shapes
        ]
        assert loaded_ids == [item["id"] for item in scene["objects"]]


def test_generation_is_deterministic(generator, regenerated):
    """A second render produces byte-identical files for every artefact."""
    output, _manifest = regenerated
    files = generator.render_samples()
    written = {path.name for path in output.iterdir() if path.is_file()}
    assert written == set(files)
    for name, payload in files.items():
        assert (output / name).read_bytes() == payload, name


def test_generate_requires_force_to_overwrite(generator, regenerated):
    """Existing samples are never overwritten without an explicit flag."""
    output, _manifest = regenerated
    with pytest.raises(generator.SampleOutputError):
        generator.generate(output)
    generator.generate(output, force=True)


def test_manifest_matches_review_ledger(manifest, regenerated):
    """Documented batches and supported shapes match the review ledger."""
    from anylabeling.services.dense_review.models import (
        BatchDefinition,
        ReviewConfig,
    )
    from anylabeling.services.dense_review.session import DenseReviewSession
    from anylabeling.views.labeling.label_file import LabelFile

    output, _manifest = regenerated
    for scene in manifest["scenes"]:
        config = ReviewConfig(
            batches=tuple(
                BatchDefinition(
                    name=batch["name"], labels=tuple(batch["labels"])
                )
                for batch in scene["batches"]
            )
        )
        assert config.validate() == ()
        label_file = LabelFile(str(output / scene["label"]))
        session = DenseReviewSession.from_shapes(
            config,
            label_file.shapes,
            "sample-fingerprint",
            scene["image_width"],
            scene["image_height"],
        )
        batches = session.state.batches
        actual_batches = [
            (batch.name, len(batch.member_ids)) for batch in batches
        ]
        expected_batches = [
            (batch["name"], batch["member_count"])
            for batch in scene["batches"]
        ]
        assert actual_batches[: len(expected_batches)] == expected_batches
        other = [batch for batch in batches if batch.batch_id == "__other__"]
        other_count = len(other[0].member_ids) if other else 0
        assert other_count == scene["other_pending_count"]
        completion = session.completion_status()
        if scene["expected"]["outcome"] == "partial":
            assert completion.supported is False
            assert completion.complete is False
        else:
            assert completion.supported is True


def test_label_version_tracks_application(manifest):
    """The serialized label version stays aligned with the application."""
    source = (REPO_ROOT / "anylabeling" / "app_info.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^__version__ = "([^"]+)"', source, re.MULTILINE)
    assert match is not None
    assert manifest["label_format_version"] == match.group(1)
    for scene in manifest["scenes"]:
        payload = _read_label_json(SAMPLES_DIR / scene["label"])
        assert payload["version"] == manifest["label_format_version"]

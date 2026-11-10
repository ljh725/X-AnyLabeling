"""Per-image statistics hook for batch pre-labelling (task 4.3).

``batch.save_auto_labeling_result`` is the only place a batch prediction is
written, and it is shared by both batch drivers (the UI-thread loop in
``process_next_image`` and the worker ``BatchProcessingThread``).  These tests
pin that boundary without Qt widgets, a real model, or a real controller:

* one notification per image, after the atomic write succeeded;
* ``applied`` carries the image, the label file, the provenance and the exact
  shapes that were saved;
* a failed write and a missing prediction are reported as ``failed`` /
  ``skipped`` and never as applied;
* a partly failed batch does not become an all-success statement;
* statistics must never start timing, finish a round, or break annotation
  saving when the observer is absent or raises.
"""

from __future__ import annotations

import json

import pytest

from anylabeling.views.labeling.utils import batch


class RecordingSignal:
    """Minimal stand-in for a pyqtSignal used by the legacy manager path."""

    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class FakeManager:
    """Model manager surface that ``save_auto_labeling_result`` touches."""

    collect_prediction_provenance = False

    def __init__(self):
        self.prediction_unapplied = RecordingSignal()
        self.batch_prediction_saved = RecordingSignal()


class FakeAutoLabelingWidget:
    def __init__(self):
        self.model_manager = FakeManager()


class FakeController:
    """Records the batch entry point and fails on any per-session call."""

    language = "en_US"

    def __init__(self, *, raise_on_call=False):
        self.calls = []
        self.degraded = []
        self.raise_on_call = raise_on_call

    def prediction_saved(self, image_path, label_path, provenance=None,
                         shapes=None, status="applied"):
        if self.raise_on_call:
            raise RuntimeError("statistics store is closed")
        self.calls.append({
            "image_path": image_path,
            "label_path": label_path,
            "provenance": provenance,
            "shapes": shapes,
            "status": status,
        })
        return True

    def degrade(self, operation, error=None):
        self.degraded.append((operation, str(error)))

    # Any of these would mean the batch hooked into the live round instead of
    # the path-scoped entry point; ``notify_metrics`` turns the AttributeError
    # into ``degrade``, which the tests also assert is empty.
    finish_round = None
    tick = None
    pause = None
    prediction_applied = None
    prediction_unapplied = None


class FakeHost:
    def __init__(self, controller=None, output_dir=""):
        self.correction_metrics = controller
        self.auto_labeling_widget = FakeAutoLabelingWidget()
        self.output_dir = output_dir
        self._config = {"store_data": False}
        self._batch_failed_count = 0


class FakeShape:
    def __init__(self, shape_id, label="cat", points=None):
        self.shape_id = shape_id
        self.label = label
        self.points = points or [[0, 0], [10, 0], [10, 10], [0, 10]]

    def to_dict(self):
        return {
            "label": self.label,
            "points": [list(point) for point in self.points],
            "group_id": None,
            "description": "",
            "difficult": False,
            "shape_type": "rectangle",
            "flags": {},
            "attributes": {},
            "kie_linking": [],
            "score": None,
            "locked": False,
            "xanylabeling_shape_id": self.shape_id,
        }


class FakeResult:
    def __init__(self, shapes, provenance=None, description="", replace=True):
        self.shapes = list(shapes)
        self.provenance = provenance or {}
        self.description = description
        self.tags = None
        self.flags = None
        self.replace = replace


PROVENANCE = {
    "model": "yolov8n",
    "model_version": "8.0",
    "mode": "replacement",
    "run_id": "run-batch-1",
}


def _write_image(tmp_path, index):
    image = tmp_path / ("img-%02d.png" % index)
    image.write_bytes(b"")
    return str(image)


def _label_path(tmp_path, index, output_dir=""):
    name = "img-%02d.json" % index
    if output_dir:
        return str(output_dir / name)
    return str(tmp_path / name)


def _prepare(tmp_path, index, output_dir=""):
    """Create the image plus an existing label file so no PIL decode happens."""
    image = _write_image(tmp_path, index)
    label = _label_path(tmp_path, index, output_dir)
    with open(label, "w", encoding="utf-8") as stream:
        json.dump({"shapes": [], "description": ""}, stream)
    return image, label


def _result(index, provenance=None):
    return FakeResult(
        [FakeShape("shape-%02d" % index)],
        provenance=dict(provenance if provenance is not None else PROVENANCE),
    )


def test_three_saved_images_notify_once_each_with_paths_and_provenance(tmp_path):
    controller = FakeController()
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    host = FakeHost(controller, output_dir=str(labels_dir))
    prepared = [_prepare(tmp_path, index, labels_dir) for index in range(3)]

    for index, (image, _label) in enumerate(prepared):
        assert batch.save_auto_labeling_result(host, image, _result(index)) is True

    assert len(controller.calls) == 3
    assert controller.degraded == []
    for index, (image, label) in enumerate(prepared):
        call = controller.calls[index]
        assert call["image_path"] == image
        assert call["label_path"] == label
        assert call["status"] == "applied"
        assert call["provenance"] == PROVENANCE
        assert call["shapes"] == [FakeShape("shape-%02d" % index).to_dict()]
        with open(label, encoding="utf-8") as stream:
            assert json.load(stream)["shapes"] == call["shapes"]

    # the batch hook never starts timing or finishes anything by itself
    assert controller.degraded == []


def test_failed_write_yields_one_failed_notification_and_no_applied_one(tmp_path):
    controller = FakeController()
    host = FakeHost(controller)
    prepared = [_prepare(tmp_path, index) for index in range(2)]
    original = batch.atomic_write_json

    def failing_write(path, data):
        if path.endswith("img-01.json"):
            raise OSError("disk full")
        return original(path, data)

    batch.atomic_write_json = failing_write
    try:
        assert batch.save_auto_labeling_result(
            host, prepared[0][0], _result(0)
        ) is True
        assert batch.save_auto_labeling_result(
            host, prepared[1][0], _result(1)
        ) is False
    finally:
        batch.atomic_write_json = original

    assert controller.degraded == []
    assert [call["status"] for call in controller.calls] == ["applied", "failed"]
    failed = controller.calls[1]
    assert failed["image_path"] == prepared[1][0]
    assert failed["label_path"] == prepared[1][1]
    assert failed["provenance"] == PROVENANCE
    assert failed["shapes"] in ((), [], None)
    assert host._batch_failed_count == 0  # the caller owns the batch counter


def test_missing_prediction_is_skipped_not_applied(tmp_path):
    controller = FakeController()
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    host = FakeHost(controller, output_dir=str(labels_dir))
    image, label = _prepare(tmp_path, 0, labels_dir)

    assert batch.save_auto_labeling_result(host, image, None) is False
    assert controller.degraded == []
    assert len(controller.calls) == 1
    call = controller.calls[0]
    assert call["status"] == "skipped"
    assert call["image_path"] == image
    assert call["label_path"] == label
    assert call["shapes"] in ((), [], None)


def test_partial_failure_never_claims_the_whole_batch_succeeded(tmp_path):
    controller = FakeController()
    host = FakeHost(controller)
    prepared = [_prepare(tmp_path, index) for index in range(3)]
    original = batch.atomic_write_json

    def failing_write(path, data):
        if path.endswith("img-01.json"):
            raise OSError("permission denied")
        return original(path, data)

    batch.atomic_write_json = failing_write
    outcomes = []
    try:
        for index, (image, _label) in enumerate(prepared):
            outcomes.append(
                batch.save_auto_labeling_result(host, image, _result(index))
            )
    finally:
        batch.atomic_write_json = original

    assert outcomes == [True, False, True]
    statuses = [call["status"] for call in controller.calls]
    assert statuses == ["applied", "failed", "applied"]
    assert statuses.count("applied") == 2
    assert "completed" not in statuses and "finished" not in statuses
    assert controller.degraded == []


def test_absent_or_broken_controller_never_breaks_annotation_saving(tmp_path):
    absent = FakeHost(None)
    image, _label = _prepare(tmp_path, 0)
    assert batch.save_auto_labeling_result(absent, image, _result(0)) is True

    broken = FakeHost(FakeController(raise_on_call=True))
    image, _label = _prepare(tmp_path, 1)
    assert batch.save_auto_labeling_result(broken, image, _result(1)) is True
    assert broken.correction_metrics.degraded
    assert broken.correction_metrics.degraded[0][0] == "prediction_saved"

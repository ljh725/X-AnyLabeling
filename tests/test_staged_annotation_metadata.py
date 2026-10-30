import json
import threading
from pathlib import Path

import pytest

from anylabeling.views.labeling.utils.staged_annotation_loading import (
    annotation_path,
    read_annotation_metadata,
)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, "unchecked"),
        ({"checked": False}, "unchecked"),
        ({"checked": True}, "passed"),
        ({"checked": "failed"}, "failed"),
        ({"shapes": [{"checked": True}]}, "unchecked"),
        ({"shapes": [], "checked": True}, "passed"),
        ({"shapes": [{"label": "person"}, {"label": "car"}]}, "unchecked"),
        ({"padding": "x" * 8190, "checked": "failed"}, "failed"),
    ],
)
def test_review_is_taken_from_top_level(tmp_path, data, expected):
    path = tmp_path / "a.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = read_annotation_metadata(path)
    assert (result.presence, result.review) == ("present", expected)


def test_missing_and_invalid_files_are_distinct(tmp_path):
    path = tmp_path / "a.json"
    assert read_annotation_metadata(path).presence == "missing"
    path.write_text('{"checked": true,', encoding="utf-8")
    result = read_annotation_metadata(path)
    assert (result.presence, result.review) == ("error", "error")
    assert result.error


def test_output_directory_path(tmp_path):
    image = str(tmp_path / "images" / "a.jpg")
    output = str(tmp_path / "labels")
    assert annotation_path(image, output) == str(tmp_path / "labels" / "a.json")
    assert annotation_path(image, None) == str(tmp_path / "images" / "a.json")


def test_worker_emits_context_and_completes(tmp_path):
    from anylabeling.views.labeling.utils.staged_annotation_loading import MetadataWorker

    paths = [str(tmp_path / f"{i}.jpg") for i in range(3)]
    (tmp_path / "1.json").write_text('{"checked": true}', encoding="utf-8")
    worker = MetadataWorker(paths, None, 7, {paths[1]: 4}, batch_size=2)
    worker.start()
    first = worker.results.get(timeout=3)
    second = worker.results.get(timeout=3)
    assert worker.results.get(timeout=3) is None
    worker.thread.join(timeout=3)
    assert not worker.thread.is_alive()
    assert [record[1] for record in first + second] == paths
    assert first[1][0:3] == (7, paths[1], 4)
    assert first[1][3].review == "passed"


def test_worker_continues_after_corrupt_file(tmp_path):
    from anylabeling.views.labeling.utils.staged_annotation_loading import MetadataWorker

    paths = [str(tmp_path / f"{i}.jpg") for i in range(3)]
    (tmp_path / "1.json").write_text("{", encoding="utf-8")
    (tmp_path / "2.json").write_text('{"checked": "failed", "shapes": []}', encoding="utf-8")
    worker = MetadataWorker(paths, None, 1, {}, batch_size=10)
    worker.start()
    records = worker.results.get(timeout=3)
    assert [record[3].presence for record in records] == ["missing", "error", "present"]
    assert records[2][3].review == "failed"
    assert worker.results.get(timeout=3) is None
    worker.thread.join(timeout=3)


def test_worker_can_cancel_when_queue_is_full(tmp_path):
    from anylabeling.views.labeling.utils.staged_annotation_loading import MetadataWorker

    paths = [str(tmp_path / f"{i}.jpg") for i in range(20)]
    worker = MetadataWorker(paths, None, 1, {}, batch_size=1)
    worker.start()
    # Wait until the producer is back-pressured, then cancel without draining.
    for _ in range(4):
        assert worker.results.get(timeout=3)
    worker.cancel()
    worker.thread.join(timeout=3)
    assert not worker.thread.is_alive()


def test_priority_candidate_is_read_before_remaining_paths(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import staged_annotation_loading as module

    paths = [str(tmp_path / f"{i}.jpg") for i in range(5)]
    entered, release = threading.Event(), threading.Event()
    original = module.read_annotation_metadata

    def slow_first(path):
        if path.endswith("0.json"):
            entered.set()
            assert release.wait(3)
        return original(path)

    monkeypatch.setattr(module, "read_annotation_metadata", slow_first)
    worker = module.MetadataWorker(paths, None, 1, {}, batch_size=1)
    worker.start()
    assert entered.wait(3)
    worker.prioritize(paths[4])
    release.set()
    assert worker.results.get(timeout=3)[0][1] == paths[0]
    assert worker.results.get(timeout=3)[0][1] == paths[4]
    worker.cancel()
    worker.thread.join(timeout=3)
    assert not worker.thread.is_alive()


def test_permission_error_is_not_missing(tmp_path, monkeypatch):
    import builtins

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(builtins, "open", denied)
    result = read_annotation_metadata(tmp_path / "a.json")
    assert (result.presence, result.review) == ("error", "error")


def test_controller_coalesces_and_discards_old_results(tmp_path, monkeypatch):
    import time
    from anylabeling.views.labeling.utils import staged_annotation_loading as module

    entered, release = threading.Event(), threading.Event()
    original = module.read_annotation_metadata

    def block(path):
        if path.endswith("old.json"):
            entered.set()
            assert release.wait(3)
        return original(path)

    monkeypatch.setattr(module, "read_annotation_metadata", block)
    controller = module.MetadataController()
    old = str(tmp_path / "old.jpg")
    latest = str(tmp_path / "latest.jpg")
    controller.request([old], None, {})
    assert entered.wait(3)
    controller.request([str(tmp_path / "middle.jpg")], None, {})
    generation = controller.request([latest], None, {})
    release.set()
    records = []
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        records.extend(controller.poll())
        if not controller.is_running():
            records.extend(controller.poll())
            break
        time.sleep(0.005)
    assert [(r[0], r[1]) for r in records] == [(generation, latest)]


def test_view_worker_sorts_and_filters_in_background(tmp_path):
    from anylabeling.views.labeling.utils.staged_annotation_loading import ViewWorker

    for name in ("image10.png", "image2.png", "image1.png"):
        (tmp_path / name).touch()
    worker = ViewWorker(3, directory=str(tmp_path), extensions=(".png",), pattern="#2")
    worker.start()
    messages = [worker.results.get(timeout=3) for _ in range(3)]
    worker.thread.join(timeout=3)
    assert [Path(p).name for p in messages[0][2]] == ["image1.png", "image2.png", "image10.png"]
    assert [Path(p).name for p in messages[1][2]] == ["image2.png"]
    assert messages[2] == (3, "done", 0)


def test_view_worker_reports_corrupt_attribute_data(tmp_path):
    from anylabeling.views.labeling.utils.staged_annotation_loading import ViewWorker

    path = str(tmp_path / "a.png")
    (tmp_path / "a.json").write_text("{", encoding="utf-8")
    worker = ViewWorker(1, paths=[path], pattern="label::person")
    worker.start()
    assert worker.results.get(timeout=3) == (1, "done", 1)
    worker.thread.join(timeout=3)


def test_metadata_controller_retries_in_same_generation(tmp_path):
    import time
    from anylabeling.views.labeling.utils.staged_annotation_loading import MetadataController

    image = str(tmp_path / "a.png")
    label = tmp_path / "a.json"
    label.write_text("{", encoding="utf-8")
    controller = MetadataController()
    generation = controller.request([image], None, {})

    def collect():
        records = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            records.extend(controller.poll())
            if not controller.is_running():
                records.extend(controller.poll())
                return records
            time.sleep(0.005)
        raise AssertionError("worker did not finish")

    assert collect()[0][3].review == "error"
    label.write_text('{"checked": true}', encoding="utf-8")
    controller.retry(image, None, 2)
    result = collect()[0]
    assert result[:3] == (generation, image, 2)
    assert result[3].review == "passed"

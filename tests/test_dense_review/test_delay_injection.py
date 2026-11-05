"""Delay-injection tests for dense-review asynchronous work.

No test sleeps waiting for a background task.  Card crops are completed by
a fake executor that records the provider's done callback, so a "late"
result is delivered exactly when the test asks for it.  Background
annotation scans are completed by pushing batches into the controller's
worker queue, which exercises the same generation filter used by the real
thread.
"""

import copy
import json
import os
import queue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.dense_review.thumbnails import (
    ThumbnailProvider,
)
from anylabeling.views.labeling.settings.schema import (
    load_template_config,
)
from anylabeling.views.labeling.utils.staged_annotation_loading import (
    AnnotationMetadata,
    MetadataController,
)
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        []
    )
    application.setQuitOnLastWindowClosed(False)
    return application


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    config = copy.deepcopy(load_template_config())
    config.update(auto_save=False)
    session_target = os.path.abspath(
        os.path.join(".tmp", f"dense-review-config-{os.getpid()}-{id(tmp_path)}.yaml")
    )
    user_config.begin_session(
        target_path=session_target,
        origin="file",
        template=copy.deepcopy(config),
        effective=copy.deepcopy(config),
        ensure_created=True,
        normalizer=normalize_user_config,
    )
    window = MainWindow(app, config=config)
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    yield window
    view = window.labeling_widget.view
    workspace = getattr(view, "dense_review_workspace", None)
    if workspace is not None:
        workspace.close()
        workspace.shutdown()
    view.dirty = False
    window.close()
    app.removeEventFilter(view)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _prepare_image(tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 200), color=(220, 220, 220)).save(image_path)
    annotation = {
        "version": "4.2.1",
        "imageWidth": 200,
        "imageHeight": 200,
        "imagePath": "image.png",
        "imageData": None,
        "shapes": [
            {
                "label": "A",
                "shape_type": "rectangle",
                "points": [[10, 10], [50, 10], [50, 50], [10, 50]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "B",
                "shape_type": "rectangle",
                "points": [[70, 10], [110, 10], [110, 50], [70, 50]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    }
    (tmp_path / "image.json").write_text(
        json.dumps(annotation), encoding="utf-8"
    )
    return str(image_path)


def _png_bytes(color="red"):
    image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor(color))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class _FakeFuture:
    """Future whose completion the test controls."""

    def __init__(self):
        self._callbacks = []
        self._result = None
        self._exception = None

    def add_done_callback(self, callback):
        self._callbacks.append(callback)

    def result(self):
        if self._exception is not None:
            raise self._exception
        return self._result

    def finish(self, result):
        self._result = result
        for callback in list(self._callbacks):
            callback(self)

    def fail(self, error):
        self._exception = error
        for callback in list(self._callbacks):
            callback(self)


class _FakeExecutor:
    """Record submitted crops instead of running them on a thread."""

    def __init__(self):
        self.requests = []
        self.futures = []
        self.shutdown_calls = []

    def submit(self, _function, request):
        self.requests.append(request)
        future = _FakeFuture()
        self.futures.append(future)
        return future

    def shutdown(self, wait=False, cancel_futures=False):
        self.shutdown_calls.append((wait, cancel_futures))


def _provider_with_fake_worker():
    provider = ThumbnailProvider()
    executor = _FakeExecutor()
    provider._executor = executor
    return provider, executor


def test_fast_image_switch_drops_late_card_result(app):
    provider, executor = _provider_with_fake_worker()
    ready = []
    failed = []
    provider.ready.connect(
        lambda shape_id, image: ready.append((shape_id, image))
    )
    provider.failed.connect(lambda shape_id, reason: failed.append(shape_id))
    provider.start_generation(1)
    assert (
        provider.request("id1", (0, 0, 10, 10), 0.35, (120, 80), "", None)
        is None
    )
    old_request = executor.requests[0]
    assert old_request.generation == provider.generation
    assert "id1" in provider._pending

    # The user switches images while the card crop is still in flight.
    provider.start_generation(2)
    assert provider.generation == 2
    executor.futures[0].finish(
        ("id1", old_request.generation, _png_bytes("red"))
    )
    provider._drain()

    assert ready == []
    assert failed == []
    assert provider.cached_latest("id1") is None
    assert not provider._cache
    assert "id1" not in provider._pending

    # A request from the new generation still completes normally.
    assert (
        provider.request("id1", (0, 0, 10, 10), 0.35, (120, 80), "", None)
        is None
    )
    new_request = executor.requests[1]
    executor.futures[1].finish(
        ("id1", new_request.generation, _png_bytes("blue"))
    )
    provider._drain()
    assert [shape_id for shape_id, _image in ready] == ["id1"]
    cached = provider.cached_image("id1", (0, 0, 10, 10), 0.35, (120, 80))
    assert cached is not None
    assert cached.pixelColor(0, 0).name() == "#0000ff"
    provider.shutdown()
    assert executor.shutdown_calls


def test_fast_output_directory_switch_drops_late_result(app):
    provider, executor = _provider_with_fake_worker()
    ready = []
    provider.ready.connect(lambda shape_id, image: ready.append(shape_id))
    provider.start_generation(1)
    provider.request(
        "id1",
        (0, 0, 10, 10),
        0.35,
        (120, 80),
        "/old/image.png",
        None,
        "old-source",
    )
    old_request = executor.requests[0]
    provider.start_generation(2)
    provider.request(
        "id1",
        (40, 40, 50, 50),
        0.35,
        (120, 80),
        "/new/image.png",
        None,
        "new-source",
    )
    new_request = executor.requests[1]
    executor.futures[0].finish(
        ("id1", old_request.generation, _png_bytes("red"))
    )
    provider._drain()
    assert ready == []
    assert not provider._cache
    expected_key = provider.request_key(
        "id1", 2, (40, 40, 50, 50), 0.35, (120, 80), "new-source"
    )
    assert provider._latest_requests["id1"] == expected_key

    executor.futures[1].finish(
        ("id1", new_request.generation, _png_bytes("green"))
    )
    provider._drain()
    assert ready == ["id1"]
    assert (
        provider.cached_image(
            "id1",
            (40, 40, 50, 50),
            0.35,
            (120, 80),
            "new-source",
        )
        is not None
    )
    provider.shutdown()


def test_late_old_bounds_result_is_dropped(app):
    provider, executor = _provider_with_fake_worker()
    ready = []
    provider.ready.connect(lambda shape_id, image: ready.append(shape_id))
    provider.start_generation(3)
    provider.request("id1", (0, 0, 10, 10), 0.35, (120, 80), "", None)
    assert len(executor.requests) == 1
    provider.request("id1", (20, 20, 30, 30), 0.35, (120, 80), "", None)
    assert len(executor.requests) == 2

    executor.futures[0].finish(
        ("id1", executor.requests[0].generation, _png_bytes("red"))
    )
    provider._drain()
    assert ready == []
    assert not provider._cache
    assert "id1" in provider._pending
    assert provider.failed_shape_ids() == set()

    executor.futures[1].finish(
        ("id1", executor.requests[1].generation, _png_bytes("green"))
    )
    provider._drain()
    assert ready == ["id1"]
    assert (
        provider.cached_image("id1", (0, 0, 10, 10), 0.35, (120, 80)) is None
    )
    assert (
        provider.cached_image("id1", (20, 20, 30, 30), 0.35, (120, 80))
        is not None
    )
    provider.shutdown()


def test_late_failure_does_not_mark_new_card_failed(app):
    provider, executor = _provider_with_fake_worker()
    failed = []
    provider.failed.connect(lambda shape_id, reason: failed.append(shape_id))
    provider.start_generation(1)
    provider.request("id1", (0, 0, 10, 10), 0.35, (120, 80), "", None)
    provider.start_generation(2)
    executor.futures[0].fail(RuntimeError("late crop failure"))
    provider._drain()
    assert failed == []
    assert provider.failed_shape_ids() == set()
    assert not provider._cache
    provider.shutdown()


class _FakeThread:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive


class _FakeMetadataWorker:
    def __init__(self, generation):
        self.generation = generation
        self.thread = _FakeThread()
        self.results = queue.Queue()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def prioritize(self, path):
        pass


def test_stale_scan_backfill_is_dropped_after_switch():
    controller = MetadataController()
    worker = _FakeMetadataWorker(1)
    controller.worker = worker
    controller.generation = 1
    worker.results.put(
        [(1, "/old/image.png", 0, AnnotationMetadata("present", "passed"))]
    )

    # The user switches the output directory / image set while the scan
    # of the previous directory is still in flight.
    controller.request(["/new/image.png"], "/new", {"/new/image.png": 0})
    assert controller.generation == 2
    assert worker.cancelled is True
    assert controller.pending is not None

    assert controller.poll() == []
    assert worker.results.empty()
    assert controller.generation == 2

    controller.worker = None
    controller.pending = None
    assert controller.is_running() is False


def test_delayed_results_never_pollute_window_state(
    window, tmp_path, monkeypatch
):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view

    # A scan ticket from a previous directory arrives after the user
    # already moved on to a new generation.
    widget._metadata_timer.stop()
    widget._metadata_controller = MetadataController()
    widget._metadata_generation = 7
    widget._metadata_results.clear()
    scan_path = str(tmp_path / "late.png")
    scan_item = QtWidgets.QListWidgetItem(scan_path)
    scan_item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, 7)
    scan_item.setData(QtCore.Qt.ItemDataRole.UserRole + 2, "ready")
    widget.file_list_widget.addItem(scan_item)
    widget.fn_to_index[scan_path] = widget.file_list_widget.count() - 1
    processed = widget._metadata_processed
    widget._metadata_results.append(
        (6, scan_path, 0, AnnotationMetadata("present", "failed"))
    )
    widget._poll_metadata()
    assert widget._metadata_processed == processed
    assert scan_item.data(QtCore.Qt.ItemDataRole.UserRole + 1) == 7
    assert scan_item.data(QtCore.Qt.ItemDataRole.UserRole + 2) == "ready"

    # The current generation still updates the same row.
    widget._metadata_results.append(
        (7, scan_path, 0, AnnotationMetadata("present", "failed"))
    )
    widget._poll_metadata()
    assert widget._metadata_processed == processed + 1
    assert scan_item.data(QtCore.Qt.ItemDataRole.UserRole + 2) == "failed"

    # A card crop is in flight while the workspace refreshes its cards.
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    session = widget.dense_review_session
    provider = workspace.thumbnails
    provider._executor.shutdown(wait=False, cancel_futures=True)
    executor = _FakeExecutor()
    provider._executor = executor
    provider.start_generation(provider.generation + 1)
    provider._drain()

    shape_id = session.state.current_object
    shape = session.object(shape_id)
    provider.request(shape_id, shape.bounds, 0.35, (360, 240), "", None)
    assert len(executor.requests) == 1
    stale = executor.requests[0]
    ready = []
    provider.ready.connect(lambda card_id, image: ready.append(card_id))
    workspace._refresh_from_host()
    assert provider.generation > stale.generation
    current = session.state.current_object
    selected = workspace._selected_shape_ids()

    executor.futures[0].finish(
        (stale.shape_id, stale.generation, _png_bytes())
    )
    provider._drain()
    assert ready == []
    assert not provider._cache
    assert workspace._failed_ids == set()
    assert session.state.current_object == current
    assert workspace._selected_shape_ids() == selected

    # A second card crop is left in flight while the workspace closes.
    provider.request(shape_id, shape.bounds, 0.35, (360, 240), "", None)
    pending_request = executor.requests[-1]
    pending = executor.futures[-1]
    workspace.close()
    app.processEvents()
    assert workspace.isVisible() is False
    workspace.shutdown()
    assert workspace.thumbnails._timer.isActive() is False
    assert executor.shutdown_calls

    # The worker finishes after the window is gone; no Qt exception and no
    # failure state leaks into the next session.
    pending.finish((shape_id, pending_request.generation, _png_bytes()))
    provider._drain()
    assert session.state.current_object == shape_id
    assert workspace._failed_ids == set()

    # Reopening and then cancelling the output-directory dialog keeps the
    # in-memory progress and the thumbnail generation unchanged.
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    workspace._complete_batch()
    app.processEvents()
    assert session.object("id1").confirmed_both()
    output_dir = widget.output_dir
    generation = workspace.thumbnails.generation
    round_generation = widget._dense_review_round_generation
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: ""),
    )
    widget.change_output_dir_dialog()
    app.processEvents()
    assert widget.output_dir == output_dir
    assert widget.dense_review_session is session
    assert session.object("id1").confirmed_both()
    assert workspace.thumbnails.generation == generation
    assert widget._dense_review_round_generation == round_generation
    workspace.refresh_all()
    app.processEvents()

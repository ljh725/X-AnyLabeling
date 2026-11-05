import io

import pytest
from PIL import Image
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.dense_review.thumbnails import (
    ThumbnailProvider,
    ThumbnailRequest,
    crop_thumbnail,
)


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        []
    )
    application.setQuitOnLastWindowClosed(False)
    yield application


def _png_bytes():
    image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("red"))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def _request(image_path, bounds, margin=0.5, size=(120, 80)):
    return ThumbnailRequest(
        shape_id="id1",
        generation=1,
        bounds=bounds,
        margin_ratio=margin,
        target_size=size,
        image_path=str(image_path),
        image_bytes=None,
    )


def test_crop_thumbnail_clamps_to_image_edges(tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (100, 80), color=(10, 20, 30)).save(path)
    shape_id, generation, data = crop_thumbnail(
        _request(path, (-10, -10, 20, 20))
    )
    assert shape_id == "id1"
    assert generation == 1
    with Image.open(io.BytesIO(data)) as image:
        assert image.width <= 120
        assert image.height <= 80
        assert image.width > 0
        assert image.height > 0


def test_crop_thumbnail_rejects_outside_bounds(tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (100, 80)).save(path)
    with pytest.raises(ValueError):
        crop_thumbnail(_request(path, (200, 200, 300, 300)))


def test_crop_thumbnail_requires_source():
    with pytest.raises(ValueError):
        crop_thumbnail(_request("", (0, 0, 10, 10)))


def test_cache_is_keyed_by_bounds_and_source_version(app):
    provider = ThumbnailProvider()
    provider.start_generation(1)
    image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("red"))
    old_key = provider.request_key(
        "id1",
        provider.generation,
        (0, 0, 10, 10),
        0.35,
        (360, 240),
        "source-1",
    )
    provider._cache[old_key] = image
    provider._latest_requests["id1"] = old_key
    assert (
        provider.cached_image(
            "id1", (0, 0, 10, 10), 0.35, (360, 240), "source-1"
        )
        is image
    )
    assert (
        provider.cached_image(
            "id1", (20, 20, 30, 30), 0.35, (360, 240), "source-1"
        )
        is None
    )
    assert (
        provider.cached_image(
            "id1", (0, 0, 10, 10), 0.35, (360, 240), "source-2"
        )
        is None
    )
    provider.invalidate_shape("id1")
    assert (
        provider.cached_image(
            "id1", (0, 0, 10, 10), 0.35, (360, 240), "source-1"
        )
        is None
    )
    assert "id1" not in provider._latest_requests
    provider.shutdown()


def test_stale_same_id_result_is_ignored(app):
    provider = ThumbnailProvider()
    provider.start_generation(1)
    old_request = ThumbnailRequest(
        shape_id="id1",
        generation=provider.generation,
        bounds=(0, 0, 10, 10),
        margin_ratio=0.35,
        target_size=(360, 240),
        image_path="",
        image_bytes=None,
        source_version="source-1",
    )
    new_request = ThumbnailRequest(
        shape_id="id1",
        generation=provider.generation,
        bounds=(50, 50, 60, 60),
        margin_ratio=0.35,
        target_size=(360, 240),
        image_path="",
        image_bytes=None,
        source_version="source-1",
    )
    new_key = provider.request_key(
        "id1",
        new_request.generation,
        new_request.bounds,
        new_request.margin_ratio,
        new_request.target_size,
        new_request.source_version,
    )
    provider._latest_requests["id1"] = new_key
    provider._pending.add("id1")
    provider._handle_message(("ready", old_request, _png_bytes()))
    assert not provider._cache
    assert "id1" in provider._pending
    provider._handle_message(("ready", new_request, _png_bytes()))
    cached = provider.cached_image(
        "id1", (50, 50, 60, 60), 0.35, (360, 240), "source-1"
    )
    assert cached is not None
    assert "id1" not in provider._pending
    provider.shutdown()


def test_drain_defers_finished_cards_while_interacting(app):
    provider = ThumbnailProvider()
    provider.start_generation(1)
    request = _request("image.png", (0, 0, 10, 10))
    key = provider.request_key(
        request.shape_id,
        request.generation,
        request.bounds,
        request.margin_ratio,
        request.target_size,
        request.source_version,
    )
    provider._latest_requests[request.shape_id] = key
    provider._pending.add(request.shape_id)
    provider._queue.put(("ready", request, _png_bytes()))

    provider.set_defer_predicate(lambda: True)
    provider._drain()
    # A drag frame must not pay for decode, cache fill or card signals.
    assert provider._queue.qsize() == 1
    assert not provider._cache

    provider.set_defer_predicate(lambda: False)
    provider._drain()
    assert provider._queue.empty()
    assert provider._cache[key] is not None
    provider.shutdown()


def test_crop_yielding_waits_until_interaction_ends(app, tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (100, 80), color=(10, 20, 30)).save(path)
    provider = ThumbnailProvider()
    provider.start_generation(1)
    calls = {"count": 0}

    def predicate():
        calls["count"] += 1
        return calls["count"] < 3

    provider.set_defer_predicate(predicate)
    shape_id, generation, data = provider._crop_yielding(
        _request(path, (0, 0, 40, 40))
    )
    assert calls["count"] == 3
    assert shape_id == "id1"
    assert generation == 1
    with Image.open(io.BytesIO(data)) as image:
        assert image.width > 0
    provider.shutdown()

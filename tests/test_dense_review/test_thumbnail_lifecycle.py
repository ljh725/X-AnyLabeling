"""Exercise real executor cancellation, backpressure and late completion."""

import threading
import time

from PIL import Image

from anylabeling.views.labeling.dense_review.thumbnails import (
    ThumbnailProvider,
)


def _drain_until(app, provider, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        provider._drain()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), provider.resource_stats()


def test_real_executor_bounds_backlog_and_recovers_after_switch(
    qt_application, tmp_path
):
    path = tmp_path / "source.png"
    Image.new("RGB", (60, 60), "blue").save(path)
    provider = ThumbnailProvider()
    interacting = threading.Event()
    interacting.set()
    provider.set_defer_predicate(interacting.is_set)
    received = []
    provider.ready.connect(lambda shape_id, image: received.append(shape_id))
    try:
        provider.start_generation(1)
        for index in range(120):
            provider.request(
                f"old-{index}", (0, 0, 40, 40), 0.2, (60, 60), str(path), None
            )
        stats = provider.resource_stats()
        assert stats["outstanding"] <= stats["limit"]
        assert stats["inflight"] <= stats["limit"]
        assert len(provider._pending) <= stats["limit"]
        provider.start_generation(2)
        interacting.clear()
        _drain_until(
            qt_application,
            provider,
            lambda: provider.resource_stats()["outstanding"] == 0,
        )
        assert received == []
        assert provider._queue.empty()
        provider.request("new", (0, 0, 40, 40), 0.2, (60, 60), str(path), None)
        _drain_until(qt_application, provider, lambda: received == ["new"])
        assert provider.cached_latest("new") is not None
    finally:
        interacting.clear()
        provider.shutdown()


def test_shutdown_interrupts_worker_waiting_for_drag(qt_application, tmp_path):
    path = tmp_path / "source.png"
    Image.new("RGB", (60, 60), "red").save(path)
    provider = ThumbnailProvider()
    entered = threading.Event()

    def dragging():
        entered.set()
        return True

    provider.set_defer_predicate(dragging)
    provider.start_generation(1)
    provider.request("old", (0, 0, 40, 40), 0.2, (60, 60), str(path), None)
    assert entered.wait(2), "real worker must enter the interaction wait"
    provider.shutdown()
    _drain_until(
        qt_application,
        provider,
        lambda: provider.resource_stats()["outstanding"] == 0,
    )
    assert provider._queue.empty()
    assert not provider._timer.isActive()
    provider.request("closed", (0, 0, 40, 40), 0.2, (60, 60), str(path), None)
    assert not provider._pending

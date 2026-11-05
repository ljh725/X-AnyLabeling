"""Bounded background thumbnail generation for object cards."""

from __future__ import annotations

import io
import os.path as osp
import queue
import threading
from collections import OrderedDict
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from PIL import Image
from PyQt6 import QtCore, QtGui

# Decode and publish at most this many finished crops per timer tick so card
# repaints stay below one frame budget during a drag.
_DRAIN_BATCH = 8
_REQUEST_LIMIT = 32


@dataclass(frozen=True)
class ThumbnailRequest:
    """One card crop request in image-space coordinates."""

    shape_id: str
    generation: int
    bounds: tuple[float, float, float, float]
    margin_ratio: float
    target_size: tuple[int, int]
    image_path: str
    image_bytes: Optional[bytes]
    source_version: str = ""
    cancelled: threading.Event = field(
        default_factory=threading.Event, compare=False, repr=False
    )


def crop_thumbnail(
    request: ThumbnailRequest,
) -> tuple[str, int, bytes]:
    """Load, context-crop and thumbnail one object; run on a worker."""
    if request.image_path and osp.isfile(request.image_path):
        with Image.open(request.image_path) as source:
            image = source.convert("RGB")
    elif request.image_bytes:
        with Image.open(io.BytesIO(request.image_bytes)) as source:
            image = source.convert("RGB")
    else:
        raise ValueError("source image is unavailable")
    width, height = image.size
    x0, y0, x1, y1 = request.bounds
    box_width = max(1.0, x1 - x0)
    box_height = max(1.0, y1 - y0)
    margin_x = box_width * request.margin_ratio
    margin_y = box_height * request.margin_ratio
    left = max(0, int(round(x0 - margin_x)))
    top = max(0, int(round(y0 - margin_y)))
    right = min(width, int(round(x1 + margin_x)))
    bottom = min(height, int(round(y1 + margin_y)))
    if right <= left or bottom <= top:
        raise ValueError("object bounds are outside the image")
    crop = image.crop((left, top, right, bottom))
    crop.thumbnail(request.target_size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    return request.shape_id, request.generation, buffer.getvalue()


class ThumbnailProvider(QtCore.QObject):
    """Generate only requested cards, discard stale generations."""

    ready = QtCore.pyqtSignal(str, object)
    failed = QtCore.pyqtSignal(str, str)
    capacity_available = QtCore.pyqtSignal()

    def __init__(
        self,
        parent: Optional[QtCore.QObject] = None,
        cache_limit: int = 64,
    ) -> None:
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="dense-review-thumb"
        )
        self._queue: queue.Queue = queue.Queue()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._drain)
        self._generation = 0
        self._cache: OrderedDict[tuple, QtGui.QImage] = OrderedDict()
        self._pending: set[str] = set()
        self._failed: dict[str, str] = {}
        self._latest_requests: dict[str, tuple] = {}
        self._cache_limit = max(4, int(cache_limit))
        self._defer_predicate: Optional[Callable[[], bool]] = None
        self._lock = threading.Lock()
        self._load = 0
        self._futures: dict = {}
        self._cancelled = threading.Event()
        self._closed = False
        self._saturated = False

    def set_defer_predicate(
        self, predicate: Optional[Callable[[], bool]]
    ) -> None:
        """Defer draining while ``predicate`` reports active interaction.

        Thumbnail decode and card updates are background work; blocking a
        drag frame with them is what OpenSpec 10.1/10.2 measures.
        """
        self._defer_predicate = predicate

    @property
    def generation(self) -> int:
        return self._generation

    def set_cache_limit(self, limit: int) -> None:
        self._cache_limit = max(4, int(limit))
        self._trim_cache()

    def start_generation(self, generation: int) -> None:
        """Discard all results from a previous image/output directory."""
        self._cancelled.set()
        with self._lock:
            self._generation = max(self._generation + 1, int(generation))
            futures = list(self._futures)
        self._cancelled = threading.Event()
        for future in futures:
            cancel = getattr(future, "cancel", None)
            if cancel is not None:
                cancel()
        self._cache.clear()
        self._pending.clear()
        self._failed.clear()
        self._latest_requests.clear()
        while True:
            try:
                self._queue.get_nowait()
                self._release_capacity()
            except queue.Empty:
                break

    def failed_shape_ids(self) -> set[str]:
        return set(self._failed)

    @staticmethod
    def request_key(
        shape_id: str,
        generation: int,
        bounds: Sequence[float],
        margin_ratio: float,
        target_size: tuple[int, int],
        source_version: str = "",
    ) -> tuple:
        return (
            shape_id,
            int(generation),
            tuple(float(value) for value in bounds),
            round(float(margin_ratio), 4),
            tuple(target_size),
            str(source_version),
        )

    def cached_image(
        self,
        shape_id: str,
        bounds: Sequence[float],
        margin_ratio: float,
        target_size: tuple[int, int],
        source_version: str = "",
    ) -> Optional[QtGui.QImage]:
        key = self.request_key(
            shape_id,
            self._generation,
            bounds,
            margin_ratio,
            target_size,
            source_version,
        )
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
        return image

    def cached_latest(self, shape_id: str) -> Optional[QtGui.QImage]:
        key = self._latest_requests.get(shape_id)
        if key is None:
            return None
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
        return image

    def invalidate_shape(self, shape_id: str) -> None:
        for key in [key for key in self._cache if key[0] == shape_id]:
            del self._cache[key]
        self._pending.discard(shape_id)
        self._failed.pop(shape_id, None)
        self._latest_requests.pop(shape_id, None)

    def request(
        self,
        shape_id: str,
        bounds: Sequence[float],
        margin_ratio: float,
        target_size: tuple[int, int],
        image_path: str,
        image_bytes: Optional[bytes],
        source_version: str = "",
    ) -> Optional[QtGui.QImage]:
        """Return a cached image or schedule one background request."""
        if self._closed:
            return None
        if len(bounds) != 4:
            self._failed[shape_id] = "对象边界无效"
            return None
        key = self.request_key(
            shape_id,
            self._generation,
            bounds,
            margin_ratio,
            target_size,
            source_version,
        )
        previous = self._latest_requests.get(shape_id)
        if previous is not None and previous != key:
            self.invalidate_shape(shape_id)
        self._latest_requests[shape_id] = key
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        if shape_id in self._pending:
            return None
        with self._lock:
            if self._load >= _REQUEST_LIMIT:
                self._saturated = True
                if not self._timer.isActive():
                    self._timer.start()
                return None
            self._load += 1
        self._pending.add(shape_id)
        request = ThumbnailRequest(
            shape_id=shape_id,
            generation=self._generation,
            bounds=tuple(float(value) for value in bounds),
            margin_ratio=float(margin_ratio),
            target_size=tuple(target_size),
            image_path=str(image_path or ""),
            image_bytes=image_bytes,
            source_version=str(source_version),
            cancelled=self._cancelled,
        )
        try:
            future = self._executor.submit(self._crop_yielding, request)
        except RuntimeError:
            self._pending.discard(shape_id)
            self._release_capacity()
            return None
        with self._lock:
            self._futures[future] = request
        future.add_done_callback(
            lambda done, pending=request: self._completed(pending, done)
        )
        if not self._timer.isActive():
            self._timer.start()
        return None

    def _crop_yielding(self, request: ThumbnailRequest):
        """Crop one card, but never while the user is manipulating the canvas.

        The worker thread holds the GIL for most of a crop, which adds a
        measurable per-frame cost to a drag (OpenSpec 10.1/10.2). Yielding here
        keeps direct manipulation at baseline latency; the card simply appears
        after the gesture ends.
        """
        predicate = self._defer_predicate
        while predicate is not None:
            if request.cancelled.is_set():
                raise CancelledError()
            try:
                if not predicate():
                    break
            except Exception:  # noqa: BLE001 - never spin on a dead host
                break
            request.cancelled.wait(0.01)
        if request.cancelled.is_set():
            raise CancelledError()
        return crop_thumbnail(request)

    def _completed(self, request: ThumbnailRequest, future) -> None:
        message = None
        try:
            # Decode on the worker thread: PNG decode in the GUI thread was the
            # dominant drag-frame cost measured by OpenSpec 10.1/10.2.
            if request.cancelled.is_set() or self._closed:
                return
            image = QtGui.QImage()
            if not image.loadFromData(future.result()[2], "PNG"):
                raise ValueError("图块解码失败")
            message = ("ready", request, image)
        except Exception as error:  # noqa: BLE001
            message = ("failed", request, f"{type(error).__name__}: {error}")
        finally:
            # A slot covers the submitted task AND its queued result. This
            # bounds the executor backlog and decoded QImages together, even
            # while GUI publication is paused during a drag.
            with self._lock:
                self._futures.pop(future, None)
                if (
                    message is not None
                    and not self._closed
                    and not request.cancelled.is_set()
                    and request.generation == self._generation
                ):
                    self._queue.put_nowait(message)
                else:
                    self._load = max(0, self._load - 1)

    def _release_capacity(self) -> None:
        with self._lock:
            self._load = max(0, self._load - 1)

    def resource_stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "inflight": len(self._futures),
                "outstanding": self._load,
                "limit": _REQUEST_LIMIT,
            }

    def _drain(self) -> None:
        # Never compete with direct manipulation: a drag frame that has to wait
        # for PNG decode and card repaints is exactly what the benchmark flags.
        if self._defer_predicate is not None and self._defer_predicate():
            return
        # Small time-slices keep card refreshes from blocking drag frames when
        # a whole batch of thumbnails finishes at once (OpenSpec 10.1/10.2).
        handled = 0
        while handled < _DRAIN_BATCH:
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                break
            handled += 1
            self._release_capacity()
            self._handle_message(message)
        with self._lock:
            available = self._load < _REQUEST_LIMIT
            empty = self._load == 0
        if self._saturated and available:
            self._saturated = False
            self.capacity_available.emit()
        if empty and self._queue.empty():
            self._timer.stop()

    def _handle_message(self, message) -> None:
        kind, request, payload = message
        key = self.request_key(
            request.shape_id,
            request.generation,
            request.bounds,
            request.margin_ratio,
            request.target_size,
            request.source_version,
        )
        if (
            request.generation != self._generation
            or self._latest_requests.get(request.shape_id) != key
        ):
            return
        if kind == "ready":
            image = payload
            if not isinstance(image, QtGui.QImage):
                # Tests and older callers may enqueue encoded PNG bytes.
                image = QtGui.QImage()
                if not image.loadFromData(payload, "PNG"):
                    self._pending.discard(request.shape_id)
                    self._failed[request.shape_id] = "图块解码失败"
                    self.failed.emit(request.shape_id, "图块解码失败")
                    return
            self._cache[key] = image
            self._cache.move_to_end(key)
            self._trim_cache()
            self._pending.discard(request.shape_id)
            self._failed.pop(request.shape_id, None)
            self.ready.emit(request.shape_id, image)
            return
        self._pending.discard(request.shape_id)
        self._failed[request.shape_id] = payload
        self.failed.emit(request.shape_id, payload)

    def _trim_cache(self) -> None:
        while len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)

    def shutdown(self) -> None:
        self._closed = True
        self.start_generation(self._generation + 1)
        self._timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

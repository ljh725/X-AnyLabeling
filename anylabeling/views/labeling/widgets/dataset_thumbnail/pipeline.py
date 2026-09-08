"""Bounded background I/O, decoding and rendering for thumbnail pages."""

from __future__ import annotations

import math
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterable, Optional

from PyQt6 import QtCore, QtGui

from anylabeling.views.labeling.dataset_index import DatasetThumbnailRef

from .cache import ThumbnailCacheKey, ThumbnailDiskCache, ThumbnailMemoryCache
from .render_options import RenderOptions

HORIZONTAL_PADDING_RATIO = 0.15
VERTICAL_PADDING_RATIO = 0.15
_CLOSING_RENDERERS: set = set()


def thumbnail_crop_rect(
    bbox: tuple[float, float, float, float],
    image_size: tuple[int, int],
    padding: float = HORIZONTAL_PADDING_RATIO,
) -> Optional[tuple[int, int, int, int]]:
    """Return a bounded crop with per-axis object padding."""
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    x = max(0, math.floor(left - width * padding))
    y = max(0, math.floor(top - height * padding))
    x2 = min(image_size[0], math.ceil(right + width * padding))
    y2 = min(image_size[1], math.ceil(bottom + height * padding))
    if x2 <= x or y2 <= y:
        return None
    return x, y, x2 - x, y2 - y


def _request_key(
    ref: DatasetThumbnailRef,
    size: tuple,
    policy: str = RenderOptions().cache_policy,
) -> tuple:
    """Identify a page request without synchronous filesystem access."""
    return ref.image_path, ref.shape_id, ref.bbox, size, policy


@dataclass(frozen=True)
class ThumbnailRenderResult:
    """One outcome with an immutable image and measured worker stages."""

    generation: int
    ref: DatasetThumbnailRef
    key: Optional[ThumbnailCacheKey]
    image_bytes: Optional[bytes] = None
    error: str = ""
    image: Optional[QtGui.QImage] = None
    timings_ms: dict[str, float] = field(default_factory=dict)


class _RenderSignals(QtCore.QObject):
    """Deliver individual results and unconditional task completion."""

    result = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal(object)


class _RenderTask(QtCore.QRunnable):
    """Read one image's metadata/cache and decode it at most once."""

    def __init__(
        self,
        generation: int,
        entries: list[
            tuple[DatasetThumbnailRef, tuple[int, int], RenderOptions]
        ],
        memory: ThumbnailMemoryCache,
        disk: ThumbnailDiskCache,
        cancelled: threading.Event,
    ) -> None:
        """Keep worker-owned values alive until completion is delivered."""
        super().__init__()
        self.generation = generation
        self.entries = entries
        self.memory = memory
        self.disk = disk
        self.cancelled = cancelled
        self.signals = _RenderSignals()

    def run(self) -> None:
        """Guarantee a completion signal even after I/O or codec errors."""
        try:
            self._run_entries()
        finally:
            self.signals.finished.emit(self)

    def _run_entries(self) -> None:
        """Reuse source stat and lazily decoded pixels within this batch."""
        source = None
        stat = None
        source_error = ""
        start = time.perf_counter()
        try:
            stat = os.stat(self.entries[0][0].image_path)
        except OSError:
            source_error = "image file is missing"
        stat_ms = (time.perf_counter() - start) * 1000
        for position, (ref, size, options) in enumerate(self.entries):
            if self.cancelled.is_set():
                return
            metrics = {"stat": stat_ms if position == 0 else 0.0}
            key = None
            try:
                if source_error:
                    raise ValueError(source_error)
                key = ThumbnailCacheKey.for_ref(
                    ref,
                    stat.st_mtime_ns,
                    stat.st_size,
                    size,
                    options.cache_policy,
                )
                if key is None or not ref.shape_id.strip():
                    raise ValueError("object has no valid bbox or Shape ID")
                value = self.memory.get(key)
                if value is None:
                    start = time.perf_counter()
                    value = self.disk.get(key)
                    metrics["cache_read"] = (
                        time.perf_counter() - start
                    ) * 1000
                start = time.perf_counter()
                image = QtGui.QImage.fromData(value, "PNG") if value else None
                metrics["cache_decode"] = (time.perf_counter() - start) * 1000
                if image is None or image.isNull():
                    if source is None:
                        start = time.perf_counter()
                        source = QtGui.QImage(ref.image_path)
                        metrics["source_read_decode"] = (
                            time.perf_counter() - start
                        ) * 1000
                    if source.isNull():
                        raise ValueError("image could not be read")
                    value, image = self._render(
                        source, ref, key, metrics, options
                    )
                else:
                    metrics["cache_hit"] = 1.0
                self.memory.put(key, value)
                result = ThumbnailRenderResult(
                    self.generation,
                    ref,
                    key,
                    value,
                    image=image,
                    timings_ms=metrics,
                )
            except Exception as exc:  # Worker failures become retryable cards.
                result = ThumbnailRenderResult(
                    self.generation,
                    ref,
                    key,
                    error=str(exc),
                    timings_ms=metrics,
                )
            if not self.cancelled.is_set():
                self.signals.result.emit(result)

    def _render(
        self,
        source: QtGui.QImage,
        ref: DatasetThumbnailRef,
        key: ThumbnailCacheKey,
        metrics: dict[str, float],
        options: RenderOptions,
    ) -> tuple[bytes, QtGui.QImage]:
        """Measure crop, scale, PNG encoding and atomic cache writing."""
        start = time.perf_counter()
        rect = (
            (0, 0, source.width(), source.height())
            if options.mode == "full"
            else thumbnail_crop_rect(
                ref.bbox, (source.width(), source.height()), options.padding
            )
        )
        if rect is None:
            raise ValueError("bbox has no visible area")
        crop = source.copy(QtCore.QRect(*rect))
        metrics["crop"] = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        image = crop.scaled(
            QtCore.QSize(*key.size),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        metrics["scale"] = (time.perf_counter() - start) * 1000
        if options.show_box:
            painter = QtGui.QPainter(image)
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffcb30"), 2))
            left, top, right, bottom = ref.bbox
            sx, sy = image.width() / rect[2], image.height() / rect[3]
            target = QtCore.QRectF(
                (left - rect[0]) * sx,
                (top - rect[1]) * sy,
                (right - left) * sx,
                (bottom - top) * sy,
            )
            painter.drawRect(
                target.intersected(
                    QtCore.QRectF(1, 1, image.width() - 2, image.height() - 2)
                )
            )
            painter.end()
        start = time.perf_counter()
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("thumbnail encoding failed")
        value = bytes(buffer.data())
        metrics["encode"] = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        if not self.cancelled.is_set():
            self.disk.put(key, value)
        metrics["cache_write"] = (time.perf_counter() - start) * 1000
        return value, image


class ThumbnailRenderer(QtCore.QObject):
    """Schedule at most one page of requests with visible items first."""

    result_ready = QtCore.pyqtSignal(object)

    def __init__(
        self,
        cache_root: str,
        memory_limit: int = 512,
        max_concurrency: int = 2,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        """Initialize caches and a pool whose lifetime exceeds its window."""
        super().__init__(parent)
        self.memory = ThumbnailMemoryCache(memory_limit)
        self.disk = ThumbnailDiskCache(cache_root)
        self._generation = 0
        self._closed = False
        self._cancelled = threading.Event()
        self._inflight = set()
        self._requested = set()
        self._pending = OrderedDict()
        self._tasks = {}
        self._pool = QtCore.QThreadPool(QtCore.QCoreApplication.instance())
        self._pool.setMaxThreadCount(max(1, int(max_concurrency)))
        self.queue_peak = 0
        self.cancelled_requests = 0

    @property
    def generation(self) -> int:
        """Return the current page token."""
        return self._generation

    def invalidate(self) -> int:
        """Drop queued old work and ask running batches to stop early."""
        self._cancelled.set()
        self.cancelled_requests += sum(len(v) for v in self._pending.values())
        self._cancelled = threading.Event()
        self._pending.clear()
        self._inflight.clear()
        self._requested.clear()
        self._generation += 1
        return self._generation

    def request(
        self,
        refs: Iterable[DatasetThumbnailRef],
        size: tuple[int, int] = (180, 140),
        generation: Optional[int] = None,
        prefetch: Iterable[DatasetThumbnailRef] = (),
        options: RenderOptions = RenderOptions(),
    ) -> int:
        """Queue lightweight refs; all file access happens in workers."""
        if self._closed:
            return self._generation
        if generation is None:
            generation = self.invalidate()
        if generation != self._generation:
            return self._generation
        visible = tuple(refs)
        size = tuple(size)
        for ref in (*visible, *prefetch):
            key = _request_key(ref, size, options.cache_policy)
            if key in self._requested or len(self._requested) >= 100:
                continue
            self._requested.add(key)
            self._inflight.add((generation, key))
            self._pending.setdefault(ref.image_path, []).append(
                (ref, size, options)
            )
        for ref in reversed(visible):
            if ref.image_path in self._pending:
                self._pending.move_to_end(ref.image_path, last=False)
        self.queue_peak = max(
            self.queue_peak, sum(len(v) for v in self._pending.values())
        )
        self._start_pending()
        return generation

    def retry(self, refs: Iterable[DatasetThumbnailRef]) -> None:
        """Allow explicit retry of completed failures in the same page."""
        identities = {(ref.image_path, ref.shape_id) for ref in refs}
        self._requested = {
            key for key in self._requested if key[:2] not in identities
        }

    def _start_pending(self) -> None:
        """Submit only available worker slots, never an unbounded Qt queue."""
        while (
            not self._closed
            and self._pending
            and len(self._tasks) < self._pool.maxThreadCount()
        ):
            _path, entries = self._pending.popitem(last=False)
            task = _RenderTask(
                self._generation,
                entries,
                self.memory,
                self.disk,
                self._cancelled,
            )
            self._tasks[id(task)] = task
            task.signals.result.connect(self._on_result)
            task.signals.finished.connect(self._on_task_finished)
            self._pool.start(task)

    @QtCore.pyqtSlot(object)
    def _on_result(self, result: ThumbnailRenderResult) -> None:
        """Apply only current results, without re-decoding PNG on the GUI."""
        if self._closed or result.generation != self._generation:
            return
        if result.key is not None:
            key = _request_key(
                result.ref, result.key.size, result.key.crop_policy
            )
            self._inflight.discard((result.generation, key))
        self.result_ready.emit(result)

    @QtCore.pyqtSlot(object)
    def _on_task_finished(self, task: _RenderTask) -> None:
        """Release a slot and continue the newest page after cancellation."""
        self._tasks.pop(id(task), None)
        for ref, size, options in task.entries:
            self._inflight.discard(
                (
                    task.generation,
                    _request_key(ref, size, options.cache_policy),
                )
            )
        if self._closed:
            if not self._tasks:
                self._pool.deleteLater()
                _CLOSING_RENDERERS.discard(self)
                self.deleteLater()
        else:
            self._start_pending()

    def close(self) -> None:
        """Detach pending workers so closing a window never joins threads."""
        if self._closed:
            return
        self.invalidate()
        self._closed = True
        self.setParent(None)
        if self._tasks:
            _CLOSING_RENDERERS.add(self)
        else:
            self._pool.deleteLater()

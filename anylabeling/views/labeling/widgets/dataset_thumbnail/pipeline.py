"""Asynchronous, cache-backed dataset thumbnail rendering."""

from __future__ import annotations

import math
import os
import os.path as osp
from dataclasses import dataclass
from typing import Iterable, Optional

from PyQt6 import QtCore, QtGui

from anylabeling.views.labeling.dataset_index import DatasetThumbnailRef

from .cache import (
    THUMBNAIL_CROP_POLICY_VERSION,
    ThumbnailCacheKey,
    ThumbnailDiskCache,
    ThumbnailMemoryCache,
)

HORIZONTAL_PADDING_RATIO = 0.15


def thumbnail_crop_rect(
    bbox: tuple[float, float, float, float],
    image_size: tuple[int, int],
) -> Optional[tuple[int, int, int, int]]:
    """Return a bounded crop with horizontal-only object padding."""
    left, top, right, bottom = bbox
    bbox_width = right - left
    if bbox_width <= 0:
        return None
    pad_x = bbox_width * HORIZONTAL_PADDING_RATIO
    x = max(0, math.floor(left - pad_x))
    y = max(0, math.floor(top))
    x2 = min(int(image_size[0]), math.ceil(right + pad_x))
    y2 = min(int(image_size[1]), math.ceil(bottom))
    width, height = x2 - x, y2 - y
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


@dataclass(frozen=True)
class ThumbnailRenderResult:
    """One asynchronous render outcome for one object reference."""

    generation: int
    ref: DatasetThumbnailRef
    key: Optional[ThumbnailCacheKey]
    image_bytes: Optional[bytes] = None
    error: str = ""


class _RenderSignals(QtCore.QObject):
    """Signals owned by a worker so it can communicate across threads."""

    finished = QtCore.pyqtSignal(object)


class _RenderTask(QtCore.QRunnable):
    """Decode one source image and render all requested crops from it."""

    def __init__(
        self,
        generation: int,
        image_path: str,
        entries: list[tuple[DatasetThumbnailRef, ThumbnailCacheKey]],
        memory: ThumbnailMemoryCache,
        disk: ThumbnailDiskCache,
    ) -> None:
        """Initialize a grouped image render task."""
        super().__init__()
        self.setAutoDelete(True)
        self.generation = generation
        self.image_path = image_path
        self.entries = entries
        self.memory = memory
        self.disk = disk
        self.signals = _RenderSignals()

    def run(self) -> None:
        """Decode once, crop each bbox, and emit independent outcomes."""
        image = QtGui.QImage(self.image_path)
        if image.isNull():
            self.signals.finished.emit(
                [
                    ThumbnailRenderResult(
                        self.generation,
                        ref,
                        key,
                        error="image could not be read",
                    )
                    for ref, key in self.entries
                ]
            )
            return
        results = []
        for ref, key in self.entries:
            result = self._render_one(image, ref, key)
            results.append(result)
        self.signals.finished.emit(results)

    def _render_one(
        self,
        image: QtGui.QImage,
        ref: DatasetThumbnailRef,
        key: ThumbnailCacheKey,
    ) -> ThumbnailRenderResult:
        """Render one bbox from an already decoded image."""
        assert ref.bbox is not None
        crop_rect = thumbnail_crop_rect(
            ref.bbox, (image.width(), image.height())
        )
        if crop_rect is None:
            return ThumbnailRenderResult(
                self.generation, ref, key, error="bbox has no visible area"
            )
        x, y, width, height = crop_rect
        cropped = image.copy(QtCore.QRect(x, y, width, height))
        scaled = cropped.scaled(
            QtCore.QSize(*key.size),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        if not scaled.save(buffer, "PNG"):
            return ThumbnailRenderResult(
                self.generation, ref, key, error="thumbnail encoding failed"
            )
        value = bytes(buffer.data())
        self.memory.put(key, value)
        self.disk.put(key, value)
        return ThumbnailRenderResult(self.generation, ref, key, value)


class ThumbnailRenderer(QtCore.QObject):
    """Coordinate cache lookups and grouped background thumbnail renders."""

    result_ready = QtCore.pyqtSignal(object)

    def __init__(
        self,
        cache_root: str,
        memory_limit: int = 512,
        max_concurrency: int = 2,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        """Initialize renderer caches and a private generation counter."""
        super().__init__(parent)
        self.memory = ThumbnailMemoryCache(memory_limit)
        self.disk = ThumbnailDiskCache(cache_root)
        self._generation = 0
        self._closed = False
        self._inflight: set[tuple[int, str]] = set()
        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(max(1, int(max_concurrency)))

    @property
    def generation(self) -> int:
        """Return the current request generation."""
        return self._generation

    def invalidate(self) -> int:
        """Advance generation so all already-running tasks become stale."""
        self._generation += 1
        return self._generation

    def request(
        self,
        refs: Iterable[DatasetThumbnailRef],
        size: tuple[int, int] = (180, 140),
        generation: Optional[int] = None,
    ) -> int:
        """Request visible references and return their generation token."""
        if self._closed:
            return self._generation
        if generation is None:
            generation = self.invalidate()
        elif generation != self._generation:
            return self._generation
        grouped: dict[
            str, list[tuple[DatasetThumbnailRef, ThumbnailCacheKey]]
        ] = {}
        for ref in refs:
            try:
                stat = os.stat(ref.image_path)
            except OSError:
                self.result_ready.emit(
                    ThumbnailRenderResult(
                        generation,
                        ref,
                        None,
                        error="image file is missing",
                    )
                )
                continue
            key = ThumbnailCacheKey.for_ref(
                ref,
                stat.st_mtime_ns,
                stat.st_size,
                size,
                THUMBNAIL_CROP_POLICY_VERSION,
            )
            if key is None or not ref.shape_id.strip():
                self.result_ready.emit(
                    ThumbnailRenderResult(
                        generation,
                        ref,
                        key,
                        error="object has no valid bbox or Shape ID",
                    )
                )
                continue
            cached = self.memory.get(key)
            if cached is None:
                cached = self.disk.get(key)
                if cached is not None:
                    self.memory.put(key, cached)
            if cached is not None:
                self.result_ready.emit(
                    ThumbnailRenderResult(generation, ref, key, cached)
                )
                continue
            inflight_key = (generation, key.token)
            if inflight_key in self._inflight:
                continue
            self._inflight.add(inflight_key)
            grouped.setdefault(ref.image_path, []).append((ref, key))
        for image_path, entries in grouped.items():
            task = _RenderTask(
                generation, image_path, entries, self.memory, self.disk
            )
            task.signals.finished.connect(self._on_task_finished)
            self._pool.start(task)
        return generation

    def close(self) -> None:
        """Invalidate all outstanding work and ignore future requests."""
        self.invalidate()
        self._closed = True

    @QtCore.pyqtSlot(object)
    def _on_task_finished(self, results: object) -> None:
        """Forward worker results; consumers enforce generation freshness."""
        for result in results:
            if result.key is not None:
                self._inflight.discard((result.generation, result.key.token))
        if self._closed:
            return
        for result in results:
            self.result_ready.emit(result)

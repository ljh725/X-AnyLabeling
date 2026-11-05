"""Offscreen GUI benchmark for the dense-review workspace.

Implements the measurements requested by OpenSpec change
``add-dense-annotation-review-workflow`` tasks 10.1-10.3:

* cold/warm object and batch switch latency (p50/p95);
* GUI heartbeat delay while object-card thumbnails generate (16 ms timer);
* drag/frame latency with the workspace open, closed and with card work
  running in the background;
* thumbnail-cache entry/byte counts before and after navigating through
  many objects, proving the LRU stays bounded.

The script is deliberately a *harness*: it never changes production code
and it never asserts the provisional thresholds.  Threshold breaches are
reported in the JSON and do not change the exit code.  A non-zero exit is
reserved for harness failures (no window, no session, drag not moving).

Run with, for example::

    python -B scripts/benchmark_dense_review.py --objects 300 \
        --samples 30 --repeats 3 --json report.json

``QT_QPA_PLATFORM=offscreen`` is set before PyQt is imported.  All state
(config, QSettings, images and annotations) lives in a throw-away
directory below ``.tmp``; the user profile is never touched.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import shutil
import statistics
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _entry in (str(REPO_ROOT), str(SCRIPT_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from PIL import Image, ImageDraw  # noqa: E402
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.resources import resources  # noqa: E402,F401
from anylabeling.views.labeling import (  # noqa: E402
    label_widget as label_widget_module,
)
from anylabeling.views.labeling.dense_review import (  # noqa: E402
    thumbnails as thumbnails_module,
)
from anylabeling.views.mainwindow import MainWindow  # noqa: E402
from dev_isolation import IsolatedConfig  # noqa: E402

LABELS = ("person", "car", "bike", "truck", "sign", "light")
COLORS = (
    (206, 84, 74),
    (72, 126, 208),
    (92, 168, 94),
    (222, 172, 62),
    (150, 104, 186),
    (76, 180, 180),
)
THRESHOLDS = {
    "warm_switch_p95_ms": 150.0,
    "heartbeat_p95_ms": 50.0,
    "drag_regression_pct": 10.0,
}
HEARTBEAT_INTERVAL_MS = 16
THUMBNAIL_TARGET = (360, 240)


class BenchmarkError(RuntimeError):
    """Raised when the harness itself cannot take a measurement."""


# -- statistics ---------------------------------------------------------


def percentile(values: Iterable[float], fraction: float) -> float:
    """Linear-interpolated percentile, matching numpy's default."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize(values: Iterable[float]) -> dict[str, Any]:
    """Return the p50/p95/max summary used throughout the report."""
    samples = [float(value) for value in values]
    if not samples:
        return {
            "count": 0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
            "min_ms": 0.0,
        }
    return {
        "count": len(samples),
        "p50_ms": round(percentile(samples, 0.50), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
        "mean_ms": round(statistics.fmean(samples), 3),
        "min_ms": round(min(samples), 3),
    }


class Condition:
    """Accumulate one latency condition across repetitions."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.samples: list[float] = []
        self.per_repeat: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}
        self.unsampled = False

    def add_repeat(self, values: Iterable[float]) -> None:
        batch = [float(value) for value in values]
        self.samples.extend(batch)
        summary = summarize(batch)
        self.per_repeat.append(summary)
        if not batch:
            self.unsampled = True

    def report(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "summary": summarize(self.samples),
            "per_repeat": self.per_repeat,
            "samples_ms": [round(value, 3) for value in self.samples],
        }
        data.update(self.meta)
        if self.unsampled:
            data["unsampled"] = True
        return data


# -- deterministic fixture ---------------------------------------------


def _cell_geometry(object_count: int) -> tuple[int, int, int]:
    """Choose a grid and cell size for the requested object count."""
    cell = 200 if object_count <= 60 else 120
    columns = max(1, int(math.ceil(math.sqrt(object_count * 4.0 / 3.0))))
    rows = max(1, int(math.ceil(object_count / float(columns))))
    return columns, rows, cell


def synthesize_dataset(
    root: Path, object_count: int, seed: int = 11
) -> dict[str, Any]:
    """Create one image + annotation + review config without downloads."""
    root.mkdir(parents=True, exist_ok=True)
    labels = list(LABELS[: min(len(LABELS), max(1, object_count))])
    rng = random.Random(seed)
    columns, rows, cell = _cell_geometry(object_count)
    width, height = columns * cell, rows * cell
    image = Image.new("RGB", (width, height), (236, 238, 241))
    draw = ImageDraw.Draw(image)
    for column in range(columns + 1):
        x = min(width - 1, column * cell)
        draw.line([(x, 0), (x, height - 1)], fill=(220, 223, 227))
    for row in range(rows + 1):
        y = min(height - 1, row * cell)
        draw.line([(0, y), (width - 1, y)], fill=(220, 223, 227))
    shapes: list[dict[str, Any]] = []
    margin = max(6, cell // 10)
    for index in range(object_count):
        column, row = index % columns, index // columns
        label_index = index % len(labels)
        x0 = column * cell + margin
        y0 = row * cell + margin
        shrink_x = (index * 3) % max(2, cell // 8)
        shrink_y = (index * 5) % max(2, cell // 8)
        x1 = min(width - 1, column * cell + cell - margin - shrink_x)
        y1 = min(height - 1, row * cell + cell - margin - shrink_y)
        base = COLORS[label_index]
        shade = (index * 13 + rng.randrange(0, 24)) % 36 - 18
        color = tuple(max(0, min(255, value + shade)) for value in base)
        draw.rectangle([x0, y0, x1, y1], fill=color)
        draw.rectangle([x0, y0, x1, y1], outline=(28, 28, 30), width=2)
        draw.line([(x0, y0), (x1, y1)], fill=(250, 250, 250), width=2)
        shapes.append(
            {
                "label": labels[label_index],
                "shape_type": "rectangle",
                "points": [
                    [x0, y0],
                    [x1, y0],
                    [x1, y1],
                    [x0, y1],
                ],
                "xanylabeling_shape_id": "obj-%04d" % index,
            }
        )
    image_path = root / "dense.png"
    image.save(image_path)
    annotation = {
        "version": "4.2.1",
        "imageWidth": width,
        "imageHeight": height,
        "imagePath": image_path.name,
        "imageData": None,
        "shapes": shapes,
    }
    annotation_path = root / "dense.json"
    annotation_path.write_text(
        json.dumps(annotation, ensure_ascii=False), encoding="utf-8"
    )
    config_dir = root / ".xanylabeling" / "dense_review"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "batches": [{"name": label, "labels": [label]} for label in labels],
        "rules": {
            "rules": {
                label: {"box_rule": "visible", "note": ""} for label in labels
            },
            "default_box_rule": "unknown",
        },
        "coverage": {"columns": 4, "rows": 3, "overlap": 0.15},
    }
    (config_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "image_path": str(image_path),
        "annotation_path": str(annotation_path),
        "width": width,
        "height": height,
        "object_count": object_count,
        "labels": labels,
        "file_bytes": image_path.stat().st_size,
    }


# -- window under test --------------------------------------------------


class EventCounter(QtCore.QObject):
    """Count paint events for one widget without touching production code."""

    def __init__(self, event_type: QtCore.QEvent.Type) -> None:
        super().__init__()
        self._event_type = event_type
        self.count = 0

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == self._event_type:
            self.count += 1
        return False

    def reset(self) -> None:
        self.count = 0


class WindowHarness:
    """A real MainWindow + LabelingWidget with the review workspace open."""

    def __init__(self, dataset: dict[str, Any], root: Path) -> None:
        self.dataset = dataset
        self.root = root
        self.app: Optional[QtWidgets.QApplication] = None
        self.window: Optional[MainWindow] = None
        self.workspace = None
        self._settings_path = root / "settings.ini"
        self._config_path = root / "config.yaml"
        self._isolation: Optional[IsolatedConfig] = None
        self._canvas_counter: Optional[EventCounter] = None
        self._card_counter: Optional[EventCounter] = None

    # -- lifecycle -----------------------------------------------------

    @property
    def view(self):
        if self.window is None:
            raise BenchmarkError("window is not open")
        return self.window.labeling_widget.view

    def open(self) -> None:
        self.app = QtWidgets.QApplication.instance()
        if self.app is None:
            self.app = QtWidgets.QApplication([])
        self.app.setQuitOnLastWindowClosed(False)
        # A real, isolated configuration session: the benchmark exercises the
        # same startup/persistence path as the application instead of handing
        # a template mapping to MainWindow and never being able to save.
        self._isolation = IsolatedConfig(self.root / "config")
        self._isolation.__enter__()
        self._config_path = Path(self._isolation.target_path)
        config = self._isolation.config
        config.update(auto_save=False)
        self.window = MainWindow(self.app, config=config)
        self.window.resize(1600, 1000)
        self.window.show()
        self.pump()
        if not self.view.load_file(self.dataset["image_path"]):
            raise BenchmarkError("the fixture image could not be loaded")
        self.pump()
        self.view.open_dense_review()
        self.pump()
        self.workspace = self.view.dense_review_workspace
        if self.workspace is None or self.view.dense_review_session is None:
            raise BenchmarkError("the dense-review workspace did not open")
        self._canvas_counter = EventCounter(QtCore.QEvent.Type.Paint)
        self._card_counter = EventCounter(QtCore.QEvent.Type.Paint)
        self.view.canvas.installEventFilter(self._canvas_counter)
        self.workspace.card_list.viewport().installEventFilter(
            self._card_counter
        )
        self.wait_for_thumbnails()

    def close(self) -> None:
        view = None
        try:
            if self.window is not None:
                view = self.window.labeling_widget.view
        except Exception:  # noqa: BLE001
            view = None
        try:
            if self.workspace is not None:
                self.workspace.close()
                self.workspace.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            if view is not None:
                view.dirty = False
                if self._canvas_counter is not None:
                    view.canvas.removeEventFilter(self._canvas_counter)
                if (
                    self._card_counter is not None
                    and getattr(view, "dense_review_workspace", None)
                    is not None
                ):
                    view.dense_review_workspace.card_list.viewport().removeEventFilter(
                        self._card_counter
                    )
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.window is not None:
                self.window.close()
                if self.app is not None:
                    self.app.removeEventFilter(view)
                    self.window.deleteLater()
                    self.app.sendPostedEvents(
                        None, QtCore.QEvent.Type.DeferredDelete
                    )
                    self.pump()
        finally:
            if self._isolation is not None:
                self._isolation.__exit__(None, None, None)
                self._isolation = None
            self.window = None
            self.workspace = None

    def reset_round(self) -> None:
        """Reload the image so every repetition starts from a clean state."""
        self.view.dirty = False
        if not self.view.load_file(self.dataset["image_path"]):
            raise BenchmarkError("the fixture image could not be reloaded")
        self.pump()
        self.workspace = self.view.dense_review_workspace
        if self.workspace is None or self.view.dense_review_session is None:
            raise BenchmarkError("the workspace did not reopen")
        self.workspace.refresh_all(force_cards=True)
        self.pump()
        self.wait_for_thumbnails()

    # -- helpers -------------------------------------------------------

    @property
    def session(self):
        return self.view.dense_review_session

    @property
    def provider(self):
        return self.workspace.thumbnails

    def process(self, seconds: float = 0.0) -> None:
        if self.app is None:
            return
        deadline = time.monotonic() + max(0.0, seconds)
        self.pump()
        while time.monotonic() < deadline:
            self.pump()
            time.sleep(0.002)

    def pump(self, milliseconds: int = 1) -> None:
        """Run one event-loop turn so zero-delay timers are dispatched."""
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def wait_for_thumbnails(self, timeout: float = 20.0) -> None:
        self._wait_until(
            lambda: not self.provider._pending, timeout, "thumbnails"
        )

    def _wait_until(
        self,
        predicate: Callable[[], bool],
        timeout: float,
        what: str,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if predicate():
                return
            time.sleep(0.002)
        raise BenchmarkError("timed out waiting for %s" % what)

    def ids_for_batch(self, batch_id: str) -> list[str]:
        return list(self.session.state.member_ids(batch_id))

    def batch_for_object(self, shape_id: str) -> str:
        return self.session.state.batch_for_object(shape_id)

    def non_empty_batches(self) -> list[str]:
        result = []
        for batch in self.session.state.batches:
            if batch.member_ids:
                result.append(batch.batch_id)
        return result

    def all_shape_ids(self) -> list[str]:
        result: list[str] = []
        for batch in self.session.state.batches:
            result.extend(batch.member_ids)
        return result

    def cache_snapshot(self) -> dict[str, Any]:
        provider = self.provider
        total_bytes = 0
        for image in provider._cache.values():
            try:
                total_bytes += int(image.sizeInBytes())
            except Exception:  # noqa: BLE001
                total_bytes += 0
        return {
            "entries": len(provider._cache),
            "limit": int(provider._cache_limit),
            "bytes": total_bytes,
            "pending": len(provider._pending),
            "failed": len(provider._failed),
            "latest_requests": len(provider._latest_requests),
            "card_request_keys": len(self.workspace._card_request_keys),
            "shape_items": self.workspace._card_model.icon_count(),
            "card_count": self.workspace._card_model.rowCount(),
            "resources": self.workspace.card_resource_stats(),
            "worker": provider.resource_stats(),
            "generation": int(provider.generation),
        }

    def reset_thumbnail_cache(self) -> None:
        provider = self.provider
        self.workspace._generation += 1
        provider.start_generation(self.workspace._generation)
        self.workspace._last_thumb_generation = provider.generation
        self.workspace._card_request_keys.clear()
        self.workspace._failed_ids.clear()

    def warm_batch(
        self, batch_id: str, ids: Optional[list[str]] = None
    ) -> None:
        """Navigate once (or through explicit ids) and wait for crops.

        Warming the first member also warms every card visible in the
        viewport, because ``_navigate_to`` rebuilds the card list and the
        deferred request pass runs for all visible cards.
        """
        targets = ids
        if targets is None:
            members = self.ids_for_batch(batch_id)
            targets = members[:1]
        for shape_id in targets:
            self.workspace._navigate_to(batch_id, shape_id)
            self.pump()
        self.wait_for_thumbnails()

    def request_objects(self, shape_ids: Iterable[str]) -> int:
        """Schedule direct background crops, bypassing card visibility."""
        provider = self.provider
        image_path, image_bytes = self.view.dense_review_image_source()
        source_version = self.view.dense_review_image_info()[0]
        margin = self.workspace.context_spin.value() / 100.0
        scheduled = 0
        for shape_id in shape_ids:
            item = self.session.object(shape_id)
            if item is None:
                continue
            provider.invalidate_shape(shape_id)
            provider.request(
                shape_id,
                item.bounds,
                margin,
                THUMBNAIL_TARGET,
                image_path,
                image_bytes,
                source_version,
            )
            scheduled += 1
        return scheduled

    def batch_row(self, batch_id: str) -> int:
        for row in range(self.workspace.batch_list.count()):
            item = self.workspace.batch_list.item(row)
            if (
                item is not None
                and item.data(QtCore.Qt.ItemDataRole.UserRole) == batch_id
            ):
                return row
        raise BenchmarkError("batch row not found: %s" % batch_id)


# -- measured units -----------------------------------------------------


def measure_switch(
    harness: WindowHarness,
    navigate: Callable[[], None],
    *,
    expected_batch: str,
    expected_object: str,
) -> tuple[float, int, int]:
    """Run one navigation and return (ms, canvas paints, card paints)."""
    canvas = harness._canvas_counter
    cards = harness._card_counter
    canvas.reset()
    cards.reset()
    started = time.perf_counter()
    navigate()
    # Correctness is part of the endpoint: a fast return on the previous
    # batch, or a timer turn without a target paint, is not a switch sample.
    target = expected_object
    batch_id = expected_batch

    def target_ready():
        workspace = harness.workspace
        view = harness.view
        current = workspace.batch_list.currentItem()
        selected = view.canvas.selected_shapes
        return (
            canvas.count > 0
            and harness.session.state.current_batch == batch_id
            and harness.session.state.current_object == target
            and view.canvas.isEnabled()
            and not view.canvas.pixmap.isNull()
            and not view.canvas.is_loading
            and current is not None
            and current.data(QtCore.Qt.ItemDataRole.UserRole) == batch_id
            and tuple(workspace._card_model.shape_ids())
            == tuple(harness.session.state.member_ids(batch_id))
            and selected
            and selected[0].xanylabeling_shape_id == target
            and target in workspace._selected_shape_ids()
        )

    harness._wait_until(target_ready, 5.0, "correct editable target paint")
    elapsed = (time.perf_counter() - started) * 1000.0
    return elapsed, canvas.count, cards.count


def time_call(harness: WindowHarness, action: Callable[[], None]) -> float:
    started = time.perf_counter()
    action()
    harness.pump()
    return (time.perf_counter() - started) * 1000.0


class Heartbeat:
    """A precise 16 ms timer that records event-loop overshoot."""

    def __init__(self, app: QtWidgets.QApplication) -> None:
        self._timer = QtCore.QTimer()
        self._timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self._timer.setInterval(HEARTBEAT_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._interval_ns = HEARTBEAT_INTERVAL_MS * 1_000_000
        self._last: Optional[int] = None
        self.delays: list[float] = []

    def _tick(self) -> None:
        now = time.perf_counter_ns()
        if self._last is not None:
            delay = (now - self._last - self._interval_ns) / 1_000_000.0
            self.delays.append(max(0.0, delay))
        self._last = now

    def start(self) -> None:
        self._last = None
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()


def measure_heartbeat(
    harness: WindowHarness,
    samples: int,
    with_cards: bool,
) -> tuple[list[float], dict[str, Any]]:
    """Measure timer overshoot, optionally while crops are generated."""
    app = harness.app
    provider = harness.provider
    meta: dict[str, Any] = {
        "interval_ms": HEARTBEAT_INTERVAL_MS,
        "pending_peak": 0,
        "chunks": 0,
    }
    ids = harness.all_shape_ids()
    cursor = [0]
    max_chunks = max(4, samples)

    def schedule_chunk() -> None:
        if not ids:
            return
        chunk = []
        for _ in range(8):
            shape_id = ids[cursor[0] % len(ids)]
            cursor[0] += 1
            chunk.append(shape_id)
        meta["chunks"] += 1
        harness.request_objects(chunk)

    heartbeat = Heartbeat(app)
    if with_cards:
        schedule_chunk()
    heartbeat.start()
    deadline = time.monotonic() + max(10.0, samples * 0.1)
    try:
        while len(heartbeat.delays) < samples:
            app.processEvents()
            meta["pending_peak"] = max(
                meta["pending_peak"], len(provider._pending)
            )
            if (
                with_cards
                and not provider._pending
                and meta["chunks"] < max_chunks
            ):
                schedule_chunk()
            if time.monotonic() > deadline:
                break
            time.sleep(0.002)
    finally:
        heartbeat.stop()
    meta["scheduled_chunks"] = meta["chunks"]
    meta["pending_peak"] = meta["pending_peak"]
    return heartbeat.delays, meta


class CropRecorder:
    """Time worker-side crops and count crops started during a drag."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.durations: list[float] = []
        self.calls = 0
        self.drag_active = False
        self.drag_calls = 0

    def wrap(self, original):
        def timed(request):
            started = time.perf_counter()
            started_during_drag = self.drag_active
            try:
                return original(request)
            finally:
                elapsed = (time.perf_counter() - started) * 1000.0
                with self._lock:
                    self.calls += 1
                    self.durations.append(elapsed)
                    if started_during_drag:
                        self.drag_calls += 1

        return timed


class CallCounter:
    """Count calls to a module-level helper (fingerprint inspection)."""

    def __init__(self, original):
        self._original = original
        self.count = 0
        self.drag_active = False
        self.drag_count = 0

    def __call__(self, *args, **kwargs):
        self.count += 1
        if self.drag_active:
            self.drag_count += 1
        return self._original(*args, **kwargs)


def perform_drag(
    harness: WindowHarness,
    moves: int = 5,
) -> tuple[list[float], list[int], bool]:
    """Send a real press/move/release sequence on the canvas."""
    view = harness.view
    canvas = view.canvas
    shape_id = harness.session.current_object().shape_id
    view.dense_review_focus_object(shape_id)
    harness.pump()
    shape = view._dense_review_find_shape(shape_id)
    if shape is None:
        raise BenchmarkError("drag shape is missing")
    before = shape.bounding_rect().center()
    center = shape.bounding_rect().center()
    scale = max(canvas.scale, 1e-6)
    offset = canvas.offset_to_center()
    point = (center + offset) * scale
    press = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(point.x(), point.y()),
        QtCore.QPointF(point.x(), point.y()),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(press)
    harness.pump()
    latencies: list[float] = []
    frames: list[int] = []
    for step in range(1, moves + 1):
        position = QtCore.QPointF(point.x() + step, point.y() + step)
        move = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            position,
            position,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        harness._canvas_counter.reset()
        started = time.perf_counter()
        canvas.mouseMoveEvent(move)
        harness.pump()
        latencies.append((time.perf_counter() - started) * 1000.0)
        frames.append(harness._canvas_counter.count)
    position = QtCore.QPointF(point.x() + moves, point.y() + moves)
    release = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        position,
        position,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseReleaseEvent(release)
    harness.pump()
    after = shape.bounding_rect().center()
    moved = (after - before).manhattanLength() > 0.0
    return latencies, frames, moved


def measure_drag(
    harness: WindowHarness,
    samples: int,
    before_drag: Optional[Callable[[], None]] = None,
    background: bool = False,
) -> tuple[list[float], dict[str, Any]]:
    moves = 5
    drags = max(1, int(math.ceil(samples / float(moves))))
    values: list[float] = []
    frame_counts: list[int] = []
    moved_any = False
    active_samples = 0
    pending_peak = 0
    crop_recorder = getattr(harness, "crop_recorder", None)
    fingerprint = getattr(harness, "fingerprint_counter", None)
    request_counter = getattr(harness, "request_counter", None)
    for drag_index in range(drags):
        if before_drag is not None and drag_index == 0:
            before_drag()
        if crop_recorder is not None:
            crop_recorder.drag_active = True
        if fingerprint is not None:
            fingerprint.drag_active = True
        if request_counter is not None:
            request_counter.drag_active = True
        try:
            latencies, frames, moved = perform_drag(harness, moves)
        finally:
            if crop_recorder is not None:
                crop_recorder.drag_active = False
            if fingerprint is not None:
                fingerprint.drag_active = False
            if request_counter is not None:
                request_counter.drag_active = False
        moved_any = moved_any or moved
        values.extend(latencies)
        frame_counts.extend(frames)
        if background:
            pending = len(harness.provider._pending)
            pending_peak = max(pending_peak, pending)
            if pending:
                active_samples += len(latencies)
    meta = {
        "moves_per_drag": moves,
        "drags": drags,
        "moved": moved_any,
        "frame_paints": frame_counts,
        "frame_paints_min": min(frame_counts) if frame_counts else 0,
    }
    if background:
        meta["pending_peak"] = pending_peak
        meta["samples_with_background_work"] = active_samples
        meta["background_active_fraction"] = round(
            active_samples / float(max(1, len(values))), 3
        )
    return values[:samples], meta


# -- report assembly ----------------------------------------------------


def _environment(
    dataset: dict[str, Any],
    harness: WindowHarness,
) -> dict[str, Any]:
    app = harness.app
    screen = app.primaryScreen()
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "pyqt": QtCore.PYQT_VERSION_STR,
        "qt": QtCore.QT_VERSION_STR,
        "qt_qpa_platform": os.environ.get("QT_QPA_PLATFORM", ""),
        "offscreen": os.environ.get("QT_QPA_PLATFORM") == "offscreen",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "pid": os.getpid(),
        "repo_root": str(REPO_ROOT),
        "device_pixel_ratio": (
            screen.devicePixelRatio() if screen is not None else None
        ),
        "image": {
            "width": dataset["width"],
            "height": dataset["height"],
            "objects": dataset["object_count"],
            "labels": dataset["labels"],
            "file_bytes": dataset["file_bytes"],
        },
        "window": {"width": 1600, "height": 1000},
        "workspace": {
            "width": harness.workspace.width(),
            "height": harness.workspace.height(),
        },
        "thumbnail_target": list(THUMBNAIL_TARGET),
        "context_percent": harness.workspace.context_spin.value(),
        "cache_limit": int(harness.provider._cache_limit),
        "batches": [
            {
                "id": batch.batch_id,
                "name": batch.name,
                "members": len(batch.member_ids),
            }
            for batch in harness.session.state.batches
        ],
    }


def _thresholds(report: dict[str, Any]) -> list[dict[str, Any]]:
    conditions = report["conditions"]

    def summary(name: str) -> dict[str, Any]:
        return conditions[name]["summary"]

    warm_object = summary("object_switch_warm")["p95_ms"]
    warm_batch = summary("batch_switch_warm")["p95_ms"]
    batch_measured = summary("batch_switch_warm")["count"] > 0
    combined = max(warm_object, warm_batch) if batch_measured else 0.0
    heartbeat = summary("heartbeat_cards")["p95_ms"]
    heartbeat_count = summary("heartbeat_cards")["count"]
    baseline = summary("drag_baseline")["p95_ms"]
    drag_open = summary("drag_open_all")["p95_ms"]
    drag_background = summary("drag_open_background")["p95_ms"]

    def regression(value: float) -> float:
        if baseline <= 0.0:
            return 0.0
        return round((value - baseline) / baseline * 100.0, 3)

    def check(
        check_id: str,
        measured: float,
        limit: float,
        unit: str,
        comparison: str,
        extra: Optional[dict[str, Any]] = None,
        measured_ok: bool = True,
    ) -> dict[str, Any]:
        passed = measured_ok and measured <= limit
        item = {
            "id": check_id,
            "measured": measured,
            "limit": limit,
            "unit": unit,
            "comparison": comparison,
            "passed": bool(passed),
            "threshold": True,
        }
        if not measured_ok:
            item["unsampled"] = True
        if extra:
            item.update(extra)
        return item

    return [
        check(
            "warm_object_switch_p95",
            warm_object,
            THRESHOLDS["warm_switch_p95_ms"],
            "ms",
            "measured <= limit",
            measured_ok=summary("object_switch_warm")["count"] > 0,
        ),
        check(
            "warm_batch_switch_p95",
            warm_batch,
            THRESHOLDS["warm_switch_p95_ms"],
            "ms",
            "measured <= limit",
            measured_ok=batch_measured,
        ),
        check(
            "warm_switch_p95_combined",
            combined,
            THRESHOLDS["warm_switch_p95_ms"],
            "ms",
            "max(object, batch) <= limit",
            measured_ok=batch_measured,
        ),
        check(
            "heartbeat_cards_p95",
            heartbeat,
            THRESHOLDS["heartbeat_p95_ms"],
            "ms",
            "measured <= limit",
            measured_ok=heartbeat_count > 0,
        ),
        check(
            "drag_open_regression",
            regression(drag_open),
            THRESHOLDS["drag_regression_pct"],
            "%",
            "regression <= limit",
            {
                "baseline_p95_ms": baseline,
                "condition_p95_ms": drag_open,
            },
            measured_ok=summary("drag_baseline")["count"] > 0,
        ),
        check(
            "drag_background_regression",
            regression(drag_background),
            THRESHOLDS["drag_regression_pct"],
            "%",
            "regression <= limit",
            {
                "baseline_p95_ms": baseline,
                "condition_p95_ms": drag_background,
            },
            measured_ok=summary("drag_baseline")["count"] > 0,
        ),
    ]


def _summary_line(report: dict[str, Any]) -> str:
    parts = []
    for check in report["thresholds"]:
        state = "PASS" if check["passed"] else "FAIL"
        parts.append(
            "%s=%s(%.3f%s)"
            % (check["id"], state, check["measured"], check["unit"])
        )
    return "; ".join(parts)


# -- main benchmark -----------------------------------------------------


def run_benchmark(
    object_count: int = 30,
    samples: int = 30,
    repeats: int = 3,
    seed: int = 11,
    json_path: Optional[str] = None,
    allow_fail: bool = False,
    keep_temp: bool = False,
    work_root: Optional[str] = None,
    lifecycle_switches: int = 0,
) -> dict[str, Any]:
    """Run the whole benchmark and return the JSON-ready report."""
    if object_count < 2:
        raise BenchmarkError("benchmark needs at least two objects")
    if samples < 1 or repeats < 1:
        raise BenchmarkError("samples and repeats must be positive")
    base = Path(work_root) if work_root else REPO_ROOT / ".tmp"
    run_root = base / ("dense-review-bench-" + uuid.uuid4().hex[:10])
    os.makedirs(run_root, mode=0o777, exist_ok=False)
    dataset_root = run_root / "dataset"
    started_at = time.perf_counter()
    report: dict[str, Any] = {
        "schema": "dense-review-benchmark/2",
        "config": {
            "objects": object_count,
            "samples": samples,
            "repeats": repeats,
            "seed": seed,
            "allow_fail": bool(allow_fail),
            "heartbeat_interval_ms": HEARTBEAT_INTERVAL_MS,
        },
        "conditions": {},
        "harness": {"errors": [], "warnings": []},
    }
    conditions: dict[str, Condition] = {
        name: Condition(name)
        for name in (
            "object_switch_cold",
            "object_switch_warm",
            "batch_switch_cold",
            "batch_switch_warm",
            "heartbeat_idle",
            "heartbeat_cards",
            "drag_baseline",
            "drag_open_all",
            "drag_open_focus",
            "drag_open_background",
            "text_refresh",
        )
    }
    harness: Optional[WindowHarness] = None
    recorder = CropRecorder()
    fingerprint = None
    original_crop = None
    try:
        dataset = synthesize_dataset(dataset_root, object_count, seed=seed)
        harness = WindowHarness(dataset, run_root)
        harness.open()
        report["environment"] = _environment(dataset, harness)
        report["harness"]["notes"] = [
            "Offscreen Qt uses software rasterization; absolute drag "
            "latency is not comparable to a GPU desktop session. Compare "
            "the relative open/closed regression instead.",
            "The offscreen QFontDatabase has no font directory, so card "
            "text rasterization may be cheaper than on a desktop session.",
            "A cold switch resets the whole ThumbnailProvider generation "
            "before the sample; a warm switch reuses the warmed LRU.",
            "Batch switching uses the public list selection path. Each "
            "navigation sample waits for a paint of the correct selected "
            "target with enabled, non-loading canvas and matching batch "
            "and card selection. A mismatched target or timeout aborts "
            "the harness rather than becoming a fast passing sample.",
            "Each drag sample is one synthetic mouse move plus one event "
            "loop turn; each drag moves the box by five screen pixels and "
            "releases it, which triggers the production card refresh.",
            "The host may run unrelated work concurrently; every "
            "condition is repeated three times and the threshold uses "
            "the p95 of all 90 samples, with per-repeat p95 reported.",
        ]
        original_crop = thumbnails_module.crop_thumbnail
        thumbnails_module.crop_thumbnail = recorder.wrap(original_crop)
        fingerprint = CallCounter(label_widget_module.image_fingerprint)
        label_widget_module.image_fingerprint = fingerprint
        harness.crop_recorder = recorder
        harness.fingerprint_counter = fingerprint
        request_counter = CallCounter(
            harness.workspace._request_visible_thumbnails
        )
        harness.workspace._request_visible_thumbnails = request_counter
        harness.request_counter = request_counter

        cache_before = harness.cache_snapshot()
        cache_probe: dict[str, Any] = {}
        for repeat_index in range(repeats):
            if repeat_index > 0:
                harness.reset_round()
            _measure_repeat(
                harness,
                conditions,
                samples,
                repeat_index,
                cache_probe if repeat_index == 0 else None,
                allow_fail,
            )
        report["conditions"] = {
            name: condition.report() for name, condition in conditions.items()
        }
        report["cold_warm_deltas"] = _cold_warm_deltas(report["conditions"])
        report["cache"] = _cache_report(harness, cache_before, cache_probe)
        if lifecycle_switches:
            report["image_lifecycle"] = probe_image_lifecycle(
                harness, lifecycle_switches
            )
        report["source_pixels"] = {
            "thumbnail_source_cache": "none; crop_thumbnail re-opens the "
            "image file for each request",
            "crop_calls": recorder.calls,
            "crop_duration_ms": summarize(recorder.durations),
            "crops_started_during_drag": recorder.drag_calls,
            "request_passes_during_drag": (request_counter.drag_count),
            "fingerprint_calls": fingerprint.count,
            "fingerprint_calls_during_drag": fingerprint.drag_count,
        }
    except Exception as error:  # noqa: BLE001
        report["harness"]["errors"].append(
            "%s: %s" % (type(error).__name__, error)
        )
        report["harness"]["traceback"] = traceback.format_exc()
        raise
    finally:
        if harness is not None:
            harness.close()
        if original_crop is not None:
            thumbnails_module.crop_thumbnail = original_crop
        if fingerprint is not None:
            label_widget_module.image_fingerprint = fingerprint._original
        report["elapsed_seconds"] = round(time.perf_counter() - started_at, 3)
        report["harness"]["warnings"] = report["harness"].get("warnings", [])
        if not keep_temp:
            shutil.rmtree(run_root, ignore_errors=True)
        else:
            report["temp_root"] = str(run_root)

    report["thresholds"] = _thresholds(report)
    report["passed"] = all(
        item["passed"]
        for item in report["thresholds"]
        if item.get("threshold")
    )
    report["summary"] = _summary_line(report)
    if json_path:
        destination = Path(json_path)
        if not destination.is_absolute():
            destination = Path.cwd() / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def _cold_warm_deltas(
    conditions: dict[str, Any],
) -> dict[str, Any]:
    """Report how much the warm cache reduces each switch p50/p95."""
    result: dict[str, Any] = {}
    pairs = {
        "object_switch": (
            "object_switch_cold",
            "object_switch_warm",
        ),
        "batch_switch": (
            "batch_switch_cold",
            "batch_switch_warm",
        ),
    }
    for name, (cold_name, warm_name) in pairs.items():
        cold = conditions[cold_name]["summary"]
        warm = conditions[warm_name]["summary"]
        if not cold["count"] or not warm["count"]:
            result[name] = {"measured": False}
            continue

        def reduction(cold_value: float, warm_value: float) -> float:
            if cold_value <= 0.0:
                return 0.0
            return round((cold_value - warm_value) / cold_value * 100.0, 3)

        result[name] = {
            "measured": True,
            "cold_p50_ms": cold["p50_ms"],
            "warm_p50_ms": warm["p50_ms"],
            "p50_reduction_pct": reduction(cold["p50_ms"], warm["p50_ms"]),
            "cold_p95_ms": cold["p95_ms"],
            "warm_p95_ms": warm["p95_ms"],
            "p95_reduction_pct": reduction(cold["p95_ms"], warm["p95_ms"]),
        }
    return result


def _measure_repeat(
    harness: WindowHarness,
    conditions: dict[str, Condition],
    samples: int,
    repeat_index: int,
    cache_probe: Optional[dict[str, Any]],
    allow_unsampled: bool = False,
) -> None:
    """Take every condition once for one repetition."""
    workspace = harness.workspace
    batches = harness.non_empty_batches()
    if not batches:
        raise BenchmarkError("the fixture produced no review batches")

    first_batch = batches[0]
    object_targets = harness.ids_for_batch(first_batch)[:samples]
    if not object_targets:
        raise BenchmarkError("the first batch has no objects")

    cold_values = []
    for index in range(samples):
        shape_id = object_targets[index % len(object_targets)]
        harness.reset_thumbnail_cache()
        value, _canvas, _cards = measure_switch(
            harness,
            lambda batch=first_batch, sid=shape_id: (
                workspace._navigate_to(batch, sid)
            ),
            expected_batch=first_batch,
            expected_object=shape_id,
        )
        cold_values.append(value)
    conditions["object_switch_cold"].add_repeat(cold_values)

    harness.warm_batch(first_batch, object_targets)
    warm_values = []
    for index in range(samples):
        shape_id = object_targets[index % len(object_targets)]
        value, _canvas, _cards = measure_switch(
            harness,
            lambda batch=first_batch, sid=shape_id: (
                workspace._navigate_to(batch, sid)
            ),
            expected_batch=first_batch,
            expected_object=shape_id,
        )
        warm_values.append(value)
    conditions["object_switch_warm"].add_repeat(warm_values)

    if len(batches) >= 2:
        batch_values = batches[:2]
        cold_batch = []
        for index in range(samples):
            batch_id = batch_values[(index + 1) % len(batch_values)]
            harness.reset_thumbnail_cache()
            row = harness.batch_row(batch_id)
            value, _canvas, _cards = measure_switch(
                harness,
                lambda target=row: (
                    workspace.batch_list.setCurrentRow(target)
                ),
                expected_batch=batch_id,
                expected_object=harness.ids_for_batch(batch_id)[0],
            )
            cold_batch.append(value)
        conditions["batch_switch_cold"].add_repeat(cold_batch)

        for batch_id in batch_values:
            row = harness.batch_row(batch_id)
            workspace.batch_list.setCurrentRow(row)
            harness.pump()
            workspace._request_visible_thumbnails()
            harness.pump()
            harness.wait_for_thumbnails()
        workspace.batch_list.setCurrentRow(harness.batch_row(batch_values[0]))
        harness.pump()
        warm_batch_values = []
        for index in range(samples):
            batch_id = batch_values[(index + 1) % len(batch_values)]
            row = harness.batch_row(batch_id)
            value, _canvas, _cards = measure_switch(
                harness,
                lambda target=row: (
                    workspace.batch_list.setCurrentRow(target)
                ),
                expected_batch=batch_id,
                expected_object=harness.ids_for_batch(batch_id)[0],
            )
            warm_batch_values.append(value)
        conditions["batch_switch_warm"].add_repeat(warm_batch_values)
    else:
        note = "fewer than two non-empty batches"
        for name in (
            "batch_switch_cold",
            "batch_switch_warm",
        ):
            conditions[name].unsampled = True
            conditions[name].meta["note"] = note
        if not allow_unsampled:
            raise BenchmarkError(note)

    harness.wait_for_thumbnails()
    idle, idle_meta = measure_heartbeat(harness, samples, False)
    conditions["heartbeat_idle"].add_repeat(idle)
    conditions["heartbeat_idle"].meta.update(idle_meta)
    cards, card_meta = measure_heartbeat(harness, samples, True)
    conditions["heartbeat_cards"].add_repeat(cards)
    conditions["heartbeat_cards"].meta.update(card_meta)
    harness.wait_for_thumbnails()

    text_values = []
    for _ in range(samples):
        text_values.append(
            time_call(
                harness,
                lambda: workspace._refresh_cards(force=False),
            )
        )
    conditions["text_refresh"].add_repeat(text_values)

    _measure_drag_conditions(harness, conditions, samples)
    if cache_probe is not None:
        cache_probe.update(_probe_cache(harness))
    harness.process(0.05)


def _warm_drag(harness: WindowHarness) -> None:
    """Discard one two-move drag before timing a condition."""
    perform_drag(harness, 2)
    harness.pump()


def _measure_drag_conditions(
    harness: WindowHarness,
    conditions: dict[str, Condition],
    samples: int,
) -> None:
    """Measure drags with the workspace closed, open and under load."""
    view = harness.view
    workspace = harness.workspace
    if not workspace.isVisible():
        view.open_dense_review()
        harness.pump()
        harness.wait_for_thumbnails()

    def marks() -> tuple[int, int]:
        return (
            harness.crop_recorder.drag_calls,
            harness.request_counter.drag_count,
        )

    def annotate(meta: dict[str, Any], base: tuple[int, int]) -> None:
        meta["crops_started_during_drag"] = (
            harness.crop_recorder.drag_calls - base[0]
        )
        meta["request_passes_during_drag"] = (
            harness.request_counter.drag_count - base[1]
        )

    view.dense_review_set_display_mode("all")
    harness.pump()
    _warm_drag(harness)
    base = marks()
    values, meta = measure_drag(harness, samples)
    annotate(meta, base)
    conditions["drag_open_all"].add_repeat(values)
    conditions["drag_open_all"].meta.update(meta)

    view.dense_review_set_display_mode("focus")
    harness.pump()
    _warm_drag(harness)
    base = marks()
    values, meta = measure_drag(harness, samples)
    annotate(meta, base)
    conditions["drag_open_focus"].add_repeat(values)
    conditions["drag_open_focus"].meta.update(meta)

    view.dense_review_set_display_mode("all")
    harness.pump()
    _warm_drag(harness)

    def start_background() -> None:
        targets = harness.all_shape_ids()
        if len(targets) > 60:
            current = harness.session.current_object()
            batch_id = harness.batch_for_object(current.shape_id)
            targets = harness.ids_for_batch(batch_id)
        rounds = 3 if len(targets) <= 60 else 1
        for _ in range(rounds):
            harness.request_objects(targets)
        harness.pump()

    base = marks()
    values, meta = measure_drag(
        harness, samples, before_drag=start_background, background=True
    )
    annotate(meta, base)
    conditions["drag_open_background"].add_repeat(values)
    conditions["drag_open_background"].meta.update(meta)

    workspace.close()
    harness.pump()
    harness.wait_for_thumbnails(15.0)
    if workspace.isVisible():
        raise BenchmarkError("the workspace did not close")
    _warm_drag(harness)
    base = marks()
    values, meta = measure_drag(harness, samples)
    annotate(meta, base)
    conditions["drag_baseline"].add_repeat(values)
    conditions["drag_baseline"].meta.update(meta)

    view.open_dense_review()
    harness.pump()
    harness.wait_for_thumbnails()


def _probe_cache(harness: WindowHarness) -> dict[str, Any]:
    """Navigate through many objects and watch the LRU cache plateau."""
    ids = harness.all_shape_ids()
    if not ids:
        raise BenchmarkError("no objects available for the cache probe")
    switches = min(300, max(90, len(ids)))
    trace: list[dict[str, Any]] = []
    entries_series: list[int] = []
    peak_entries = 0
    peak_bytes = 0
    sample_every = max(1, switches // 20)
    started = time.perf_counter()
    before = harness.cache_snapshot()
    current_batch = None
    for index in range(switches):
        shape_id = ids[index % len(ids)]
        batch_id = harness.batch_for_object(shape_id)
        if batch_id != current_batch:
            harness.workspace.batch_list.setCurrentRow(
                harness.batch_row(batch_id)
            )
            harness.pump()
            current_batch = batch_id
        harness.workspace._navigate_to(batch_id, shape_id)
        harness.pump()
        harness.wait_for_thumbnails(5.0)
        snapshot = harness.cache_snapshot()
        entries_series.append(snapshot["entries"])
        peak_entries = max(peak_entries, snapshot["entries"])
        peak_bytes = max(peak_bytes, snapshot["bytes"])
        if index % sample_every == 0 or index == switches - 1:
            trace.append(
                {
                    "switch": index + 1,
                    "entries": snapshot["entries"],
                    "bytes": snapshot["bytes"],
                    "pending": snapshot["pending"],
                    "latest_requests": snapshot["latest_requests"],
                    "card_request_keys": snapshot["card_request_keys"],
                }
            )
    final = harness.cache_snapshot()
    provider = harness.provider
    unique = len(ids)
    target = min(unique, provider._cache_limit)
    plateau_switch = next(
        (
            index + 1
            for index, entries in enumerate(entries_series)
            if entries >= target
        ),
        switches,
    )
    late = entries_series[plateau_switch - 1 :]
    bounded = (
        peak_entries <= provider._cache_limit
        and final["entries"] <= provider._cache_limit
        and all(entries <= target for entries in late)
    )
    return {
        "probe": {
            "switches": switches,
            "unique_objects": unique,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "before": before,
            "after": final,
            "peak_entries": peak_entries,
            "peak_bytes": peak_bytes,
            "plateau_switch": plateau_switch,
            "plateau_entries": target,
            "late_entries_max": max(late) if late else 0,
            "final": final,
            "bounded": bounded,
            "trace": trace,
        }
    }


def _cache_report(
    harness: WindowHarness,
    before: dict[str, Any],
    probe: dict[str, Any],
) -> dict[str, Any]:
    provider = harness.provider
    data = {
        "provider": "anylabeling.views.labeling.dense_review"
        ".thumbnails.ThumbnailProvider",
        "limit_entries": int(provider._cache_limit),
        "target_size": list(THUMBNAIL_TARGET),
        "margin_ratio": harness.workspace.context_spin.value() / 100.0,
        "key_fields": [
            "shape_id",
            "generation",
            "bounds",
            "margin_ratio",
            "target_size",
            "source_version",
        ],
        "initial": before,
        "after": harness.cache_snapshot(),
    }
    data.update(probe)
    if "probe" in data:
        data["peak_entries"] = data["probe"]["peak_entries"]
        data["peak_bytes"] = data["probe"]["peak_bytes"]
        data["bounded"] = data["probe"]["bounded"]
    # A generation action must drop every cached image and per-shape key.
    workspace = harness.workspace
    workspace._generation += 1
    provider.start_generation(workspace._generation)
    workspace._last_thumb_generation = provider.generation
    workspace._card_request_keys.clear()
    workspace._failed_ids.clear()
    reset = harness.cache_snapshot()
    workspace.refresh_all(force_cards=True)
    harness.pump()
    data["image_switch_reset"] = reset
    data["reset_cleared_entries"] = reset["entries"] == 0
    data["notes"] = [
        "Image entries are bounded by the provider LRU "
        "(limit_entries); the probe shows the plateau.",
        "latest_requests/card_request_keys are one small tuple per "
        "visited object, not per switch or per pixel; start_generation "
        "clears them.",
        "The provider has no source-pixel cache: crop_thumbnail opens "
        "the image file once per request on a worker thread.",
    ]
    return data


# -- command line -------------------------------------------------------


def probe_image_lifecycle(harness: WindowHarness, switches: int) -> dict:
    """Load real image/annotation/output paths, never fake a generation."""
    import psutil

    process = psutil.Process()
    dataset = harness.dataset
    source = Path(dataset["image_path"])
    annotation = json.loads(
        Path(dataset["annotation_path"]).read_text(encoding="utf-8")
    )
    paths = []
    output = harness.root / "lifecycle-output"
    output.mkdir(exist_ok=True)
    for index in range(2):
        path = source.with_name("lifecycle-%s.png" % index)
        shutil.copyfile(source, path)
        payload = dict(annotation, imagePath=path.name)
        text = json.dumps(payload)
        path.with_suffix(".json").write_text(text, encoding="utf-8")
        (output / path.with_suffix(".json").name).write_text(
            text, encoding="utf-8"
        )
        paths.append(path)
    view = harness.view
    if view.dirty and not view._save_file(view.get_label_file()):
        raise BenchmarkError("could not save synthetic drag results")
    trace = []
    for index in range(switches):
        view.output_dir = str(output) if (index // 2) % 2 else ""
        if not view.load_file(str(paths[index % 2])):
            raise BenchmarkError("real lifecycle image load failed")
        harness.pump()
        harness.workspace = view.dense_review_workspace
        if index % 4 == 0:
            harness.workspace.close()
            view.open_dense_review()
            harness.pump()
        harness.workspace._request_visible_thumbnails()
        harness._wait_until(
            lambda: not harness.provider._pending
            and harness.provider.resource_stats()["outstanding"] == 0,
            10,
            "real lifecycle crops",
        )
        stats = harness.cache_snapshot()
        stats.update(
            switch=index + 1,
            image=str(view.image_path),
            output_dir=view.output_dir,
            rss_bytes=process.memory_info().rss,
        )
        trace.append(stats)
    bounded = all(
        row["entries"] <= row["limit"]
        and row["resources"]["icons"]
        <= harness.workspace._card_model.ICON_LIMIT
        and row["worker"]["outstanding"] <= row["worker"]["limit"]
        and row["pending"] == 0
        for row in trace
    )
    return {
        "switches": switches,
        "method": "normal load_file, two images, two outputs, close/reopen",
        "trace": trace,
        "bounded_graphical_resources": bounded,
        "peak_rss_bytes": max(row["rss_bytes"] for row in trace),
        "memory_note": "RSS includes Qt/allocator caches; inspect warm "
        "trace for growth separately from discrete cache limits.",
    }


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offscreen dense-review GUI benchmark"
    )
    parser.add_argument(
        "--objects",
        type=int,
        required=True,
        choices=(30, 300),
        help="number of synthesized rectangle objects",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=30,
        help="samples per condition per repetition (default: 30)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="repetitions of every condition (default: 3)",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default="",
        help="write the raw JSON report to this path",
    )
    parser.add_argument(
        "--allow-fail",
        action="store_true",
        help=(
            "accepted for CI compatibility; threshold breaches never "
            "change the exit code. A condition that cannot be measured "
            "is recorded instead of aborting the run"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=11,
        help="fixture synthesis seed (default: 11)",
    )
    parser.add_argument(
        "--lifecycle-switches",
        type=int,
        default=0,
        help="also probe real image/output-directory switching and RSS",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="keep the synthesized fixture directory",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        report = run_benchmark(
            object_count=args.objects,
            samples=args.samples,
            repeats=args.repeats,
            seed=args.seed,
            json_path=args.json_path or None,
            allow_fail=args.allow_fail,
            keep_temp=args.keep_temp,
            lifecycle_switches=args.lifecycle_switches,
        )
    except Exception as error:  # noqa: BLE001
        payload = {
            "schema": "dense-review-benchmark/1",
            "harness_error": "%s: %s" % (type(error).__name__, error),
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(
            "[bench] harness error: %s" % error,
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        "[bench] objects=%s samples=%s repeats=%s elapsed=%.1fs"
        % (
            args.objects,
            args.samples,
            args.repeats,
            report.get("elapsed_seconds", 0.0),
        ),
        file=sys.stderr,
    )
    print("[bench] %s" % report["summary"], file=sys.stderr)
    for check in report["thresholds"]:
        print(
            "[bench] %-30s %s measured=%.3f limit=%.3f %s"
            % (
                check["id"],
                "PASS" if check["passed"] else "FAIL",
                check["measured"],
                check["limit"],
                check["unit"],
            ),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

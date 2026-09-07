"""Measure synthetic thumbnail browsing with a real SQLite index and Qt."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

import psutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.dataset_index import DatasetFilterIndex
from anylabeling.views.labeling.widgets.dataset_thumbnail import (
    DatasetLabelThumbnailWindow,
)


class Controller(QtCore.QObject):
    """Adapt a real index to the read-only browser interface."""

    is_query_ready = True
    state_value = "ready"
    is_busy = False

    def __init__(self, index: DatasetFilterIndex) -> None:
        """Keep the index in the GUI thread, as in the application."""
        super().__init__()
        self.index = index

    def __getattr__(self, name: str):
        """Delegate index query methods."""
        return getattr(self.index, name)


def elapsed(start: float) -> float:
    """Return milliseconds since a monotonic timestamp."""
    return (time.perf_counter() - start) * 1000


def settle(app, window, timeout: float = 20) -> dict:
    """Measure the first visible screen and event processing stalls."""
    start = last = time.perf_counter()
    longest = first = 0.0
    while time.perf_counter() - start < timeout:
        app.processEvents()
        now = time.perf_counter()
        longest = max(longest, (now - last) * 1000)
        last = now
        if window._model._images and not first:
            first = elapsed(start)
        viewport = window.view.viewport().rect()
        rows = [
            row
            for row in range(window._model.rowCount())
            if window.view.visualRect(window._model.index(row, 0)).intersects(
                viewport
            )
        ]
        if rows and all(
            window._model.item_key(window._model.ref_at(row))
            in window._model._images
            for row in rows
        ):
            return dict(
                first_ms=first, screen_ms=elapsed(start), event_gap_ms=longest
            )
        time.sleep(0.001)
    raise RuntimeError("visible thumbnails did not finish")


def sample(app, root: Path, count: int, size: tuple) -> dict:
    """Generate patterned fixtures and measure cold/hot browser behavior."""
    root.mkdir()
    paths = []
    for i in range(8):
        path = root / f"{i}.png"
        img = QtGui.QImage(*size, QtGui.QImage.Format.Format_RGB32)
        painter = QtGui.QPainter(img)
        for y in range(0, size[1], 16):
            painter.fillRect(
                0, y, size[0], 16, QtGui.QColor((y + i) % 255, 90, 140)
            )
        painter.end()
        img.save(str(path))
        shapes = [
            dict(
                label="person" if j % 3 else "head",
                shape_type="rectangle",
                xanylabeling_shape_id=f"{i * count + j:032x}",
                points=[[30 + j % 20, 40], [160, 240]],
            )
            for j in range(count // 8)
        ]
        path.with_suffix(".json").write_text(
            json.dumps(dict(shapes=shapes)), encoding="utf-8"
        )
        paths.append(str(path))
    index = DatasetFilterIndex(str(root / "index.sqlite"))
    t = time.perf_counter()
    index.rebuild(paths, dataset_root=str(root))
    result = dict(scan_ms=elapsed(t), objects=count, resolution=size)
    t = time.perf_counter()
    index.query_thumbnail_objects("person")
    result["query_ms"] = elapsed(t)
    t = time.perf_counter()
    options = {}
    if (
        "defer_initial_load"
        in inspect.signature(DatasetLabelThumbnailWindow).parameters
    ):
        options["defer_initial_load"] = True
    window = DatasetLabelThumbnailWindow(
        Controller(index), "bench", str(root), **options
    )
    # Isolate disposable test caches from user caches.
    window._renderer.disk.root = str(root / "cache")
    stages = []
    window._renderer.result_ready.connect(
        lambda value: stages.append(getattr(value, "timings_ms", {}))
    )
    window.show()
    result["shell_ms"] = elapsed(t)
    result["cold"] = settle(app, window)
    memory = psutil.Process().memory_info()
    result["rss_after_screen_mb"] = memory.rss / 1024**2
    result["process_peak_rss_mb"] = (
        getattr(memory, "peak_wset", memory.rss) / 1024**2
    )
    result["worker_stages_ms"] = {
        name: sum(stage.get(name, 0) for stage in stages)
        for name in {key for stage in stages for key in stage}
    }
    result["source_decodes"] = sum(
        "source_read_decode" in stage for stage in stages
    )
    t = time.perf_counter()
    window.show()
    window.raise_()
    app.processEvents()
    result["activate_ms"] = elapsed(t)
    ref = index.query_thumbnail_objects("person").items[0]
    t = time.perf_counter()
    window.focus_object(ref.image_path, ref.shape_id)
    result["locate_ms"] = elapsed(t)
    result["hot"] = settle(app, window)
    t = time.perf_counter()
    for _ in range(5):
        window._next_page()
        window._previous_page()
    result["ten_page_changes_ms"] = elapsed(t)
    result["queue_peak"] = getattr(window._renderer, "queue_peak", None)
    result["cancelled_requests"] = getattr(
        window._renderer, "cancelled_requests", None
    )
    t = time.perf_counter()
    window.close()
    app.processEvents()
    result["close_ms"] = elapsed(t)
    index.close()
    return result


def main() -> None:
    """Write reproducible raw samples and percentile summaries as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    data = dict(
        platform=platform.platform(),
        python=platform.python_version(),
        qt=QtCore.QT_VERSION_STR,
        processor=platform.processor(),
        logical_cpus=os.cpu_count(),
        total_ram_mb=psutil.virtual_memory().total / 1024**2,
        storage="local temporary directory; physical medium not identified",
        memory="RSS after screen; process peak is cumulative across samples",
        fixture="synthetic patterned PNG",
        cache="cold application cache; OS cache uncontrolled",
        samples=[],
    )
    with tempfile.TemporaryDirectory(prefix="thumbnail-benchmark-") as tmp:
        for count, size in [
            (104, (640, 480)),
            (504, (1920, 1080)),
            (2000, (3840, 2160)),
        ]:
            for run in range(args.samples):
                item = sample(app, Path(tmp) / f"{count}-{run}", count, size)
                data["samples"].append(item)
        data["summary"] = {}
        for metric in ["shell_ms", "activate_ms", "locate_ms", "close_ms"]:
            values = sorted(item[metric] for item in data["samples"])
            data["summary"][metric] = dict(
                p50=statistics.median(values),
                p95=values[min(len(values) - 1, int(len(values) * 0.95))],
            )
    Path(args.output).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data["summary"], indent=2))


if __name__ == "__main__":
    main()

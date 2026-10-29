"""Measure the repository's folder loader with real files and PyQt6 widgets.

Only folder-list construction is measured: application startup, image decoding,
canvas rendering and EXIF processing are deliberately outside this benchmark.
Repository methods are compiled unchanged from their AST to avoid importing
unrelated model/training dependencies. UI-shell collaborators are minimal.
"""

from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import importlib.util
import json
import logging
import os
import os.path as osp
from pathlib import Path
import platform
import re
import statistics
import sys
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / ".deps"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import natsort
import psutil
from PyQt6 import QtCore, QtGui, QtWidgets, QtTest
from PyQt6.QtCore import Qt


def compile_function(path, name, namespace, class_name=None):
    """Compile an unchanged function from a source file without its imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = tree.body
    if class_name:
        body = next(n for n in body if isinstance(n, ast.ClassDef) and n.name == class_name).body
    node = next(n for n in body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


SEARCH_PATH = ROOT / "anylabeling/views/labeling/utils/file_search.py"
spec = importlib.util.spec_from_file_location("benchmark_file_search", SEARCH_PATH)
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)
WIDGET_PATH = ROOT / "anylabeling/views/labeling/label_widget.py"
QT_PATH = ROOT / "anylabeling/views/labeling/utils/qt.py"
IMAGE_PATH = ROOT / "anylabeling/views/labeling/utils/image.py"

namespace = dict(
    QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, Qt=Qt,
    os=os, osp=osp, re=re, natsort=natsort,
    logger=logging.getLogger("benchmark"), EXTRA_IMAGE_EXTENSIONS=(".heic", ".heif"),
    CHECKED_FIELD_PATTERN=re.compile(r'"checked"\s*:\s*(true|false|"failed")'),
    LabelFile=SimpleNamespace(is_label_file=lambda path: osp.splitext(path)[1].lower() == ".json"),
    parse_search_pattern=search.parse_search_pattern,
    matches_filename=search.matches_filename,
    matches_label_attribute=search.matches_label_attribute,
)
namespace["get_supported_image_extensions"] = compile_function(IMAGE_PATH, "get_supported_image_extensions", namespace)
scan_images = compile_function(QT_PATH, "scan_all_images", namespace)
FileListWidget = compile_function(WIDGET_PATH, "FileListWidget", namespace)
METHODS = {}
for method in (
    "import_image_folder", "_label_file_checked", "_set_file_item_checked",
    "_create_file_list_item", "_annotation_checked_text", "open_next_image",
):
    METHODS[method] = compile_function(WIDGET_PATH, method, namespace, "LabelingWidget")


class Harness(QtWidgets.QWidget):
    """Provide real list widgets and harmless app-shell collaborators."""

    def __init__(self):
        super().__init__()
        self.file_list_widget = FileListWidget()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.file_list_widget)
        self.resize(700, 700)
        self._config = {"file_list_checkbox_editable": False, "exif_scan_enabled": False}
        self.output_dir = None
        self.filename = None
        self.fn_to_index = {}
        self.shared_view_store = {}
        self.compare_view_manager = SimpleNamespace(is_active=lambda: False)
        self.actions = SimpleNamespace(**{
            name: QtGui.QAction(self) for name in (
                "open_next_image", "open_prev_image", "open_next_unchecked_image", "open_prev_unchecked_image"
            )
        })
        self.file_status_icons = {}
        for status, color in ((False, "gray"), (True, "green"), ("failed", "red")):
            pixmap = QtGui.QPixmap(12, 12)
            pixmap.fill(QtGui.QColor(color))
            self.file_status_icons[status] = QtGui.QIcon(pixmap)
        self.last_open_dir = None
        self.stats = {}

    def may_continue(self):
        return True

    def update_browse_actions(self):
        pass

    def toggle_actions(self, value):
        pass


for method, function in METHODS.items():
    setattr(Harness, method, function)


def timed_stage(name, function, stats):
    """Collect inclusive stage times without changing results."""
    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            stats[name] = stats.get(name, 0.0) + time.perf_counter() - started
    return wrapped


def make_dataset(count, case):
    """Create actual PNG/JSON pairs, including three review states."""
    directory = HERE / "data" / f"{case}_{count}"
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "complete.json"
    if marker.exists():
        return directory, json.loads(marker.read_text(encoding="utf-8"))
    image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    png = bytes(buffer.data())
    number = 1 if case == "single" else 50
    first_size = None
    total_bytes = 0
    for i in range(count):
        stem = f"image_{i:05d}"
        shapes = [{
            "label": ("person" if j == 0 and i % 2 == 0 else f"class_{j % 10}"),
            "points": [[1, 1], [20, 1], [20, 20], [1, 20]],
            "group_id": j % 3, "shape_type": "rectangle", "flags": {},
            "description": "manual annotation", "difficult": False,
        } for j in range(number)]
        data = {"version": "4.2.1", "flags": {}}
        if case != "legacy":
            data["checked"] = (False, True, "failed")[i % 3]
        data.update(shapes=shapes, imagePath=f"{stem}.png", imageData=None, imageHeight=32, imageWidth=32)
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        (directory / f"{stem}.png").write_bytes(png)
        (directory / f"{stem}.json").write_bytes(payload)
        first_size = first_size or len(payload)
        total_bytes += len(payload)
    metadata = {"files": count, "shapes_per_file": number, "sample_json_bytes": first_size, "json_total_bytes": total_bytes}
    marker.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return directory, metadata


def validate_list(window, count, case, pattern):
    expected = count // 2 if pattern else count
    assert window.file_list_widget.count() == expected
    assert len(window.fn_to_index) == expected
    for row in (0, expected // 2, expected - 1):
        item = window.file_list_widget.item(row)
        original_index = int(Path(item.text()).stem.split("_")[-1])
        status = False if case == "legacy" else (False, True, "failed")[original_index % 3]
        assert item.data(Qt.ItemDataRole.UserRole) == status
        assert item.checkState() == Qt.CheckState.Checked


def measure(app, directory, count, case, pattern, iteration):
    window = Harness()
    stats = {}
    namespace["utils"] = SimpleNamespace(scan_all_images=timed_stage("scan", scan_images, stats))
    namespace["matches_label_attribute"] = timed_stage("attribute", search.matches_label_attribute, stats)
    window._label_file_checked = timed_stage("status", window._label_file_checked, stats)
    window._create_file_list_item = timed_stage("create_inclusive", window._create_file_list_item, stats)
    window.show()
    QtTest.QTest.qWait(30)
    gc.collect()
    process = psutil.Process()
    rss_before = process.memory_info().rss
    beats = []
    timer = QtCore.QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(time.perf_counter()))
    timer.start()
    QtTest.QTest.qWait(30)
    beats.append(time.perf_counter())
    started = time.perf_counter()
    window.import_image_folder(str(directory), pattern=pattern, load=False)
    returned = time.perf_counter()
    app.processEvents()
    settled = time.perf_counter()
    QtTest.QTest.qWait(30)
    timer.stop()
    validate_list(window, count, case, pattern)
    rss_after = process.memory_info().rss
    result = {
        "case": case, "count": count, "pattern": pattern, "iteration": iteration,
        "loader_seconds": returned - started, "loader_and_initial_events_seconds": settled - started,
        "scan_seconds": stats.get("scan", 0), "status_read_seconds": stats.get("status", 0),
        "attribute_parse_seconds": stats.get("attribute", 0),
        "item_setup_excluding_status_seconds": stats.get("create_inclusive", 0) - stats.get("status", 0),
        "list_insertion_and_other_seconds": returned - started - stats.get("scan", 0) - stats.get("attribute", 0) - stats.get("create_inclusive", 0),
        "largest_heartbeat_gap_seconds": max(b - a for a, b in zip(beats, beats[1:])),
        "rss_delta_mib": (rss_after - rss_before) / 1024 ** 2,
        "rows": window.file_list_widget.count(),
    }
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--counts", type=int, nargs="+", default=[1000, 10000])
    args = parser.parse_args()
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = {
        "environment": {"python": sys.version, "qt": QtCore.QT_VERSION_STR, "pyqt": QtCore.PYQT_VERSION_STR,
                        "os": platform.platform(), "cpu": platform.processor(), "logical_cpu_count": os.cpu_count(),
                        "physical_memory_gib": psutil.virtual_memory().total / 1024 ** 3,
                        "platform_plugin": app.platformName(), "root": str(ROOT)},
        "scope": "Unchanged production directory-loader and status-reader methods, actual PyQt6 QListWidget, valid synthetic PNG and JSON files. App shell is minimal; first-image decode/canvas, EXIF and app startup excluded. OS caches are NOT flushed. Stage wrappers add small timing overhead. Methods run on UI thread. No production code modified.",
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (WIDGET_PATH, QT_PATH, IMAGE_PATH, SEARCH_PATH)},
        "datasets": {}, "runs": [], "summaries": [],
    }
    output = HERE / "results.json"
    for count in args.counts:
        for case in ("single", "multi", "legacy"):
            print(f"Preparing {case} {count}", flush=True)
            directory, metadata = make_dataset(count, case)
            report["datasets"][f"{case}_{count}"] = metadata
            for pattern in (None, "label::person"):
                runs = []
                for iteration in range(1, args.runs + 1):
                    result = measure(app, directory, count, case, pattern, iteration)
                    runs.append(result)
                    report["runs"].append(result)
                    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                summary = {"case": case, "count": count, "pattern": pattern}
                for key in runs[0]:
                    if key.endswith("seconds") or key == "rss_delta_mib":
                        summary[key + "_median"] = statistics.median(r[key] for r in runs)
                summary["loader_seconds_min"] = min(r["loader_seconds"] for r in runs)
                summary["loader_seconds_max"] = max(r["loader_seconds"] for r in runs)
                report["summaries"].append(summary)
                output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {output}", flush=True)


if __name__ == "__main__":
    main()

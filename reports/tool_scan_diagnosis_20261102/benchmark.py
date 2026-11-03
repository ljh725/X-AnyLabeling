"""Read-only measurements of shipped tool paths; no annotation writes."""
from __future__ import annotations

import argparse
import builtins
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.label_dialog import LabelModifyDialog
from anylabeling.views.labeling.widgets.overview_dialog import OverviewDialog
from anylabeling.views.labeling.widgets.unique_label_qlist_widget import UniqueLabelQListWidget


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    network_root = os.path.normcase(os.path.abspath(args.images)).split("站立检测训练集")[0]

    def protect(event, values):
        if event == "open":
            target, mode, flags = values
            if isinstance(target, (str, bytes, os.PathLike)):
                target = os.path.normcase(os.path.abspath(target))
                if target.startswith(network_root) and (
                    (isinstance(mode, str) and any(c in mode for c in "wax+"))
                    or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
                ):
                    raise PermissionError("Benchmark forbids network writes")
        if event in {"os.remove", "os.rename", "os.rmdir", "os.mkdir"}:
            for value in values[:2]:
                if isinstance(value, (str, bytes, os.PathLike)) and os.path.normcase(os.path.abspath(value)).startswith(network_root):
                    raise PermissionError("Benchmark forbids network mutations")

    sys.addaudithook(protect)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    started = time.perf_counter()
    images = sorted(str(p) for p in Path(args.images).iterdir() if p.suffix.lower() == ".jpg")
    names = {p.name for p in Path(args.labels).iterdir() if p.suffix.lower() == ".json"}
    matched = sum(Path(p).stem + ".json" in names for p in images)
    result = {
        "interpreter": sys.executable, "qt": QtCore.QT_VERSION_STR,
        "images": args.images, "labels": args.labels,
        "image_count": len(images), "json_directory_count": len(names),
        "matched_json_count": matched,
        "enumeration_seconds": time.perf_counter() - started,
        "mode": "offscreen; shipped methods; read-only network audit hook; sequential runs, OS/SMB caches uncontrolled",
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [
            ROOT / "anylabeling/views/labeling/widgets/overview_dialog.py",
            ROOT / "anylabeling/views/labeling/widgets/label_dialog.py",
        ]}, "runs": [],
    }
    print(json.dumps({k: result[k] for k in ("image_count", "json_directory_count", "matched_json_count", "enumeration_seconds")}), flush=True)
    if matched != len(images):
        raise RuntimeError("Some image basenames lack matching JSON; verify output_dir before benchmarking")

    def measure(kind, paths):
        parent = QtWidgets.QWidget()
        parent.file_list_widget = QtWidgets.QListWidget()
        parent.file_list_widget.addItems(paths)
        parent.output_dir = args.labels
        parent.supported_shape = Shape.get_supported_shape()
        parent.unique_label_list = UniqueLabelQListWidget()
        parent.label_info = {}
        parent._get_rgb_by_label = lambda label: (0, 255, 0)
        stage = {"tool": kind, "files": len(paths)}
        metrics = {"exists_seconds": 0.0, "exists_calls": 0,
                   "open_seconds": 0.0, "open_calls": 0,
                   "json_load_seconds": 0.0, "json_load_calls": 0,
                   "decode_seconds": 0.0, "shape_count": 0, "classes": set()}
        original_exists, original_open = os.path.exists, builtins.open
        original_load, original_decode = json.load, json.JSONDecoder.decode
        def exists(*a, **kw):
            before = time.perf_counter()
            try:
                return original_exists(*a, **kw)
            finally:
                metrics["exists_seconds"] += time.perf_counter() - before
                metrics["exists_calls"] += 1
        def fopen(*a, **kw):
            before = time.perf_counter()
            try:
                return original_open(*a, **kw)
            finally:
                metrics["open_seconds"] += time.perf_counter() - before
                metrics["open_calls"] += 1
        def decode(*a, **kw):
            before = time.perf_counter()
            try:
                return original_decode(*a, **kw)
            finally:
                metrics["decode_seconds"] += time.perf_counter() - before
        def load(*a, **kw):
            before = time.perf_counter()
            data = original_load(*a, **kw)
            metrics["json_load_seconds"] += time.perf_counter() - before
            metrics["json_load_calls"] += 1
            metrics["shape_count"] += len(data.get("shapes", []))
            metrics["classes"].update(s["label"] for s in data.get("shapes", []) if "label" in s)
            if metrics["json_load_calls"] % 1000 == 0:
                print(f'{kind}: {metrics["json_load_calls"]}/{len(paths)}', flush=True)
            return data

        gaps = []
        last = time.perf_counter()
        def tick():
            nonlocal last
            now = time.perf_counter()
            gaps.append(now - last)
            last = now
        timer = QtCore.QTimer()
        timer.setInterval(10)
        timer.timeout.connect(tick)
        timer.start()
        app.processEvents()
        before = time.perf_counter()
        with patch("os.path.exists", exists), patch("builtins.open", fopen), patch("json.load", load), patch.object(json.JSONDecoder, "decode", decode):
            if kind == "overview":
                dialog = OverviewDialog.__new__(OverviewDialog)
                QtWidgets.QDialog.__init__(dialog, parent)
                dialog.parent = parent
                dialog.supported_shape = parent.supported_shape
                dialog.image_file_list = dialog.get_image_file_list()
                dialog.start_index, dialog.end_index = 1, len(paths)
                dialog.showing_label_infos = True
                dialog.table = QtWidgets.QTableWidget(dialog)
                dialog.populate_table()
                stage["table_rows"] = dialog.table.rowCount()
                stage["table_columns"] = dialog.table.columnCount()
            else:
                # Preserve the real constructor, measure scan and UI separately.
                original_scan, original_ui = LabelModifyDialog.init_label_info, LabelModifyDialog.init_ui
                def scan(obj):
                    t = time.perf_counter()
                    original_scan(obj)
                    stage["init_label_info_seconds"] = time.perf_counter() - t
                def ui(obj):
                    t = time.perf_counter()
                    original_ui(obj)
                    stage["init_ui_seconds"] = time.perf_counter() - t
                with patch.object(LabelModifyDialog, "init_label_info", scan), patch.object(LabelModifyDialog, "init_ui", ui):
                    dialog = LabelModifyDialog(parent)
                stage["table_rows"] = dialog.table_widget.rowCount()
        stage["elapsed_seconds"] = time.perf_counter() - before
        # Drain the pending timer so a GUI-thread stall is included.
        app.processEvents()
        tick()
        timer.stop()
        stage["heartbeat_max_gap_seconds"] = max(gaps, default=0)
        stage["heartbeat_deliveries"] = len(gaps) - 1
        metrics["class_count"] = len(metrics["classes"])
        metrics["classes"] = sorted(metrics["classes"])
        stage.update(metrics)
        result["runs"].append(stage)
        print(json.dumps(stage, ensure_ascii=False), flush=True)
        dialog.close()
        parent.close()
        dialog.deleteLater()
        parent.deleteLater()
        app.processEvents()
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    for kind in ("overview", "label_manager"):
        measure(kind, images[:100])
    for kind in ("overview", "label_manager"):
        measure(kind, images)


if __name__ == "__main__":
    main()

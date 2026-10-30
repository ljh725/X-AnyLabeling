"""Read-only real-application test: output-directory confirmation to painting.

Original datasets are never written: auto-save, keep-prev, and EXIF handling
are disabled in a private application profile. Only the directory-picker return
value is substituted, eliminating human interaction time. All loader and canvas
methods otherwise execute in the genuine MainWindow with application resources.
"""

import copy
import functools
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
import psutil
from unittest.mock import patch

from probe import HERE, ROOT, MainWindow, QtCore, QtWidgets, load_template_config
from PyQt6 import QtTest
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.label_file import LabelFile
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling import utils

IMAGES = Path(r"D:\A0-part2-kps-3-class-dataset\PRW\PRW_image_11792")
LABELS = Path(r"D:\A0-part2-kps-3-class-dataset\PRW\PRW_json_11792")
ACTIVE = False
STATS = {}
COUNTS = {}
RUN_START = 0
FIRST_PAINT = None
FIRST_EDITABLE = None
EXPECTED_SHAPES = 54


PROTECTED_ROOTS = tuple(os.path.normcase(str(path.resolve())) + os.sep for path in (IMAGES, LABELS))


def is_protected(path):
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    value = os.path.normcase(os.path.abspath(os.fsdecode(path)))
    return any(value.startswith(root) or value == root[:-1] for root in PROTECTED_ROOTS)


def reject_dataset_writes(event, args):
    """Reject file writes/deletes/renames into original datasets at runtime."""
    if event == "open" and is_protected(args[0]):
        flags = args[2] or 0
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise PermissionError("Benchmark prohibits writing original datasets")
    if event in ("os.remove", "os.rmdir", "os.mkdir") and is_protected(args[0]):
        raise PermissionError("Benchmark prohibits modifying original datasets")
    if event == "os.rename" and any(is_protected(path) for path in args[:2]):
        raise PermissionError("Benchmark prohibits renaming original datasets")


sys.addaudithook(reject_dataset_writes)


def timed(name, function):
    """Time unchanged real methods; all UI work remains in the UI thread."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        global FIRST_PAINT, FIRST_EDITABLE
        if not ACTIVE:
            return function(*args, **kwargs)
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            ended = time.perf_counter()
            STATS[name] = STATS.get(name, 0.0) + ended - started
            COUNTS[name] = COUNTS.get(name, 0) + 1
            if name == "load_current_file" and args[0].canvas.isEnabled() and FIRST_EDITABLE is None:
                FIRST_EDITABLE = ended - RUN_START
            if name == "canvas_paint" and len(args[0].shapes) == EXPECTED_SHAPES and FIRST_PAINT is None:
                FIRST_PAINT = ended - RUN_START
            if name == "create_file_item" and COUNTS[name] % 2000 == 0:
                print(f"progress {COUNTS[name]}/11792 at {ended-RUN_START:.3f}s", flush=True)
    return wrapped


for owner, attribute, name in (
    (LabelingWidget, "import_image_folder", "folder_import"),
    (LabelingWidget, "_label_file_checked", "status_read"),
    (LabelingWidget, "_create_file_list_item", "create_file_item"),
    (LabelingWidget, "file_selection_changed", "selection_callback"),
    (LabelingWidget, "load_file", "load_current_file"),
    (LabelingWidget, "reset_state", "reset_state"),
    (LabelingWidget, "load_shapes", "widget_load_shapes"),
    (LabelingWidget, "add_label", "add_label"),
    (LabelingWidget, "_restore_shape_locks", "restore_locks"),
    (LabelingWidget, "_refresh_shape_filters", "refresh_filters"),
    (LabelingWidget, "update_thumbnail_display", "thumbnail"),
    (LabelFile, "load", "label_file_parse"),
    (Canvas, "load_shapes", "canvas_load_shapes"),
    (Canvas, "store_shapes", "undo_snapshot"),
    (Canvas, "paintEvent", "canvas_paint"),
    (Shape, "paint", "individual_shape_paint"),
):
    setattr(owner, attribute, timed(name, getattr(owner, attribute)))
utils.scan_all_images = timed("scan_and_sort", utils.scan_all_images)
utils.img_data_to_qimage = timed("decode_image", utils.img_data_to_qimage)
original_property = LabelingWidget.image_list
LabelingWidget.image_list = property(timed("image_list_materialization", original_property.fget))


def source_hashes():
    paths = (
        "anylabeling/views/labeling/label_widget.py",
        "anylabeling/views/labeling/label_file.py",
        "anylabeling/views/labeling/widgets/canvas.py",
        "anylabeling/views/labeling/shape.py",
    )
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def annotation_manifest():
    """Use directory-entry metadata without warming all annotation contents."""
    with os.scandir(LABELS) as entries:
        return {entry.name: (entry.stat().st_size, entry.stat().st_mtime_ns) for entry in entries if entry.is_file() and entry.name.lower().endswith(".json")}


def image_manifest():
    with os.scandir(IMAGES) as entries:
        return {entry.name: (entry.stat().st_size, entry.stat().st_mtime_ns) for entry in entries if entry.is_file()}


def main():
    global ACTIVE, STATS, COUNTS, RUN_START, FIRST_PAINT, FIRST_EDITABLE
    assert IMAGES.is_dir() and LABELS.is_dir()
    print("Reading source manifests (outside timed region)", flush=True)
    labels_before = annotation_manifest()
    images_before = image_manifest()
    sources_before = source_hashes()
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    widget = window.labeling_widget.view
    errors = []
    widget.error_message = lambda *args: errors.append(str(args))
    # Prepare the user's initial state: images are open, no output directory.
    started = time.perf_counter()
    widget.import_image_folder(str(IMAGES))
    deadline = time.perf_counter() + 180
    while (widget._view_timer.isActive() or widget._metadata_timer.isActive()) and time.perf_counter() < deadline:
        QtTest.QTest.qWait(10)
    assert not widget._view_timer.isActive() and not widget._metadata_timer.isActive()
    app.processEvents()
    initial_seconds = time.perf_counter() - started
    assert not errors, errors
    assert widget.file_list_widget.count() == 11792
    assert widget.canvas.shapes == []
    first_image = Path(widget.filename)
    expected_json = LABELS / (first_image.stem + ".json")
    first_data = json.loads(expected_json.read_text(encoding="utf-8"))
    assert len(first_data["shapes"]) == EXPECTED_SHAPES
    first_label_sha = hashlib.sha256(expected_json.read_bytes()).hexdigest()
    print(f"Initial images-only open: {initial_seconds:.3f}s; first={first_image.name}", flush=True)
    report = {
        "date": "2026-10-29 Asia/Shanghai",
        "scope": "Genuine MainWindow with full real signal connections, resource icons and default drawing settings; real user dataset. Offscreen Qt; private config/settings. Directory picker alone is substituted. Autosave, keep-prev, EXIF scan disabled; audit hook rejects original dataset writes/deletes/renames. No app source changes. OS cache not flushed; earlier inspection may warm some files, so this is not a controlled cold-cache test. No human directory-picker time or monitor/GPU presentation latency included.",
        "environment": {"python": sys.version, "qt": QtCore.QT_VERSION_STR, "window": [1600, 1000]},
        "images": str(IMAGES), "labels": str(LABELS), "file_count": len(labels_before),
        "json_total_bytes": sum(v[0] for v in labels_before.values()),
        "first_image": first_image.name, "first_image_dimensions": [first_data["imageWidth"], first_data["imageHeight"]],
        "first_shapes": EXPECTED_SHAPES, "first_shape_types": {kind: sum(s["shape_type"] == kind for s in first_data["shapes"]) for kind in {s["shape_type"] for s in first_data["shapes"]}},
        "initial_images_only_open_seconds": initial_seconds, "source_sha256": sources_before, "runs": [],
    }
    for iteration in range(1, 4):
        STATS, COUNTS = {}, {}
        FIRST_PAINT = None
        FIRST_EDITABLE = None
        heartbeats = []
        rss_samples = []
        process = psutil.Process()
        heartbeat = QtCore.QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: (heartbeats.append(time.perf_counter()), rss_samples.append(process.memory_info().rss)))
        heartbeat.start()
        QtTest.QTest.qWait(30)
        heartbeats.append(time.perf_counter())
        assert widget.file_list_widget.count() == 11792
        RUN_START = time.perf_counter()
        ACTIVE = True
        with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(LABELS)):
            widget.change_output_dir_dialog()
        function_return = time.perf_counter()
        app.processEvents()
        deadline = time.perf_counter() + 10
        while FIRST_PAINT is None and time.perf_counter() < deadline:
            app.processEvents()
            QtTest.QTest.qWait(1)
        first_settled = time.perf_counter()
        deadline = time.perf_counter() + 180
        while widget._metadata_timer.isActive() and time.perf_counter() < deadline:
            QtTest.QTest.qWait(10)
        assert not widget._metadata_timer.isActive(), "Background scan timed out"
        assert widget._metadata_processed == 11791, widget._metadata_processed
        assert widget._metadata_errors == 0, widget._metadata_errors
        assert all(widget._metadata_state(widget.file_list_widget.item(i)) != "unknown" for i in range(widget.file_list_widget.count()))
        settled = time.perf_counter()
        ACTIVE = False
        QtTest.QTest.qWait(30)
        heartbeat.stop()
        assert not errors, errors
        assert FIRST_PAINT is not None, "No paint event with loaded annotations"
        assert len(widget.canvas.shapes) == EXPECTED_SHAPES
        assert len(widget.label_list) == EXPECTED_SHAPES
        assert Path(widget.label_file.filename) == expected_json
        assert hashlib.sha256(expected_json.read_bytes()).hexdigest() == first_label_sha
        result = {
            "full_list_ready_seconds": 0.0,  # reused and complete before confirmation
            "background_complete_seconds": settled-RUN_START,
            "first_editable_seconds": FIRST_EDITABLE,
            "peak_sampled_rss_bytes": max(rss_samples),
            "presence_counts": {str(state): sum(widget.file_list_widget.item(i).checkState() == state for i in range(widget.file_list_widget.count())) for state in (QtCore.Qt.CheckState.Checked, QtCore.Qt.CheckState.Unchecked, QtCore.Qt.CheckState.PartiallyChecked)},
            "queue_limits": {"metadata_batches": 4, "batch_size": 128, "gui_buffer_records": 512},
            "metadata_processed": widget._metadata_processed, "metadata_errors": widget._metadata_errors,
            "heartbeat_p95_seconds": sorted(b-a for a,b in zip(heartbeats, heartbeats[1:]))[int(0.95 * (len(heartbeats)-2))], "iteration": iteration, "output_change_return_seconds": function_return-RUN_START,
            "first_annotated_paint_seconds": FIRST_PAINT, "settled_seconds": settled-RUN_START,
            "largest_ui_heartbeat_gap_seconds": max(b-a for a,b in zip(heartbeats,heartbeats[1:])),
            "stage_seconds_inclusive": dict(STATS), "stage_call_counts": dict(COUNTS),
            "actual_loaded_shapes": len(widget.canvas.shapes), "canvas_pixels": [widget.canvas.width(), widget.canvas.height()],
        }
        report["runs"].append(result)
        (ROOT / "reports/staged_annotation_loading/review2_fix_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    # Separately measure repainting an already loaded frame; do not count loads.
    STATS, COUNTS = {}, {}
    ACTIVE = True
    paints = []
    for _ in range(20):
        started = time.perf_counter()
        widget.canvas.repaint()
        paints.append(time.perf_counter()-started)
    ACTIVE = False
    report["loaded_frame_repaint"] = {
        "trials": len(paints), "median_seconds": statistics.median(paints),
        "min_seconds": min(paints), "max_seconds": max(paints),
        "stage_seconds_inclusive": dict(STATS), "stage_call_counts": dict(COUNTS),
    }
    widget.dirty = False
    window.close()
    app.processEvents()
    print("Verifying all original annotation files unchanged", flush=True)
    assert annotation_manifest() == labels_before
    assert image_manifest() == images_before
    assert source_hashes() == sources_before
    report["read_only_verification"] = {"dataset_write_audit_guard_active": True, "all_json_size_mtime_unchanged": True, "first_json_sha256_unchanged": True, "image_size_mtime_unchanged": True, "source_sha256_unchanged": True}
    report["summary"] = {
        key + "_median": statistics.median(run[key] for run in report["runs"])
        for key in ("output_change_return_seconds", "first_annotated_paint_seconds", "settled_seconds", "largest_ui_heartbeat_gap_seconds")
    }
    (ROOT / "reports/staged_annotation_loading/review2_fix_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("READ_ONLY_VERIFIED", flush=True)


if __name__ == "__main__":
    main()

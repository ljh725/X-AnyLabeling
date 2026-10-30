"""CUSTOM-003 acceptance benchmark: real production code, no substitute slots.

Both the status slot and the canvas refresh path are the shipped methods.  The
only instrumentation is counting wrappers that call the original
implementation, so the numbers can be attributed to the committed change.

Measured per sample: one mouse move = `sendEvent` + one `processEvents` (the
event-queue cost of the moved frame is included, as in the diagnosis report).

Usage:
  python benchmark_drag_fix.py --label fixed  --out results_fixed.json
  python benchmark_drag_fix.py --label baseline --out results_baseline.json
Run the same file from the pre-fix worktree for the baseline numbers.
"""
import argparse
import copy
import hashlib
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROFILE = HERE / "profile"
PROFILE.mkdir(exist_ok=True)
(PROFILE / "config.yaml").write_text("{}", encoding="utf-8")
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

QtCore_settings = QtCore.QSettings
QtCore.QSettings = lambda *a, **kw: QtCore_settings(
    str(PROFILE / "settings.ini"), QtCore_settings.Format.IniFormat
)

from anylabeling import config as app_config  # noqa: E402
from anylabeling.resources import resources  # noqa: F401,E402

app_config._work_directory = str(PROFILE)
app_config.current_config_file = str(PROFILE / "config.yaml")

import yaml  # noqa: E402

from anylabeling.views.labeling.label_widget import LabelingWidget  # noqa: E402
from anylabeling.views.labeling.settings.schema import load_template_config  # noqa: E402
from anylabeling.views.labeling.shape import Shape  # noqa: E402
from anylabeling.views.labeling.widgets.canvas import Canvas  # noqa: E402
from anylabeling.views.mainwindow import MainWindow  # noqa: E402

IMAGE = Path(r"D:\A0-part2-kps-3-class-dataset\PRW\PRW_image_11792\PRW_c1s1_000151.jpg")
LABELS = Path(r"D:\A0-part2-kps-3-class-dataset\PRW\PRW_json_11792")
USER_CONFIG = Path(r"C:\Users\20441\.xanylabelingrc")
PROTECTED = (IMAGE.parent, LABELS)
WINDOW_SIZE = (2560, 1377)

COUNTS = {"paint": 0, "image_list": 0}
ORIGINAL_PAINT = Canvas.paintEvent
ORIGINAL_IMAGE_LIST = LabelingWidget.image_list


def audit(event, args):
    """Refuse any write that targets the read-only dataset directories."""
    if event not in ("open", "os.remove", "os.rename", "os.rmdir", "os.mkdir"):
        return
    values = args[:2] if event == "os.rename" else args[:1]
    for value in values:
        if not isinstance(value, (str, bytes, os.PathLike)):
            continue
        target = Path(os.fsdecode(value)).absolute()
        if not any(target == path or path in target.parents for path in PROTECTED):
            continue
        if event != "open" or (args[2] or 0) & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ):
            raise PermissionError("CUSTOM-003 benchmark keeps datasets read-only")


def install_counters():
    def paint(self, event):
        COUNTS["paint"] += 1
        return ORIGINAL_PAINT(self, event)

    def image_list(self):
        COUNTS["image_list"] += 1
        return ORIGINAL_IMAGE_LIST.fget(self)

    Canvas.paintEvent = paint
    LabelingWidget.image_list = property(image_list)


def summary(values):
    values = sorted(values)
    return {
        "n": len(values),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(values[min(len(values) - 1, int(len(values) * 0.95))], 3),
        "min_ms": round(values[0], 3),
        "max_ms": round(values[-1], 3),
    }


def pump_until(app, condition, limit=180):
    start = time.perf_counter()
    while not condition():
        app.processEvents()
        time.sleep(0.001)
        if time.perf_counter() - start > limit:
            raise TimeoutError("background lifecycle did not finish")


def effective_config(snapshot_path):
    """Return the exact config the window runs with, plus its fingerprint.

    The template config, the saved user config and the benchmark overrides
    (auto_save/keep_prev) all participate, so dumping the merged result is the
    only way to prove two runs used the same display configuration.  When the
    snapshot already exists it is reused verbatim and the user config is not
    read again.
    """
    if snapshot_path is not None and snapshot_path.exists():
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        config = copy.deepcopy(load_template_config())
        config.clear()
        config.update(snapshot)
        return config, hashlib.sha256(snapshot_path.read_bytes()).hexdigest(), True

    config = copy.deepcopy(load_template_config())
    if USER_CONFIG.exists():
        app_config.update_dict(
            config,
            app_config.normalize_user_config(
                yaml.safe_load(USER_CONFIG.read_text(encoding="utf-8"))
            ),
        )
    config.update(auto_save=False, keep_prev=False)
    payload = json.dumps(config, sort_keys=True, ensure_ascii=False, indent=2, default=str)
    if snapshot_path is not None:
        # Hash the file bytes, never the in-memory string: writing on Windows
        # would otherwise turn \n into \r\n and give the same config a
        # different fingerprint in the other tree.
        snapshot_path.write_text(payload, encoding="utf-8", newline="\n")
        return (
            config,
            hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            False,
        )
    return config, hashlib.sha256(payload.encode("utf-8")).hexdigest(), False


def build_window(app, config):
    QtCore_settings(str(PROFILE / "settings.ini"), QtCore_settings.Format.IniFormat).clear()
    window = MainWindow(app, config=config)
    window.resize(*WINDOW_SIZE)
    window.show()
    app.processEvents()
    return window


def reset_target(canvas, target, original_points):
    canvas.moving_shape = False
    target.points = [QtCore.QPointF(p) for p in original_points]
    canvas.shapes_backups = canvas.shapes_backups[:1] or canvas.shapes_backups
    canvas.selection_changed.emit([target])
    canvas.h_vertex = None
    canvas.h_edge = None
    canvas.h_cuboid_face = None
    canvas.h_shape = target
    center = target.bounding_rect().center()
    canvas.prev_point = center
    canvas.calculate_offsets(center)
    return center


def stop_background(widget, app):
    widget._metadata_timer.stop()
    widget._metadata_controller.cancel()
    widget._metadata_results.clear()
    worker = getattr(widget._metadata_controller, "worker", None)
    if worker is not None:
        pump_until(app, lambda: not worker.thread.is_alive())
    widget.async_exif_scanner.stop_scan()
    pump_until(app, lambda: widget.async_exif_scanner.thread is None)


def prime_metadata(widget, app, paths):
    widget.file_list_widget.setUpdatesEnabled(False)
    with QtCore.QSignalBlocker(widget.file_list_widget):
        for index in range(widget.file_list_widget.count()):
            item = widget.file_list_widget.item(index)
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, None)
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 2, "unknown")
            item.setCheckState(QtCore.Qt.CheckState.PartiallyChecked)
    widget.file_list_widget.setUpdatesEnabled(True)
    app.processEvents()
    widget._metadata_results.clear()
    widget._metadata_revisions = {}
    widget._metadata_processed = 0
    widget._metadata_total = len(paths)
    widget._metadata_generation = widget._metadata_controller.request(
        paths, widget.output_dir, {}
    )
    # Wait for the first real disk batch: the sample must cover the initial
    # status publication, not already-cached rows.
    pump_until(app, lambda: not widget._metadata_controller.worker.results.empty())
    widget._metadata_timer.start()


def run_moves(app, canvas, center, moves):
    events = []
    COUNTS.update(paint=0, image_list=0)
    for index in range(moves):
        scene = center + QtCore.QPointF((index % 12) * 0.75, (index % 8) * 0.5)
        local = (scene + canvas.offset_to_center()) * canvas.scale
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            local,
            local,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        start = time.perf_counter()
        app.sendEvent(canvas, event)
        handler = time.perf_counter() - start
        app.processEvents()
        total = time.perf_counter() - start
        events.append(
            {
                "handler_ms": handler * 1000.0,
                "cycle_ms": total * 1000.0,
            }
        )
    return {
        "cycle": summary([event["cycle_ms"] for event in events]),
        "handler": summary([event["handler_ms"] for event in events]),
        "paints": COUNTS["paint"],
        "image_list_reads": COUNTS["image_list"],
        "events": events,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="fixed")
    parser.add_argument("--out", default="results.json")
    parser.add_argument("--moves", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument(
        "--conditions", default="none,metadata,exif,both"
    )
    parser.add_argument("--list-sizes", default="1,1000,11792")
    parser.add_argument("--skip-background", action="store_true")
    parser.add_argument(
        "--config-snapshot",
        default="",
        help="frozen effective config; written on the first run, reused afterwards",
    )
    args = parser.parse_args()

    sys.addaudithook(audit)
    install_counters()

    snapshot_path = HERE / args.config_snapshot if args.config_snapshot else None
    config, config_sha, snapshot_loaded = effective_config(snapshot_path)
    script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    print(
        f"CONFIG snapshot={snapshot_path} sha256={config_sha} loaded={snapshot_loaded}",
        flush=True,
    )

    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = build_window(app, config)
    widget: LabelingWidget = window.labeling_widget.view
    canvas = widget.canvas
    widget.output_dir = str(LABELS)
    errors = []
    widget.error_message = lambda *a: errors.append(str(a))

    widget.import_image_folder(str(IMAGE.parent))
    pump_until(
        app,
        lambda: not widget._view_timer.isActive()
        and not widget._metadata_timer.isActive(),
    )
    assert not errors, errors
    assert widget.file_list_widget.count() == 11792, widget.file_list_widget.count()
    assert len(canvas.shapes) == 54, len(canvas.shapes)

    paths = widget.file_list_widget
    all_paths = [paths.item(i).text() for i in range(paths.count())]
    target = next(s for s in canvas.shapes if s.shape_type == "rectangle")
    original_points = [QtCore.QPointF(p) for p in target.points]

    source_files = [
        ROOT / "anylabeling/views/labeling/label_widget.py",
        ROOT / "anylabeling/views/labeling/widgets/canvas.py",
        ROOT / "anylabeling/views/labeling/shape.py",
    ]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    print("READY files=11792 shapes=54", flush=True)

    rows = []
    conditions = [c for c in args.conditions.split(",") if c]
    cases = [
        (condition, rep)
        for rep in range(args.rounds)
        for condition in conditions
    ]
    random.Random(30010).shuffle(cases)

    for condition, rep in cases:
        stop_background(widget, app)
        center = reset_target(canvas, target, original_points)
        app.processEvents()
        if condition in ("metadata", "both"):
            prime_metadata(widget, app, all_paths)
        if condition in ("exif", "both"):
            widget.async_exif_scanner.start_scan(all_paths)
        sample = run_moves(app, canvas, center, args.moves)
        row = {
            "background": condition,
            "round": rep,
            "metadata_active": widget._metadata_timer.isActive(),
            "exif_active": widget.async_exif_scanner.thread is not None,
            "metadata_processed": widget._metadata_processed,
            **sample,
        }
        rows.append(row)
        print(
            json.dumps({k: v for k, v in row.items() if k != "events"}),
            flush=True,
        )
        (HERE / f"partial_{args.label}.json").write_text(
            json.dumps(rows, indent=2), encoding="utf-8"
        )

    stop_background(widget, app)

    size_rows = []
    if args.list_sizes:
        for size in [int(v) for v in args.list_sizes.split(",") if v]:
            center = reset_target(canvas, target, original_points)
            widget.file_list_widget.setUpdatesEnabled(False)
            with QtCore.QSignalBlocker(widget.file_list_widget):
                widget.file_list_widget.clear()
                widget.file_list_widget.addItems(
                    [str(IMAGE)] + [str(IMAGE.parent / f"scale_{i:06d}.jpg") for i in range(1, size)]
                )
            widget.file_list_widget.setUpdatesEnabled(True)
            app.processEvents()
            sample = run_moves(app, canvas, center, args.moves)
            row = {"list_size": size, **sample}
            size_rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "events"}), flush=True)

    report = {
        "label": args.label,
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_sha256": hashes,
        "root": str(ROOT),
        "qt": QtCore.QT_VERSION_STR,
        "pyqt": QtCore.PYQT_VERSION_STR,
        "python": sys.version,
        "config_source": str(USER_CONFIG),
        "config_source_sha256": (
            hashlib.sha256(USER_CONFIG.read_bytes()).hexdigest()
            if USER_CONFIG.exists()
            else None
        ),
        "config_snapshot": str(snapshot_path) if snapshot_path else None,
        "config_snapshot_sha256": config_sha,
        "config_snapshot_loaded": snapshot_loaded,
        "interpreter": sys.executable,
        "argv": sys.argv,
        "script": str(Path(__file__).resolve()),
        "script_sha256": script_sha,
        "window": list(WINDOW_SIZE),
        "files": 11792,
        "image": str(IMAGE),
        "shapes": len(canvas.shapes),
        "moves": args.moves,
        "rounds": args.rounds,
        "scope": (
            "Real PRW directory imported through the normal folder flow; user display config; "
            "private offscreen window 2560x1377; autosave disabled; dataset directories write "
            "protected by an audit hook. Shipped mouseMoveEvent/show_shape; only counting "
            "wrappers call the originals. One sample = sendEvent + one processEvents, so the "
            "moved frame is included. Not a physical screen FPS measurement."
        ),
        "cases": rows,
        "list_size_cases": size_rows,
    }
    out = HERE / args.out
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    window.close()
    print("WROTE", out, flush=True)


if __name__ == "__main__":
    main()

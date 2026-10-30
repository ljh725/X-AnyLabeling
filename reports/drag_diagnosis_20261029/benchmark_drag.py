"""Offline drag diagnosis in the real UI; runtime-only A/B substitutions."""
import copy
from contextlib import nullcontext
import functools
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
os.environ["QT_API"] = "pyqt6"
from PyQt6 import QtCore, QtGui, QtWidgets
import anylabeling.resources.resources

PROFILE = HERE / "profile"
PROFILE.mkdir(exist_ok=True)
(PROFILE / "config.yaml").write_text("{}", encoding="utf-8")
Settings = QtCore.QSettings
QtCore.QSettings = lambda *a, **kw: Settings(str(PROFILE / "settings.ini"), Settings.Format.IniFormat)
from anylabeling import config as app_config
app_config._work_directory = str(PROFILE)
app_config.current_config_file = str(PROFILE / "config.yaml")
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.widgets.canvas import Canvas

IMAGE = Path(r"D:\A0-part2-kps-3-class-dataset\PRW\PRW_image_11792\PRW_c1s1_000151.jpg")
LABELS = Path(r"D:\A0-part2-kps-3-class-dataset\PRW\PRW_json_11792")
PROTECTED = (IMAGE.parent, LABELS)
ACTIVE = False
METRICS = {}


def audit(event, args):
    if event not in ("open", "os.remove", "os.rename", "os.rmdir", "os.mkdir"):
        return
    paths = args[:2] if event == "os.rename" else args[:1]
    for value in paths:
        if not isinstance(value, (str, bytes, os.PathLike)):
            continue
        target = Path(os.fsdecode(value)).absolute()
        if not any(target == p or p in target.parents for p in PROTECTED):
            continue
        if event != "open" or (args[2] or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise PermissionError("Diagnosis prohibits modifying datasets")


sys.addaudithook(audit)


def timed(name, function):
    @functools.wraps(function)
    def call(*args, **kwargs):
        if not ACTIVE:
            return function(*args, **kwargs)
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            metric = METRICS.setdefault(name, [0, 0.0])
            metric[0] += 1
            metric[1] += time.perf_counter() - start
    return call


original_list = LabelingWidget.image_list
LabelingWidget.image_list = property(timed("image_list", original_list.fget))
for owner, method in ((Canvas, "paintEvent"), (Canvas, "bounded_move_shapes"),
                      (LabelingWidget, "show_shape"), (LabelingWidget, "shape_selection_changed")):
    setattr(owner, method, timed(method, getattr(owner, method)))


def summary(values):
    values = sorted(values)
    return {"median_ms": round(statistics.median(values) * 1000, 3),
            "p95_ms": round(values[int((len(values) - 1) * .95)] * 1000, 3),
            "max_ms": round(max(values) * 1000, 3)}


def main():
    global ACTIVE, METRICS
    print("START", flush=True)
    source_paths = [ROOT / p for p in ("anylabeling/views/labeling/label_widget.py",
                    "anylabeling/views/labeling/widgets/canvas.py", "anylabeling/views/labeling/shape.py")]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    label_path = LABELS / (IMAGE.stem + ".json")
    label_before = hashlib.sha256(label_path.read_bytes()).hexdigest()
    app = QtWidgets.QApplication([])
    print("QAPPLICATION", flush=True)
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    print("MAINWINDOW", flush=True)
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    widget = window.labeling_widget.view
    canvas = widget.canvas
    errors = []
    widget.error_message = lambda *args: errors.append(str(args))
    widget.output_dir = str(LABELS)
    with QtCore.QSignalBlocker(widget.file_list_widget):
        widget.file_list_widget.addItem(str(IMAGE))
        widget.file_list_widget.setCurrentRow(0)
    widget.fn_to_index = {str(IMAGE): 0}
    assert widget.load_file(str(IMAGE)) is not False
    assert not errors, errors
    app.processEvents()
    assert not widget._view_timer.isActive() and not widget._metadata_timer.isActive()
    assert widget.async_exif_scanner.thread is None
    target = next(s for s in canvas.shapes if s.shape_type == "rectangle")
    shapes_original = list(canvas.shapes)
    scenarios = []
    real_status_slot = widget.show_shape

    def constant_status(h, w, pos):
        widget.status(str(widget.tr("X: %d, Y: %d | H: %d, W: %d")) % (int(pos.x()), int(pos.y()), h, w))

    for visible_count in (3, len(shapes_original)):
        canvas.shapes = [s for s in shapes_original if s.shape_type == "rectangle"] if visible_count == 3 else shapes_original
        for files in (1, 1000, 11000):
            with QtCore.QSignalBlocker(widget.file_list_widget):
                widget.file_list_widget.clear()
                widget.file_list_widget.addItems([str(IMAGE)] + [str(IMAGE.parent / f"synthetic_{i:06d}.jpg") for i in range(1, files)])
                widget.file_list_widget.setCurrentRow(0)
            app.processEvents()
            for mode in ("baseline", "status_without_list_scan", "status_and_coalesced_paint"):
                status_slot = real_status_slot if mode == "baseline" else constant_status
                canvas.show_shape.disconnect()
                canvas.show_shape.connect(status_slot)
                context = patch.object(Canvas, "repaint", lambda self, *a: self.update()) if mode == "status_and_coalesced_paint" else nullcontext()
                with context:
                    METRICS = {}
                    ACTIVE = True
                    start = time.perf_counter()
                    canvas.selection_changed.emit([target])
                    selection_ms = (time.perf_counter() - start) * 1000
                    ACTIVE = False
                    selection_metrics = copy.deepcopy(METRICS)
                    canvas.h_vertex = None
                    canvas.h_edge = None
                    canvas.h_shape = target
                    center = target.bounding_rect().center()
                    canvas.prev_point = center
                    canvas.calculate_offsets(center)
                    canvas.moving_shape = False
                    app.processEvents()
                    METRICS = {}
                    values = []
                    original_points = [QtCore.QPointF(p) for p in target.points]
                    ACTIVE = True
                    for i in range(90):
                        scene = center + QtCore.QPointF((i % 12) * .75, (i % 8) * .5)
                        local = (scene + canvas.offset_to_center()) * canvas.scale
                        event = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, local, local,
                                QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier)
                        start = time.perf_counter()
                        app.sendEvent(canvas, event)
                        app.processEvents()
                        values.append(time.perf_counter() - start)
                    ACTIVE = False
                    assert target.points != original_points, "Mouse events did not move rectangle"
                    row = {"files": files, "shapes": len(canvas.shapes), "mode": mode,
                           "moves": len(values), "selection_ms": round(selection_ms, 3),
                           "selection_metrics": selection_metrics, "event": summary(values),
                           "methods": {k: {"calls": v[0], "total_ms": round(v[1] * 1000, 3),
                                       "ms_per_move": round(v[1] * 1000 / len(values), 3)} for k, v in METRICS.items()}}
                    scenarios.append(row)
                    print(json.dumps(row), flush=True)
                    target.points = original_points
                    canvas.moving_shape = False
                    widget.dirty = False
    canvas.show_shape.disconnect()
    canvas.show_shape.connect(real_status_slot)
    canvas.shapes = shapes_original
    widget.dirty = False
    window.close()
    app.processEvents()
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    assert before == after
    assert label_before == hashlib.sha256(label_path.read_bytes()).hexdigest()
    report = {"qt": QtCore.QT_VERSION_STR, "python": sys.version, "image": str(IMAGE),
              "scope": "Real MainWindow and mouse-move handler, offscreen. Same real 1920x1080 image; synthetic path list only; no background scans. Three real rectangles, or original 54 shapes. Runtime-only A/B substitutions; original data and application source unmodified. Event includes processEvents; no monitor presentation timing. Sequential, warm-cache trials, not hardware FPS.",
              "source_sha256": before, "source_unchanged": before == after, "annotation_unchanged": True,
              "scenarios": scenarios}
    (HERE / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE", flush=True)


if __name__ == "__main__":
    import traceback
    sys.excepthook = lambda kind, value, tb: traceback.print_exception(kind, value, tb)
    main()

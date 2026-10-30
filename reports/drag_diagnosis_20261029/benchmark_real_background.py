"""Actual PRW directory, user display config, controlled real background work."""
import importlib.util
from pathlib import Path
import copy
import json
import random
import time
import hashlib
import sys
from contextlib import nullcontext
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("drag_probe", HERE / "benchmark_drag.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
import yaml
from PyQt6 import QtCore, QtGui, QtWidgets


def pump_until(app, condition, limit=120):
    start = time.perf_counter()
    while not condition():
        app.processEvents()
        time.sleep(.001)
        if time.perf_counter() - start > limit:
            raise TimeoutError("background lifecycle did not finish")


def main():
    import faulthandler
    faulthandler.dump_traceback_later(45, repeat=True)
    for name in ("_poll_metadata", "_poll_view", "status"):
        setattr(b.LabelingWidget, name, b.timed(name, getattr(b.LabelingWidget, name)))
    config_path = Path(r"C:\Users\20441\.xanylabelingrc")
    source_files = [b.ROOT / p for p in ("anylabeling/views/labeling/label_widget.py", "anylabeling/views/labeling/widgets/canvas.py", "anylabeling/views/labeling/shape.py")]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    config = copy.deepcopy(b.load_template_config())
    b.app_config.update_dict(config, b.app_config.normalize_user_config(yaml.safe_load(config_path.read_text(encoding="utf-8"))))
    config.update(auto_save=False, keep_prev=False, exif_scan_enabled=False)
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    b.Settings(str(HERE / "profile" / "settings.ini"), b.Settings.Format.IniFormat).clear()
    print("CREATING_WINDOW", flush=True)
    window = b.MainWindow(app, config=config)
    print("WINDOW_READY", flush=True)
    window.resize(2560, 1377)
    window.show()
    app.processEvents()
    w = window.labeling_widget.view
    c = w.canvas
    w.output_dir = str(b.LABELS)
    errors = []
    w.error_message = lambda *args: errors.append(str(args))
    w.import_image_folder(str(b.IMAGE.parent))
    print("IMPORT_STARTED", flush=True)
    pump_until(app, lambda: not w._view_timer.isActive() and not w._metadata_timer.isActive())
    assert not errors, errors
    assert w.file_list_widget.count() == 11792
    assert len(c.shapes) == 54
    paths = w.image_list
    original_status = w.show_shape
    exif_findings = []
    w.async_exif_scanner.exif_detected.disconnect()
    w.async_exif_scanner.exif_detected.connect(lambda files: exif_findings.append(len(files)))
    target = next(s for s in c.shapes if s.shape_type == "rectangle")
    original_points = [QtCore.QPointF(p) for p in target.points]
    print("READY actual_files=11792 actual_shapes=54", flush=True)

    def fast_status(h, width, pos):
        w.status(str(w.tr("X: %d, Y: %d | H: %d, W: %d")) % (int(pos.x()), int(pos.y()), h, width))

    def cleanup():
        w._metadata_timer.stop()
        w._metadata_controller.cancel()
        w._metadata_results.clear()
        worker = w._metadata_controller.worker
        if worker:
            pump_until(app, lambda: not worker.thread.is_alive())
        w.async_exif_scanner.stop_scan()
        pump_until(app, lambda: w.async_exif_scanner.thread is None)
        c.moving_shape = False
        target.points = [QtCore.QPointF(p) for p in original_points]
        w.dirty = False

    cases = [(background, mode, rep) for rep in range(2)
             for background in ("none", "metadata", "exif", "both")
             for mode in ("baseline", "fast_status", "fast_status_coalesced")]
    random.Random(30010).shuffle(cases)
    rows = []
    for background, mode, rep in cases:
        cleanup()
        c.show_shape.disconnect()
        c.show_shape.connect(original_status if mode == "baseline" else fast_status)
        c.selection_changed.emit([target])
        c.h_vertex = None
        c.h_edge = None
        c.h_shape = target
        center = target.bounding_rect().center()
        c.prev_point = center
        c.calculate_offsets(center)
        app.processEvents()
        if background in ("metadata", "both"):
            w.file_list_widget.setUpdatesEnabled(False)
            with QtCore.QSignalBlocker(w.file_list_widget):
                for index in range(w.file_list_widget.count()):
                    item = w.file_list_widget.item(index)
                    item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, None)
                    item.setData(QtCore.Qt.ItemDataRole.UserRole + 2, "unknown")
                    item.setCheckState(QtCore.Qt.CheckState.PartiallyChecked)
            w.file_list_widget.setUpdatesEnabled(True)
            app.processEvents()
            w._metadata_results.clear()
            w._metadata_revisions = {}
            w._metadata_processed = 0
            w._metadata_total = len(paths)
            w._metadata_generation = w._metadata_controller.request(paths, w.output_dir, {})
            # Ensure real results are available during the measured interval;
            # otherwise a short drag could end before the first disk batch.
            pump_until(app, lambda: not w._metadata_controller.worker.results.empty())
            w._metadata_timer.start()
        if background in ("exif", "both"):
            w.async_exif_scanner.start_scan(paths)
        events = []
        b.METRICS = {}
        b.ACTIVE = True
        ctx = patch.object(b.Canvas, "repaint", lambda self, *args: self.update()) if mode == "fast_status_coalesced" else nullcontext()
        with ctx:
            for i in range(100):
                scene = center + QtCore.QPointF((i % 12) * .75, (i % 8) * .5)
                local = (scene + c.offset_to_center()) * c.scale
                event = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, local, local,
                        QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton,
                        QtCore.Qt.KeyboardModifier.NoModifier)
                flags = [w._metadata_timer.isActive(), w.async_exif_scanner.thread is not None]
                start = time.perf_counter()
                app.sendEvent(c, event)
                handler = time.perf_counter() - start
                app.processEvents()
                total = time.perf_counter() - start
                events.append({"handler_ms": handler * 1000, "cycle_ms": total * 1000,
                               "metadata_active": flags[0], "exif_active": flags[1]})
        b.ACTIVE = False
        assert target.points != original_points
        row = {"background": background, "mode": mode, "rep": rep,
               "event": b.summary([e["cycle_ms"] / 1000 for e in events]),
               "handler": b.summary([e["handler_ms"] / 1000 for e in events]),
               "metadata_events": sum(e["metadata_active"] for e in events),
               "exif_events": sum(e["exif_active"] for e in events),
               "metadata_processed": w._metadata_processed,
               "methods": {k: {"calls": v[0], "total_ms": v[1] * 1000} for k, v in b.METRICS.items()},
               "events": events}
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k not in ("events", "methods")}), flush=True)
        (HERE / "real_background_partial.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    cleanup()
    c.show_shape.disconnect()
    c.show_shape.connect(original_status)
    window.close()
    app.processEvents()
    assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    report = {"date": "2026-10-30", "source_sha256": hashes, "qt": QtCore.QT_VERSION_STR,
              "config_source": str(config_path), "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
              "files": len(paths), "image": w.filename, "shapes": len(c.shapes),
              "scope": "User-confirmed real PRW directory loaded via normal import. Saved user display configuration; 2560x1377 private offscreen window. Actual metadata reader and EXIF workers; no synthetic paths or artificial IO delays. Metadata list entries reset to unknown and first real batch ready before timing to test initial status publication, not unchanged cached rows. 24 randomized scenarios, 100 movements each. Autosave disabled, original dataset write-protected. User running window untouched. Background jobs stopped after each sample; worker active state recorded per event. Not a screen FPS measurement.",
              "cases": rows}
    (HERE / "real_background_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE", flush=True)
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    import traceback
    sys.excepthook = lambda kind, value, tb: traceback.print_exception(kind, value, tb)
    main()

"""Additional review coverage for drops at the view-drain boundary."""
import copy
import json
import sys
import time
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from test_staged_output_window import (
    isolated_settings, _wait, _close_window, QtGui,
    QtWidgets, MainWindow, load_template_config,
)


def make_window():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    return app, window, window.labeling_widget.view


def write_image(path):
    img = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor("white"))
    assert img.save(str(path))


def test_drop_after_done_before_list_buffer_drained(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    write_image(images / "0000.png")
    for index in range(1, 600):
        (images / f"{index:04}.png").touch()
    dropped = tmp_path / "extra.png"
    write_image(dropped)
    app, window, widget = make_window()
    try:
        widget.import_image_folder(str(images))
        deadline = time.monotonic() + 5
        while widget._view_controller.worker.results.qsize() < 4 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert widget._view_controller.worker.results.qsize() == 4
        # Drive the real polling callback while preserving an active timer.
        # Stop at the supported state: producer done, UI insertion unfinished.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            widget._poll_view()
            if widget._view_finished and widget._view_buffer:
                break
            time.sleep(0.005)
        assert widget._view_finished and widget._view_buffer
        assert widget._view_timer.isActive()
        widget.import_dropped_image_files([str(dropped)])
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert str(dropped) in widget.image_list, (
            f"Dropped file disappeared; unconsumed pending drops={widget._view_pending_dropped}"
        )
    finally:
        _close_window(window, app)


def test_dropped_nonmatch_does_not_bypass_active_filter(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    write_image(images / "cat.png")
    dropped = tmp_path / "dog.png"
    write_image(dropped)
    app, window, widget = make_window()
    try:
        widget.import_image_folder(str(images))
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        widget.file_search.setText("cat")
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        widget.import_dropped_image_files([str(dropped)])
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert [Path(p).name for p in widget.image_list] == ["cat.png"]
    finally:
        _close_window(window, app)


@pytest.mark.parametrize(
    "pattern,expected",
    [("cat", ["cat.png"]), ("dog", ["dog.png"]), ("#1", ["cat.png"]),
     ("#2", ["dog.png"]), ("label::cat", ["cat.png"]), ("label::dog", ["dog.png"])],
)
def test_drop_respects_each_search_mode_and_keeps_edits(tmp_path, pattern, expected):
    images = tmp_path / "images"
    images.mkdir()
    for path, label in ((images / "cat.png", "cat"), (tmp_path / "dog.png", "dog")):
        write_image(path)
        path.with_suffix(".json").write_text(json.dumps({
            "version": "4.2.1", "shapes": [{"label": label, "shape_type": "point", "points": [[2, 2]]}],
            "imagePath": path.name, "imageData": None, "imageHeight": 32, "imageWidth": 32,
        }), encoding="utf8")
    app, window, widget = make_window()
    try:
        widget.import_image_folder(str(images))
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        widget.dirty = True
        widget.file_search.setText(pattern)
        _wait(lambda: not widget._view_timer.isActive())
        widget.import_dropped_image_files([str(tmp_path / "dog.png")])
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert [Path(path).name for path in widget.image_list] == expected
        assert Path(widget.filename).name == "cat.png"
        assert widget.dirty
        assert widget.canvas.shapes[0].label == "cat"
    finally:
        _close_window(window, app)


def test_nonmatching_drop_during_view_drain_is_filtered(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    write_image(images / "0000.png")
    for index in range(1, 600):
        (images / f"{index:04}.png").touch()
    dropped = tmp_path / "extra.jpg"
    write_image(dropped)
    app, window, widget = make_window()
    try:
        widget.import_image_folder(str(images), pattern="png")
        deadline = time.monotonic() + 5
        while widget._view_controller.worker.results.qsize() < 4 and time.monotonic() < deadline:
            time.sleep(0.005)
        while time.monotonic() < deadline:
            widget._poll_view()
            if widget._view_finished and widget._view_buffer:
                break
            time.sleep(0.005)
        assert widget._view_finished and widget._view_buffer
        # import_image_folder accepts an explicit pattern; keep the visible
        # search field in sync without firing a second request.
        from PyQt6 import QtCore
        with QtCore.QSignalBlocker(widget.file_search):
            widget.file_search.setText("png")
        widget.import_dropped_image_files([str(dropped)])
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert str(dropped) not in widget.image_list
        assert len(widget.image_list) == 600
    finally:
        _close_window(window, app)


def test_drop_during_blocked_attribute_search_uses_latest_filter(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import staged_annotation_loading as module
    images = tmp_path / "images"
    images.mkdir()
    for path, label in ((images / "cat.png", "cat"), (tmp_path / "dog.png", "dog")):
        write_image(path)
        path.with_suffix(".json").write_text(json.dumps({
            "version": "4.2.1", "shapes": [{"label": label, "shape_type": "point", "points": [[2, 2]]}],
            "imagePath": path.name, "imageData": None, "imageHeight": 32, "imageWidth": 32,
        }), encoding="utf8")
    app, window, widget = make_window()
    entered, release = threading.Event(), threading.Event()
    original = module.matches_filename
    def blocked(path, pattern):
        if not release.is_set():
            entered.set()
            assert release.wait(5)
        return original(path, pattern)
    try:
        widget.import_image_folder(str(images))
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        monkeypatch.setattr(module, "matches_filename", blocked)
        widget.dirty = True
        widget.file_search.setText("label::dog")
        _wait(entered.is_set)
        widget.import_dropped_image_files([str(tmp_path / "dog.png")])
        release.set()
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert [Path(path).name for path in widget.image_list] == ["dog.png"]
        assert Path(widget.filename).name == "cat.png"
        assert widget.dirty
    finally:
        release.set()
        _close_window(window, app)


def test_drop_after_opening_single_file_retains_it(tmp_path):
    cat, dog = tmp_path / "cat.png", tmp_path / "dog.png"
    write_image(cat)
    write_image(dog)
    app, window, widget = make_window()
    try:
        assert widget.load_file(str(cat))
        widget.import_dropped_image_files([str(dog)])
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert [Path(path).name for path in widget.image_list] == ["cat.png", "dog.png"]
        widget.file_search.setText("dog")
        _wait(lambda: not widget._view_timer.isActive())
        assert [Path(path).name for path in widget.image_list] == ["dog.png"]
        assert Path(widget.filename).name == "cat.png"
    finally:
        _close_window(window, app)


def test_navigation_during_empty_filtered_rebuild_does_not_wait_forever(tmp_path):
    cat, dog = tmp_path / "cat.png", tmp_path / "dog.png"
    write_image(cat)
    write_image(dog)
    app, window, widget = make_window()
    try:
        assert widget.load_file(str(cat))
        widget.import_dropped_image_files([str(dog)])
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        widget.file_search.setText("no-match")
        widget.open_next_unchecked_image()
        _wait(lambda: not widget._view_timer.isActive())
        assert widget.image_list == []
        assert widget._pending_review_navigation is None
        assert Path(widget.filename).name == "cat.png"
    finally:
        _close_window(window, app)

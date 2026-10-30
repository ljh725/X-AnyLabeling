"""Review-only reproductions; temporary datasets, no production source edits."""

import copy
import json
import queue
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from test_staged_output_window import (
    isolated_settings, _wait, _close_window, QtCore, QtGui,
    QtWidgets, MainWindow, load_template_config,
)
from anylabeling.views.labeling.utils import staged_annotation_loading as module


@pytest.mark.parametrize("kind", ["metadata", "view"])
def test_final_publication_between_empty_poll_and_worker_cleanup(tmp_path, monkeypatch, kind):
    entered, release = threading.Event(), threading.Event()
    image = str(tmp_path / "a.png")
    if kind == "metadata":
        original = module.read_annotation_metadata
        def blocked(path):
            entered.set()
            assert release.wait(5)
            return original(path)
        monkeypatch.setattr(module, "read_annotation_metadata", blocked)
        controller = module.MetadataController()
        controller.request([image], None, {})
    else:
        original = module.matches_filename
        def blocked(*args):
            entered.set()
            assert release.wait(5)
            return original(*args)
        monkeypatch.setattr(module, "matches_filename", blocked)
        controller = module.ViewController()
        controller.request(paths=[image])
    assert entered.wait(5)
    worker = controller.worker
    original_get = worker.results.get_nowait

    def empty_then_producer_exits():
        try:
            return original_get()
        except queue.Empty:
            # Force the legal scheduling gap between observing an empty queue
            # and testing whether the producer has exited.
            release.set()
            worker.thread.join(timeout=5)
            assert not worker.thread.is_alive()
            raise

    monkeypatch.setattr(worker.results, "get_nowait", empty_then_producer_exits)
    try:
        records = controller.poll()
        records.extend(controller.poll())
        assert records, (
            f"{kind}: final records lost; worker queue still contains "
            f"{worker.results.qsize()} messages, controller.worker={controller.worker}"
        )
        if kind == "view":
            assert any(record[1] == "done" for record in records)
        assert not controller.is_running()
    finally:
        release.set()
        controller.cancel()
        worker.thread.join(timeout=5)


@pytest.mark.parametrize("kind", ["metadata", "view"])
def test_finished_worker_with_queued_results_is_still_running(tmp_path, kind):
    image = str(tmp_path / "a.png")
    if kind == "metadata":
        controller = module.MetadataController()
        controller.request([image], None, {})
    else:
        controller = module.ViewController()
        controller.request(paths=[image])
    worker = controller.worker
    worker.thread.join(timeout=5)
    assert not worker.thread.is_alive()
    assert controller.is_running()
    records = controller.poll()
    assert records
    if kind == "view":
        assert any(record[1] == "done" for record in records)
    assert not controller.is_running()


@pytest.mark.parametrize("kind", ["metadata", "view"])
def test_new_request_discards_finished_old_queue(tmp_path, kind):
    import time
    old, new = str(tmp_path / "old.png"), str(tmp_path / "new.png")
    if kind == "metadata":
        controller = module.MetadataController()
        controller.request([old], None, {})
    else:
        controller = module.ViewController()
        controller.request(paths=[old])
    controller.worker.thread.join(timeout=5)
    if kind == "metadata":
        generation = controller.request([new], None, {})
    else:
        generation = controller.request(paths=[new])
    records = []
    deadline = time.monotonic() + 5
    while controller.is_running() and time.monotonic() < deadline:
        records.extend(controller.poll())
        time.sleep(0.005)
    records.extend(controller.poll())
    assert records and all(record[0] == generation for record in records)
    assert any(new in record[1] if kind == "metadata" else record[1] == "matches" and new in record[2] for record in records)


def test_opening_pending_image_resolves_presence_as_well_as_review(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    for name in ("a", "b"):
        img = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        img.fill(QtGui.QColor("white"))
        assert img.save(str(tmp_path / f"{name}.png"))
        (tmp_path / f"{name}.json").write_text(json.dumps({
            "version": "4.2.1", "shapes": [], "imagePath": f"{name}.png",
            "imageData": None, "imageHeight": 32, "imageWidth": 32,
            "checked": True,
        }), encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    original = module.read_annotation_metadata
    def blocked(path):
        if str(path).endswith("b.json"):
            entered.set()
            assert release.wait(5)
        return original(path)
    monkeypatch.setattr(module, "read_annotation_metadata", blocked)
    widget = window.labeling_widget.view
    try:
        widget.import_image_folder(str(tmp_path))
        _wait(entered.is_set)
        widget.load_file(str(tmp_path / "b.png"))
        assert widget.label_file is not None
        release.set()
        _wait(lambda: not widget._metadata_timer.isActive())
        item = widget._current_file_item()
        assert widget._metadata_state(item) == "ready"
        assert item.checkState() == QtCore.Qt.CheckState.Checked
    finally:
        release.set()
        _close_window(window, app)


def test_directory_supplied_at_startup_loads_first_image(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    img = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor("white"))
    assert img.save(str(tmp_path / "a.png"))
    window = MainWindow(app, config=config, filename=str(tmp_path))
    window.show()
    widget = window.labeling_widget.view
    try:
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert widget.file_list_widget.count() == 1
        assert widget.filename == str(tmp_path / "a.png")
        assert not widget.image.isNull(), "Startup directory finished but first image was never loaded"
    finally:
        _close_window(window, app)


def test_dropped_image_is_not_left_unknown_to_review_navigation(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    images = tmp_path / "images"
    images.mkdir()
    img = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor("white"))
    assert img.save(str(images / "a.png"))
    dropped = tmp_path / "b.png"
    assert img.save(str(dropped))
    window = MainWindow(app, config=config)
    window.show()
    widget = window.labeling_widget.view
    try:
        widget.import_image_folder(str(images))
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        widget.import_dropped_image_files([str(dropped)])
        widget.open_next_unchecked_image()
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert widget.filename == str(dropped), (
            f"Dropped image has state {widget._metadata_state(widget.file_list_widget.item(1))}; "
            f"pending navigation={widget._pending_review_navigation}"
        )
    finally:
        _close_window(window, app)


@pytest.mark.parametrize("has_label,search", [(False, ""), (True, ""), (False, "#2"), (True, "#2")])
def test_startup_directory_loads_filtered_image_and_preserves_context(tmp_path, has_label, search):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False, file_search=search)
    images = tmp_path / "images"
    images.mkdir()
    for name in ("a", "b"):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(images / f"{name}.png"))
        if has_label:
            (images / f"{name}.json").write_text(json.dumps({
                "version": "4.2.1", "shapes": [], "imagePath": f"{name}.png",
                "imageData": None, "imageHeight": 32, "imageWidth": 32,
                "checked": True,
            }), encoding="utf-8")
    QtCore.QSettings().setValue("last_open_dir", str(tmp_path / "old"))
    window = MainWindow(app, config=config, filename=str(images))
    window.show()
    widget = window.labeling_widget.view
    try:
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert Path(widget.filename).name == ("b.png" if search else "a.png")
        assert not widget.image.isNull()
        assert (widget.label_file is not None) == has_label
        assert widget.last_open_dir == str(images)
    finally:
        _close_window(window, app)


def test_current_image_without_json_clears_old_presence(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    for name in ("a", "b"):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(tmp_path / f"{name}.png"))
    entered, release = threading.Event(), threading.Event()
    original = module.read_annotation_metadata
    def blocked(path):
        if str(path).endswith("b.json"):
            entered.set()
            assert release.wait(5)
        return original(path)
    monkeypatch.setattr(module, "read_annotation_metadata", blocked)
    window = MainWindow(app, config=config)
    window.show()
    widget = window.labeling_widget.view
    try:
        widget.import_image_folder(str(tmp_path))
        _wait(entered.is_set)
        widget.file_list_widget.item(1).setCheckState(QtCore.Qt.CheckState.Checked)
        widget.load_file(str(tmp_path / "b.png"))
        release.set()
        _wait(lambda: not widget._metadata_timer.isActive())
        assert widget._current_file_item().checkState() == QtCore.Qt.CheckState.Unchecked
        assert widget._metadata_state(widget._current_file_item()) == "ready"
    finally:
        release.set()
        _close_window(window, app)


def test_current_image_permission_error_is_not_published_as_ready(tmp_path, monkeypatch):
    import os
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    for name in ("a", "b"):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(tmp_path / f"{name}.png"))
    entered, release = threading.Event(), threading.Event()
    original_read = module.read_annotation_metadata
    def blocked(path):
        if str(path).endswith("b.json"):
            entered.set()
            assert release.wait(5)
        return original_read(path)
    monkeypatch.setattr(module, "read_annotation_metadata", blocked)
    window = MainWindow(app, config=config)
    window.show()
    widget = window.labeling_widget.view
    try:
        widget.import_image_folder(str(tmp_path))
        _wait(entered.is_set)
        target = str(tmp_path / "b.json")
        original_stat = os.stat
        def denied(path, *args, **kwargs):
            if str(path) == target:
                raise PermissionError("denied")
            return original_stat(path, *args, **kwargs)
        errors = []
        with monkeypatch.context() as context:
            context.setattr(os, "stat", denied)
            context.setattr(widget, "error_message", lambda *args: errors.append(args))
            with QtCore.QSignalBlocker(widget.file_list_widget):
                widget.file_list_widget.setCurrentRow(1)
            assert widget.load_file(str(tmp_path / "b.png")) is False
            assert errors
            assert widget._metadata_state(widget.file_list_widget.item(1)) == "unknown"
    finally:
        release.set()
        _close_window(window, app)


def test_drops_during_path_scan_are_appended_and_searchable(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    images = tmp_path / "images"
    images.mkdir()
    for path in (images / "a.png", tmp_path / "b.png", tmp_path / "c.png"):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(path))
    entered, release = threading.Event(), threading.Event()
    original = module.matches_filename
    def blocked(path, pattern):
        if path.endswith("a.png") and not release.is_set():
            entered.set()
            assert release.wait(5)
        return original(path, pattern)
    monkeypatch.setattr(module, "matches_filename", blocked)
    window = MainWindow(app, config=config)
    window.show()
    widget = window.labeling_widget.view
    try:
        widget.import_image_folder(str(images))
        _wait(entered.is_set)
        widget.import_dropped_image_files([str(tmp_path / "b.png"), str(tmp_path / "c.png")])
        release.set()
        _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
        assert [Path(path).name for path in widget.image_list] == ["a.png", "b.png", "c.png"]
        widget.open_next_unchecked_image()
        assert Path(widget.filename).name == "b.png"
        widget.file_search.setText("c.png")
        _wait(lambda: not widget._view_timer.isActive())
        assert [Path(path).name for path in widget.image_list] == ["c.png"]
    finally:
        release.set()
        _close_window(window, app)


def test_drops_during_metadata_scan_remain_navigable(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    images = tmp_path / "images"
    images.mkdir()
    for path in (images / "a.png", images / "b.png", tmp_path / "c.png", tmp_path / "d.png"):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(path))
    (images / "b.json").write_text('{"checked": true, "shapes": []}', encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    original = module.read_annotation_metadata
    def blocked(path):
        if str(path).endswith("b.json") and not release.is_set():
            entered.set()
            assert release.wait(5)
        return original(path)
    monkeypatch.setattr(module, "read_annotation_metadata", blocked)
    window = MainWindow(app, config=config)
    window.show()
    widget = window.labeling_widget.view
    try:
        widget.import_image_folder(str(images))
        _wait(entered.is_set)
        widget.import_dropped_image_files([str(tmp_path / "c.png"), str(tmp_path / "d.png")])
        widget.open_next_unchecked_image()
        assert widget._pending_review_navigation is not None
        release.set()
        _wait(lambda: widget.filename == str(tmp_path / "c.png"))
        _wait(lambda: not widget._metadata_timer.isActive())
        assert [Path(path).name for path in widget.image_list] == ["a.png", "b.png", "c.png", "d.png"]
    finally:
        release.set()
        _close_window(window, app)

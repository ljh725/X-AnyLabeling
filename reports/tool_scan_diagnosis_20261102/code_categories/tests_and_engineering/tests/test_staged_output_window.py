"""Real-window checks using only temporary image and annotation files."""

import copy
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets
from anylabeling import config as app_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    monkeypatch.setattr(app_config, "current_config_file", str(tmp_path / "config.yaml"))
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore, "QSettings",
        lambda *args, **kwargs: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )


def _wait(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QtTest.QTest.qWait(10)
    assert predicate()


def _close_window(window, app):
    widget = window.labeling_widget.view
    widget.dirty = False
    window.close()
    _wait(lambda: not window.isVisible())
    app.removeEventFilter(widget)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_output_switch_reads_current_then_background(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False, file_list_checkbox_editable=True)
    window = MainWindow(app, config=config)
    window.show()
    images = tmp_path / "images"
    labels = tmp_path / "labels"
    images.mkdir()
    labels.mkdir()
    for i in range(3):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(images / f"{i}.png"))
        (labels / f"{i}.json").write_text(json.dumps({
            "version": "4.2.1", "shapes": [], "imagePath": f"{i}.png",
            "imageData": None, "imageHeight": 32, "imageWidth": 32,
            "checked": i == 1,
        }), encoding="utf-8")
    widget = window.labeling_widget.view
    widget.import_image_folder(str(images))
    _wait(lambda: not widget._view_timer.isActive())
    first = widget.filename
    changed, update_threads = [], []
    original_update = widget._set_file_item_checked

    def record_update(item, checked):
        update_threads.append(QtCore.QThread.currentThread())
        return original_update(item, checked)

    with patch.object(widget, "_set_file_item_checked", side_effect=record_update), patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(labels)):
        widget.change_output_dir_dialog()
        assert widget.filename == first
        assert Path(widget.label_file.filename) == labels / "0.json"
        widget.file_list_widget.itemChanged.connect(lambda item: changed.append(item.text()))
        _wait(lambda: not widget._metadata_timer.isActive())
    assert update_threads and all(thread is app.thread() for thread in update_threads)
    assert not changed
    assert widget.file_list_widget.item(1).data(QtCore.Qt.ItemDataRole.UserRole) is True
    assert widget.file_list_widget.item(1).flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable
    widget.file_list_widget.item(1).setCheckState(QtCore.Qt.CheckState.Unchecked)
    assert widget.file_list_widget.item(1).checkState() == QtCore.Qt.CheckState.Unchecked
    widget.file_list_widget.item(1).setCheckState(QtCore.Qt.CheckState.Checked)
    widget.open_next_unchecked_image()
    assert Path(widget.filename).name == "2.png"
    widget.other_data["checked"] = True
    assert widget.save_labels(str(labels / "2.json"))
    from anylabeling.views.labeling.utils.staged_annotation_loading import AnnotationMetadata
    widget._metadata_results.append((widget._metadata_generation, widget.filename, 0, AnnotationMetadata("present", "unchecked")))
    widget._poll_metadata()
    assert widget.file_list_widget.item(2).data(QtCore.Qt.ItemDataRole.UserRole) is True
    assert json.loads((labels / "2.json").read_text(encoding="utf-8"))["checked"] is True
    widget.dirty = True
    widget.file_search.setText("#1")
    widget.file_search_changed()
    widget.file_search.setText("#3")
    widget.file_search_changed()
    _wait(lambda: not widget._view_timer.isActive())
    assert [Path(path).name for path in widget.image_list] == ["2.png"]
    assert Path(widget.filename).name == "2.png"
    assert widget.dirty
    widget.file_search.setText("checked::passed")
    widget.file_search_changed()
    _wait(lambda: not widget._view_timer.isActive())
    assert [Path(path).name for path in widget.image_list] == ["1.png", "2.png"]
    assert Path(widget.filename).name == "2.png"
    assert widget.dirty
    other_labels = tmp_path / "other-labels"
    other_labels.mkdir()
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(other_labels)), patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Cancel):
        widget.change_output_dir_dialog()
    assert widget.output_dir == str(labels)
    assert widget.dirty
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(other_labels)), patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Discard):
        widget.change_output_dir_dialog()
    _wait(lambda: not widget._view_timer.isActive())
    assert widget.output_dir == str(other_labels)
    assert Path(widget.filename).name == "2.png"
    assert widget.label_file is None
    assert not widget.canvas.shapes
    assert widget.image_list == []
    _close_window(window, app)


def test_cancelled_switch_keeps_directory(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    widget = window.labeling_widget.view
    original = widget.output_dir
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(tmp_path)), patch.object(widget, "may_continue", return_value=False):
        widget.change_output_dir_dialog()
    assert widget.output_dir == original
    _close_window(window, app)


def test_close_waits_without_destroying_running_worker(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import staged_annotation_loading as module

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    assert image.save(str(tmp_path / "a.png"))
    entered, release = threading.Event(), threading.Event()
    original = module.read_annotation_metadata

    def blocked(path):
        entered.set()
        assert release.wait(5)
        return original(path)

    monkeypatch.setattr(module, "read_annotation_metadata", blocked)
    widget = window.labeling_widget.view
    widget.import_image_folder(str(tmp_path))
    try:
        _wait(entered.is_set)
        window.close()
        QtTest.QTest.qWait(150)
        assert window.isVisible()
        release.set()
        _wait(lambda: not window.isVisible())
    finally:
        release.set()
        _close_window(window, app)


def test_review_navigation_retries_unreadable_candidate(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    for name in ("a.png", "b.png"):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(tmp_path / name))
    label = tmp_path / "b.json"
    label.write_text("{", encoding="utf-8")
    widget = window.labeling_widget.view
    widget.import_image_folder(str(tmp_path))
    _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
    widget.open_next_unchecked_image()
    assert Path(widget.filename).name == "a.png"
    assert widget._last_review_error.endswith("b.png")
    label.unlink()
    widget.open_next_unchecked_image()
    _wait(lambda: Path(widget.filename).name == "b.png")
    _close_window(window, app)


def test_close_waits_for_exif_without_forcing_thread(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import async_exif

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, exif_scan_enabled=True)
    window = MainWindow(app, config=config)
    window.show()
    image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    assert image.save(str(tmp_path / "a.png"))
    entered, release = threading.Event(), threading.Event()
    original = async_exif.ExifScannerWorker.scan_files

    def blocked(worker):
        entered.set()
        assert release.wait(5)
        original(worker)

    monkeypatch.setattr(async_exif.ExifScannerWorker, "scan_files", blocked)
    widget = window.labeling_widget.view
    widget.import_image_folder(str(tmp_path))
    try:
        _wait(entered.is_set)
        window.close()
        QtTest.QTest.qWait(150)
        assert window.isVisible()
        release.set()
        _wait(lambda: not window.isVisible())
    finally:
        release.set()
        _close_window(window, app)


def test_rapid_output_switch_discards_late_results(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import staged_annotation_loading as module

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=True, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    images = tmp_path / "images"
    first = tmp_path / "first"
    second = tmp_path / "second"
    for directory in (images, first, second):
        directory.mkdir()
    for name in ("a", "b"):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(images / f"{name}.png"))
        for directory, checked in ((first, True), (second, "failed")):
            if directory == second and name == "a":
                continue
            shapes = [{"label": "box", "shape_type": "rectangle", "points": [[2, 2], [12, 2], [12, 12], [2, 12]]}] if name == "a" and directory == first else []
            (directory / f"{name}.json").write_text(json.dumps({
                "version": "4.2.1", "shapes": shapes, "imagePath": f"{name}.png",
                "imageData": None, "imageHeight": 32, "imageWidth": 32,
                "checked": checked,
            }), encoding="utf-8")
    widget = window.labeling_widget.view
    widget.import_image_folder(str(images))
    _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
    widget.set_clean()
    entered, release = threading.Event(), threading.Event()
    original = module.read_annotation_metadata

    def blocked(path):
        if str(path) == str(first / "b.json") and not release.is_set():
            entered.set()
            assert release.wait(5)
        return original(path)

    monkeypatch.setattr(module, "read_annotation_metadata", blocked)
    try:
        for directory in (first, second, first):
            with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(directory)):
                widget.change_output_dir_dialog()
            if directory == first and not entered.is_set():
                _wait(entered.is_set)
                assert len(widget.canvas.shapes) == 1
                assert widget.canvas.isEnabled()
                shape = widget.canvas.shapes[0]
                widget._apply_field_patch([shape], {"description": "edited"}, {"description"})
                assert widget.canvas.shapes[0].description == "edited"
                widget.undo_shape_edit()
                assert widget.canvas.shapes[0].description == ""
                widget.save_file()
                assert not widget.dirty
                assert widget.load_file(str(images / "a.png"))
                assert widget.canvas.shapes[0].description == ""
            elif directory == second:
                assert not widget.canvas.shapes
                assert widget.label_file is None
        release.set()
        _wait(lambda: not widget._metadata_timer.isActive())
        assert widget.output_dir == str(first)
        assert widget.file_list_widget.item(1).data(QtCore.Qt.ItemDataRole.UserRole) is True
        assert Path(widget.label_file.filename) == first / "a.json"
    finally:
        release.set()
        _close_window(window, app)


def test_switch_saves_old_target_and_blocks_failed_save(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    images = tmp_path / "images"
    first = tmp_path / "first"
    second = tmp_path / "second"
    for directory in (images, first, second):
        directory.mkdir()
    image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    assert image.save(str(images / "a.png"))
    (first / "a.json").write_text(json.dumps({
        "version": "4.2.1", "shapes": [], "imagePath": "a.png",
        "imageData": None, "imageHeight": 32, "imageWidth": 32,
        "checked": False,
    }), encoding="utf-8")
    widget = window.labeling_widget.view
    widget.import_image_folder(str(images))
    _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(first)):
        widget.change_output_dir_dialog()
    _wait(lambda: not widget._metadata_timer.isActive())
    widget.other_data["checked"] = True
    widget.dirty = True
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(second)), patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Save):
        widget.change_output_dir_dialog()
    assert json.loads((first / "a.json").read_text(encoding="utf-8"))["checked"] is True
    assert widget.output_dir == str(second)
    assert not (second / "a.json").exists()
    widget.dirty = True
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(first)), patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Save), patch.object(widget, "save_file", return_value=None):
        widget.change_output_dir_dialog()
    assert widget.output_dir == str(second)
    assert widget.dirty
    _close_window(window, app)


def test_first_image_opens_before_full_list_is_built(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    assert image.save(str(tmp_path / "0000.png"))
    for index in range(1, 500):
        (tmp_path / f"{index:04}.png").touch()
    widget = window.labeling_widget.view

    class PaintObserver(QtCore.QObject):
        count_at_first_image = None

        def eventFilter(self, watched, event):
            if event.type() == QtCore.QEvent.Type.Paint and widget.filename and widget.canvas.isEnabled():
                if self.count_at_first_image is None:
                    self.count_at_first_image = widget.file_list_widget.count()
            return False

    observer = PaintObserver()
    widget.canvas.installEventFilter(observer)
    widget.import_image_folder(str(tmp_path))
    _wait(lambda: observer.count_at_first_image is not None)
    assert widget.canvas.isEnabled()
    assert observer.count_at_first_image < 500
    assert widget._view_timer.isActive()
    _wait(lambda: not widget._view_timer.isActive())
    assert [Path(path).name for path in widget.image_list] == [f"{i:04}.png" for i in range(500)]
    _close_window(window, app)


def test_empty_and_missing_directory_show_distinct_status(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    widget = window.labeling_widget.view
    widget.import_image_folder(str(tmp_path))
    _wait(lambda: not widget._view_timer.isActive())
    assert "No matching images" in window.statusBar().currentMessage()
    widget.import_image_folder(str(tmp_path / "missing"))
    _wait(lambda: not widget._view_timer.isActive())
    assert "Image scan failed" in window.statusBar().currentMessage()
    _close_window(window, app)


def test_navigation_waits_and_manual_selection_cancels(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import staged_annotation_loading as module

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    for name, checked in (("a", False), ("b", True), ("c", "failed"), ("d", False)):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(tmp_path / f"{name}.png"))
        (tmp_path / f"{name}.json").write_text(json.dumps({
            "version": "4.2.1", "shapes": [], "imagePath": f"{name}.png",
            "imageData": None, "imageHeight": 32, "imageWidth": 32,
            "checked": checked,
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
    widget.import_image_folder(str(tmp_path))
    try:
        _wait(entered.is_set)
        widget.open_next_unchecked_image()
        pending = widget._pending_review_navigation
        assert pending is not None
        widget.open_next_unchecked_image()
        assert widget._pending_review_navigation == pending
        widget.load_file(str(tmp_path / "c.png"))
        assert widget._pending_review_navigation is None
        release.set()
        _wait(lambda: not widget._metadata_timer.isActive())
        assert Path(widget.filename).name == "c.png"
        widget.open_prev_unchecked_image()
        assert Path(widget.filename).name == "a.png"
        widget.open_next_unchecked_image()
        assert Path(widget.filename).name == "d.png"
        widget.open_next_unchecked_image()
        assert Path(widget.filename).name == "d.png"
    finally:
        release.set()
        _close_window(window, app)


def test_rapid_attribute_search_discards_blocked_old_request(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import staged_annotation_loading as module

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    for name, label in (("a", None), ("b", "old"), ("c", "new")):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(tmp_path / f"{name}.png"))
        shapes = [] if label is None else [{"label": label, "shape_type": "point", "points": [[2, 2]]}]
        (tmp_path / f"{name}.json").write_text(json.dumps({
            "version": "4.2.1", "shapes": shapes, "imagePath": f"{name}.png",
            "imageData": None, "imageHeight": 32, "imageWidth": 32,
        }), encoding="utf-8")
    widget = window.labeling_widget.view
    widget.import_image_folder(str(tmp_path))
    _wait(lambda: not widget._view_timer.isActive() and not widget._metadata_timer.isActive())
    entered, release = threading.Event(), threading.Event()
    original = module.matches_label_attribute

    def blocked(image, label, pattern, **kwargs):
        if pattern.attribute_filter["value"] == "old":
            entered.set()
            assert release.wait(5)
        return original(image, label, pattern, **kwargs)

    monkeypatch.setattr(module, "matches_label_attribute", blocked)
    try:
        widget.file_search.setText("label::old")
        _wait(entered.is_set)
        widget.file_search.setText("label::new")
        release.set()
        _wait(lambda: not widget._view_timer.isActive())
        assert [Path(path).name for path in widget.image_list] == ["c.png"]
        assert Path(widget.filename).name == "a.png"
        alternate = tmp_path / "alternate"
        alternate.mkdir()
        (alternate / "a.json").write_text(json.dumps({
            "version": "4.2.1", "shapes": [{"label": "old", "shape_type": "point", "points": [[2, 2]]}],
            "imagePath": "a.png", "imageData": None, "imageHeight": 32, "imageWidth": 32,
        }), encoding="utf-8")
        entered.clear()
        release.clear()
        widget.file_search.setText("label::old")
        _wait(entered.is_set)
        with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(alternate)):
            widget.change_output_dir_dialog()
        release.set()
        _wait(lambda: not widget._view_timer.isActive())
        assert widget.output_dir == str(alternate)
        assert [Path(path).name for path in widget.image_list] == ["a.png"]
        assert Path(widget.filename).name == "a.png"
    finally:
        release.set()
        _close_window(window, app)


def test_save_wins_against_blocked_old_worker_result(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import staged_annotation_loading as module

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    for name in ("a", "b"):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(tmp_path / f"{name}.png"))
        (tmp_path / f"{name}.json").write_text(json.dumps({
            "version": "4.2.1", "shapes": [], "imagePath": f"{name}.png",
            "imageData": None, "imageHeight": 32, "imageWidth": 32,
            "checked": False,
        }), encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    original = module.read_annotation_metadata

    def blocked(path):
        result = original(path)
        if str(path).endswith("a.json"):
            entered.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(module, "read_annotation_metadata", blocked)
    widget = window.labeling_widget.view
    widget.import_image_folder(str(tmp_path))
    try:
        _wait(entered.is_set)
        widget.other_data["checked"] = True
        assert widget.save_labels(str(tmp_path / "a.json"))
        release.set()
        _wait(lambda: not widget._metadata_timer.isActive())
        assert widget.file_list_widget.item(0).data(QtCore.Qt.ItemDataRole.UserRole) is True
        assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))["checked"] is True
    finally:
        release.set()
        _close_window(window, app)


def test_first_image_does_not_wait_for_per_file_delays(tmp_path, monkeypatch):
    from anylabeling.views.labeling.utils import staged_annotation_loading as module

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", auto_save=False, keep_prev=False, exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.show()
    for index in range(20):
        image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        assert image.save(str(tmp_path / f"{index:02}.png"))
        shapes = [{"label": "box", "shape_type": "rectangle", "points": [[2, 2], [12, 2], [12, 12], [2, 12]]}] if index == 0 else []
        (tmp_path / f"{index:02}.json").write_text(json.dumps({
            "version": "4.2.1", "shapes": shapes, "imagePath": f"{index:02}.png",
            "imageData": None, "imageHeight": 32, "imageWidth": 32,
        }), encoding="utf-8")
    original = module.read_annotation_metadata

    def slow(path):
        time.sleep(0.05)
        return original(path)

    monkeypatch.setattr(module, "read_annotation_metadata", slow)
    widget = window.labeling_widget.view
    widget.import_image_folder(str(tmp_path))
    _wait(lambda: widget.filename is not None and widget.canvas.isEnabled())
    assert len(widget.canvas.shapes) == 1
    _wait(lambda: widget._metadata_controller.is_running())
    assert widget._metadata_processed < 20
    _wait(lambda: not widget._metadata_timer.isActive())
    _close_window(window, app)

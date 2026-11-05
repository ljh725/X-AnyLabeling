"""Canvas panel review controls mirror the existing image ``checked`` state."""

import copy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6 import QtCore, QtWidgets

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    # begin_session() creates the target from the template; pre-creating an
    # empty file would leave the persisted baseline empty and turn the
    # startup display saves into phantom conflicts.
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    template = copy.deepcopy(load_template_config())
    user_config.begin_session(
        target_path=str(config_file),
        origin="file",
        template=copy.deepcopy(template),
        effective=copy.deepcopy(template),
        ensure_created=True,
        normalizer=normalize_user_config,
    )
    window = MainWindow(app, config=copy.deepcopy(load_template_config()))
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    window.labeling_widget.view.error_message = lambda *args, **kwargs: None
    yield window
    window.labeling_widget.view.dirty = False
    window.close()
    app.removeEventFilter(window.labeling_widget.view)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    user_config.end_session()


def make_image(tmp_path, name, color="white"):
    path = tmp_path / name
    Image.new("RGB", (64, 64), color).save(path)
    return str(path)


def test_panel_is_disabled_until_an_image_is_loaded(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment

    assert panel.isHidden()
    for button in panel.status_buttons.values():
        assert not button.isEnabled()

    widget.set_annotation_checked(True)
    assert widget.other_data.get("checked") is None
    assert not os.path.exists(str(tmp_path / "image.json"))


def test_panel_review_selection_saves_and_syncs(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    image = make_image(tmp_path, "image.png", "red")

    assert widget.load_file(image)
    assert not panel.isHidden()
    assert panel.status_buttons["failed"].isEnabled()

    panel.status_buttons["failed"].click()
    assert widget._annotation_checked() == "failed"
    assert widget.actions.fail_annotation_checked.isChecked()

    label_path = widget.get_label_file()
    with open(label_path, encoding="utf-8") as stream:
        data = json.load(stream)
    assert data["checked"] == "failed"

    widget.actions.toggle_annotation_checked.trigger()
    assert widget._annotation_checked() is True
    assert panel.status_buttons[True].isChecked()


def test_panel_follows_target_image_status(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    first = make_image(tmp_path, "a.png", "red")
    second = make_image(tmp_path, "b.png", "blue")

    assert widget.load_file(first)
    panel.status_buttons[True].click()
    assert widget._annotation_checked() is True

    assert widget.load_file(second)
    assert widget._annotation_checked() is False
    assert panel.status_buttons[False].isChecked()

    assert widget.load_file(first)
    assert widget._annotation_checked() is True
    assert panel.status_buttons[True].isChecked()


def test_stale_metadata_cannot_override_manual_status(window, tmp_path):
    from types import SimpleNamespace

    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    image = make_image(tmp_path, "image.png")

    assert widget.load_file(image)
    widget.file_list_widget.addItem(image)
    widget.fn_to_index[image] = widget.file_list_widget.count() - 1
    widget._metadata_generation = 1
    widget._metadata_revisions[image] = 1
    widget._metadata_total = 1
    widget._metadata_processed = 0

    panel.status_buttons["failed"].click()
    stale_revision = 1
    widget._metadata_results.append(
        (
            1,
            image,
            stale_revision,
            SimpleNamespace(review="unchecked", presence="present"),
        )
    )
    widget._poll_metadata()

    item = widget._current_file_item()
    assert widget._annotation_checked() == "failed"
    assert widget._file_item_annotation_checked(item)
    assert item.data(QtCore.Qt.ItemDataRole.UserRole) == "failed"


def test_programmatic_sync_does_not_save(window, tmp_path, monkeypatch):
    widget = window.labeling_widget.view
    image = make_image(tmp_path, "image.png")
    assert widget.load_file(image)

    saved = []
    monkeypatch.setattr(
        widget, "save_labels", lambda filename: saved.append(filename) or True
    )

    panel = widget.canvas_adjustment
    panel.set_status(False)
    widget._sync_annotation_checked_state()

    assert saved == []
    assert panel.status_buttons[False].isChecked()


def test_repeated_selection_does_not_rewrite(window, tmp_path, monkeypatch):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    image = make_image(tmp_path, "image.png")
    assert widget.load_file(image)

    saved = []
    monkeypatch.setattr(
        widget, "save_labels", lambda filename: saved.append(filename) or True
    )

    panel.status_buttons["failed"].click()
    assert not widget.dirty
    panel.status_buttons["failed"].click()

    assert len(saved) == 1
    assert widget._annotation_checked() == "failed"


def test_failed_save_keeps_retryable_dirty_state(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    image = make_image(tmp_path, "image.png")
    assert widget.load_file(image)

    widget.save_labels = lambda filename: False
    panel.status_buttons["failed"].click()

    assert widget.dirty
    assert widget._annotation_checked() == "failed"
    assert panel.status_buttons["failed"].isChecked()

    label_path = widget.get_label_file()
    if os.path.exists(label_path):
        with open(label_path, encoding="utf-8") as stream:
            data = json.load(stream)
        assert data["checked"] != "failed"

    del widget.save_labels
    widget.set_annotation_checked("failed")
    assert not widget.dirty
    with open(label_path, encoding="utf-8") as stream:
        data = json.load(stream)
    assert data["checked"] == "failed"

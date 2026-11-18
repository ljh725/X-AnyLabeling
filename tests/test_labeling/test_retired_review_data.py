"""Verify ordinary annotation compatibility with retired workbench data."""

import json

import pytest
import yaml
from PIL import Image
from PyQt6 import QtCore, QtWidgets

from anylabeling.config import get_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.label_converter import LabelConverter
from anylabeling.views.labeling.settings.schema import SETTINGS_KEYS
from anylabeling.views.mainwindow import MainWindow


@pytest.mark.parametrize("checked", [False, True, "failed"])
def test_retired_workbench_data_survives_normal_edit(tmp_path, checked):
    legacy = {
        "dense_review": {"task": "coverage", "image_height": 310},
        "inspector_auto_advance": False,
        "inspector_window_geometry": "legacy-geometry",
        "shortcuts": {
            "open_dense_review": "Ctrl+Alt+R",
            "inspector_next_issue": "F2",
            "dense_review_complete_batch": "Ctrl+Return",
            "open": "Ctrl+Alt+O",
        },
        "auto_save": False,
    }
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(legacy), encoding="utf-8")
    payload = {"version": "unknown", "objects": [None, "旧记录"]}
    image_path = tmp_path / "image.png"
    blank_path = tmp_path / "blank.png"
    label_path = image_path.with_suffix(".json")
    for path in (image_path, blank_path):
        Image.new("RGB", (80, 80)).save(path)
    annotation = {
        "version": "4.2.1",
        "imagePath": image_path.name,
        "imageWidth": 80,
        "imageHeight": 80,
        "imageData": None,
        "flags": {},
        "checked": checked,
        "xanylabeling_dense_review": payload,
        "vendor_extension": {"nested": [1, 2]},
        "shapes": [{
            "label": "box",
            "shape_type": "rectangle",
            "points": [[10, 10], [30, 10], [30, 30], [10, 30]],
            "xanylabeling_shape_id": "old-box-id",
            "vendor_field": "keep",
        }],
    }
    label_path.write_text(json.dumps(annotation), encoding="utf-8")
    sidecars = {
        ".xanylabeling/inspection/report.json": b'{"issues": []}\n',
        ".xanylabeling/inspection/profiles.json": b'{"rules": []}\n',
        ".xanylabeling/dense_review/config.json": b'{"legacy": true}\n',
        ".xanylabeling/dense_review/progress.json": b'{"objects": []}\n',
    }
    for relative, content in sidecars.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(app, config=get_config(str(config_file), show_msg=False))
    widget = window.labeling_widget.view
    try:
        assert not hasattr(widget.actions, "open_inspector")
        assert not hasattr(widget.actions, "open_dense_review")
        assert not any("dense_review" in key or "inspector" in key for key in SETTINGS_KEYS)
        assert widget.actions.open.shortcut().toString() == "Ctrl+Alt+O"

        assert widget.load_file(str(image_path))
        assert widget._annotation_checked() == checked
        widget.canvas.shapes[0].move_by(QtCore.QPointF(5, 0))
        widget.set_dirty()
        assert widget._save_file(str(label_path))
        assert widget.load_file(str(blank_path))
        assert widget._save_file(str(blank_path.with_suffix(".json")))
        blank = json.loads(blank_path.with_suffix(".json").read_text(encoding="utf-8"))
        assert "xanylabeling_dense_review" not in blank
        assert widget.load_file(str(image_path))
        assert widget._annotation_checked() == checked
        assert widget.canvas.shapes[0].xanylabeling_shape_id == "old-box-id"
    finally:
        widget.dirty = False
        window.close()
        app.removeEventFilter(widget)
        window.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    saved = json.loads(label_path.read_text(encoding="utf-8"))
    assert saved["xanylabeling_dense_review"] == payload
    assert saved["vendor_extension"] == annotation["vendor_extension"]
    assert saved["checked"] == checked
    assert saved["shapes"][0]["vendor_field"] == "keep"
    assert saved["shapes"][0]["points"][0] == [15, 10]
    retained_config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert retained_config["dense_review"] == legacy["dense_review"]
    assert retained_config["inspector_window_geometry"] == "legacy-geometry"
    assert all(retained_config["shortcuts"][key] == value for key, value in legacy["shortcuts"].items())
    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (tmp_path / ".xanylabeling").rglob("*") if path.is_file()
    } == sidecars

    classes_file = tmp_path / "classes.txt"
    classes_file.write_text("box\n", encoding="utf-8")
    destination = tmp_path / "training.txt"
    converter = LabelConverter(classes_file=str(classes_file))
    assert not converter.custom_to_yolo(str(label_path), str(destination), "hbb")
    class_index, *box = destination.read_text(encoding="utf-8").split()
    assert class_index == "0"
    assert [float(value) for value in box] == pytest.approx([0.3125, 0.25, 0.25, 0.25])

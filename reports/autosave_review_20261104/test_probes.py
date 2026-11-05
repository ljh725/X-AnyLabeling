"""Review probes: failures describe unmet autosave guarantees."""
import json
from unittest.mock import Mock

from PyQt6 import QtWidgets

from tests.conftest import qt_application, isolated_user_configuration
from tests.test_labeling.test_drag_commit import app, view, add_rectangle
from tests.test_dense_review.test_workspace import _prepare_image


def test_autosave_edit_roundtrip(view, tmp_path):
    add_rectangle(view)
    view._config["auto_save"] = True
    view.set_dirty()
    target = tmp_path / "drag.json"
    assert json.loads(target.read_text(encoding="utf-8"))["shapes"][0]["label"] == "person"
    assert not view.dirty
    assert view.load_file(view.image_path)
    assert view.canvas.shapes[0].label == "person"


def test_failed_write_preserves_dirty_and_leave_guard(view, tmp_path, monkeypatch):
    add_rectangle(view)
    view._config["auto_save"] = True
    view.set_dirty()
    target = tmp_path / "drag.json"
    original = target.read_bytes()
    monkeypatch.setattr(view, "error_message", Mock())
    monkeypatch.setattr("anylabeling.views.labeling.label_file.os.replace", Mock(side_effect=PermissionError("locked file")))
    view.canvas.shapes[0].label = "changed"
    view.set_dirty()
    assert view.dirty
    assert target.read_bytes() == original
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", Mock(return_value=QtWidgets.QMessageBox.StandardButton.Cancel))
    assert not view.may_continue()


def test_output_directory_autosave(view, tmp_path):
    add_rectangle(view)
    view.output_dir = str(tmp_path / "output")
    view._config["auto_save"] = True
    view.set_dirty()
    assert (tmp_path / "output" / "drag.json").is_file()
    assert not (tmp_path / "drag.json").exists()
    assert not view.dirty


def test_directory_creation_failure_is_handled(view, tmp_path, monkeypatch):
    add_rectangle(view)
    view.output_dir = str(tmp_path / "blocked")
    view._config["auto_save"] = True
    error = Mock()
    monkeypatch.setattr(view, "error_message", error)
    monkeypatch.setattr("anylabeling.views.labeling.label_widget.os.makedirs", Mock(side_effect=PermissionError("directory denied")))
    view.set_dirty()
    assert view.dirty
    error.assert_called_once()


def test_save_as_target_is_retained_by_autosave(view, tmp_path):
    add_rectangle(view)
    custom = tmp_path / "custom.json"
    assert view._save_file(str(custom))
    view._config["auto_save"] = True
    view.canvas.shapes[0].label = "changed"
    view.set_dirty()
    assert json.loads(custom.read_text(encoding="utf-8"))["shapes"][0]["label"] == "changed"


def test_autosave_observes_dense_review_conflict_guard(view, tmp_path, monkeypatch):
    image = _prepare_image(tmp_path)
    assert view.load_file(image)
    view.open_dense_review()
    view.dense_review_workspace._complete_batch()
    view.save_file()
    target = tmp_path / "image.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["description"] = "external edit must survive"
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert view._dense_review_external_conflict()
    guard = Mock(return_value=False)
    monkeypatch.setattr(view, "_dense_review_resolve_conflict", guard)
    view._config["auto_save"] = True
    view.set_dirty()
    assert json.loads(target.read_text(encoding="utf-8"))["description"] == "external edit must survive"
    guard.assert_called_once()
    assert view.dirty

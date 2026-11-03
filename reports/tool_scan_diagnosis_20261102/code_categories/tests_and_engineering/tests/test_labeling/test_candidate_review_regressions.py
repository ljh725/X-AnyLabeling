"""Exercise candidate review fixes through the real labeling window."""

import copy
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling import config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.rectangle_size import RectangleSizeRule
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    """Keep one application alive across the window regression cases."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def view(
    app: QtWidgets.QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[LabelingWidget]:
    """Open a blank image with isolated user configuration and Qt settings."""
    monkeypatch.setattr(config, "_work_directory", str(tmp_path))
    monkeypatch.setattr(
        config, "current_config_file", str(tmp_path / "config.yaml")
    )
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore,
        "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    for name, size in (("first", 200), ("second", 50), ("same", 200)):
        image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtCore.Qt.GlobalColor.white)
        assert image.save(str(tmp_path / f"{name}.png"))
    settings = copy.deepcopy(load_template_config())
    settings["auto_save"] = False
    window = MainWindow(app, config=settings)
    window.show()
    app.processEvents()
    widget = window.labeling_widget.view
    monkeypatch.setattr(
        widget, "error_message", lambda *args: pytest.fail(str(args))
    )
    assert widget.load_file(str(tmp_path / "first.png"))
    app.processEvents()
    yield widget
    widget.rectangle_creation.cancel()
    widget.dirty = False
    window.close()
    app.removeEventFilter(widget)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def add_rectangle(view: LabelingWidget) -> Shape:
    """Load and select one rectangle with a label-specific size rule."""
    shape = Shape(label="cat", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(10, 10),
        QtCore.QPointF(30, 10),
        QtCore.QPointF(30, 30),
        QtCore.QPointF(10, 30),
    ]
    shape.close()
    view.load_shapes([shape])
    view.toggle_draw_mode(edit=True)
    view.canvas.select_shapes([shape])
    return shape


def edit_label(
    view: LabelingWidget, monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    """Accept the single-object dialog without opening a modal window."""
    monkeypatch.setattr(
        view.label_dialog,
        "pop_up",
        lambda **kwargs: (label, {}, None, "", False, []),
    )
    view.edit_label()


def wait_for_size_scan(canvas: Canvas) -> None:
    """Wait for the coalesced scan without depending on UI rendering speed."""
    deadline = QtCore.QDeadlineTimer(2000)
    while canvas._rectangle_size_scan_timer.isActive():
        assert not deadline.hasExpired(), "Size-rule rescan did not finish"
        QtTest.QTest.qWait(10)


@pytest.mark.parametrize("auto_save", [False, True])
def test_right_drag_copy_can_save(
    view: LabelingWidget, tmp_path: Path, auto_save: bool
) -> None:
    """Copy here produces a distinct identity accepted by the save path."""
    original = add_rectangle(view)
    view._config["auto_save"] = auto_save
    original_id = original.xanylabeling_shape_id
    view.canvas.selected_shapes_copy = [original.copy()]
    view.copy_shape()
    assert len(view.canvas.shapes) == 2
    assert original.xanylabeling_shape_id == original_id
    assert view.canvas.shapes[-1].xanylabeling_shape_id != original_id
    target = tmp_path / "first.json"
    assert view.save_labels(str(target))
    data = json.loads(target.read_text(encoding="utf-8"))
    assert len({s["xanylabeling_shape_id"] for s in data["shapes"]}) == 2


def test_right_drag_move_keeps_identity(view: LabelingWidget) -> None:
    """Move here preserves the original annotation identity."""
    original = add_rectangle(view)
    original_id = original.xanylabeling_shape_id
    view.canvas.selected_shapes_copy = [original.copy()]
    view.canvas.selected_shapes_copy[0].points[0] = QtCore.QPointF(5, 5)
    view.move_shape()
    assert len(view.canvas.shapes) == 1
    assert original.xanylabeling_shape_id == original_id
    assert original.points[0] == QtCore.QPointF(5, 5)


def test_batch_undo_preserves_single_label_edit(
    view: LabelingWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Undoing a batch keeps the label accepted immediately before it."""
    shape = add_rectangle(view)
    edit_label(view, monkeypatch, "dog")
    view._apply_field_patch([shape], {"description": "batch"}, {"description"})
    view.undo_shape_edit()
    assert view.canvas.shapes[0].label == "dog"
    assert view.canvas.shapes[0].description == ""


def test_batch_undo_preserves_saved_attribute_edit(
    view: LabelingWidget,
) -> None:
    """An attribute saved before a batch survives that batch's undo."""
    shape = add_rectangle(view)
    line = QtWidgets.QLineEdit("reviewed")
    view.attribute_line_changed(0, "status", line)
    view._relabel_selection([shape], "dog")
    view.undo_shape_edit()
    assert view.canvas.shapes[0].label == "cat"
    assert view.canvas.shapes[0].attributes == {"status": "reviewed"}


def test_extreme_available_on_first_blank_image(view: LabelingWidget) -> None:
    """A newly loaded unannotated image enables four-extreme creation."""
    assert not view.canvas.shapes
    assert view.rectangle_creation.commands["rectangle_extreme"].isEnabled()


@pytest.mark.parametrize("next_image", ["second", "same"])
def test_file_change_cancels_extreme_draft(
    view: LabelingWidget, tmp_path: Path, next_image: str
) -> None:
    """File changes discard old boundaries regardless of image dimensions."""
    workflow = view.rectangle_creation
    workflow.start_extreme()
    assert workflow.draft.accept(10, 100)
    assert workflow.draft.accept(150, 10)
    assert view.load_file(str(tmp_path / f"{next_image}.png"))
    assert workflow.draft is None
    assert view.canvas.editing()
    assert not workflow.commands["rectangle_back"].isEnabled()
    assert workflow.commands["rectangle_extreme"].isEnabled()


def test_close_image_cancels_extreme_draft(view: LabelingWidget) -> None:
    """Clearing the image drops its draft and disables image actions."""
    workflow = view.rectangle_creation
    workflow.start_extreme()
    assert workflow.draft.accept(10, 20)
    view.reset_state()
    assert workflow.draft is None
    assert not workflow.commands["rectangle_extreme"].isEnabled()


def test_failed_image_load_cancels_extreme_draft(
    view: LabelingWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable new image cannot retain the previous image's draft."""
    workflow = view.rectangle_creation
    workflow.start_extreme()
    assert workflow.draft.accept(10, 20)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"invalid image")
    errors = []
    monkeypatch.setattr(
        view, "error_message", lambda *args: errors.append(args)
    )
    assert not view.load_file(str(broken))
    assert errors
    assert workflow.draft is None
    assert not workflow.commands["rectangle_extreme"].isEnabled()


def test_image_adjustment_preserves_extreme_draft(
    view: LabelingWidget,
) -> None:
    """Replacing pixels for brightness adjustment retains the same draft."""
    workflow = view.rectangle_creation
    workflow.start_extreme()
    assert workflow.draft.accept(10, 20)
    draft = workflow.draft
    view.canvas.load_pixmap(view.canvas.pixmap, clear_shapes=False)
    assert workflow.draft is draft
    assert draft.points == [(10, 20)]


def test_size_warning_returns_after_filter_unhides_shape(
    view: LabelingWidget,
) -> None:
    """A rectangle excluded from a scan is checked when made visible."""
    add_rectangle(view)
    view._sync_label_list_visibility(lambda item: False)
    view.canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    view.canvas.show_rectangle_size_violations = True
    wait_for_size_scan(view.canvas)
    assert not view.canvas.rectangle_size_issues
    view._sync_label_list_visibility(lambda item: True)
    wait_for_size_scan(view.canvas)
    assert len(view.canvas.rectangle_size_issues) == 1


def test_size_warning_refreshes_after_single_label_edit(
    view: LabelingWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing a rule-matched label removes its obsolete warning."""
    add_rectangle(view)
    view.canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    view.canvas.show_rectangle_size_violations = True
    wait_for_size_scan(view.canvas)
    assert len(view.canvas.rectangle_size_issues) == 1
    edit_label(view, monkeypatch, "dog")
    wait_for_size_scan(view.canvas)
    assert not view.canvas.rectangle_size_issues

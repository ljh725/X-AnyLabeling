"""Commit timing of a real rectangle drag (CUSTOM-003).

The refresh change must not alter when a drag is committed: one save on
release with auto-save enabled, and an enabled undo that restores the position
from before the drag.  A per-move commit would show up here as extra saves.
"""

import copy
import json
import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def view(
    app: QtWidgets.QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[LabelingWidget]:
    monkeypatch.setattr(config, "_work_directory", str(tmp_path))
    monkeypatch.setattr(config, "current_config_file", str(tmp_path / "config.yaml"))
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore,
        "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    image = QtGui.QImage(200, 200, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtCore.Qt.GlobalColor.white)
    assert image.save(str(tmp_path / "drag.png"))
    settings = copy.deepcopy(load_template_config())
    settings["auto_save"] = False
    window = MainWindow(app, config=settings)
    window.show()
    app.processEvents()
    widget = window.labeling_widget.view
    monkeypatch.setattr(widget, "error_message", lambda *args: pytest.fail(str(args)))
    assert widget.load_file(str(tmp_path / "drag.png"))
    app.processEvents()
    yield widget
    widget.rectangle_creation.cancel()
    widget.dirty = False
    window.close()
    app.removeEventFilter(widget)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def add_rectangle(view: LabelingWidget) -> Shape:
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(40, 40),
        QtCore.QPointF(120, 40),
        QtCore.QPointF(120, 120),
        QtCore.QPointF(40, 120),
    ]
    shape.close()
    view.load_shapes([shape])
    view.toggle_draw_mode(edit=True)
    view.canvas.select_shapes([shape])
    return shape


def send(
    canvas: Canvas,
    kind: QtCore.QEvent.Type,
    point: tuple[float, float],
    held: bool = False,
) -> None:
    pos = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    button = (
        QtCore.Qt.MouseButton.NoButton
        if kind == QtCore.QEvent.Type.MouseMove
        else QtCore.Qt.MouseButton.LeftButton
    )
    buttons = (
        QtCore.Qt.MouseButton.LeftButton
        if held or kind == QtCore.QEvent.Type.MouseButtonPress
        else QtCore.Qt.MouseButton.NoButton
    )
    event = QtGui.QMouseEvent(
        kind, pos, pos, button, buttons, QtCore.Qt.KeyboardModifier.NoModifier
    )
    {
        QtCore.QEvent.Type.MouseMove: canvas.mouseMoveEvent,
        QtCore.QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
        QtCore.QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
    }[kind](event)


def bounds(shape: Shape) -> tuple[float, float, float, float]:
    xs = [point.x() for point in shape.points]
    ys = [point.y() for point in shape.points]
    return min(xs), min(ys), max(xs), max(ys)


def assert_bounds(shape: Shape, expected: tuple[float, float, float, float]) -> None:
    assert bounds(shape) == pytest.approx(expected, abs=0.01)


def test_autosave_runs_once_when_the_drag_is_released(
    view: LabelingWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-save follows the existing release commit, never a single move."""
    canvas = view.canvas
    shape = add_rectangle(view)
    view._config["auto_save"] = True
    saves: list = []
    original = view.save_labels

    def counting_save(*args, **kwargs):
        saves.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(view, "save_labels", counting_save)

    send(canvas, QtCore.QEvent.Type.MouseMove, (80, 80))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (80, 80))
    for step in range(1, 6):
        send(canvas, QtCore.QEvent.Type.MouseMove, (80 + step, 80 + step), held=True)
    assert saves == [], "moving must not save"

    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (85, 85))
    assert len(saves) == 1
    assert_bounds(shape, (45, 45, 125, 125))


def test_drag_survives_save_and_reopen(
    view: LabelingWidget, tmp_path: Path
) -> None:
    """The saved file and the reopened canvas agree with the drop position."""
    canvas = view.canvas
    add_rectangle(view)
    image_path = view.image_path
    label_path = str(tmp_path / "drag.json")

    send(canvas, QtCore.QEvent.Type.MouseMove, (80, 80))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (80, 80))
    for step in range(1, 6):
        send(canvas, QtCore.QEvent.Type.MouseMove, (80 + step, 80 + step), held=True)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (85, 85))

    assert view.save_labels(label_path)

    data = json.loads(Path(label_path).read_text(encoding="utf-8"))
    saved = data["shapes"][0]["points"]
    saved_x = [point[0] for point in saved]
    saved_y = [point[1] for point in saved]
    assert min(saved_x) == pytest.approx(45, abs=0.01)
    assert max(saved_x) == pytest.approx(125, abs=0.01)
    assert min(saved_y) == pytest.approx(45, abs=0.01)
    assert max(saved_y) == pytest.approx(125, abs=0.01)

    assert view.load_file(image_path)
    assert len(canvas.shapes) == 1
    assert_bounds(canvas.shapes[0], (45, 45, 125, 125))


def test_undo_is_available_after_the_drag(view: LabelingWidget) -> None:
    """The drop leaves exactly one undo step for the whole drag."""
    canvas = view.canvas
    shape = add_rectangle(view)

    send(canvas, QtCore.QEvent.Type.MouseMove, (80, 80))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (80, 80))
    for step in range(1, 5):
        send(canvas, QtCore.QEvent.Type.MouseMove, (80 + step, 80 + step), held=True)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (84, 84))

    assert view.actions.undo.isEnabled()
    assert_bounds(shape, (44, 44, 124, 124))

    canvas.restore_shape()
    assert_bounds(canvas.shapes[0], (40, 40, 120, 120))

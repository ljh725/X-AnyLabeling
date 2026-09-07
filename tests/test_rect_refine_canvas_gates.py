"""Canvas integration tests for lightweight three-box focus."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anylabeling.config as _cfgmod  # noqa: E402

_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "anylabeling",
    "configs",
    "xanylabeling_config.yaml",
)
_cfgmod.current_config_file = _CFG_PATH

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.views.labeling.label_wrapper import (  # noqa: E402
    LabelingWrapper,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402

pytest.importorskip("PIL")
from PIL import Image as _PIL_Image  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QtWidgets.QApplication]:
    """Provide one offscreen QApplication for this module."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def png_path(tmp_path: Path) -> str:
    """Create one small image for the real labeling widget."""
    path = tmp_path / "img.png"
    _PIL_Image.new("RGB", (300, 300), (255, 255, 255)).save(path)
    return str(path)


@pytest.fixture
def widget(
    qapp: QtWidgets.QApplication,
    png_path: str,
) -> Iterator[Any]:
    """Provide a real LabelingWidget with one loaded image."""
    del qapp
    main_window = QtWidgets.QMainWindow()
    wrapper = LabelingWrapper(main_window)
    labeling_widget = wrapper.view
    assert labeling_widget.load_file(png_path) is True
    yield labeling_widget
    main_window.close()


def _rect(
    label: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> Shape:
    """Create one axis-aligned rectangle Shape."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + width, y),
        QtCore.QPointF(x + width, y + height),
        QtCore.QPointF(x, y + height),
    ]
    return shape


def _enter_focus(
    widget: Any,
    person: Shape,
    head: Shape,
    *extra: Shape,
) -> None:
    """Load Shapes, enable the mode, and focus from the person."""
    widget.load_shapes(
        [person, head, *extra],
        replace=True,
        store_backup=False,
    )
    widget._toggle_rect_refine_mode(True)
    widget.canvas.select_shapes([person], source="canvas")
    assert widget._rect_refine_focus_controller.has_focus is True


def test_no_focus_keeps_native_base_visibility(widget: Any) -> None:
    """Without focus, main visibility is exactly the existing base layer."""
    canvas = widget.canvas
    assert canvas._main_visibility_predicate is None

    shape = _rect("person", 0, 0, 10, 10)
    canvas.visible[shape] = True
    assert canvas.main_visible(shape) is True

    shape.hidden_by_filter = True
    assert canvas.base_visible(shape) is False
    assert canvas.main_visible(shape) is False


def test_real_widget_selection_never_auto_navigates_thumbnails(
    widget: Any,
) -> None:
    """Repeated category selection cannot feed back into thumbnail queries."""
    import json
    from anylabeling.views.labeling.dataset_index import DatasetFilterIndex
    from anylabeling.views.labeling.widgets.dataset_thumbnail import (
        DatasetLabelThumbnailWindow,
    )

    shapes = [_rect("person", 20, 20, 30, 40), _rect("head", 80, 20, 20, 20)]
    widget.load_shapes(shapes, replace=True, store_backup=False)
    source = Path(widget.filename).with_suffix(".json")
    source.write_text(
        json.dumps(
            {
                "shapes": [
                    dict(
                        label=shape.label,
                        shape_type="rectangle",
                        xanylabeling_shape_id=shape.xanylabeling_shape_id,
                        points=[[p.x(), p.y()] for p in shape.points],
                    )
                    for shape in shapes
                ]
            }
        ),
        encoding="utf-8",
    )
    index = DatasetFilterIndex(":memory:")
    index.rebuild([widget.filename], dataset_root=str(source.parent))

    class Controller(QtCore.QObject):
        """Count real index reads while the main widget changes selection."""

        is_query_ready = True
        state_value = "ready"
        is_busy = False
        query_calls = 0

        def query_thumbnail_objects(self, *args):
            """Count page queries."""
            self.query_calls += 1
            return index.query_thumbnail_objects(*args)

        def __getattr__(self, name):
            """Forward remaining read-only index queries."""
            return getattr(index, name)

    controller = Controller()
    window = DatasetLabelThumbnailWindow(
        controller, "test", str(Path(widget.filename).parent)
    )
    widget._dataset_thumbnail_window = window
    window.show()
    QtWidgets.QApplication.processEvents()
    initial = controller.query_calls
    label = window._selected_label
    for i in range(100):
        widget.canvas.select_shapes([shapes[i % 2]], source="canvas")
    assert controller.query_calls == initial
    assert window._selected_label == label
    widget.canvas.select_shapes([shapes[0]], source="inspector")
    action = widget.object_mark_actions.locate_in_thumbnails
    assert action.isEnabled()
    assert action.shortcut().toString() == "Ctrl+Alt+T"
    action.trigger()
    assert window._selected_label == "person"
    assert not window._selected_refs()
    widget.canvas.prev_point = QtCore.QPointF(25, 25)
    widget.canvas.move_by_keyboard(QtCore.QPointF(1, 0))
    widget.canvas.keyReleaseEvent(
        QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyRelease,
            QtCore.Qt.Key.Key_Right,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
    )
    assert widget.canvas.is_shape_restorable
    window.close()
    widget._dataset_thumbnail_window = None
    widget.set_clean()
    index.close()


def test_focus_hides_nonmembers_and_preserves_base_hidden(widget: Any) -> None:
    """Focus narrows the task layer without overriding native hiding."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    hidden_face = _rect("face", 50, 30, 30, 35)
    hidden_face.hidden_by_filter = True
    stranger = _rect("car", 200, 200, 50, 50)
    _enter_focus(widget, person, head, hidden_face, stranger)

    canvas = widget.canvas
    assert canvas.main_visible(person) is True
    assert canvas.main_visible(head) is True
    assert canvas.base_visible(hidden_face) is False
    assert canvas.main_visible(hidden_face) is False
    assert canvas.base_visible(stranger) is True
    assert canvas.main_visible(stranger) is False


def test_focused_nonmember_is_not_interactive(widget: Any) -> None:
    """A filtered-out Shape cannot be hovered, selected, or edited."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    stranger = _rect("car", 200, 200, 50, 50)
    _enter_focus(widget, person, head, stranger)

    assert widget.canvas.is_shape_interactive(person) is True
    assert widget.canvas.is_shape_interactive(stranger) is False
    candidates = (
        widget.canvas._shape_hit_candidates(QtCore.QPointF(225, 225)) or []
    )
    assert stranger not in candidates


def test_focused_member_keeps_native_keyboard_move(
    widget: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Focus does not install the removed whole-shape edit blocker."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    _enter_focus(widget, person, head)
    offsets: list[QtCore.QPointF] = []
    monkeypatch.setattr(widget.canvas, "move_by_keyboard", offsets.append)

    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Right,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    widget.canvas.keyPressEvent(event)

    assert offsets == [QtCore.QPointF(1.0, 0.0)]


def test_canvas_has_no_legacy_transaction_hooks(widget: Any) -> None:
    """Canvas exposes focus primitives but no workflow-era hooks."""
    canvas = widget.canvas
    assert hasattr(canvas, "set_main_visibility_predicate")
    assert hasattr(canvas, "escape_pressed")
    assert not hasattr(canvas, "set_escape_workgroup_handler")
    assert not hasattr(canvas, "set_whole_shape_edit_blocker")
    assert not hasattr(canvas, "set_overlay_provider")


def test_navigator_keeps_base_layer_while_canvas_is_focused(
    widget: Any,
) -> None:
    """The overview remains governed by the pre-existing visibility state."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    stranger = _rect("car", 200, 200, 50, 50)
    _enter_focus(widget, person, head, stranger)
    captured: dict[str, Any] = {}

    class _FakeNavigator:
        """Capture the navigator visibility map."""

        @staticmethod
        def isVisible() -> bool:
            """Report the fake navigator as visible."""
            return True

        @staticmethod
        def set_shapes(shapes: list[Shape], visibility: dict) -> None:
            """Record the navigator inputs."""
            captured["shapes"] = shapes
            captured["visibility"] = dict(visibility)

    widget.navigator_dialog = _FakeNavigator()
    widget.update_navigator_shapes()

    visibility = captured["visibility"]
    assert visibility[stranger] is True
    assert visibility[person] is True
    assert visibility[head] is True


def test_escape_clears_focus_only(widget: Any) -> None:
    """Esc removes the focus predicate while keeping the mode enabled."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    _enter_focus(widget, person, head)

    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    widget.canvas.keyPressEvent(event)

    assert widget._rect_refine_focus_controller.has_focus is False
    assert widget._rect_refine_focus_controller.enabled is True
    assert widget.canvas._main_visibility_predicate is None


def test_rect_edge_escape_takes_priority_over_focus(widget: Any) -> None:
    """An active rectangle-edge drag consumes Esc before focus clearing."""
    from anylabeling.views.labeling.rect_edge_alignment import iter_edges

    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    _enter_focus(widget, person, head)
    canvas = widget.canvas
    canvas.set_rect_edge_align_enabled(True)
    canvas.rect_edge_active_edge = next(iter(iter_edges(person)))
    canvas.rect_edge_drag_start_points = list(person.points)
    assert canvas.rect_edge_dragging is True

    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.keyPressEvent(event)

    assert canvas.rect_edge_dragging is False
    assert widget._rect_refine_focus_controller.has_focus is True
    assert canvas._main_visibility_predicate is not None

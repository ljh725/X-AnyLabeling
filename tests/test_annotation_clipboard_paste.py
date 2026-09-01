"""Regression tests for repeatable annotation clipboard paste."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

import pytest

from anylabeling.config import get_default_config
from anylabeling.services.auto_labeling import model_manager
from anylabeling.views.labeling import label_widget as label_widget_module
from anylabeling.views.labeling.label_file import LabelFile
from anylabeling.views.labeling.rectangle_size.models import RectangleSizeRule
from anylabeling.views.labeling.shape import Shape


def _rectangle(
    label: str = "person",
    *,
    group_id: int = 7,
    offset: float = 0.0,
) -> Shape:
    """Return one richly populated rectangle for paste assertions."""
    shape = Shape(
        label=label,
        shape_type="rectangle",
        group_id=group_id,
        description=f"{label} description",
        flags={"reviewed": True},
        attributes={"occluded": False},
    )
    shape.points = [
        QtCore.QPointF(10.0 + offset, 10.0),
        QtCore.QPointF(30.0 + offset, 30.0),
    ]
    return shape


def _point_tuples(shape: Shape) -> tuple[tuple[float, float], ...]:
    """Return immutable point coordinates for one Shape."""
    return tuple((point.x(), point.y()) for point in shape.points)


def _backup_snapshot(canvas: object) -> tuple[tuple[dict[str, Any], ...], ...]:
    """Return a serializable Canvas backup snapshot."""
    return tuple(
        tuple(shape.to_dict() for shape in backup)
        for backup in canvas.shapes_backups
    )


@pytest.fixture
def labeling_widget(qapp, monkeypatch) -> Iterator[object]:
    """Yield a real LabelingWidget with isolated configuration state."""
    config = copy.deepcopy(get_default_config())
    config["system_clipboard"] = False
    config["auto_save"] = False
    monkeypatch.setattr(
        label_widget_module, "save_config", lambda _config: None
    )
    monkeypatch.setattr(model_manager, "get_config", lambda: config)
    main_window = QtWidgets.QMainWindow()
    wrapper = QtWidgets.QWidget()
    wrapper.parent = main_window
    widget = label_widget_module.LabelingWidget(
        parent=wrapper,
        config=config,
    )
    try:
        yield widget
    finally:
        widget.rectangle_size_controller.monitor.clear_shapes()
        widget.dirty = False
        widget.close()
        widget.deleteLater()
        wrapper.deleteLater()
        main_window.deleteLater()
        qapp.processEvents()


def test_in_memory_repeated_paste_creates_independent_shapes(
    labeling_widget,
) -> None:
    """Two paste commands must create two independent live annotations."""
    widget = labeling_widget
    source = _rectangle()
    widget.load_shapes([source], store_backup=False)
    widget.canvas._set_selected_shapes([source], source="canvas")
    widget.copy_selected_shape()
    clipboard_template = widget._copied_shapes[0]
    events = []
    widget._behavior_action = lambda name, **_kwargs: events.append(name)

    widget.paste_selected_shape()
    widget.paste_selected_shape()

    assert len(widget.canvas.shapes) == 3
    first, second = widget.canvas.shapes[-2:]
    assert first is not second
    assert first is not clipboard_template
    assert second is not clipboard_template
    assert first.xanylabeling_shape_id != second.xanylabeling_shape_id
    assert len({id(shape) for shape in widget.canvas.shapes}) == 3
    assert widget.label_list.find_item_by_shape(first).shape() is first
    assert widget.label_list.find_item_by_shape(second).shape() is second
    assert widget.rectangle_size_controller.monitor.shapes == tuple(
        widget.canvas.shapes
    )
    assert events == ["shape_created", "shape_created"]

    second_x = second.points[0].x()
    first.points[0].setX(99.0)
    assert second.points[0].x() == second_x


def test_repeated_multi_shape_paste_preserves_fields_and_resets_transients(
    labeling_widget,
) -> None:
    """Each multi-shape paste must create a complete independent batch."""
    widget = labeling_widget
    person = _rectangle("person", group_id=12)
    head = _rectangle("head", group_id=12, offset=4.0)
    widget.load_shapes([person, head], store_backup=False)
    widget.canvas._set_selected_shapes([person, head], source="canvas")
    person.hovered = True
    person.fill = True
    person.visible = False
    person.hidden_by_filter = True
    widget.copy_selected_shape()

    widget.paste_selected_shape()
    widget.paste_selected_shape()

    first_batch = widget.canvas.shapes[2:4]
    second_batch = widget.canvas.shapes[4:6]
    assert len(first_batch) == len(second_batch) == 2
    pasted = first_batch + second_batch
    assert len({id(shape) for shape in pasted}) == 4
    assert len({shape.xanylabeling_shape_id for shape in pasted}) == 4
    for batch in (first_batch, second_batch):
        assert [shape.label for shape in batch] == ["person", "head"]
        assert [shape.group_id for shape in batch] == [12, 12]
        assert [shape.description for shape in batch] == [
            "person description",
            "head description",
        ]
        assert [shape.flags for shape in batch] == [
            {"reviewed": True},
            {"reviewed": True},
        ]
        assert [shape.attributes for shape in batch] == [
            {"occluded": False},
            {"occluded": False},
        ]
        assert [_point_tuples(shape) for shape in batch] == [
            _point_tuples(person),
            _point_tuples(head),
        ]
    for shape in pasted:
        assert shape.selected is False
        assert shape.hovered is False
        assert shape.fill is False
        assert shape.visible is True
        assert getattr(shape, "hidden_by_filter", False) is False


def test_clipboard_templates_survive_three_image_replacements(
    labeling_widget,
) -> None:
    """One clipboard template must materialize independently on each image."""
    widget = labeling_widget
    source = _rectangle()
    widget.load_shapes([source], store_backup=False)
    widget.canvas._set_selected_shapes([source], source="canvas")
    widget.copy_selected_shape()
    clipboard_template = widget._copied_shapes[0]
    events = []
    widget._behavior_action = lambda name, **_kwargs: events.append(name)
    template_id = clipboard_template.xanylabeling_shape_id
    pasted_by_image = []

    for _image_index in range(3):
        widget.label_list.clear()
        widget.canvas.load_shapes([], replace=True, store_backup=False)
        widget.paste_selected_shape()
        pasted_by_image.append(widget.canvas.shapes[0])

    assert widget._copied_shapes[0] is clipboard_template
    assert clipboard_template.xanylabeling_shape_id == template_id
    assert len({id(shape) for shape in pasted_by_image}) == 3
    assert len({shape.xanylabeling_shape_id for shape in pasted_by_image}) == 3
    assert all(shape is not clipboard_template for shape in pasted_by_image)


def test_system_clipboard_repeated_paste_remains_compatible(
    labeling_widget,
) -> None:
    """System clipboard paste must also create aligned independent objects."""
    widget = labeling_widget
    widget._config["system_clipboard"] = True
    source = _rectangle("head")
    widget.load_shapes([source], store_backup=False)
    widget.canvas._set_selected_shapes([source], source="canvas")
    widget.copy_selected_shape()

    widget.paste_selected_shape()
    widget.paste_selected_shape()

    first, second = widget.canvas.shapes[-2:]
    assert first is not second
    assert first.xanylabeling_shape_id != second.xanylabeling_shape_id
    assert first.label == second.label == "head"
    assert widget.label_list.find_item_by_shape(first).shape() is first
    assert widget.label_list.find_item_by_shape(second).shape() is second


def test_canvas_invalid_append_is_atomic(canvas) -> None:
    """Canvas must reject object aliases before changing any live state."""
    current = _rectangle()
    canvas.load_shapes([current], replace=True, store_backup=True)
    canvas._set_selected_shapes([current], source="canvas")
    before_shapes = tuple(canvas.shapes)
    before_selection = tuple(canvas.selected_shapes)
    before_backups = _backup_snapshot(canvas)
    snapshots = []
    canvas.shapes_changed.connect(snapshots.append)

    with pytest.raises(ValueError, match="already owned"):
        canvas.load_shapes([current], replace=False)

    assert tuple(canvas.shapes) == before_shapes
    assert tuple(canvas.selected_shapes) == before_selection
    assert _backup_snapshot(canvas) == before_backups
    assert snapshots == []

    duplicate = _rectangle("head")
    with pytest.raises(ValueError, match="duplicate objects"):
        canvas.load_shapes([duplicate, duplicate], replace=False)

    assert tuple(canvas.shapes) == before_shapes
    assert tuple(canvas.selected_shapes) == before_selection
    assert _backup_snapshot(canvas) == before_backups
    assert snapshots == []


def test_canvas_replace_allows_current_objects_but_rejects_aliases(
    canvas,
) -> None:
    """Replacement may reuse current objects but may not repeat one object."""
    first = _rectangle()
    second = _rectangle("head")
    canvas.load_shapes([first, second], replace=True, store_backup=False)

    canvas.load_shapes([second, first], replace=True, store_backup=False)
    assert canvas.shapes == [second, first]

    before_shapes = tuple(canvas.shapes)
    with pytest.raises(ValueError, match="duplicate objects"):
        canvas.load_shapes([first, first], replace=True, store_backup=False)

    assert tuple(canvas.shapes) == before_shapes


def test_label_widget_invalid_append_is_atomic(labeling_widget) -> None:
    """Wrapper preflight must run before label-list or dirty-state mutation."""
    widget = labeling_widget
    current = _rectangle()
    widget.load_shapes([current], replace=True, store_backup=True)
    widget.dirty = False
    before_shapes = tuple(widget.canvas.shapes)
    before_labels = tuple(item.shape() for item in widget.label_list)
    before_selection = tuple(widget.canvas.selected_shapes)
    before_backups = _backup_snapshot(widget.canvas)
    snapshots = []
    widget.canvas.shapes_changed.connect(snapshots.append)

    with pytest.raises(ValueError, match="already owned"):
        widget.load_shapes([current], replace=False)

    assert tuple(widget.canvas.shapes) == before_shapes
    assert tuple(item.shape() for item in widget.label_list) == before_labels
    assert tuple(widget.canvas.selected_shapes) == before_selection
    assert _backup_snapshot(widget.canvas) == before_backups
    assert widget.dirty is False
    assert snapshots == []


def test_offscreen_smoke_undo_save_reload_and_size_overlay(
    labeling_widget,
    tmp_path,
    qapp,
) -> None:
    """Exercise slow/rapid paste, undo, JSON reload, and size monitoring."""
    widget = labeling_widget
    widget.rectangle_size_controller.set_rules(
        (RectangleSizeRule(label="person", min_width_px=40.0),)
    )
    widget.rectangle_size_controller.set_enabled(True)
    source = _rectangle()
    widget.load_shapes([source], store_backup=False)
    widget.canvas._set_selected_shapes([source], source="canvas")
    widget.copy_selected_shape()

    widget.paste_selected_shape()
    QtTest.QTest.qWait(40)
    widget.paste_selected_shape()
    widget.paste_selected_shape()
    qapp.processEvents()

    assert len(widget.canvas.shapes) == 4
    assert len({id(shape) for shape in widget.canvas.shapes}) == 4
    assert len(widget.canvas.rectangle_size_issues) == 4

    widget.undo_shape_edit()
    qapp.processEvents()
    assert len(widget.canvas.shapes) == 3
    assert len({id(shape) for shape in widget.canvas.shapes}) == 3
    assert len(widget.canvas.rectangle_size_issues) == 3

    image_path = tmp_path / "paste-smoke.png"
    label_path = tmp_path / "paste-smoke.json"
    image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    assert image.save(str(image_path))
    LabelFile().save(
        filename=str(label_path),
        shapes=[shape.to_dict() for shape in widget.canvas.shapes],
        image_path=image_path.name,
        image_height=100,
        image_width=100,
        image_data=None,
        other_data={},
        flags={},
    )

    reloaded = LabelFile(str(label_path))
    widget.label_list.clear()
    widget.load_shapes(
        reloaded.shapes,
        replace=True,
        update_last_label=False,
        store_backup=False,
    )
    qapp.processEvents()

    assert len(widget.canvas.shapes) == 3
    assert len({id(shape) for shape in widget.canvas.shapes}) == 3
    assert (
        len({shape.xanylabeling_shape_id for shape in widget.canvas.shapes})
        == 3
    )
    assert len(widget.canvas.rectangle_size_issues) == 3

"""Exercise digit shortcuts through mouse completion and JSON reload."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from PyQt6 import QtCore, QtTest, QtWidgets

from anylabeling import config as app_config, user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.auto_labeling.types import AutoLabelingMode
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch, request):
    # Production hands the live config object to the session as ``effective``.
    shared = request.node.get_closest_marker("shared_config") is not None
    app = QtWidgets.QApplication.instance()
    config_path = tmp_path / "config.yaml"
    # begin_session() creates the target from the template; pre-creating an
    # empty file would leave the persisted baseline empty and turn the
    # startup display saves into phantom conflicts that block the window in a
    # modal dialog before the test can patch ``error_message``.
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    monkeypatch.setattr(app_config, "current_config_file", str(config_path))
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore, "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    config = copy.deepcopy(load_template_config())
    user_config.begin_session(
        target_path=str(config_path), origin="file",
        template=copy.deepcopy(config), effective=config if shared else copy.deepcopy(config),
        ensure_created=True, normalizer=normalize_user_config,
    )
    result = MainWindow(app, config=config)
    result.resize(1400, 900)
    result.show()
    result.activateWindow()
    app.processEvents()
    widget = result.labeling_widget.view
    widget.error_message = Mock()
    # A digit binding must avoid the label popup entirely.
    widget.label_dialog.pop_up = Mock(side_effect=AssertionError("Unexpected popup"))
    yield result
    widget.dirty = False
    result.close()
    app.removeEventFilter(widget)
    result.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def click_points(widget, points):
    """Complete the shape under construction with the given image clicks."""
    canvas = widget.canvas
    canvas.setFocus()
    QtWidgets.QApplication.processEvents()
    for x, y in points:
        point = (QtCore.QPointF(x, y) + canvas.offset_to_center()) * canvas.scale
        QtTest.QTest.mouseClick(
            canvas, QtCore.Qt.MouseButton.LeftButton, pos=point.toPoint()
        )
    QtWidgets.QApplication.processEvents()
    assert canvas.current is None


def draw_rectangle(
    widget, digit, first=(20, 30), second=(100, 110), expected_shapes=1
):
    canvas = widget.canvas
    canvas.setFocus()
    QtWidgets.QApplication.processEvents()
    QtTest.QTest.keyClick(canvas, getattr(QtCore.Qt.Key, f"Key_{digit}"))
    assert canvas.drawing()
    assert canvas.create_mode == "rectangle"
    assert widget.digit_to_label == "车辆"
    click_points(widget, (first, second))
    assert len(canvas.shapes) == expected_shapes
    assert len(widget.label_list) == expected_shapes
    widget.error_message.assert_not_called()


def draw_plain_rectangle(widget, first=(120, 30), second=(180, 100)):
    """Finish one rectangle through the ordinary tool, without a digit key."""
    widget.toggle_draw_mode(edit=False, create_mode="rectangle")
    click_points(widget, (first, second))
    widget.error_message.assert_not_called()


def select_class(widget, label):
    """Preselect one class in the label list, like a user single click."""
    items = widget.unique_label_list.find_items_by_label(label)
    item = (
        items[0]
        if items
        else widget.unique_label_list.create_item_from_label(label)
    )
    if not items:
        widget.unique_label_list.addItem(item)
    widget.unique_label_list.clearSelection()
    item.setSelected(True)
    assert widget.unique_label_list.selectedItems() == [item]
    return item


def test_digit_hint_menu_placement_persistence_and_canvas_space(window):
    import yaml

    widget = window.labeling_widget.view
    action = widget.actions.show_digit_shortcuts
    bar = widget.digit_shortcut_bar
    view_actions = widget.menus.view.actions()
    assert view_actions.index(action) == view_actions.index(widget.rectangle_edge_action) + 1
    assert action not in widget.actions.tool
    assert bar.isHidden()
    canvas_height = widget._central_widget.height()

    action.trigger()
    QtWidgets.QApplication.processEvents()
    assert action.isChecked()
    assert bar.isVisible()
    assert widget._central_widget.height() < canvas_height
    assert not any(button.isEnabled() for button in bar.buttons.values())
    target = user_config.current_session().target_path
    with open(target, encoding="utf-8") as stream:
        assert yaml.safe_load(stream)["show_digit_shortcuts"] is True

    action.trigger()
    QtWidgets.QApplication.processEvents()
    assert bar.isHidden()
    assert widget._central_widget.height() == canvas_height
    with open(target, encoding="utf-8") as stream:
        assert yaml.safe_load(stream)["show_digit_shortcuts"] is False


def test_digit_hint_toggle_rolls_back_on_save_failure(window, monkeypatch):
    widget = window.labeling_widget.view
    monkeypatch.setattr(widget, "update_user_preference", lambda *_args: False)
    widget.actions.show_digit_shortcuts.trigger()
    assert not widget.actions.show_digit_shortcuts.isChecked()
    assert widget.digit_shortcut_bar.isHidden()


@pytest.mark.parametrize("auto_save", [True, False])
def test_digit_hint_click_and_key_share_draw_and_relabel_behavior(window, tmp_path, auto_save):
    widget = window.labeling_widget.view
    widget._config["auto_save"] = auto_save
    baseline = dict(widget.drawing_digit_shortcuts or {})
    proposed = dict(baseline)
    proposed.update({
        1: {"mode": "rectangle", "label": "车辆"},
        2: {"mode": "rectangle", "label": "Book"},
    })
    assert widget._commit_digit_shortcuts(proposed, baseline)[0]
    assert widget.digit_shortcut_bar.buttons[1].label == "车辆"
    image_path = tmp_path / "digit-hints.png"
    Image.new("RGB", (200, 160), "white").save(image_path)
    assert widget.load_file(str(image_path))
    widget.actions.show_digit_shortcuts.trigger()
    bar = widget.digit_shortcut_bar

    bar.buttons[1].click()
    assert widget.digit_to_label == "车辆"
    assert widget.canvas.create_mode == "rectangle"
    assert bar.buttons[1].isChecked()
    assert window.grab().save(str(tmp_path / "digit-hints-window.png"))
    click_points(widget, ((20, 30), (100, 110)))
    assert widget.canvas.shapes[0].label == "车辆"
    widget.canvas.select_shapes([widget.canvas.shapes[0]])
    assert bar.buttons[2].isEnabled()
    bar.buttons[2].click()
    assert widget.canvas.shapes[0].label == "Book"
    assert bar.buttons[2].isChecked()

    # Hiding hints must leave physical digit-key shortcuts operational.
    widget.actions.show_digit_shortcuts.trigger()
    widget.canvas.setFocus()
    QtTest.QTest.keyClick(widget.canvas, QtCore.Qt.Key.Key_1)
    assert widget.canvas.shapes[0].label == "车辆"
    assert bar.buttons[1].isChecked()
    widget.error_message.assert_not_called()


@pytest.mark.parametrize("auto_save", [True, False])
@pytest.mark.parametrize("use_output_dir", [False, True])
@pytest.mark.parametrize("popup", [True, False])
@pytest.mark.parametrize("selected_label", [False, True])
def test_digit_rectangle_save_roundtrip(
    window, tmp_path, monkeypatch,
    auto_save, use_output_dir, popup, selected_label
):
    widget = window.labeling_widget.view
    widget._config.update(auto_save=auto_save, display_label_popup=popup)
    widget.drawing_digit_shortcuts = {3: {"label": "车辆", "mode": "rectangle"}}
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 160), "white").save(image_path)
    if use_output_dir:
        widget.output_dir = str(tmp_path / "labels")
    assert widget.load_file(str(image_path))
    if selected_label:
        item = widget.unique_label_list.create_item_from_label("其他类别")
        widget.unique_label_list.addItem(item)
        item.setSelected(True)

    target = (tmp_path / "labels" if use_output_dir else tmp_path) / "image.json"
    draw_rectangle(widget, 3)
    if not auto_save:
        assert widget.dirty
        assert widget.actions.save.isEnabled()
        assert not target.exists()
        monkeypatch.setattr(widget, "save_file_dialog", lambda: str(target))
        QtTest.QTest.keyClick(
            widget.canvas, QtCore.Qt.Key.Key_S,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        QtWidgets.QApplication.processEvents()

    assert target.exists()
    assert not widget.dirty
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert len(saved["shapes"]) == 1
    shape = saved["shapes"][0]
    assert shape["label"] == "车辆"
    assert shape["shape_type"] == "rectangle"
    assert len(shape["points"]) == 4
    for actual, expected in zip(shape["points"], [(20, 30), (100, 30), (100, 110), (20, 110)]):
        assert actual == pytest.approx(expected, abs=0.6)
    assert saved["imageWidth"] == 200
    assert saved["imageHeight"] == 160
    assert widget.load_file(str(image_path))
    assert len(widget.canvas.shapes) == 1
    restored = widget.canvas.shapes[0].to_dict()
    assert restored["label"] == "车辆"
    assert [list(point) for point in restored["points"]] == shape["points"]
    widget.error_message.assert_not_called()


@pytest.mark.parametrize("digit", range(10))
def test_every_digit_can_save_a_rectangle(window, tmp_path, digit):
    widget = window.labeling_widget.view
    widget._config.update(auto_save=True, display_label_popup=True)
    widget.drawing_digit_shortcuts = {digit: {"label": "车辆", "mode": "rectangle"}}
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 160), "white").save(image_path)
    assert widget.load_file(str(image_path))
    draw_rectangle(widget, digit)
    saved = json.loads(image_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert len(saved["shapes"]) == 1
    shape = saved["shapes"][0]
    assert shape["label"] == "车辆"
    assert shape["shape_type"] == "rectangle"
    assert len(shape["points"]) == 4
    for actual, expected in zip(
        shape["points"], [(20, 30), (100, 30), (100, 110), (20, 110)]
    ):
        assert actual == pytest.approx(expected, abs=0.6)
    assert saved["imageWidth"] == 200
    assert saved["imageHeight"] == 160
    assert widget.load_file(str(image_path))
    restored = widget.canvas.shapes[0].to_dict()
    assert restored["label"] == "车辆"
    assert [list(point) for point in restored["points"]] == shape["points"]
    widget.error_message.assert_not_called()


def test_digit_binding_is_consumed_by_the_completed_rectangle(window, tmp_path):
    """The finished rectangle takes the digit class and clears its binding."""
    widget = window.labeling_widget.view
    widget._config.update(auto_save=True, display_label_popup=False)
    widget.drawing_digit_shortcuts = {3: {"label": "车辆", "mode": "rectangle"}}
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 160), "white").save(image_path)
    assert widget.load_file(str(image_path))
    select_class(widget, "其他类别")

    draw_rectangle(widget, 3)
    assert widget.digit_to_label is None
    assert widget.canvas.shapes[0].label == "车辆"

    # The next, ordinary rectangle must follow the normal class rules again.
    select_class(widget, "其他类别")
    draw_plain_rectangle(widget, first=(120, 120), second=(190, 155))
    assert [shape.label for shape in widget.canvas.shapes] == [
        "车辆",
        "其他类别",
    ]
    saved = json.loads(
        image_path.with_suffix(".json").read_text(encoding="utf-8")
    )
    assert [shape["label"] for shape in saved["shapes"]] == [
        "车辆",
        "其他类别",
    ]


@pytest.mark.parametrize(
    "abandon", ["escape", "escape_after_click", "edit", "next_image"]
)
def test_abandoned_digit_binding_does_not_label_a_plain_rectangle(
    window, tmp_path, abandon
):
    widget = window.labeling_widget.view
    widget._config.update(auto_save=True, display_label_popup=False)
    widget.drawing_digit_shortcuts = {3: {"label": "车辆", "mode": "rectangle"}}
    image_path = tmp_path / "first.png"
    Image.new("RGB", (200, 160), "white").save(image_path)
    assert widget.load_file(str(image_path))
    canvas = widget.canvas
    canvas.setFocus()
    QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_3)
    assert widget.digit_to_label == "车辆"

    if abandon == "escape_after_click":
        point = (QtCore.QPointF(20, 30) + canvas.offset_to_center()) * canvas.scale
        QtTest.QTest.mouseClick(
            canvas, QtCore.Qt.MouseButton.LeftButton, pos=point.toPoint()
        )
        assert canvas.current is not None
    if abandon.startswith("escape"):
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_Escape)
    elif abandon == "edit":
        widget.actions.edit_mode.trigger()
    else:
        image_path = tmp_path / "next.png"
        Image.new("RGB", (200, 160), "white").save(image_path)
        assert widget.load_file(str(image_path))

    assert widget.digit_to_label is None
    assert not canvas.shapes
    select_class(widget, "其他类别")
    if abandon.startswith("escape"):
        assert canvas.drawing()
        click_points(widget, ((20, 30), (100, 110)))
    else:
        draw_plain_rectangle(widget)
    assert [shape.label for shape in canvas.shapes] == ["其他类别"]
    saved = json.loads(image_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert [shape["label"] for shape in saved["shapes"]] == ["其他类别"]
    widget.error_message.assert_not_called()


def test_last_label_reuse_cannot_override_digit_binding(window, tmp_path):
    widget = window.labeling_widget.view
    widget._config.update(
        auto_save=True,
        display_label_popup=False,
        auto_use_last_label=True,
    )
    widget.drawing_digit_shortcuts = {3: {"label": "车辆", "mode": "rectangle"}}
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 160), "white").save(image_path)
    assert widget.load_file(str(image_path))

    select_class(widget, "其他类别")
    draw_plain_rectangle(widget)
    assert widget.canvas.shapes[0].label == "其他类别"
    assert widget.find_last_label() == "其他类别"

    widget.unique_label_list.clearSelection()
    draw_rectangle(
        widget, 3, first=(120, 120), second=(190, 155), expected_shapes=2
    )
    assert [shape.label for shape in widget.canvas.shapes] == [
        "其他类别",
        "车辆",
    ]
    assert widget.digit_to_label is None


class _NewShapeHost:
    """Minimal double that drives the real ``LabelingWidget.new_shape``."""

    def __init__(
        self,
        draft_label="",
        preselected=None,
        digit_to_label=None,
        popup=False,
    ):
        self._config = {
            "display_label_popup": popup,
            "auto_use_last_label": False,
            "auto_use_last_gid": False,
            "validate_label": None,
        }
        self.canvas = SimpleNamespace(
            shapes=[Shape(label=draft_label, shape_type="rectangle")],
            drawing=lambda: False,
            create_mode="rectangle",
        )
        self.canvas.set_last_label = self._set_last_label
        item = SimpleNamespace(data=lambda _role: preselected)
        self.unique_label_list = SimpleNamespace(
            selectedItems=lambda: [item] if preselected else []
        )
        self.label_list = SimpleNamespace(clearSelection=lambda: None)
        self.label_dialog = Mock()
        self.label_dialog.pop_up = Mock(
            side_effect=AssertionError("Unexpected label popup")
        )
        self.attributes = {}
        self.digit_to_label = digit_to_label
        self.actions = SimpleNamespace(
            edit_mode=Mock(),
            undo_last_point=Mock(),
            undo=Mock(),
            create_brush_polygon_mode=Mock(isEnabled=Mock(return_value=True)),
        )
        self.error_message = Mock()
        self.add_label = Mock()
        self.set_dirty = Mock()
        self.validate_label = Mock(return_value=True)

    def _set_last_label(self, text, flags, group_id):
        shape = self.canvas.shapes[-1]
        shape.label = text
        shape.flags = flags
        shape.group_id = group_id
        return shape


def test_binding_precedes_preselected_class_without_popup():
    host = _NewShapeHost(
        draft_label="", preselected="其他类别", digit_to_label="车辆"
    )

    LabelingWidget.new_shape(host)

    assert host.canvas.shapes[-1].label == "车辆"
    assert host.digit_to_label is None
    host.label_dialog.pop_up.assert_not_called()
    host.error_message.assert_not_called()


def test_ordinary_creation_without_binding_uses_preselected_class():
    host = _NewShapeHost(draft_label="", preselected="其他类别")

    LabelingWidget.new_shape(host)

    assert host.canvas.shapes[-1].label == "其他类别"
    assert host.digit_to_label is None


def test_auto_labeling_special_mark_outranks_the_digit_binding():
    host = _NewShapeHost(
        draft_label=AutoLabelingMode.ADD,
        preselected="其他类别",
        digit_to_label="车辆",
    )

    LabelingWidget.new_shape(host)

    assert host.canvas.shapes[-1].label == AutoLabelingMode.ADD
    assert host.digit_to_label == "车辆"


def _write_png(path):
    Image.new("RGB", (200, 160), "white").save(path)
    return str(path)


def test_cards_follow_image_lifecycle(window, tmp_path):
    widget = window.labeling_widget.view
    bar = widget.digit_shortcut_bar
    baseline = dict(widget.drawing_digit_shortcuts or {})
    proposed = dict(baseline)
    proposed[1] = {"mode": "rectangle", "label": "车辆"}
    assert widget._commit_digit_shortcuts(proposed, baseline)[0]
    assert not bar.buttons[1].isEnabled()

    assert widget.load_file(_write_png(tmp_path / "ok.png"))
    assert bar.buttons[1].isEnabled()
    bar.buttons[1].click()
    assert bar.buttons[1].isChecked()
    # Ordinary drawing in progress disables the cards.
    point = QtCore.QPointF(20, 30)
    widget.canvas.setFocus()
    click_points_partial = (point + widget.canvas.offset_to_center()) * widget.canvas.scale
    QtTest.QTest.mouseClick(
        widget.canvas, QtCore.Qt.MouseButton.LeftButton,
        pos=click_points_partial.toPoint(),
    )
    assert widget.canvas.current is not None
    assert not bar.buttons[1].isEnabled()
    widget.canvas.cancel_drawing()
    assert widget.digit_to_label is None
    assert bar.buttons[1].isEnabled()
    assert not bar.buttons[1].isChecked()

    bar.buttons[1].click()
    assert bar.buttons[1].isChecked()
    # Missing and corrupt files both reset the image and disable the cards.
    assert not widget.load_file(str(tmp_path / "missing.png"))
    assert not bar.buttons[1].isEnabled()
    assert not bar.buttons[1].isChecked()

    assert widget.load_file(_write_png(tmp_path / "ok2.png"))
    assert bar.buttons[1].isEnabled()
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    assert not widget.load_file(str(bad))
    assert not bar.buttons[1].isEnabled()
    assert not bar.buttons[1].isChecked()
    assert widget.load_file(_write_png(tmp_path / "ok3.png"))
    assert bar.buttons[1].isEnabled()


def test_cards_disabled_during_extreme_draft(window, tmp_path):
    widget = window.labeling_widget.view
    bar = widget.digit_shortcut_bar
    baseline = dict(widget.drawing_digit_shortcuts or {})
    proposed = dict(baseline)
    proposed[1] = {"mode": "rectangle", "label": "车辆"}
    assert widget._commit_digit_shortcuts(proposed, baseline)[0]
    assert widget.load_file(_write_png(tmp_path / "ok.png"))
    workflow = widget.rectangle_creation
    assert bar.buttons[1].isEnabled()

    workflow.start_extreme()
    assert workflow.draft is not None
    assert not bar.buttons[1].isEnabled()
    workflow.cancel()
    assert workflow.draft is None
    assert bar.buttons[1].isEnabled()

    bar.buttons[1].click()
    assert widget.digit_to_label == "车辆"
    workflow.start_extreme()
    assert widget.digit_to_label is None
    assert not bar.buttons[1].isEnabled()
    widget._config["display_label_popup"] = False
    select_class(widget, "其他类别")
    click_points(widget, ((20, 30), (100, 80), (60, 110), (20, 80)))
    assert workflow.draft is None
    assert [shape.label for shape in widget.canvas.shapes] == ["其他类别"]
    assert bar.buttons[1].isEnabled()

    workflow.continue_drawing()
    assert widget.digit_to_label == "其他类别"
    select_class(widget, "车辆")
    click_points(widget, ((120, 30), (180, 80), (160, 110), (120, 80)))
    assert workflow.draft is None
    assert [shape.label for shape in widget.canvas.shapes] == ["其他类别"] * 2
    assert widget.digit_to_label is None
    assert bar.buttons[1].isEnabled()


@pytest.mark.shared_config
def test_config_session_commit_syncs_menu_and_bar(window, monkeypatch):
    widget = window.labeling_widget.view
    action = widget.actions.show_digit_shortcuts
    bar = widget.digit_shortcut_bar
    assert bar.isHidden() and not action.isChecked()
    user_config.save_values({"show_digit_shortcuts": True})
    QtWidgets.QApplication.processEvents()
    assert action.isChecked() and bar.isVisible()
    user_config.save_values({"show_digit_shortcuts": False})
    QtWidgets.QApplication.processEvents()
    assert not action.isChecked() and bar.isHidden()


def test_legacy_mode_only_mapping_works_for_key_and_card(window, tmp_path):
    widget = window.labeling_widget.view
    bar = widget.digit_shortcut_bar
    widget.drawing_digit_shortcuts = {
        1: {"mode": "rectangle"},
        "2": {"mode": "polygon", "label": "Car"},
        0: {"mode": "rectangle", "label": "Zero"},
    }
    bar.set_mappings(widget.drawing_digit_shortcuts)
    assert widget.load_file(_write_png(tmp_path / "ok.png"))
    bar.buttons[1].click()
    assert widget.digit_to_label == "object"
    assert widget.canvas.create_mode == "rectangle"
    widget.toggle_draw_mode(edit=True)
    widget.create_digit_mode(2)
    assert widget.digit_to_label == "Car"
    assert widget.canvas.create_mode == "polygon"
    widget.toggle_draw_mode(edit=True)
    widget.canvas.setFocus()
    QtTest.QTest.keyClick(widget.canvas, QtCore.Qt.Key.Key_0)
    assert widget.digit_to_label == "Zero"
    assert 0 not in bar.buttons

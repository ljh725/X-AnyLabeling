"""Regression tests for the canvas viewport reset context menus."""

from types import SimpleNamespace

from PyQt6 import QtGui, QtWidgets

from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.widgets.canvas import Canvas


def _action(text: str) -> QtGui.QAction:
    """Create a context-menu action for the lightweight fixture."""
    return QtGui.QAction(text)


def _build_widget_stub() -> SimpleNamespace:
    """Build only the state consumed by the menu rebuild helper."""
    reset_actions = tuple(
        _action(text)
        for text in (
            "Reset Current Image View",
            "Reset Views from Current to End",
            "Reset All Image Views",
        )
    )
    action_names = (
        "create_mode",
        "create_brush_polygon_mode",
        "create_rectangle_mode",
        "create_cuboid_mode",
        "create_rotation_mode",
        "create_quadrilateral_mode",
        "create_circle_mode",
        "create_line_mode",
        "create_point_mode",
        "create_line_strip_mode",
        "edit_mode",
    )
    actions = {name: _action(name) for name in action_names}
    actions.update(
        menu=(_action("Create Rectangle"),),
        tool=(),
        editMenu=(),
        toggle_annotation_checked=_action("Checked"),
        reset_current_image_view=reset_actions[0],
        reset_views_from_current_to_end=reset_actions[1],
        reset_all_image_views=reset_actions[2],
    )
    widget = SimpleNamespace(
        canvas=Canvas(),
        actions=SimpleNamespace(**actions),
        tools=QtWidgets.QMenu(),
        menus=SimpleNamespace(edit=QtWidgets.QMenu()),
        _canvas_copy_action=_action("&Copy here"),
        _canvas_move_action=_action("&Move here"),
    )
    widget._append_filter_submenus = lambda *args, **kwargs: (
        None,
        None,
        None,
    )
    widget._rebuild_canvas_context_menus = lambda: (
        LabelingWidget._rebuild_canvas_context_menus(widget)
    )
    return widget


def _texts(menu: QtWidgets.QMenu) -> list[str]:
    """Return visible action texts, excluding separators."""
    return [
        action.text() for action in menu.actions() if not action.isSeparator()
    ]


def test_rebuilding_canvas_menus_preserves_reset_actions(qapp) -> None:
    """Both canvas menus retain exactly one copy of each reset action."""
    widget = _build_widget_stub()

    LabelingWidget._rebuild_canvas_context_menus(widget)
    LabelingWidget._rebuild_canvas_context_menus(widget)

    expected = [
        "Reset Current Image View",
        "Reset Views from Current to End",
        "Reset All Image Views",
    ]
    for menu in widget.canvas.menus:
        texts = _texts(menu)
        assert [text for text in texts if text in expected] == expected
        assert all(texts.count(text) == 1 for text in expected)


def test_populate_mode_actions_rebuilds_reset_actions(qapp) -> None:
    """Mode refreshes must not erase the canvas viewport reset actions."""
    widget = _build_widget_stub()

    LabelingWidget.populate_mode_actions(widget)

    expected = {
        "Reset Current Image View",
        "Reset Views from Current to End",
        "Reset All Image Views",
    }
    assert expected.issubset(set(_texts(widget.canvas.menus[0])))


def test_shape_move_canvas_menu_keeps_copy_and_move_actions(qapp) -> None:
    """The shape-move menu keeps its original actions beside reset actions."""
    widget = _build_widget_stub()

    LabelingWidget._rebuild_canvas_context_menus(widget)

    texts = _texts(widget.canvas.menus[1])
    assert texts[:2] == ["&Copy here", "&Move here"]
    assert texts[-3:] == [
        "Reset Current Image View",
        "Reset Views from Current to End",
        "Reset All Image Views",
    ]


def test_canvas_reset_actions_trigger_the_bound_slots(qapp) -> None:
    """Both canvas menus expose actions that remain connected when rebuilt."""
    widget = _build_widget_stub()
    calls = []
    scopes = {
        "Reset Current Image View": "current",
        "Reset Views from Current to End": "range",
        "Reset All Image Views": "all",
    }
    for action in widget.actions.menu:
        action.setEnabled(True)
    for action_name, scope in scopes.items():
        action = getattr(
            widget.actions,
            {
                "Reset Current Image View": "reset_current_image_view",
                "Reset Views from Current to End": (
                    "reset_views_from_current_to_end"
                ),
                "Reset All Image Views": "reset_all_image_views",
            }[action_name],
        )
        action.triggered.connect(
            lambda _checked=False, scope=scope: calls.append(scope)
        )

    LabelingWidget._rebuild_canvas_context_menus(widget)
    for menu in widget.canvas.menus:
        for action in menu.actions():
            if action.text() in scopes:
                action.trigger()

    assert calls == ["current", "range", "all", "current", "range", "all"]


def test_reset_slots_resolve_current_range_and_dataset_targets():
    """The three UI scopes map to the intended file collections."""
    widget = SimpleNamespace(
        filename="b.png",
        image_list=["a.png", "b.png", "c.png"],
        fn_to_index={"a.png": 0, "b.png": 1, "c.png": 2},
        tr=lambda text: text,
    )
    calls = []
    widget._reset_image_views_for_files = (
        lambda filenames, scope: calls.append((list(filenames), scope))
    )
    widget._get_files_from_current_to_end = lambda: widget.image_list[
        widget.fn_to_index[widget.filename] :
    ]

    LabelingWidget.reset_current_image_view(widget)
    LabelingWidget.reset_views_from_current_to_end(widget)
    LabelingWidget.reset_all_image_views(widget)

    assert calls[0][0] == ["b.png"]
    assert calls[1][0] == ["b.png", "c.png"]
    assert calls[2][0] == ["a.png", "b.png", "c.png"]

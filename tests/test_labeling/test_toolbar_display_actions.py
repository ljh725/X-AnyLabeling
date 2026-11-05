"""The main toolbar reuses the existing display actions and stays scrollable."""

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.labeling.widgets.toolbar import ToolBarScrollArea
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


def test_toolbar_reuses_existing_display_actions(window):
    widget = window.labeling_widget.view
    actions = widget.actions
    required = [
        actions.fit_window,
        actions.fit_width,
        actions.show_masks,
        actions.show_texts,
        actions.show_labels,
        actions.show_scores,
        actions.show_degrees,
        actions.show_attributes,
        actions.show_linking,
        actions.show_groups,
        actions.group_selected_shapes,
        actions.ungroup_selected_shapes,
    ]

    for action in required:
        assert action is not None
        assert action.text()
        assert not action.icon().isNull(), action.text()

    button_actions = [
        button.defaultAction()
        for button in widget.tools.findChildren(QtWidgets.QToolButton)
    ]
    missing = [
        action.text() for action in required if action not in button_actions
    ]
    assert missing == []


def test_toolbar_and_menu_share_display_state(window):
    widget = window.labeling_widget.view
    action = widget.actions.show_labels
    original = action.isChecked()

    assert action in widget.menus.view.actions()

    action.trigger()
    assert action.isChecked() is (not original)
    assert widget.canvas.show_labels is action.isChecked()

    action.trigger()
    assert action.isChecked() is original
    assert widget.canvas.show_labels is original


def test_toolbar_does_not_add_display_mode_selector(window):
    widget = window.labeling_widget.view
    labels = [
        button.defaultAction().text()
        for button in widget.tools.findChildren(QtWidgets.QToolButton)
        if button.defaultAction() is not None
    ]

    assert "Label Mode" not in labels
    assert "Instance Mode" not in labels
    assert "Binary Mask" not in labels


def test_toolbar_scroll_area_consumes_wheel(window):
    widget = window.labeling_widget.view
    area = widget.tools_scroll_area
    assert isinstance(area, ToolBarScrollArea)

    bar = area.horizontalScrollBar()
    bar.setRange(0, 100)
    bar.setValue(0)
    position = QtCore.QPointF(10, 10)
    event = QtGui.QWheelEvent(
        position,
        position,
        QtCore.QPoint(),
        QtCore.QPoint(0, -120),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase,
        False,
    )

    area.wheelEvent(event)

    assert event.isAccepted()
    assert bar.value() > 0


@pytest.mark.parametrize("pixel", [False, True], ids=["angle", "pixel"])
@pytest.mark.parametrize("delta", [(120, 0), (-120, 0), (0, 120), (0, -120)])
def test_viewport_wheel_direction_and_no_canvas_navigation(
    window, pixel, delta
):
    """Dispatch through the viewport, including native horizontal gestures."""
    from PyQt6 import QtTest

    widget = window.labeling_widget.view
    area = widget.tools_scroll_area
    bar = area.horizontalScrollBar()
    bar.setRange(0, 1000)
    bar.setValue(500)
    zooms = QtTest.QSignalSpy(widget.canvas.zoom_request)
    scrolls = QtTest.QSignalSpy(widget.canvas.scroll_request)
    point = QtCore.QPointF(10, 10)
    event = QtGui.QWheelEvent(
        point,
        point,
        QtCore.QPoint(*delta) if pixel else QtCore.QPoint(),
        QtCore.QPoint() if pixel else QtCore.QPoint(*delta),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    QtWidgets.QApplication.sendEvent(area.viewport(), event)

    assert event.isAccepted()
    assert bar.value() == 500 - (delta[1] or delta[0])
    assert len(zooms) == len(scrolls) == 0


@pytest.mark.parametrize("start, delta", [(0, 120), (100, -120)])
def test_toolbar_wheel_stays_at_boundary_and_is_consumed(window, start, delta):
    area = window.labeling_widget.view.tools_scroll_area
    bar = area.horizontalScrollBar()
    bar.setRange(0, 100)
    bar.setValue(start)
    point = QtCore.QPointF(10, 10)
    event = QtGui.QWheelEvent(
        point,
        point,
        QtCore.QPoint(),
        QtCore.QPoint(delta, 0),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QtWidgets.QApplication.sendEvent(area.viewport(), event)
    assert event.isAccepted()
    assert bar.value() == start

"""Offscreen tests for the spatial coverage grid widget."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtTest import QTest

from anylabeling.views.labeling.dense_review.workspace import _CoverageGrid
from anylabeling.views.labeling.utils.style import blend_hex
from anylabeling.views.labeling.utils.theme import get_theme


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _region(region_id, row, column, rect, **state):
    return SimpleNamespace(
        region_id=region_id,
        row=row,
        column=column,
        rect=rect,
        completed=state.get("completed", False),
        difficult=state.get("difficult", False),
        skipped=state.get("skipped", False),
    )


def _plan(regions, width=1000, height=500, columns=2, rows=2):
    return SimpleNamespace(
        image_width=width,
        image_height=height,
        columns=columns,
        rows=rows,
        regions=regions,
        current_region="",
    )


def _four_state_plan():
    return _plan(
        [
            _region("r0", 0, 0, (0, 0, 500, 250), completed=True),
            _region("r1", 0, 1, (500, 0, 1000, 250), difficult=True),
            _region("r2", 1, 0, (0, 250, 500, 500), skipped=True),
            _region("r3", 1, 1, (500, 250, 1000, 500)),
        ]
    )


def _grid(qt_app, plan, size=(420, 320)):
    widget = _CoverageGrid()
    widget.resize(*size)
    widget.set_plan(plan, plan.current_region if plan else "")
    return widget


def _center(rect):
    return QtCore.QPoint(int(rect.center().x()), int(rect.center().y()))


def _colors_in(widget, rect, inset=6, step=4):
    image = widget.grab().toImage()
    colors = []
    left = int(rect.left()) + inset
    right = int(rect.right()) - inset
    top = int(rect.top()) + inset
    bottom = int(rect.bottom()) - inset
    for x in range(left, right, step):
        for y in range(top, bottom, step):
            color = image.pixelColor(x, y)
            colors.append((color.red(), color.green(), color.blue()))
    return colors


def _near(actual, expected, tolerance=10):
    return all(
        abs(actual[index] - expected[index]) <= tolerance for index in range(3)
    )


def _has_color(colors, expected, tolerance=12):
    return any(_near(color, expected, tolerance) for color in colors)


def _rgb(hex_color):
    color = QtGui.QColor(hex_color)
    return (color.red(), color.green(), color.blue())


def test_content_rect_keeps_image_aspect_ratio(qt_app):
    plan = _plan([_region("r0", 0, 0, (0, 0, 1000, 500))], columns=1, rows=1)
    widget = _grid(qt_app, plan)
    content = widget._content_rect()
    assert content.width() > 0
    assert abs(content.width() / content.height() - 2.0) < 0.05


def test_cell_rects_follow_region_geometry(qt_app):
    plan = _four_state_plan()
    widget = _grid(qt_app, plan)
    content = widget._content_rect()
    first = widget._cell_rect(plan.regions[0], content)
    last = widget._cell_rect(plan.regions[3], content)
    assert first.left() == pytest.approx(content.left(), abs=0.5)
    assert last.right() == pytest.approx(content.right(), abs=0.5)
    assert last.top() > first.top()


def test_state_colors_use_theme_tokens(qt_app):
    plan = _four_state_plan()
    widget = _grid(qt_app, plan)
    content = widget._content_rect()
    theme = get_theme()
    expected = [
        _rgb(theme["success"]),
        _rgb(theme["warning"]),
        _rgb(theme["primary"]),
        _rgb(blend_hex(theme["surface"], theme["background"], 0.85)),
    ]
    for region, color in zip(plan.regions, expected):
        colors = _colors_in(widget, widget._cell_rect(region, content))
        assert _has_color(colors, color, tolerance=14), (
            region.region_id,
            color,
            sorted(set(colors))[:3],
        )


def test_current_region_gets_accent_border(qt_app):
    plan = _four_state_plan()
    widget = _grid(qt_app, plan)
    content = widget._content_rect()
    widget.set_current("r1")
    cell = widget._cell_rect(plan.regions[1], content)
    band = QtCore.QRectF(
        cell.left() - 2,
        cell.top() + cell.height() * 0.2,
        5,
        cell.height() * 0.6,
    )
    colors = _colors_in(widget, band, inset=0, step=1)
    assert _has_color(colors, _rgb(get_theme()["primary"]), tolerance=30)


def test_click_emits_region_id(qt_app):
    plan = _four_state_plan()
    widget = _grid(qt_app, plan)
    content = widget._content_rect()
    received = []
    widget.region_clicked.connect(received.append)
    target = plan.regions[2]
    cell = widget._cell_rect(target, content)
    QTest.mouseClick(
        widget,
        QtCore.Qt.MouseButton.LeftButton,
        pos=QtCore.QPoint(int(cell.center().x()), int(cell.center().y()) + 20),
    )
    assert received == ["r2"]


def test_overlapping_regions_pick_last_drawn(qt_app):
    plan = _plan(
        [
            _region("r0", 0, 0, (0, 0, 600, 500)),
            _region("r1", 0, 1, (500, 0, 1000, 500)),
        ]
    )
    widget = _grid(qt_app, plan)
    content = widget._content_rect()
    overlap_point = QtCore.QPoint(
        int(widget._cell_rect(plan.regions[0], content).right()) - 2,
        int(content.center().y()),
    )
    hit = widget._hit(overlap_point)
    assert hit is not None
    assert hit.region_id == "r1"


def test_empty_plan_renders_hint_without_error(qt_app):
    widget = _grid(qt_app, None)
    assert widget._hit(QtCore.QPoint(10, 10)) is None
    image = widget.grab().toImage()
    assert not image.isNull()
    assert any(
        image.pixelColor(x, y).value() < 200
        for x in range(0, image.width(), 9)
        for y in range(0, image.height(), 9)
    )

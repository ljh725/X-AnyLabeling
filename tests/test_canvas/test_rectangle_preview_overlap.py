"""Verify rectangle preview outlines avoid duplicated shared edges."""

import os
from collections.abc import Iterator
from functools import partial
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.views.labeling.rectangle_preview import (
    FIT_CANDIDATE_COLOR,
    RectangleEdge,
    build_remaining_outline,
    creation_edges,
    normalize_box,
    path_from_edges,
    rectangle_box_from_points,
    remaining_edges,
)
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

BOX = (100.0, 100.0, 200.0, 200.0)


@pytest.fixture
def dirty_host(canvas):
    """Use real host dirty handlers without loading a window or user files.

    Only UI actions are stubs; signal routing and the dirty assignment run
    through LabelingWidget's production methods. Autosave is disabled.
    """
    from anylabeling.views.labeling.label_widget import LabelingWidget

    host = SimpleNamespace(
        dirty=False,
        correction_metrics=None,
        dense_review_session=None,
        actions=SimpleNamespace(
            save=mock.Mock(), undo=mock.Mock(), redo=mock.Mock()
        ),
        _config={"auto_save": False},
        _dense_review_undo_available=lambda: canvas.is_shape_restorable,
        _dense_review_redo_available=lambda: canvas.is_shape_redo_available,
        update_progress_title=mock.Mock(),
    )
    host.set_dirty = mock.Mock(wraps=partial(LabelingWidget.set_dirty, host))
    committed = partial(LabelingWidget._on_geometry_committed, host)
    canvas.shape_moved.connect(committed)
    canvas.shape_rotated.connect(committed)
    canvas.new_shape.connect(host.set_dirty)
    host.moves = QtTest.QSignalSpy(canvas.shape_moved)
    yield host
    canvas.shape_moved.disconnect(committed)
    canvas.shape_rotated.disconnect(committed)
    canvas.new_shape.disconnect(host.set_dirty)


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    """Provide a Qt application for offscreen canvas rendering."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication) -> Iterator[Canvas]:
    """Create one selected black rectangle on a white image."""
    widget = Canvas(parent=None)
    pixmap = QtGui.QPixmap(300, 300)
    pixmap.fill(QtGui.QColor("white"))
    widget.pixmap = pixmap
    widget.resize(300, 300)
    widget.cross_line_show = False
    widget.show_labels = False
    widget.show_texts = False
    widget.show_scores = False
    widget.show_attributes = False
    widget.show_linking = False
    widget.show_masks = False

    shape = Shape(label=None, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(100, 100),
        QtCore.QPointF(200, 100),
        QtCore.QPointF(200, 200),
        QtCore.QPointF(100, 200),
    ]
    shape.close()
    shape.selected = True
    shape.line_color = QtGui.QColor("black")
    shape.select_line_color = QtGui.QColor("black")
    shape.fill_color = QtGui.QColor(255, 0, 0, 90)
    shape.select_fill_color = QtGui.QColor(255, 0, 0, 90)
    widget.shapes = [shape]
    widget.selected_shapes = [shape]
    widget.store_shapes()
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def edges(*items: tuple[str, float, float, float]) -> list[RectangleEdge]:
    """Build comparable edge objects from short tuples."""
    return [RectangleEdge(*item) for item in items]


def horizontal(edges_list, coordinate):
    """Return horizontal segments and their spans on one line."""
    return sorted(
        (edge.start, edge.end)
        for edge in edges_list
        if edge.orientation == "horizontal" and edge.coordinate == coordinate
    )


def vertical(edges_list, coordinate):
    """Return vertical segments and their spans on one line."""
    return sorted(
        (edge.start, edge.end)
        for edge in edges_list
        if edge.orientation == "vertical" and edge.coordinate == coordinate
    )


def render(canvas: Canvas) -> QtGui.QImage:
    """Render the widget to an opaque image."""
    image = QtGui.QImage(canvas.size(), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(image)
    try:
        canvas.render(painter)
    finally:
        painter.end()
    return image


def is_ink(color: QtGui.QColor) -> bool:
    """Return whether a pixel is a dark annotation stroke."""
    return (
        color.red() < 70
        and color.green() < 70
        and color.blue() < 70
    )


def is_orange(color: QtGui.QColor) -> bool:
    """Return whether a pixel carries the orange fit candidate."""
    red, green, blue = color.red(), color.green(), color.blue()
    return red - blue > 40 and red > green > blue


def count_ink(
    image: QtGui.QImage, points: list[tuple[int, int]]
) -> int:
    """Count dark stroke samples among image pixels."""
    return sum(is_ink(image.pixelColor(x, y)) for x, y in points)


def count_orange(
    image: QtGui.QImage, points: list[tuple[int, int]]
) -> int:
    """Count orange candidate samples among image pixels."""
    return sum(is_orange(image.pixelColor(x, y)) for x, y in points)


def count_colored(
    image: QtGui.QImage, points: list[tuple[int, int]]
) -> int:
    """Count any non-white stroke sample among image pixels."""
    return sum(
        min(
            image.pixelColor(x, y).red(),
            image.pixelColor(x, y).green(),
            image.pixelColor(x, y).blue(),
        )
        < 250
        for x, y in points
    )


def start_fit(canvas: Canvas, point: tuple[float, float]) -> None:
    """Activate a point-fit preview without sending mouse events."""
    canvas._update_point_fit(
        canvas.shapes[0], QtCore.QPointF(*point)
    )


def send_mouse(
    canvas: Canvas,
    kind: QtCore.QEvent.Type,
    point: tuple[float, float],
    *,
    shift: bool = True,
    alt: bool = False,
    buttons: QtCore.Qt.MouseButton | None = None,
) -> None:
    """Send a real canvas mouse event at an image-space position."""
    pos = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    button = (
        QtCore.Qt.MouseButton.NoButton
        if kind == QtCore.QEvent.Type.MouseMove
        else QtCore.Qt.MouseButton.LeftButton
    )
    if buttons is None:
        buttons = (
            button
            if kind == QtCore.QEvent.Type.MouseButtonPress
            else QtCore.Qt.MouseButton.NoButton
        )
    modifiers = QtCore.Qt.KeyboardModifier.NoModifier
    if shift:
        modifiers |= QtCore.Qt.KeyboardModifier.ShiftModifier
    if alt:
        modifiers |= QtCore.Qt.KeyboardModifier.AltModifier
    event = QtGui.QMouseEvent(kind, pos, pos, button, buttons, modifiers)
    {
        QtCore.QEvent.Type.MouseMove: canvas.mouseMoveEvent,
        QtCore.QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
        QtCore.QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
    }[kind](event)


def nudge(canvas: Canvas, key: QtCore.Qt.Key) -> None:
    """Send a real Shift+arrow keyboard edit with Shift held down.

    ``QTest.keyClick`` synthesizes its own Shift press/release, which would
    end the fit preview. These events keep the modifier pressed so only the
    rectangle geometry changes between the two frames.
    """
    modifiers = QtCore.Qt.KeyboardModifier.ShiftModifier
    canvas.keyPressEvent(
        QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, modifiers)
    )
    canvas.keyReleaseEvent(
        QtGui.QKeyEvent(QtCore.QEvent.Type.KeyRelease, key, modifiers)
    )


def seed_pointer(canvas: Canvas) -> None:
    """Click once so a keyboard nudge uses an in-image pointer origin.

    ``Canvas.prev_point`` only follows presses, and a keyboard edit rejects
    targets that would move the shape beyond the image border at the origin.
    """
    point = (150, 150)
    send_mouse(
        canvas, QtCore.QEvent.Type.MouseButtonPress, point, shift=False
    )
    send_mouse(
        canvas, QtCore.QEvent.Type.MouseButtonRelease, point, shift=False
    )


def bounds(shape: Shape) -> tuple[float, float, float, float]:
    """Return the rectangle bounds for assertions."""
    xs = [point.x() for point in shape.points]
    ys = [point.y() for point in shape.points]
    return min(xs), min(ys), max(xs), max(ys)


def snapshot(canvas: Canvas) -> tuple[list[dict], list[list[dict]]]:
    """Capture shape serialization and the undo stack."""
    return (
        [shape.to_dict() for shape in canvas.shapes],
        [[shape.to_dict() for shape in backup]
         for backup in canvas.shapes_backups],
    )


def test_normalize_box_rejects_degenerate_and_non_finite_input() -> None:
    """Only positive, finite bounds participate in preview geometry."""
    assert normalize_box((10, 20, 5, 8)) == (5, 8, 10, 20)
    assert normalize_box((0, 0, 0, 10)) is None
    assert normalize_box((0, 0, 10, 0)) is None
    assert normalize_box((0, 0, float("nan"), 10)) is None
    assert normalize_box((0, 0, float("inf"), 10)) is None


def test_rectangle_box_from_points_requires_axis_aligned_corners() -> None:
    """Four-point rectangles are only normalized when they are aligned."""
    points = [
        QtCore.QPointF(10, 10),
        QtCore.QPointF(30, 10),
        QtCore.QPointF(30, 20),
        QtCore.QPointF(10, 20),
    ]
    assert rectangle_box_from_points(points) == (10, 10, 30, 20)
    assert rectangle_box_from_points(
        [QtCore.QPointF(10, 10), QtCore.QPointF(30, 20)]
    ) == (10, 10, 30, 20)
    diamond = [
        QtCore.QPointF(20, 5),
        QtCore.QPointF(35, 20),
        QtCore.QPointF(20, 35),
        QtCore.QPointF(5, 20),
    ]
    assert rectangle_box_from_points(diamond) is None


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (
            (100, 120, 151.5, 200),
            edges(
                ("horizontal", 100, 100, 200),
                ("vertical", 200, 100, 200),
                ("horizontal", 200, 153.5, 200),
                ("vertical", 100, 100, 118),
            ),
        ),
        (
            (120, 120, 200, 200),
            edges(
                ("horizontal", 100, 100, 200),
                ("vertical", 200, 100, 118),
                ("horizontal", 200, 100, 118),
                ("vertical", 100, 100, 200),
            ),
        ),
        (
            (120, 100, 200, 180),
            edges(
                ("horizontal", 100, 100, 118),
                ("vertical", 200, 182, 200),
                ("horizontal", 200, 100, 200),
                ("vertical", 100, 100, 200),
            ),
        ),
        (
            (100, 100, 180, 180),
            edges(
                ("horizontal", 100, 182, 200),
                ("vertical", 200, 100, 200),
                ("horizontal", 200, 100, 200),
                ("vertical", 100, 182, 200),
            ),
        ),
    ],
)
def test_fit_removes_shared_parts_in_every_quadrant(candidate, expected):
    """Shared spans are removed and non-shared edges stay full length."""
    result = remaining_edges(BOX, candidate, scale=1.0, line_width=2.0)
    assert list(result) == expected


def test_fit_keeps_near_and_point_only_intersections() -> None:
    """Edges that are close or touch at one point are never hidden."""
    near = (100.5, 120.5, 151.5, 200.5)
    result = remaining_edges(BOX, near, scale=1.0, line_width=2.0)
    assert list(result) == edges(
        ("horizontal", 100, 100, 200),
        ("vertical", 200, 100, 200),
        ("horizontal", 200, 100, 200),
        ("vertical", 100, 100, 200),
    )
    touching = (200, 200, 250, 250)
    result = remaining_edges(BOX, touching, scale=1.0, line_width=2.0)
    assert len(result) == 4
    assert result[1] == RectangleEdge("vertical", 200, 100, 200)


def test_identical_candidate_removes_the_whole_outline() -> None:
    """A same-geometry candidate leaves no stroke to draw."""
    result = remaining_edges(BOX, BOX, scale=1.0)
    assert result == ()
    path = build_remaining_outline(BOX, BOX)
    assert path.isEmpty()


@pytest.mark.parametrize(
    ("scale", "expected_end"),
    [(0.25, 112.0), (0.5, 116.0), (1.0, 118.0), (2.0, 119.0), (4.0, 119.5)],
)
def test_stroke_allowance_scales_with_screen_pixels(
    scale: float, expected_end: float
) -> None:
    """The endpoint allowance is computed from screen width and zoom."""
    result = remaining_edges(
        BOX, (100, 120, 151.5, 200), scale=scale, line_width=2.0
    )
    assert vertical(result, 100.0) == [(100.0, expected_end)]


def test_small_box_keeps_only_positive_remaining_edges() -> None:
    """Tiny boxes never produce zero- or negative-length segments."""
    result = remaining_edges(
        (10, 10, 11, 11), (10, 10, 10.5, 11), scale=4.0, line_width=2.0
    )
    assert list(result) == edges(
        ("vertical", 11, 10, 11),
    )


def test_remaining_outline_uses_open_segments() -> None:
    """Remaining edges are not reconnected into a closed path."""
    result = remaining_edges(BOX, (100, 120, 151.5, 200), scale=1.0)
    path = path_from_edges(result)
    assert path.elementCount() == 8
    for index in range(path.elementCount()):
        assert path.elementAt(index).type in (
            QtGui.QPainterPath.ElementType.MoveToElement,
            QtGui.QPainterPath.ElementType.LineToElement,
        )


@pytest.mark.parametrize(
    ("guide_x", "guide_y", "expected"),
    [
        (
            120,
            120,
            edges(
                ("horizontal", 30, 30, 120),
                ("vertical", 30, 30, 120),
            ),
        ),
        (
            30,
            30,
            edges(
                ("vertical", 120, 30, 120),
                ("horizontal", 120, 30, 120),
            ),
        ),
        (
            30,
            120,
            edges(
                ("horizontal", 30, 30, 120),
                ("vertical", 120, 30, 120),
            ),
        ),
        (
            120,
            30,
            edges(
                ("horizontal", 120, 30, 120),
                ("vertical", 30, 30, 120),
            ),
        ),
    ],
)
def test_creation_removes_only_edges_under_the_crosshair(
    guide_x, guide_y, expected
) -> None:
    """Each drag quadrant hides the two edges meeting the cursor."""
    result = creation_edges((30, 30, 120, 120), guide_x, guide_y)
    assert list(result) == expected


def test_creation_keeps_all_edges_when_guide_is_off_edge() -> None:
    """A guide not on a draft edge does not remove any stroke."""
    result = creation_edges((30, 30, 120, 120), 75, 75)
    assert len(result) == 4
    assert creation_edges((float("nan"), 0, 10, 10), 0, 0) is None


def test_shape_paint_outline_override_keeps_fill_and_vertices() -> None:
    """Only the stroke changes when a temporary outline is supplied."""
    image = QtGui.QImage(60, 60, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("white"))
    shape = Shape(label="box", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(10, 10),
        QtCore.QPointF(50, 10),
        QtCore.QPointF(50, 50),
        QtCore.QPointF(10, 50),
    ]
    shape.close()
    shape.line_color = QtGui.QColor("black")
    shape.select_line_color = QtGui.QColor("black")
    shape.fill = True
    shape.fill_color = QtGui.QColor(255, 0, 0)
    painter = QtGui.QPainter(image)
    try:
        shape.paint(painter, outline_path=QtGui.QPainterPath())
    finally:
        painter.end()
    assert not is_ink(image.pixelColor(30, 9))
    assert image.pixelColor(30, 30).red() > 200

    image.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(image)
    try:
        shape.paint(painter)
    finally:
        painter.end()
    assert is_ink(image.pixelColor(30, 9))


def test_fit_preview_hides_shared_original_edge(canvas: Canvas) -> None:
    """The selected rectangle omits the segment covered by the candidate."""
    before = snapshot(canvas)
    start_fit(canvas, (151.5, 120))
    assert canvas._point_fit_pending_box == (100, 120, 151.5, 200)
    image = render(canvas)

    assert count_ink(image, [(100, y) for y in range(130, 190)]) == 0
    assert count_ink(image, [(x, 200) for x in range(110, 145)]) == 0
    assert count_ink(image, [(x, 200) for x in range(160, 190)]) > 20
    assert count_ink(image, [(x, 100) for x in range(110, 190)]) > 60
    assert count_ink(image, [(200, y) for y in range(110, 190)]) > 60
    assert count_orange(image, [(151, y) for y in range(130, 190)]) > 0
    assert snapshot(canvas) == before


def test_fit_preview_expansion_hides_fully_shared_edges(
    canvas: Canvas,
) -> None:
    """An outward fit hides the original edges it extends along."""
    start_fit(canvas, (250, 50))
    assert canvas._point_fit_pending_box == (100, 50, 250, 200)
    image = render(canvas)
    assert count_ink(image, [(100, y) for y in range(120, 190)]) == 0
    assert count_ink(image, [(x, 200) for x in range(120, 190)]) == 0
    assert count_ink(image, [(x, 100) for x in range(110, 190)]) > 60
    assert count_ink(image, [(200, y) for y in range(110, 190)]) > 60


@pytest.mark.parametrize("show_masks", [False, True])
def test_mask_outline_uses_the_same_avoidance(
    canvas: Canvas, show_masks: bool
) -> None:
    """The extra mask outline cannot reveal the hidden original edge."""
    canvas.show_masks = show_masks
    start_fit(canvas, (151.5, 120))
    image = render(canvas)
    assert count_ink(image, [(100, y) for y in range(130, 190)]) == 0
    assert count_ink(image, [(x, 200) for x in range(110, 145)]) == 0
    assert count_ink(image, [(x, 200) for x in range(160, 190)]) > 20


def test_cancel_restores_the_complete_outline(canvas: Canvas) -> None:
    """Clearing the preview repaints the original full rectangle."""
    start_fit(canvas, (151.5, 120))
    preview_image = render(canvas)
    assert count_ink(
        preview_image, [(100, y) for y in range(130, 190)]
    ) == 0
    canvas._clear_point_fit()
    restored = render(canvas)
    assert count_ink(restored, [(100, y) for y in range(130, 190)]) >= 55
    assert count_ink(restored, [(x, 200) for x in range(110, 190)]) >= 55


def test_same_geometry_draws_no_candidate_outline(canvas: Canvas) -> None:
    """Hovering the current corner keeps the full original outline."""
    start_fit(canvas, (200, 200))
    assert canvas._point_fit_pending_box == BOX
    image = render(canvas)
    assert count_ink(image, [(x, 100) for x in range(110, 190)]) > 60
    assert count_ink(image, [(100, y) for y in range(110, 190)]) > 60
    assert count_orange(image, [(x, 100) for x in range(110, 190)]) == 0
    assert count_orange(image, [(100, y) for y in range(110, 190)]) == 0


def test_invalid_candidate_keeps_full_outline_and_red_marker(
    canvas: Canvas,
) -> None:
    """An ambiguous point never hides the original rectangle."""
    start_fit(canvas, (150.5, 120))
    assert canvas._point_fit_pending_box is None
    image = render(canvas)
    assert count_ink(image, [(100, y) for y in range(110, 190)]) > 60
    red = [
        image.pixelColor(x, y)
        for x in range(145, 158)
        for y in range(114, 127)
    ]
    assert any(
        color.red() > 200 and color.green() < 160 and color.blue() < 160
        for color in red
    )


def test_fit_preview_at_two_times_zoom(canvas: Canvas) -> None:
    """Cosmetic strokes keep the same screen-pixel avoidance at zoom."""
    canvas.resize(600, 600)
    canvas.scale = 2.0
    start_fit(canvas, (151.5, 120))
    image = render(canvas)
    shared = [(200, y) for y in range(260, 380)]
    assert count_ink(image, shared) == 0
    assert count_orange(image, [(303, y) for y in range(260, 380)]) > 0


def test_creation_guide_suppresses_shared_draft_edges(
    canvas: Canvas,
) -> None:
    """The cyan guide replaces the two draft edges under the cursor."""
    canvas.set_editing(False)
    canvas.create_mode = "rectangle"
    canvas.cross_line_show = False
    canvas.current = Shape(shape_type="rectangle")
    canvas.current.add_point(QtCore.QPointF(30, 30))
    canvas.line.shape_type = "rectangle"
    canvas.line.points = [
        QtCore.QPointF(30, 30),
        QtCore.QPointF(120, 120),
    ]
    canvas._crosshair_cursor_active = True
    canvas.prev_move_point = QtCore.QPointF(120, 120)

    guided = render(canvas)
    guided_right = [
        (120, y) for y in range(45, 110)
    ]
    guided_top = [(x, 30) for x in range(45, 110)]
    assert count_colored(guided, guided_right) < len(guided_right) * 0.9
    assert count_colored(guided, guided_top) == len(guided_top)

    canvas.rectangle_creation_crosshair_show = False
    unguided = render(canvas)
    unguided_right = [
        (120, y) for y in range(45, 110)
    ]
    assert count_colored(unguided, unguided_right) == len(unguided_right)
    assert count_colored(guided, guided_right) < count_colored(
        unguided, unguided_right
    )


def test_invalid_target_disables_candidate_and_avoidance(
    canvas: Canvas,
) -> None:
    """A multi-selection cannot leave a stale candidate or missing edge."""
    other = Shape(label=None, shape_type="rectangle")
    other.points = [
        QtCore.QPointF(20, 20),
        QtCore.QPointF(50, 20),
        QtCore.QPointF(50, 50),
        QtCore.QPointF(20, 50),
    ]
    other.close()
    other.selected = True
    canvas.shapes.append(other)
    canvas.selected_shapes.append(other)
    start_fit(canvas, (151.5, 120))
    preview = canvas._build_point_fit_preview()
    assert preview is not None
    assert not preview.valid
    assert preview.outline_path is None
    image = render(canvas)
    assert count_ink(image, [(100, y) for y in range(130, 190)]) >= 55
    assert count_orange(image, [(151, y) for y in range(130, 190)]) == 0


def test_completed_two_point_draft_keeps_all_four_edges(
    app: QtWidgets.QApplication,
) -> None:
    """Committing the draft shows the full ordinary rectangle outline."""
    widget = Canvas(parent=None)
    pixmap = QtGui.QPixmap(300, 300)
    pixmap.fill(QtGui.QColor("white"))
    widget.pixmap = pixmap
    widget.resize(300, 300)
    widget.cross_line_show = False
    widget.show_labels = False
    widget.show_texts = False
    widget.show_scores = False
    widget.show_attributes = False
    widget.show_linking = False
    widget.show()
    try:
        widget.set_editing(False)
        widget.create_mode = "rectangle"
        QtTest.QTest.mouseClick(
            widget, QtCore.Qt.MouseButton.LeftButton,
            pos=QtCore.QPoint(30, 30),
        )
        QtTest.QTest.mouseMove(widget, QtCore.QPoint(120, 120))
        QtTest.QTest.mouseClick(
            widget, QtCore.Qt.MouseButton.LeftButton,
            pos=QtCore.QPoint(120, 120),
        )
        assert len(widget.shapes) == 1
        shape = widget.shapes[0]
        shape.line_color = QtGui.QColor("black")
        shape.select_line_color = QtGui.QColor("black")
        shape.selected = False
        image = render(widget)
        assert count_ink(image, [(x, 30) for x in range(40, 110)]) == 70
        assert count_ink(image, [(x, 120) for x in range(40, 110)]) == 70
        assert count_ink(image, [(30, y) for y in range(40, 110)]) == 70
        assert count_ink(image, [(120, y) for y in range(40, 110)]) == 70
    finally:
        widget.close()
        widget.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_fit_preview_suppresses_native_crosshair_only_when_changed(
    canvas: Canvas,
) -> None:
    """The always-on crosshair yields only to a changed valid candidate."""
    canvas.cross_line_show = True
    start_fit(canvas, (151.5, 120))
    assert not canvas._native_crosshair_enabled()
    start_fit(canvas, (200, 200))
    assert canvas._native_crosshair_enabled()
    canvas._clear_point_fit()
    assert canvas._native_crosshair_enabled()


def test_export_without_preview_keeps_all_four_edges(
    canvas: Canvas,
) -> None:
    """Visualization export never consumes transient preview avoidance."""
    shape = canvas.shapes[0]
    image = canvas.render_visualization(
        canvas.pixmap,
        [shape],
        show_labels=False,
        show_scores=False,
        show_groups=False,
        show_texts=False,
        show_masks=False,
    )
    samples = (
        [(x, 100) for x in range(110, 190)]
        + [(x, 200) for x in range(110, 190)]
        + [(100, y) for y in range(110, 190)]
        + [(200, y) for y in range(110, 190)]
    )
    assert all(
        image.pixelColor(x, y).alpha() > 0
        and image.pixelColor(x, y).red() < 70
        for x, y in samples
    )


def test_candidate_color_matches_the_plan(canvas: Canvas) -> None:
    """The candidate keeps the agreed orange and screen width."""
    assert FIT_CANDIDATE_COLOR.getRgb() == (220, 130, 0, 255)
    start_fit(canvas, (151.5, 120))
    preview = canvas._build_point_fit_preview()
    assert preview is not None and preview.candidate_differs
    assert preview.outline_path is not None


def test_hover_preview_does_not_recompute_without_source_change(
    canvas: Canvas,
) -> None:
    """A steady hover reuses its candidate instead of recomputing it."""
    send_mouse(canvas, QtCore.QEvent.Type.MouseMove, (151.5, 120))
    assert canvas._point_fit_pending_box == (100, 120, 151.5, 200)
    with mock.patch.object(
        canvas, "_update_point_fit", wraps=canvas._update_point_fit
    ) as recompute:
        render(canvas)
    assert not recompute.called


@pytest.mark.parametrize("show_masks", [False, True])
def test_keyboard_nudge_recomputes_still_valid_hover_candidate(
    canvas: Canvas, show_masks: bool
) -> None:
    """A nudge under a hover preview rebuilds the candidate from new bounds."""
    canvas.show_masks = show_masks
    canvas.cross_line_show = True
    seed_pointer(canvas)
    send_mouse(canvas, QtCore.QEvent.Type.MouseMove, (151.5, 120))
    assert canvas._point_fit_pending_box == (100, 120, 151.5, 200)
    assert not canvas._native_crosshair_enabled()
    backups = len(canvas.shapes_backups)

    nudge(canvas, QtCore.Qt.Key.Key_Left)
    assert bounds(canvas.shapes[0]) == (99, 100, 199, 200)
    # The keyboard edit is the only new undo step; previews add none.
    assert len(canvas.shapes_backups) == backups + 1
    nudge_snapshot = snapshot(canvas)

    image = render(canvas)
    assert canvas._point_fit_pending_box == (99, 120, 151.5, 200)
    assert canvas._point_fit_source_box == (99, 100, 199, 200)
    assert count_orange(image, [(151, y) for y in range(130, 190)]) > 0
    assert count_ink(image, [(99, y) for y in range(130, 190)]) == 0
    assert count_ink(image, [(x, 200) for x in range(110, 145)]) == 0
    assert count_ink(image, [(x, 200) for x in range(160, 190)]) > 20
    assert count_ink(image, [(x, 100) for x in range(110, 190)]) > 60
    assert count_ink(image, [(199, y) for y in range(110, 190)]) > 60
    assert snapshot(canvas) == nudge_snapshot
    assert len(canvas.shapes_backups) == backups + 1

    with mock.patch.object(
        canvas, "_update_point_fit", wraps=canvas._update_point_fit
    ) as recompute:
        render(canvas)
    assert not recompute.called


@pytest.mark.parametrize("show_masks", [False, True])
def test_keyboard_nudge_invalidates_hover_candidate(
    canvas: Canvas, show_masks: bool
) -> None:
    """The stale orange candidate disappears once the nudge makes it invalid."""
    canvas.show_masks = show_masks
    canvas.cross_line_show = True
    seed_pointer(canvas)
    send_mouse(canvas, QtCore.QEvent.Type.MouseMove, (151.5, 120))
    assert canvas._point_fit_pending_box == (100, 120, 151.5, 200)
    assert not canvas._native_crosshair_enabled()
    backups = len(canvas.shapes_backups)

    nudge(canvas, QtCore.Qt.Key.Key_Right)
    assert bounds(canvas.shapes[0]) == (101, 100, 201, 200)
    assert len(canvas.shapes_backups) == backups + 1
    nudge_snapshot = snapshot(canvas)

    image = render(canvas)
    assert canvas._point_fit_pending_box is None
    assert canvas._point_fit_source_box == (101, 100, 201, 200)
    assert canvas._native_crosshair_enabled()
    assert count_orange(image, [(151, y) for y in range(130, 190)]) == 0
    assert count_ink(image, [(x, 200) for x in range(111, 190)]) > 60
    assert count_ink(image, [(101, y) for y in range(110, 190)]) > 60
    assert count_ink(image, [(x, 100) for x in range(111, 191)]) > 60
    assert count_ink(image, [(201, y) for y in range(110, 190)]) > 60
    # The always-on crosshair paints at half opacity, so the invalid marker
    # shows up as a light red blend rather than a fully opaque ring.
    red = [
        image.pixelColor(x, y)
        for x in range(145, 158)
        for y in range(114, 127)
    ]
    assert any(
        color.red() > 200
        and color.red() - color.green() > 40
        and color.blue() > 100
        for color in red
    )
    assert snapshot(canvas) == nudge_snapshot
    assert len(canvas.shapes_backups) == backups + 1


def test_keyboard_nudge_keeps_alt_hover_mode(canvas: Canvas) -> None:
    """Recomputing an Alt hover keeps the inward candidate semantics."""
    seed_pointer(canvas)
    send_mouse(canvas, QtCore.QEvent.Type.MouseMove, (120, 120), alt=True)
    assert canvas._point_fit_pending_box == (100, 100, 120, 120)

    nudge(canvas, QtCore.Qt.Key.Key_Left)
    image = render(canvas)
    assert canvas._point_fit_pending_box == (99, 100, 120, 120)
    assert canvas._point_fit_source_box == (99, 100, 199, 200)
    assert count_ink(image, [(x, 100) for x in range(105, 116)]) == 0
    assert count_orange(image, [(x, 100) for x in range(105, 116)]) > 0
    assert count_ink(image, [(x, 200) for x in range(110, 190)]) > 60


def test_captured_fit_cancels_when_keyboard_moves_source(
    canvas: Canvas,
) -> None:
    """A captured gesture whose geometry changed is dropped, not committed."""
    canvas.cross_line_show = True
    backups = len(canvas.shapes_backups)
    seed_pointer(canvas)
    send_mouse(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    assert canvas._point_fit_pressed
    assert canvas._point_fit_pending_box == (100, 120, 151.5, 200)
    assert not canvas._native_crosshair_enabled()

    nudge(canvas, QtCore.Qt.Key.Key_Right)
    assert bounds(canvas.shapes[0]) == (101, 100, 201, 200)
    assert len(canvas.shapes_backups) == backups + 1
    moved_snapshot = snapshot(canvas)

    image = render(canvas)
    assert canvas._point_fit_pressed
    assert canvas._point_fit_pending_box is None
    assert canvas._native_crosshair_enabled()
    assert count_orange(image, [(151, y) for y in range(130, 190)]) == 0
    assert count_ink(image, [(101, y) for y in range(110, 190)]) > 60
    assert count_ink(image, [(201, y) for y in range(110, 190)]) > 60
    assert count_ink(image, [(x, 200) for x in range(111, 145)]) > 30
    assert count_ink(image, [(x, 200) for x in range(160, 190)]) > 20

    # A pointer move before the release cannot revive the old candidate.
    send_mouse(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (151.5, 120),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert canvas._point_fit_pending_box is None
    assert canvas._native_crosshair_enabled()

    send_mouse(canvas, QtCore.QEvent.Type.MouseButtonRelease, (151.5, 120))
    assert bounds(canvas.shapes[0]) == (101, 100, 201, 200)
    assert not canvas._point_fit_pressed
    assert snapshot(canvas) == moved_snapshot
    assert len(canvas.shapes_backups) == backups + 1

    canvas.restore_shape()
    assert bounds(canvas.shapes[0]) == (100, 100, 200, 200)


def test_refit_after_cancelled_capture_commits_and_undoes(
    canvas: Canvas,
) -> None:
    """A new gesture after the cancellation still commits and undoes."""
    seed_pointer(canvas)
    send_mouse(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    nudge(canvas, QtCore.Qt.Key.Key_Right)
    render(canvas)
    send_mouse(canvas, QtCore.QEvent.Type.MouseButtonRelease, (151.5, 120))
    assert bounds(canvas.shapes[0]) == (101, 100, 201, 200)
    backups = len(canvas.shapes_backups)

    send_mouse(canvas, QtCore.QEvent.Type.MouseMove, (180, 130))
    assert canvas._point_fit_pending_box == (101, 130, 180, 200)
    send_mouse(canvas, QtCore.QEvent.Type.MouseButtonPress, (180, 130))
    send_mouse(canvas, QtCore.QEvent.Type.MouseButtonRelease, (180, 130))
    assert bounds(canvas.shapes[0]) == (101, 130, 180, 200)
    assert len(canvas.shapes_backups) == backups + 1

    canvas.restore_shape()
    assert bounds(canvas.shapes[0]) == (101, 100, 201, 200)
    canvas.restore_shape()
    assert bounds(canvas.shapes[0]) == (100, 100, 200, 200)


@pytest.mark.parametrize("initial_dirty", [False, True])
@pytest.mark.parametrize("inward", [False, True])
def test_preview_cancel_preserves_host_dirty(canvas, dirty_host,
                                           initial_dirty, inward):
    """Hover, repeated paint and modifier cancellation never mark dirty."""
    dirty_host.dirty = initial_dirty
    before = snapshot(canvas)
    send_mouse(canvas, QtCore.QEvent.Type.MouseMove, (180, 120), alt=inward)
    render(canvas)
    render(canvas)
    canvas.keyReleaseEvent(QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyRelease, QtCore.Qt.Key.Key_Shift,
        QtCore.Qt.KeyboardModifier.NoModifier,
    ))
    render(canvas)
    assert dirty_host.dirty is initial_dirty
    assert dirty_host.set_dirty.call_count == 0
    assert len(dirty_host.moves) == 0
    assert snapshot(canvas) == before


@pytest.mark.parametrize("show_masks", [False, True])
@pytest.mark.parametrize("captured", [False, True])
@pytest.mark.parametrize("key", [QtCore.Qt.Key.Key_Left,
                                 QtCore.Qt.Key.Key_Right])
def test_nudge_preview_preserves_host_dirty(canvas, dirty_host, show_masks,
                                          captured, key):
    """Only the nudge commits; recomputation/cancel/release stay silent."""
    canvas.show_masks = show_masks
    seed_pointer(canvas)
    kind = (QtCore.QEvent.Type.MouseButtonPress if captured
            else QtCore.QEvent.Type.MouseMove)
    send_mouse(canvas, kind, (151.5, 120))
    render(canvas)
    assert dirty_host.dirty is False
    assert dirty_host.set_dirty.call_count == len(dirty_host.moves) == 0

    nudge(canvas, key)
    assert dirty_host.dirty is True
    assert dirty_host.set_dirty.call_count == len(dirty_host.moves) == 1
    after_nudge = snapshot(canvas)
    # Simulate a clean checkpoint: a stray preview signal must dirty it again.
    dirty_host.dirty = False
    render(canvas)
    render(canvas)
    if captured:
        send_mouse(canvas, QtCore.QEvent.Type.MouseButtonRelease,
                   (151.5, 120))
    else:
        canvas._clear_point_fit()
    render(canvas)
    assert dirty_host.dirty is False
    assert dirty_host.set_dirty.call_count == len(dirty_host.moves) == 1
    assert snapshot(canvas) == after_nudge


@pytest.mark.parametrize("inward", [False, True])
def test_fit_commit_marks_host_dirty_once(canvas, dirty_host, inward):
    """Valid fit commits once and a single undo restores the starting box."""
    seed_pointer(canvas)
    before = snapshot(canvas)
    backups = len(canvas.shapes_backups)
    send_mouse(canvas, QtCore.QEvent.Type.MouseMove, (180, 120), alt=inward)
    render(canvas)
    assert dirty_host.dirty is False
    assert dirty_host.set_dirty.call_count == len(dirty_host.moves) == 0
    assert snapshot(canvas) == before
    send_mouse(canvas, QtCore.QEvent.Type.MouseButtonPress,
               (180, 120), alt=inward)
    send_mouse(canvas, QtCore.QEvent.Type.MouseButtonRelease,
               (180, 120), alt=inward)
    render(canvas)
    assert dirty_host.dirty is True
    assert dirty_host.set_dirty.call_count == len(dirty_host.moves) == 1
    assert len(canvas.shapes_backups) == backups + 1
    canvas.restore_shape()
    render(canvas)
    assert bounds(canvas.shapes[0]) == BOX
    assert dirty_host.set_dirty.call_count == len(dirty_host.moves) == 1

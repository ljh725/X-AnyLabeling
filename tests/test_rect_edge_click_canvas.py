"""Exercise click refinement through real Qt canvas mouse events."""

from collections.abc import Iterator

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling import rect_edge_alignment as rea
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

NO_MOD = QtCore.Qt.KeyboardModifier.NoModifier
ALT = QtCore.Qt.KeyboardModifier.AltModifier
LEFT = QtCore.Qt.MouseButton.LeftButton
NO_BUTTON = QtCore.Qt.MouseButton.NoButton


@pytest.fixture
def editor(qapp: QtWidgets.QApplication) -> Iterator[Canvas]:
    """Provide an editable selected rectangle with an actual undo baseline."""
    canvas = Canvas()
    canvas.resize(500, 500)
    pixmap = QtGui.QPixmap(500, 500)
    pixmap.fill(QtGui.QColor("white"))
    canvas.load_pixmap(pixmap)
    shape = Shape(label="person", shape_type="rectangle", group_id=7)
    shape.points = [
        QtCore.QPointF(100, 100),
        QtCore.QPointF(200, 100),
        QtCore.QPointF(200, 300),
        QtCore.QPointF(100, 300),
    ]
    shape.close()
    canvas.load_shapes([shape])
    canvas.select_shapes([shape])
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.rectangle_review_refinement_enabled = True
    canvas.rectangle_review_edge_precision_default = False
    yield canvas
    canvas.close()
    canvas.deleteLater()
    qapp.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def send(
    canvas: Canvas,
    kind: QtCore.QEvent.Type,
    point: tuple[float, float],
    modifiers: QtCore.Qt.KeyboardModifier = NO_MOD,
    held: bool = False,
) -> None:
    """Dispatch original-image coordinates through the widget event route."""
    pos = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    event = QtGui.QMouseEvent(
        kind,
        pos,
        pos,
        NO_BUTTON if kind == QtCore.QEvent.Type.MouseMove else LEFT,
        (
            LEFT
            if held or kind == QtCore.QEvent.Type.MouseButtonPress
            else NO_BUTTON
        ),
        modifiers,
    )
    QtWidgets.QApplication.sendEvent(canvas, event)


def click(
    canvas: Canvas,
    point: tuple[float, float],
    modifiers: QtCore.Qt.KeyboardModifier = NO_MOD,
) -> None:
    """Press and release exactly once without adding motion."""
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, point, modifiers)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, point, modifiers)


def box(canvas: Canvas) -> tuple[float, float, float, float]:
    """Read the first annotation's geometry."""
    return canvas.rect_edge_click.box(
        rea.geometry_from_shape(canvas.shapes[0])
    )


@pytest.mark.parametrize(
    "point,expected",
    [
        ((120, 20), (100, 20, 200, 300)),
        ((180, 200), (100, 100, 180, 300)),
        ((101, 200), (101, 100, 200, 300)),
        ((150, 298), (100, 100, 200, 298)),
    ],
)
def test_one_click_one_coordinate_one_undo(
    editor: Canvas, point: tuple[float, float], expected: tuple[float, ...]
) -> None:
    """Include near-edge clicks, stable identity, feedback and full undo."""
    original = box(editor)
    shape = editor.shapes[0]
    identity = shape.xanylabeling_shape_id
    baseline = len(editor.shapes_backups)
    signals = []
    editor.rectangle_review_edge_drag_started.connect(
        lambda e: signals.append("start")
    )
    editor.shape_moved.connect(lambda: signals.append("moved"))
    editor.rectangle_review_edge_drag_finished.connect(
        lambda ok: signals.append(ok)
    )
    click(editor, point)
    assert box(editor) == expected
    assert len(editor.shapes_backups) == baseline + 1
    assert len(editor.shapes) == 1
    assert shape.group_id == 7 and shape.xanylabeling_shape_id == identity
    assert signals == ["start", "moved", True]
    assert editor.rectangle_review_feedback_snapshot.phase == "committed"
    assert editor.rect_edge_active_edge is None
    editor.restore_shape()
    assert box(editor) == original


def test_preview_never_mutates_and_tracks_same_region(editor: Canvas) -> None:
    """Preview follows coordinates even while the candidate edge is unchanged."""
    original = box(editor)
    baseline = len(editor.shapes_backups)
    for x in (175, 185):
        send(editor, QtCore.QEvent.Type.MouseMove, (x, 200))
        assert editor.rect_edge_click.preview.right() == x
        assert editor.rect_edge_hover_edge.edge_name == "right"
        assert box(editor) == original
    assert len(editor.shapes_backups) == baseline
    send(editor, QtCore.QEvent.Type.MouseMove, (150, 200))
    assert editor.rect_edge_click.preview is None
    assert editor.rect_edge_hover_edge is None


@pytest.mark.parametrize("point", [(150, 200), (125, 150), (100, 200)])
def test_dead_zone_and_unchanged_edge_do_not_store(
    editor: Canvas, point: tuple[float, float]
) -> None:
    """Reject ambiguous clicks and skip identical coordinates."""
    original = box(editor)
    baseline = len(editor.shapes_backups)
    click(editor, point)
    assert box(editor) == original
    assert len(editor.shapes_backups) == baseline
    assert editor.rect_edge_click.lock is None


def test_alt_activates_normal_mode_and_release_clears_preview(
    editor: Canvas,
) -> None:
    """Ordinary selection stays unchanged and Alt temporarily enables clicks."""
    editor.rectangle_review_refinement_enabled = False
    click(editor, (180, 200))
    assert box(editor) == (100, 100, 200, 300)
    click(editor, (180, 200), ALT)
    assert box(editor)[2] == 180
    send(editor, QtCore.QEvent.Type.MouseMove, (170, 200), ALT)
    assert editor.rect_edge_click.preview is not None
    QtWidgets.QApplication.sendEvent(
        editor,
        QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyRelease, QtCore.Qt.Key.Key_Alt, NO_MOD
        ),
    )
    assert editor.rect_edge_click.preview is None
    assert editor.rect_edge_hover_edge is None


@pytest.mark.parametrize(
    "case", ["multi", "point", "drawing", "disabled", "hidden"]
)
def test_activation_prerequisites(editor: Canvas, case: str) -> None:
    """Never infer an edge for a missing, hidden or ambiguous target."""
    if case == "multi":
        other = editor.shapes[0].copy_for_new_object()
        editor.shapes.append(other)
        editor.select_shapes(editor.shapes)
    elif case == "point":
        editor.shapes[0].shape_type = "point"
    elif case == "drawing":
        editor.set_editing(False)
    elif case == "disabled":
        editor.set_rect_edge_align_enabled(False)
    else:
        editor.set_shape_visible(editor.shapes[0], False)
    assert not editor.rect_edge_click.active(ALT)


@pytest.mark.parametrize(
    "cancel", ["escape", "focus", "selection", "load", "changed", "alt"]
)
def test_interrupted_press_never_commits(editor: Canvas, cancel: str) -> None:
    """Invalidate pending clicks before a later release can edit stale state."""
    if cancel == "alt":
        editor.rectangle_review_refinement_enabled = False
    send(editor, QtCore.QEvent.Type.MouseButtonPress, (180, 200), ALT)
    assert editor.rect_edge_click.lock is not None
    if cancel == "escape":
        editor.keyPressEvent(
            QtGui.QKeyEvent(
                QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, ALT
            )
        )
    elif cancel == "focus":
        editor.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    elif cancel == "selection":
        editor.select_shapes([])
    elif cancel == "load":
        editor.load_pixmap(QtGui.QPixmap(500, 500))
    elif cancel == "changed":
        rea.apply_edge_coord(editor.shapes[0], "left", 105)
    else:
        editor.keyReleaseEvent(
            QtGui.QKeyEvent(
                QtCore.QEvent.Type.KeyRelease, QtCore.Qt.Key.Key_Alt, NO_MOD
            )
        )
    baseline = len(editor.shapes_backups)
    send(editor, QtCore.QEvent.Type.MouseButtonRelease, (180, 200), ALT)
    assert len(editor.shapes_backups) == baseline
    if editor.shapes:
        assert box(editor)[2] == 200
    assert editor.rect_edge_click.lock is None


def test_promotion_and_escape_use_existing_drag(editor: Canvas) -> None:
    """Dragging promotes the locked side and Escape rolls it back."""
    baseline = len(editor.shapes_backups)
    send(editor, QtCore.QEvent.Type.MouseButtonPress, (180, 200))
    send(editor, QtCore.QEvent.Type.MouseMove, (185, 200), held=True)
    assert editor.rect_edge_dragging
    assert editor.rect_edge_click.lock is None
    assert box(editor)[2] == 185
    editor.keyPressEvent(
        QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, NO_MOD
        )
    )
    send(editor, QtCore.QEvent.Type.MouseButtonRelease, (185, 200))
    assert box(editor)[2] == 200
    assert len(editor.shapes_backups) == baseline


def test_release_without_move_event_cannot_commit_old_coordinate(
    editor: Canvas,
) -> None:
    """A coalesced drag still uses its final release location."""
    baseline = len(editor.shapes_backups)
    send(editor, QtCore.QEvent.Type.MouseButtonPress, (180, 200))
    send(editor, QtCore.QEvent.Type.MouseButtonRelease, (185, 200))
    assert box(editor)[2] == 185
    assert len(editor.shapes_backups) == baseline + 1


def test_double_click_suppressed_but_distant_click_allowed(
    editor: Canvas,
) -> None:
    """Block both Qt double-click events and repeated nearby press pairs."""
    baseline = len(editor.shapes_backups)
    click(editor, (230, 340))  # Right sector; after commit the point is below.
    first = box(editor)
    send(editor, QtCore.QEvent.Type.MouseButtonDblClick, (230, 340))
    send(editor, QtCore.QEvent.Type.MouseButtonRelease, (230, 340))
    click(editor, (230, 340))
    assert box(editor) == first
    assert len(editor.shapes_backups) == baseline + 1
    click(editor, (160, 80))
    assert box(editor)[1] == 80
    assert len(editor.shapes_backups) == baseline + 2


def test_small_dimension_rejects_instead_of_clamping(editor: Canvas) -> None:
    """A one-pixel-wide original box can still produce an invalid shrink."""
    shape = editor.shapes[0]
    shape.points = [
        QtCore.QPointF(100, 100),
        QtCore.QPointF(101, 100),
        QtCore.QPointF(101, 300),
        QtCore.QPointF(100, 300),
    ]
    baseline = len(editor.shapes_backups)
    click(editor, (100.8, 200))
    assert box(editor)[2] == 101
    assert len(editor.shapes_backups) == baseline
    assert "minimum size" in editor.rect_edge_click.message


def test_ctrl_selection_is_not_region_edit(editor: Canvas) -> None:
    """Reserve Ctrl selection gestures even during refinement."""
    assert not editor.rect_edge_click.active(
        QtCore.Qt.KeyboardModifier.ControlModifier
    )


def test_render_preview_offscreen(editor: Canvas) -> None:
    """Paint guides and a proposal through the real canvas painter."""
    send(editor, QtCore.QEvent.Type.MouseMove, (120, 20))
    output = QtGui.QPixmap(editor.size())
    editor.render(output)
    assert not output.isNull()

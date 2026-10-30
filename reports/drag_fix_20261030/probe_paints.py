"""Paint-request counts for canvas pointer scenarios (CUSTOM-003).

Only a counting wrapper is installed around Canvas.paintEvent; the original
paint still runs and no production branch is replaced.  Run the same file in
the pre-fix tree and in the working tree and compare the numbers.

Usage:  python probe_paints.py [--only scenario]
"""
import argparse
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

app = QtWidgets.QApplication([])
COUNTER = {"paint": 0}
ORIGINAL_PAINT = Canvas.paintEvent


def counting_paint(self, event):
    COUNTER["paint"] += 1
    return ORIGINAL_PAINT(self, event)


Canvas.paintEvent = counting_paint


def build_canvas(shape_type="rectangle"):
    canvas = Canvas(parent=None)
    canvas.pixmap = QtGui.QPixmap(400, 300)
    canvas.pixmap.fill(QtGui.QColor("white"))
    canvas.resize(400, 300)
    canvas.scale = 1.0
    shape = Shape(label="person", shape_type=shape_type)
    shape.points = [
        QtCore.QPointF(x, y)
        for x, y in ((100, 100), (200, 100), (200, 200), (100, 200))
    ]
    shape.close()
    shape.selected = True
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]
    canvas.store_shapes()
    canvas.set_editing(True)
    canvas.show()
    app.processEvents()
    COUNTER["paint"] = 0
    return canvas, shape


def send(canvas, kind, point, button=QtCore.Qt.MouseButton.LeftButton, held=False):
    pos = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    buttons = QtCore.Qt.MouseButton.NoButton
    if held:
        buttons = button
    elif kind == QtCore.QEvent.Type.MouseButtonPress:
        buttons = button
    event = QtGui.QMouseEvent(
        kind, pos, pos, button, buttons, QtCore.Qt.KeyboardModifier.NoModifier
    )
    {
        QtCore.QEvent.Type.MouseMove: canvas.mouseMoveEvent,
        QtCore.QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
        QtCore.QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
    }[kind](event)


def scenario_shape_drag(moves=5, pump=True):
    canvas, shape = build_canvas()
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    if pump:
        app.processEvents()
    COUNTER["paint"] = 0
    start = (150, 150)
    for step in range(1, moves + 1):
        send(canvas, QtCore.QEvent.Type.MouseMove, (start[0] + step, start[1] + step), held=True)
        if pump:
            app.processEvents()
    if not pump:
        app.processEvents()
    result = {
        "paints": COUNTER["paint"],
        "moves": moves,
        "bounds": [
            min(p.x() for p in shape.points),
            min(p.y() for p in shape.points),
            max(p.x() for p in shape.points),
            max(p.y() for p in shape.points),
        ],
    }
    canvas.close()
    canvas.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    return result


def scenario_vertex_drag(moves=5, pump=True):
    canvas, shape = build_canvas()
    send(canvas, QtCore.QEvent.Type.MouseMove, (100, 100))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 100))
    if pump:
        app.processEvents()
    COUNTER["paint"] = 0
    for step in range(1, moves + 1):
        send(canvas, QtCore.QEvent.Type.MouseMove, (100 - step, 100 - step), held=True)
        if pump:
            app.processEvents()
    if not pump:
        app.processEvents()
    result = {
        "paints": COUNTER["paint"],
        "moves": moves,
        "bounds": [
            min(p.x() for p in shape.points),
            min(p.y() for p in shape.points),
            max(p.x() for p in shape.points),
            max(p.y() for p in shape.points),
        ],
    }
    canvas.close()
    canvas.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    return result


def scenario_hover(moves=5, pump=True):
    canvas, shape = build_canvas()
    COUNTER["paint"] = 0
    for step in range(moves):
        send(
            canvas,
            QtCore.QEvent.Type.MouseMove,
            (250 + step * 5, 260),
            button=QtCore.Qt.MouseButton.NoButton,
        )
        if pump:
            app.processEvents()
    if not pump:
        app.processEvents()
    result = {"paints": COUNTER["paint"], "moves": moves}
    canvas.close()
    canvas.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    return result


def scenario_hover_shape(moves=5, pump=True):
    """Hover across a shape so highlight/cursor state changes every move."""
    canvas, shape = build_canvas()
    COUNTER["paint"] = 0
    for step in range(moves):
        send(
            canvas,
            QtCore.QEvent.Type.MouseMove,
            (110 + step * 10, 150),
            button=QtCore.Qt.MouseButton.NoButton,
        )
        if pump:
            app.processEvents()
    if not pump:
        app.processEvents()
    result = {"paints": COUNTER["paint"], "moves": moves}
    canvas.close()
    canvas.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    return result


def scenario_create_preview(moves=5, pump=True):
    canvas = Canvas(parent=None)
    canvas.pixmap = QtGui.QPixmap(400, 300)
    canvas.pixmap.fill(QtGui.QColor("white"))
    canvas.resize(400, 300)
    canvas.scale = 1.0
    canvas.create_mode = "rectangle"
    canvas.set_editing(False)
    canvas.show()
    app.processEvents()
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (40, 40))
    if pump:
        app.processEvents()
    COUNTER["paint"] = 0
    for step in range(1, moves + 1):
        send(canvas, QtCore.QEvent.Type.MouseMove, (40 + step * 5, 40 + step * 5), held=True)
        if pump:
            app.processEvents()
    if not pump:
        app.processEvents()
    result = {
        "paints": COUNTER["paint"],
        "moves": moves,
        "preview_points": [[p.x(), p.y()] for p in canvas.line.points],
    }
    canvas.close()
    canvas.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    return result


def scenario_edge_drag(moves=5, pump=True):
    canvas, shape = build_canvas()
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseMove, (100, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 150))
    if pump:
        app.processEvents()
    COUNTER["paint"] = 0
    for step in range(1, moves + 1):
        send(canvas, QtCore.QEvent.Type.MouseMove, (100 - step, 150), held=True)
        if pump:
            app.processEvents()
    if not pump:
        app.processEvents()
    result = {
        "paints": COUNTER["paint"],
        "moves": moves,
        "bounds": [
            min(p.x() for p in shape.points),
            min(p.y() for p in shape.points),
            max(p.x() for p in shape.points),
            max(p.y() for p in shape.points),
        ],
    }
    canvas.close()
    canvas.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    return result


SCENARIOS = {
    "shape_drag_batched": lambda: scenario_shape_drag(5, pump=False),
    "shape_drag_pumped": lambda: scenario_shape_drag(5, pump=True),
    "vertex_drag_batched": lambda: scenario_vertex_drag(5, pump=False),
    "create_preview_batched": lambda: scenario_create_preview(5, pump=False),
    "create_preview_pumped": lambda: scenario_create_preview(5, pump=True),
    "hover_empty_batched": lambda: scenario_hover(5, pump=False),
    "hover_shape_batched": lambda: scenario_hover_shape(5, pump=False),
    "edge_drag_batched": lambda: scenario_edge_drag(5, pump=False),
    "edge_drag_pumped": lambda: scenario_edge_drag(5, pump=True),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None)
    args = parser.parse_args()
    names = [args.only] if args.only else list(SCENARIOS)
    out = {}
    for name in names:
        out[name] = SCENARIOS[name]()
        print(name, out[name], flush=True)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

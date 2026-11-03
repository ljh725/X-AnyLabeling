"""Second probe batch: inward crossing, handles at zoom, overlap priority."""

import sys

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.rect_edge_click import (
    proposed_inward_point_fit_box,
)
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
FAILURES = []


def fail(tag, detail):
    FAILURES.append((tag, detail))


def make_canvas(box, size=300, scale=1.0, extra_shapes=()):
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(size, size)
    widget.resize(size, size)
    widget.scale = scale
    shape = Shape(label="person", shape_type="rectangle")
    left, top, right, bottom = box
    shape.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    shape.close()
    shape.selected = True
    widget.shapes = [shape, *extra_shapes]
    widget.selected_shapes = [shape]
    widget.store_shapes()
    return widget, shape


def rectangle(label, box):
    shape = Shape(label=label, shape_type="rectangle")
    left, top, right, bottom = box
    shape.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    shape.close()
    return shape


# 1. Inward fit across its anchor must stay normalised and keep the anchor.
box = (100.0, 100.0, 200.0, 200.0)
for point, corner in (((120.0, 120.0), "top_left"), ((180.0, 180.0), "bottom_right")):
    base = proposed_inward_point_fit_box(box, corner, point)
    crossed = proposed_inward_point_fit_box(box, corner, (60.0, 60.0))
    if not (crossed[0] <= crossed[2] and crossed[1] <= crossed[3]):
        fail("inward/not-normalised", crossed)
    if base == crossed:
        fail("inward/crossing-ignored", base)

# 2. Handles stay inside their allowed radius at every zoom level.
for scale in (0.1, 0.3, 1.0, 2.0, 8.0):
    canvas, shape = make_canvas((100, 100, 115, 200), scale=scale)
    canvas.set_rectangle_edge_enabled(True)
    width, height = 15.0, 100.0
    radius = min(3 / scale, width / 4, height / 4)
    if radius * scale > 3 + 1e-9:
        fail("handles/radius", (scale, radius * scale))
    if radius > width / 4 + 1e-9 or radius > height / 4 + 1e-9:
        fail("handles/span", (scale, radius))
    for center, r, edge in canvas._rectangle_edge_handles(shape):
        if abs(r - radius) > 1e-9:
            fail("handles/inconsistent", (scale, r, radius))
    # The centre must never be inside a handle.
    cx, cy = (100 + 115) / 2, (100 + 200) / 2
    for center, r, edge in canvas._rectangle_edge_handles(shape):
        dist = ((center.x() - cx) ** 2 + (center.y() - cy) ** 2) ** 0.5
        if dist <= r + 1e-9:
            fail("handles/covers-centre", (scale, edge, dist, r))
    canvas.close()

# 3. An overlapping shape on top must keep native priority for handles.
top_shape = rectangle("over", (95, 140, 130, 170))
canvas, shape = make_canvas((100, 100, 115, 200), extra_shapes=[top_shape])
canvas.set_rectangle_edge_enabled(True)
hit = canvas._rectangle_edge_hit(QtCore.QPointF(100, 150))
if hit is not None:
    fail("handles/overlap-priority", hit[1])
canvas.close()

# 4. Painting must not raise at extreme zoom or with a degenerate box.
for scale, box in ((0.05, (100.0, 100.0, 100.4, 100.4)), (12.0, (10, 10, 11, 11))):
    canvas, shape = make_canvas(box, scale=scale)
    canvas.set_rectangle_edge_enabled(True)
    image = QtGui.QImage(300, 300, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("black"))
    painter = QtGui.QPainter(image)
    try:
        canvas._paint_rectangle_edge(painter)
    except Exception as exc:  # noqa: BLE001
        fail("paint/exception", (scale, repr(exc)))
    painter.end()
    canvas.close()

# 5. Hovering must never mutate geometry or history.
canvas, shape = make_canvas((100, 100, 200, 200))
canvas.set_rectangle_edge_enabled(True)
before = [(p.x(), p.y()) for p in shape.points]
history = len(canvas.shapes_backups)
for point in ((100, 150), (200, 150), (150, 100), (150, 200), (150, 150)):
    canvas._rectangle_edge_hover_move(QtCore.QPointF(*point))
if [(p.x(), p.y()) for p in shape.points] != before:
    fail("hover/mutated", None)
if len(canvas.shapes_backups) != history:
    fail("hover/history", None)
canvas.close()

app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

if FAILURES:
    for tag, detail in FAILURES:
        print("FAIL", tag, detail)
    sys.exit(1)
print("probe batch 2 passed")

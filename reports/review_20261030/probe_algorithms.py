"""Adversarial probes for the two canvas algorithm changes under review."""

import random
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.rect_edge_click import (
    corner_point,
    point_fit_decision,
)
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

FAILURES = []


def fail(tag, detail):
    FAILURES.append((tag, detail))


def make_canvas(box, size=300, scale=1.0):
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
    widget.shapes = [shape]
    widget.selected_shapes = [shape]
    widget.store_shapes()
    return widget, shape


def send(canvas, kind, point, shift=True, alt=False, held=False):
    pos = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    button = (
        QtCore.Qt.MouseButton.NoButton
        if kind == QtCore.QEvent.Type.MouseMove
        else QtCore.Qt.MouseButton.LeftButton
    )
    buttons = (
        QtCore.Qt.MouseButton.LeftButton
        if held or kind == QtCore.QEvent.Type.MouseButtonPress
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


def bounds(shape):
    xs = [p.x() for p in shape.points]
    ys = [p.y() for p in shape.points]
    return min(xs), min(ys), max(xs), max(ys)


def seg_distance(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5


def probe_point_fit_preview_matches_commit():
    """The committed box must equal the last preview box, always."""
    rng = random.Random(7)
    for _ in range(400):
        left = rng.uniform(0, 150)
        top = rng.uniform(0, 150)
        right = left + rng.uniform(2, 149)
        bottom = top + rng.uniform(2, 149)
        if right > 300 or bottom > 300:
            continue
        canvas, shape = make_canvas((left, top, right, bottom))
        scale = rng.choice([0.3, 1.0, 2.5])
        canvas.scale = scale
        press = (rng.uniform(left - 8, right + 8), rng.uniform(top - 8, bottom + 8))
        alt = rng.random() < 0.5
        send(canvas, QtCore.QEvent.Type.MouseButtonPress, press, alt=alt)
        if not canvas._point_fit_pressed:
            canvas.close()
            continue
        target = None
        for _ in range(3):
            move = (
                rng.uniform(-20, 320),
                rng.uniform(-20, 320),
            )
            send(canvas, QtCore.QEvent.Type.MouseMove, move, alt=alt, held=True)
            target = move
        preview = canvas._point_fit_pending_box
        send(canvas, QtCore.QEvent.Type.MouseButtonRelease, target, alt=alt)
        committed = bounds(shape)
        if preview is None:
            if committed != (left, top, right, bottom):
                fail("point/preview-none", (preview, committed, press))
        elif any(abs(a - b) > 1e-9 for a, b in zip(preview, committed)):
            fail("point/preview-mismatch", (preview, committed, press, scale))
        canvas.close()
    _pump()


def probe_point_fit_anchor_is_a_corner():
    """The preview anchor must be a corner of the preview rectangle."""
    rng = random.Random(11)
    for _ in range(300):
        left, top = rng.uniform(20, 120), rng.uniform(20, 120)
        right, bottom = left + rng.uniform(3, 120), top + rng.uniform(3, 120)
        if right > 290 or bottom > 290:
            continue
        canvas, shape = make_canvas((left, top, right, bottom))
        press = (rng.uniform(left, right), rng.uniform(top, bottom))
        alt = rng.random() < 0.5
        send(canvas, QtCore.QEvent.Type.MouseButtonPress, press, alt=alt)
        if not canvas._point_fit_pressed:
            canvas.close()
            continue
        move = (rng.uniform(0, 300), rng.uniform(0, 300))
        send(canvas, QtCore.QEvent.Type.MouseMove, move, alt=alt, held=True)
        anchor = canvas._point_fit_anchor
        box = canvas._point_fit_pending_box
        if anchor is not None and box is not None:
            corners = [
                (box[0], box[1]),
                (box[2], box[1]),
                (box[2], box[3]),
                (box[0], box[3]),
            ]
            if not any(
                abs(anchor[0] - cx) < 1e-6 and abs(anchor[1] - cy) < 1e-6
                for cx, cy in corners
            ):
                fail("point/anchor-not-corner", (anchor, box, press, move))
        canvas.close()
    _pump()


def probe_edge_returns_only_nearest():
    """A captured edge must be the geometrically nearest edge."""
    rng = random.Random(3)
    for _ in range(500):
        left, top = rng.uniform(0, 200), rng.uniform(0, 200)
        right, bottom = left + rng.uniform(2, 98), top + rng.uniform(2, 98)
        if right > 299 or bottom > 299:
            continue
        canvas, shape = make_canvas((left, top, right, bottom))
        canvas.scale = rng.choice([0.3, 1.0, 2.0])
        canvas.set_rectangle_edge_enabled(True)
        x = rng.uniform(left - 9, right + 9)
        y = rng.uniform(top - 9, bottom + 9)
        hit = canvas._rectangle_edge_hit(QtCore.QPointF(x, y))
        if hit is not None:
            distances = {
                "left": seg_distance(x, y, left, top, left, bottom),
                "right": seg_distance(x, y, right, top, right, bottom),
                "top": seg_distance(x, y, left, top, right, top),
                "bottom": seg_distance(x, y, left, bottom, right, bottom),
            }
            nearest = min(distances.values())
            if distances[hit[1]] > nearest + 1e-9:
                fail("edge/farther-edge", (hit[1], distances, (x, y)))
        canvas.close()
    _pump()


def probe_edge_center_never_captured():
    """The central half of a small box must stay available for moving."""
    rng = random.Random(5)
    for _ in range(300):
        left, top = rng.uniform(0, 200), rng.uniform(0, 200)
        width, height = rng.uniform(2, 28), rng.uniform(2, 28)
        right, bottom = left + width, top + height
        if right > 299 or bottom > 299:
            continue
        canvas, shape = make_canvas((left, top, right, bottom))
        canvas.scale = rng.choice([0.3, 1.0, 2.0])
        canvas.set_rectangle_edge_enabled(True)
        x = rng.uniform(left + width / 4, right - width / 4)
        y = rng.uniform(top + height / 4, bottom - height / 4)
        hit = canvas._rectangle_edge_hit(QtCore.QPointF(x, y))
        if hit is not None:
            fail("edge/centre-captured", (hit[1], (left, top, right, bottom), (x, y)))
        canvas.close()
    _pump()


def probe_edge_opposite_edge_fixed():
    """Dragging one edge must never move the opposite edge or flip the box."""
    rng = random.Random(13)
    for _ in range(200):
        left, top = rng.uniform(0, 150), rng.uniform(0, 150)
        right, bottom = left + rng.uniform(5, 140), top + rng.uniform(5, 140)
        if right > 299 or bottom > 299:
            continue
        canvas, shape = make_canvas((left, top, right, bottom))
        canvas.set_rectangle_edge_enabled(True)
        edge_point = {
            "left": ((left, (top + bottom) / 2), "left"),
            "right": ((right, (top + bottom) / 2), "right"),
            "top": (((left + right) / 2, top), "top"),
            "bottom": (((left + right) / 2, bottom), "bottom"),
        }
        name = rng.choice(list(edge_point))
        press, edge = edge_point[name]
        send(canvas, QtCore.QEvent.Type.MouseButtonPress, press, shift=False)
        if canvas._rectangle_edge_drag is None:
            canvas.close()
            continue
        dx, dy = rng.uniform(-60, 60), rng.uniform(-60, 60)
        send(
            canvas,
            QtCore.QEvent.Type.MouseMove,
            (press[0] + dx, press[1] + dy),
            shift=False,
            held=True,
        )
        after = bounds(shape)
        send(
            canvas,
            QtCore.QEvent.Type.MouseButtonRelease,
            (press[0] + dx, press[1] + dy),
            shift=False,
        )
        if edge in ("left", "right"):
            if abs(after[1] - top) > 1e-9 or abs(after[3] - bottom) > 1e-9:
                fail("edge/vertical-span-moved", (after, (left, top, right, bottom)))
        else:
            if abs(after[0] - left) > 1e-9 or abs(after[2] - right) > 1e-9:
                fail("edge/horizontal-span-moved", (after, (left, top, right, bottom)))
        if after[2] - after[0] < 1 - 1e-9 or after[3] - after[1] < 1 - 1e-9:
            fail("edge/degenerate", (after, edge, (dx, dy)))
        canvas.close()
    _pump()


def probe_edge_delta_is_exact():
    """Below the clamp, an edge must follow the pointer displacement exactly."""
    rng = random.Random(17)
    for _ in range(200):
        left, top = rng.uniform(30, 120), rng.uniform(30, 120)
        right, bottom = left + rng.uniform(10, 130), top + rng.uniform(10, 130)
        if right > 250 or bottom > 250:
            continue
        canvas, shape = make_canvas((left, top, right, bottom))
        canvas.set_rectangle_edge_enabled(True)
        press = (left, (top + bottom) / 2)
        send(canvas, QtCore.QEvent.Type.MouseButtonPress, press, shift=False)
        if canvas._rectangle_edge_drag is None:
            canvas.close()
            continue
        dx = rng.uniform(-5, 5)
        send(
            canvas,
            QtCore.QEvent.Type.MouseMove,
            (press[0] + dx, press[1]),
            shift=False,
            held=True,
        )
        after = bounds(shape)
        if abs((after[0] - left) - dx) > 1e-9:
            fail("edge/delta", (after, (left, top, right, bottom), dx))
        canvas.close()
    _pump()


def probe_edge_vertex_of_small_box():
    """An exact vertex of a small box must not be intercepted by handles."""
    rng = random.Random(19)
    for _ in range(200):
        left, top = rng.uniform(20, 200), rng.uniform(20, 200)
        width, height = rng.uniform(2, 25), rng.uniform(2, 25)
        right, bottom = left + width, top + height
        if right > 290 or bottom > 290:
            continue
        canvas, shape = make_canvas((left, top, right, bottom))
        canvas.set_rectangle_edge_enabled(True)
        for corner in ((left, top), (right, top), (right, bottom), (left, bottom)):
            hit = canvas._rectangle_edge_hit(QtCore.QPointF(*corner))
            if hit is not None:
                fail("edge/vertex-captured", (corner, hit[1], (left, top, right, bottom)))
        canvas.close()
    _pump()


def probe_nan_points():
    """Non-finite geometry must be rejected instead of raising."""
    canvas, shape = make_canvas((100, 100, 200, 200))
    shape.points[0] = QtCore.QPointF(float("nan"), 100)
    canvas.set_rectangle_edge_enabled(True)
    try:
        canvas._rectangle_edge_hit(QtCore.QPointF(101, 150))
        send(canvas, QtCore.QEvent.Type.MouseMove, (101, 150))
        send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (101, 150))
    except Exception as exc:  # noqa: BLE001
        fail("nan/exception", repr(exc))
    canvas.close()
    _pump()


def probe_decision_continuity():
    """Corner inference must not jump across the rectangle boundary."""
    rng = random.Random(23)
    for _ in range(3000):
        left, top = rng.uniform(0, 100), rng.uniform(0, 100)
        width, height = rng.uniform(0.5, 60), rng.uniform(0.5, 60)
        box = (left, top, left + width, top + height)
        scale = rng.choice([0.2, 0.5, 1.0, 2.0, 4.0])
        x = rng.uniform(left - 5, left + width + 5)
        inside = point_fit_decision(box, (x, top), scale).edge
        outside = point_fit_decision(box, (x, top - 0.001 / scale), scale).edge
        if inside != outside:
            fail("point/band-jump", (box, x, scale, inside, outside))
    if not FAILURES:
        print("continuity sample clean")


def _pump():
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


probes = [
    probe_point_fit_preview_matches_commit,
    probe_point_fit_anchor_is_a_corner,
    probe_edge_returns_only_nearest,
    probe_edge_center_never_captured,
    probe_edge_opposite_edge_fixed,
    probe_edge_delta_is_exact,
    probe_edge_vertex_of_small_box,
    probe_nan_points,
    probe_decision_continuity,
]

for probe in probes:
    before = len(FAILURES)
    probe()
    status = "OK" if len(FAILURES) == before else "FAIL"
    print(f"[{status}] {probe.__name__}")

print()
if FAILURES:
    from collections import Counter

    counts = Counter(tag for tag, _ in FAILURES)
    print("failure counts:", dict(counts))
    seen = set()
    for tag, detail in FAILURES:
        if tag in seen:
            continue
        seen.add(tag)
        print(tag, "->", detail)
    sys.exit(1)
print("all probes passed")

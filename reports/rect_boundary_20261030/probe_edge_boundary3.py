"""Confirm the two boundary gates at fit zoom and the Shift swallow."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\X-AnyLabeling-4.2.1")

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def build(box, scale, iw, ih):
    w = Canvas(parent=None)
    w.pixmap = QtGui.QPixmap(iw, ih)
    w.resize(400, 400)
    w.scale = scale
    left, top, right, bottom = box
    s = Shape(label="a", shape_type="rectangle")
    s.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    s.close()
    s.selected = True
    w.shapes = [s]
    w.selected_shapes = [s]
    w.store_shapes()
    w.set_rectangle_edge_enabled(True)
    return w, s


def send(w, img_pt, mods=QtCore.Qt.KeyboardModifier.NoModifier):
    wp = (QtCore.QPointF(*img_pt) + w.offset_to_center()) * w.scale
    ev = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        wp,
        wp,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        mods,
    )
    w.mousePressEvent(ev)
    return wp


print("### fit zoom 0.3, box 300x80 hugging the left border (small=True)")
w, s = build((0, 0, 300, 80), 0.3, 1000, 1000)
print("   small:", min(300, 80) * w.scale, "<", 3 * w.epsilon,
      "->", min(300, 80) * w.scale < 3 * w.epsilon)
print("   offset:", w.offset_to_center())
for pt in [(0, 40), (2, 40), (5, 40), (10, 40), (20, 40), (150, 0), (150, 3), (150, 10)]:
    w._rectangle_edge_drag = None
    hit = w._rectangle_edge_hit(QtCore.QPointF(*pt))
    wp = send(w, pt)
    print(f"   img{str(pt):>11} widget=({wp.x():6.1f},{wp.y():6.1f}) "
          f"hit={hit[1] if hit else None} drag="
          f"{w._rectangle_edge_drag.edge if w._rectangle_edge_drag else None}")

print("\n### normal box 300x300 at fit 0.3, same border")
w2, _ = build((0, 0, 300, 300), 0.3, 1000, 1000)
print("   small:", min(300, 300) * w2.scale < 3 * w2.epsilon)
for pt in [(2, 150), (5, 150), (10, 150)]:
    w2._rectangle_edge_drag = None
    hit = w2._rectangle_edge_hit(QtCore.QPointF(*pt))
    print(f"   img{str(pt):>11} hit={hit[1] if hit else None}")

print("\n### Shift+press swallows everything while the proposal is invalid")
w3, _ = build((0, 0, 200, 200), 1.0, 300, 300)
before = len(w3.selected_shapes)
wp = send(w3, (320, 320), QtCore.Qt.KeyboardModifier.ShiftModifier)
print("   shift click outside image -> pressed=", w3._point_fit_pressed,
      "pending=", w3._point_fit_pending_box,
      "edge_drag=", w3._rectangle_edge_drag,
      "tooltip=", repr(w3.toolTip()))
w3._point_fit_pressed = False

print("\n### edge drag requires NoModifier (rectangle_edge.py:120)")
w3._rectangle_edge_drag = None
send(w3, (5, 100), QtCore.Qt.KeyboardModifier.ShiftModifier)
print("   shift+press on left edge -> edge_drag=", w3._rectangle_edge_drag)
send(w3, (5, 100))
print("   plain press on left edge  -> edge_drag=",
      w3._rectangle_edge_drag.edge if w3._rectangle_edge_drag else None)

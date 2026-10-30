"""Sweep: which boundary-adjacent presses can start an edge drag / a fit."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\X-AnyLabeling-4.2.1")

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
IW = IH = 300


def build(box, scale=1.0, widget=(300, 300), width=IW, height=IH):
    w = Canvas(parent=None)
    w.pixmap = QtGui.QPixmap(width, height)
    w.resize(*widget)
    w.scale = scale
    left, top, right, bottom = box
    s = Shape(label="a", shape_type="rectangle")
    s.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(round(right), round(top)),
        QtCore.QPointF(round(right), round(bottom)),
        QtCore.QPointF(left, round(bottom)),
    ]
    s.close()
    s.selected = True
    w.shapes = [s]
    w.selected_shapes = [s]
    w.store_shapes()
    w.set_rectangle_edge_enabled(True)
    return w, s


def press(w, image_pt, mods=QtCore.Qt.KeyboardModifier.NoModifier):
    widget_pt = (QtCore.QPointF(*image_pt) + w.offset_to_center()) * w.scale
    e = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        widget_pt,
        widget_pt,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        mods,
    )
    w.mousePressEvent(e)
    return widget_pt


def report(label, box, probes, scale=1.0, widget=(300, 300), **kw):
    w, s = build(box, scale, widget, **kw)
    o = w.offset_to_center()
    xs = [p.x() for p in s.points]
    ys = [p.y() for p in s.points]
    small = min(max(xs) - min(xs), max(ys) - min(ys)) * w.scale < 3 * w.epsilon
    print(f"\n--- {label} box={box} scale={scale} offset=({o.x():.1f},{o.y():.1f}) small={small}")
    for pt in probes:
        w._rectangle_edge_drag = None
        w._point_fit_pressed = False
        widget_pt = (QtCore.QPointF(*pt) + o) * w.scale
        inside_widget = (
            0 <= widget_pt.x() <= w.width() and 0 <= widget_pt.y() <= w.height()
        )
        hit = w._rectangle_edge_hit(QtCore.QPointF(*pt))
        wp = press(w, pt)
        started = w._rectangle_edge_drag.edge if w._rectangle_edge_drag else None
        fit_started = w._point_fit_pressed
        w._rectangle_edge_cancel()
        w._point_fit_pressed = False
        print(
            f"   img{str(pt):>14} widget=({wp.x():.1f},{wp.y():.1f}) "
            f"in_widget={inside_widget!s:>5} hit={hit[1] if hit else None} "
            f"drag={started} fit={fit_started}"
        )
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


# 1) normal rectangle flush to the left border, press near the border
report("normal flush-left", (0, 100, 200, 250), [(-3, 175), (0, 175), (3, 175), (8, 175)])
# 2) thin strip hugging the top border (common for edge-of-image boxes)
report("thin strip top", (100, 0, 250, 18), [(175, -3), (175, 0), (175, 3), (175, 9)])
# 3) flush to the right/bottom border
report("flush right-bottom", (120, 120, 300, 300), [(299, 200), (300, 200), (302, 200), (200, 300)])
# 4) zoomed out: image smaller than widget -> outside clicks land on the canvas
report("zoomed out 0.5", (0, 60, 100, 150), [(-2, 100), (0, 100), (4, 100)], scale=0.5)
# 5) zoomed in: image bigger than widget
report("zoomed in 2.0", (0, 60, 100, 150), [(-1, 100), (0, 100), (3, 100)], scale=2.0)

# 6) shift+click fit at the border
w, s = build((0, 0, 120, 120))
for pt in [(300, 300), (299, 299), (305, 305), (295, 295)]:
    w._point_fit_pressed = False
    press(w, pt, QtCore.Qt.KeyboardModifier.ShiftModifier)
    print(
        f"\nfit click img{pt}: pressed={w._point_fit_pressed} "
        f"pending={w._point_fit_pending_box} hint={w.toolTip()!r}"
    )
    w._point_fit_pressed = False
w.close()

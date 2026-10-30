"""Probe edge-hit and shift-fit at image borders."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\X-AnyLabeling-4.2.1")

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

W = H = 300


def make(box):
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(W, H)
    widget.resize(W, H)
    left, top, right, bottom = box
    shape = Shape(label="a", shape_type="rectangle")
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
    widget.set_rectangle_edge_enabled(True)
    return widget, shape


def probe(title, box, samples):
    widget, shape = make(box)
    print(f"\n=== {title} box={box} scale={widget.scale} "
          f"offset={widget.offset_to_center()} ===")
    print("eligible:", widget._point_fit_selected_rectangle() is not None)
    print("valid_box:", widget._point_fit_valid_box(box))
    for pt in samples:
        hit = widget._rectangle_edge_hit(QtCore.QPointF(*pt))
        sk = {
            "vertex": shape.nearest_vertex(QtCore.QPointF(*pt), 10),
            "edge": shape.nearest_edge(QtCore.QPointF(*pt), 10),
            "inside": shape.contains_point(QtCore.QPointF(*pt)),
            "cands": [s.label for s in widget._shape_hit_candidates(
                QtCore.QPointF(*pt))],
            "out": widget.out_off_pixmap(QtCore.QPointF(*pt)),
        }
        print(f"  {str(pt):>14} -> {hit}   {sk}")
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


probe("left flush", (0, 100, 200, 200),
      [(-2, 150), (0, 150), (1, 150), (5, 150), (10, 150), (12, 150)])
probe("right flush", (100, 100, 299, 200),
      [(299, 150), (300, 150), (301, 150), (295, 150), (289, 150)])
probe("top flush", (100, 0, 200, 250),
      [(150, -2), (150, 0), (150, 1), (150, 5), (150, 12)])
probe("all flush", (0, 0, 299, 299),
      [(0, 150), (1, 150), (299, 150), (300, 150), (150, 0), (150, 299)])
probe("past edge", (0, 100, 300, 200),
      [(300, 150), (302, 150), (298, 150)])

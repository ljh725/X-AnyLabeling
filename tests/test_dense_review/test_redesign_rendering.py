"""Save synthetic pixel evidence at two DPRs and two source backgrounds."""

# flake8: noqa: F811
from pathlib import Path

import pytest
from PyQt6 import QtCore, QtGui

from .test_workspace_review_fixes import _open, app, open_window


@pytest.mark.parametrize("dpr", [1, 2])
@pytest.mark.parametrize("background", ["#202020", "#eeeeee"])
def test_review_render_preserves_source_and_current_outline(app, open_window, dpr, background):
    _, widget, ws = _open(app, open_window)
    canvas = widget.canvas
    source = QtGui.QPixmap(640, 480)
    source.fill(QtGui.QColor(background))
    canvas.pixmap = source
    widget.set_zoom(100)
    app.processEvents()
    size = canvas.size() * dpr
    image = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32)
    image.setDevicePixelRatio(dpr)
    image.fill(QtGui.QColor(background))
    canvas.render(image)
    shape = widget._dense_review_find_shape("rect1")
    logical = (QtCore.QPointF(40, 100) + canvas.offset_to_center()) * canvas.scale
    x, y = round(logical.x() * dpr), round(logical.y() * dpr)
    colors = [image.pixelColor(px, py) for px in range(max(0, x-3*dpr), min(image.width(), x+3*dpr)) for py in range(max(0, y-3*dpr), min(image.height(), y+3*dpr))]
    assert any(color != QtGui.QColor(background) for color in colors)
    assert canvas.dense_review_hittable(shape)
    assert ws.session.current_object().shape_id == "rect1"
    evidence = Path(__file__).resolve().parents[2] / 'reports/dense_review_redesign/2026-11-17/rendering'
    evidence.mkdir(parents=True, exist_ok=True)
    assert image.save(str(evidence / f'review-{background[1:]}-{dpr}x.png'))

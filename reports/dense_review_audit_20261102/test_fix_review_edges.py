"""Adjacent undo-order check for the three-fix review."""
from tests.test_dense_review.conftest import make_shape
from tests.test_dense_review.test_session import build_session
from PyQt6 import QtCore, QtWidgets
from tests.test_dense_review.test_workspace import window, _prepare_image


def test_manual_edit_back_to_same_content_keeps_canvas_undo_first():
    shape = make_shape("a", bounds=(5, 5, 15, 15))
    session = build_session([shape])
    assert session.confirm_object("a", ("category", "geometry"))
    shape.move_by(10, 0)
    session.sync_shapes([shape])
    shape.move_by(-10, 0)
    session.sync_shapes([shape])
    assert session._last_action == "content"
    assert not session.can_undo_progress(), (
        "Equal content hashes must not prioritize an older confirmation over the latest manual edit"
    )


def test_main_window_undo_reverts_latest_move_after_manual_roundtrip(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    host = window.labeling_widget.view
    assert host.load_file(_prepare_image(tmp_path))
    host.open_dense_review()
    session = host.dense_review_session
    assert session.confirm_object("id1", ("category", "geometry"))
    host.dense_review_after_progress_change()
    shape = host._dense_review_find_shape("id1")
    original_x = shape.points[0].x()
    for dx in (10, -10):
        shape.move_by(QtCore.QPointF(dx, 0))
        host.canvas.store_shapes()
        host.canvas.shape_moved.emit()
        app.processEvents()
    assert host._dense_review_find_shape("id1").points[0].x() == original_x
    host.undo_shape_edit()
    app.processEvents()
    assert host._dense_review_find_shape("id1").points[0].x() == original_x + 10, (
        "Ctrl+Z consumed an old review confirmation instead of undoing the last -10 pixel move"
    )

"""Independent review probes; application code is not modified."""
from PyQt6 import QtCore, QtWidgets
from tests.test_dense_review.test_session import build_session
from tests.test_dense_review.conftest import make_shape
from tests.test_dense_review.test_workspace import window, _prepare_image, _wait_until


def test_two_progress_commands_can_be_undone_consecutively():
    session = build_session([make_shape("a"), make_shape("b")])
    assert session.confirm_object("a", ("category", "geometry"))
    session.mark_difficult("b")
    assert session.undo_progress()
    assert not session.object("b").difficult
    assert session.object("a").confirmed_both()
    assert session.can_undo_progress(), "Earlier confirmation is still in history but Ctrl+Z cannot reach it"


def test_changed_bounds_request_fresh_card(window, tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance()
    host = window.labeling_widget.view
    assert host.load_file(_prepare_image(tmp_path))
    host.open_dense_review()
    workspace = host.dense_review_workspace
    assert _wait_until(app, lambda: workspace.thumbnails.cached_latest("id1") is not None)
    calls = []
    original = workspace.thumbnails.request
    def record_request(shape_id, *args, **kwargs):
        calls.append(shape_id)
        return original(shape_id, *args, **kwargs)
    monkeypatch.setattr(workspace.thumbnails, "request", record_request)
    shape = host._dense_review_find_shape("id1")
    shape.points = [QtCore.QPointF(110, 110), QtCore.QPointF(180, 110), QtCore.QPointF(180, 180), QtCore.QPointF(110, 180)]
    host.set_dirty()
    for _ in range(10):
        app.processEvents()
    assert "id1" in calls, "Moved rectangle reuses the old crop instead of requesting its new bounds"


def test_full_image_roundtrip_restores_user_zoom(window, tmp_path):
    host = window.labeling_widget.view
    assert host.load_file(_prepare_image(tmp_path))
    host.open_dense_review()
    workspace = host.dense_review_workspace
    host.dense_review_set_display_mode("focus")
    host.set_zoom(175)
    before = host.zoom_widget.value()
    workspace._toggle_full_image()
    workspace._toggle_full_image()
    assert host.zoom_widget.value() == before, "Returning from overview overwrites user zoom with auto-focus zoom"

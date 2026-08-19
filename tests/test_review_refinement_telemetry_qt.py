"""Narrow PyQt integration checks for rectangle-review telemetry signals."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui  # noqa: E402

from anylabeling.views.labeling.review_refinement.metrics import (  # noqa: E402
    EpisodeEndReason,
    FeatureStage,
    JsonlMetricsWriter,
    ReviewEpisodeCollector,
)
from anylabeling.views.labeling.rect_edge_alignment import (
    iter_edges,
)  # noqa: E402
from anylabeling.views.labeling.shape import Shape  # noqa: E402
from anylabeling.views.labeling.widgets.canvas import Canvas  # noqa: E402


def _rectangle() -> Shape:
    """Build a test rectangle for transient Canvas overlays."""
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(20, 20),
        QtCore.QPointF(80, 20),
        QtCore.QPointF(80, 80),
        QtCore.QPointF(20, 80),
    ]
    return shape


def test_canvas_telemetry_signals_are_fail_open(qapp, tmp_path) -> None:
    """Canvas signals can feed a collector without writing on disabled mode."""
    disabled_path = tmp_path / "disabled.jsonl"
    disabled = ReviewEpisodeCollector(
        JsonlMetricsWriter(disabled_path), enabled=False
    )
    canvas = Canvas()
    canvas.rectangle_review_edge_drag_started.connect(
        disabled.edge_drag_started
    )
    canvas.rectangle_review_edge_drag_finished.connect(
        disabled.edge_drag_finished
    )
    disabled.target_selected("target", FeatureStage.BASELINE)
    canvas.rectangle_review_edge_drag_started.emit("left")
    canvas.rectangle_review_edge_drag_finished.emit(True)
    disabled.target_cleared(EpisodeEndReason.SESSION_ENDED)
    assert not disabled_path.exists()


def test_canvas_telemetry_signal_episode_persists(tmp_path, qapp) -> None:
    """Enabled signal flow records only accepted drag lifecycle events."""
    path = tmp_path / "enabled.jsonl"
    collector = ReviewEpisodeCollector(
        JsonlMetricsWriter(path), enabled=True, session_id="qt-test"
    )
    canvas = Canvas()
    canvas.rectangle_review_edge_drag_started.connect(
        collector.edge_drag_started
    )
    canvas.rectangle_review_edge_drag_delta.connect(collector.edge_drag_sample)
    canvas.rectangle_review_edge_drag_finished.connect(
        collector.edge_drag_finished
    )
    collector.target_selected("target", FeatureStage.P0_GAIN)
    canvas.rectangle_review_edge_drag_started.emit("left")
    canvas.rectangle_review_edge_drag_delta.emit(1.0)
    canvas.rectangle_review_edge_drag_finished.emit(True)
    collector.target_cleared(EpisodeEndReason.SESSION_ENDED)
    assert path.is_file()
    assert path.read_text(encoding="utf-8").count("\n") == 1


def test_loupe_overlay_does_not_change_canvas_geometry(qapp) -> None:
    """Enabled loupe drawing is read-only and keeps the active edge intact."""
    canvas = Canvas()
    canvas.pixmap = QtGui.QPixmap(100, 100)
    canvas.pixmap.fill(QtGui.QColor("black"))
    shape = _rectangle()
    edge = iter_edges(shape)[0]
    canvas.selected_shapes = [shape]
    canvas.rect_edge_state.active_edge = edge
    canvas.rect_edge_state.drag_start_points = list(shape.points)
    canvas.set_rectangle_review_refinement_config(
        {
            "enabled": True,
            "assistance": {"loupe_enabled": True},
        }
    )
    target = QtGui.QPixmap(240, 180)
    painter = QtGui.QPainter(target)
    canvas._draw_rectangle_review_loupe(painter)
    painter.end()
    assert [(point.x(), point.y()) for point in shape.points] == [
        (20.0, 20.0),
        (80.0, 20.0),
        (80.0, 80.0),
        (20.0, 80.0),
    ]


def test_candidate_preview_is_explicit_and_accept_is_transactional(
    qapp,
) -> None:
    """Candidate request/reject/accept keep preview separate from geometry."""
    canvas = Canvas()
    canvas.pixmap = QtGui.QPixmap(100, 100)
    shape = _rectangle()
    edge = iter_edges(shape)[0]
    canvas.selected_shapes = [shape]
    canvas.rect_edge_state.active_edge = edge
    canvas.rect_edge_state.drag_start_points = list(shape.points)
    canvas.set_rectangle_review_refinement_config(
        {
            "enabled": True,
            "assistance": {"candidate_enabled": True},
        }
    )
    before = [(point.x(), point.y()) for point in shape.points]
    candidate = canvas.request_rectangle_review_candidate([0, 0, 8])
    assert candidate is not None
    assert [(point.x(), point.y()) for point in shape.points] == before
    canvas.reject_rectangle_review_candidate()
    assert [(point.x(), point.y()) for point in shape.points] == before
    canvas.request_rectangle_review_candidate([0, 0, 8])
    assert canvas.accept_rectangle_review_candidate()
    assert [(point.x(), point.y()) for point in shape.points] != before

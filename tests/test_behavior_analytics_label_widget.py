"""Narrow LabelingWidget tests for behavior analytics lifecycle wiring."""

import os.path as osp
from types import SimpleNamespace

from anylabeling.views.labeling import label_widget as label_widget_module


class _Telemetry:
    """Minimal telemetry stand-in that tracks image entry."""

    def __init__(self):
        """Create telemetry without an active image visit."""
        self.tracker = SimpleNamespace(image_visit=None)
        self.entered_images = []

    def enter_image(self, filename):
        """Record the image that the widget activates."""
        self.entered_images.append(filename)
        self.tracker.image_visit = object()


def test_enabling_recording_for_open_image_starts_image_visit(
    monkeypatch, tmp_path
):
    """Runtime enablement initializes the already-open image lifecycle."""
    filename = str(tmp_path / "image.jpg")
    telemetry = _Telemetry()
    widget = SimpleNamespace(
        _config={"behavior_analytics": {"enabled": False}},
        _behavior_telemetry=None,
        filename=filename,
    )

    def ensure_telemetry(project_root):
        assert project_root == osp.dirname(filename)
        widget._behavior_telemetry = telemetry

    widget._ensure_behavior_telemetry = ensure_telemetry
    monkeypatch.setattr(
        label_widget_module, "save_config", lambda _config: None
    )

    label_widget_module.LabelingWidget._set_behavior_analytics_enabled(
        widget, True
    )

    assert widget._config["behavior_analytics"]["enabled"] is True
    assert telemetry.entered_images == [filename]

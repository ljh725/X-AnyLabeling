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


class _SelectionTelemetry:
    """Capture stable Shape identities sent by selection telemetry."""

    def __init__(self):
        """Create an empty selection-event capture."""
        self.selected = []

    def select_shape(self, shape_id, **context):
        """Record one selected Shape identity and its safe context."""
        self.selected.append((shape_id, context))


class _Action:
    """Minimal QAction stand-in for selection-state updates."""

    def setEnabled(self, _enabled):
        """Accept an enabled-state update."""


class _LabelList:
    """Minimal label-list stand-in for selection mirroring."""

    def clearSelection(self):
        """Accept selection clearing."""

    def find_item_by_shape(self, _shape):
        """Return no matching visual item for the test Shape."""
        return None


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


def test_shape_selection_event_uses_persistent_id_not_index_or_address():
    """Cross-lifecycle selection events use the JSON-backed Shape identity."""
    persistent_id = "persistent-shape-identity"
    shape = SimpleNamespace(
        shape_type="point",
        selected=True,
        xanylabeling_shape_id=persistent_id,
    )
    telemetry = _SelectionTelemetry()
    action = _Action()
    widget = SimpleNamespace(
        label_list=_LabelList(),
        actions=SimpleNamespace(
            delete=action,
            duplicate=action,
            copy=action,
            edit=action,
            copy_coordinates=action,
            union_selection=action,
        ),
        canvas=SimpleNamespace(
            current=None,
            shapes=[shape],
            pose_config=SimpleNamespace(
                enabled=False,
                pose_click_to_focus=False,
            ),
        ),
        _behavior_telemetry=telemetry,
        _virtual_review_active=True,
        set_text_editing=lambda _enabled: None,
        update_attributes=lambda _index: None,
        hide_attributes_panel=lambda: None,
    )

    label_widget_module.LabelingWidget.shape_selection_changed(widget, [shape])

    assert telemetry.selected[0][0] == persistent_id
    assert telemetry.selected[0][0] != "0"
    assert telemetry.selected[0][0] != str(id(shape))

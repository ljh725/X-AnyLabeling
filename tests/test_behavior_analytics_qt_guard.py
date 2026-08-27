"""Offscreen regression coverage for programmatic label-list updates."""

import json

import pytest

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from PyQt6 import QtCore  # noqa: E402

from anylabeling.views.labeling.widgets.label_list_widget import (  # noqa: E402
    LabelListWidget,
    LabelListWidgetItem,
)


def test_programmatic_check_state_guard_is_scoped(qapp):
    """A guarded check-state update is observable as internal only."""
    widget = LabelListWidget()
    widget.show()
    qapp.processEvents()
    item = LabelListWidgetItem("shape")
    widget.add_iem(item)
    observed = []

    def on_changed(_item):
        observed.append(widget.is_programmatic_update)

    widget.item_changed.connect(on_changed)
    widget.set_item_check_state(item, QtCore.Qt.CheckState.Unchecked)
    assert observed == [True]
    assert widget.is_programmatic_update is False
    widget.deleteLater()


def test_real_attribute_action_is_one_event_with_identity(tmp_path):
    """The telemetry contract carries one attributed edit, not a storm."""
    from anylabeling.services.behavior_analytics import (
        BehaviorTelemetry,
        LocalEventRecorder,
    )

    recorder = LocalEventRecorder(tmp_path / "events", enabled=True)
    telemetry = BehaviorTelemetry(str(tmp_path), recorder)
    telemetry.start_project()
    telemetry.enter_image(str(tmp_path / "image.jpg"))
    telemetry.select_shape("shape-1")
    telemetry.action(
        "attribute_edit",
        input_source="mouse",
        result="success",
        payload={"attribute_category": "visibility"},
        net_change_summary={
            "attribute_category": "visibility",
            "before_bool": True,
            "after_bool": False,
            "change_kind": "hidden",
        },
    )
    telemetry.shutdown()
    path = next((tmp_path / "events" / "events").glob("events-*.jsonl"))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    edits = [
        row
        for row in rows
        if row.get("event_type") == "action_span"
        and row.get("payload", {}).get("action") == "attribute_edit"
    ]
    assert len(edits) == 1
    assert edits[0]["shape_id"] == "shape-1"
    assert edits[0]["object_episode_id"]
    assert edits[0]["net_change_summary"]["change_kind"] == "hidden"

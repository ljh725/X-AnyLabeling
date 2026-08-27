"""Parameterized one-operation/one-action contract tests."""

import pytest

from anylabeling.services.behavior_analytics import (
    ACTION_CATALOG,
    ActionCatalogEntry,
    EventEnvelope,
)


def _event_for(entry: ActionCatalogEntry) -> EventEnvelope:
    """Build one privacy-safe v3 terminal event for a catalog row."""
    context = {
        name: f"{entry.catalog_id}-{name}"
        for name in entry.context
        if name not in {"action_id", "result", "input_source", "net_change"}
    }
    payload = {
        "action": entry.action,
        "context": context,
    }
    if "net_change" in entry.context:
        payload["net_change"] = {"changed": True}
    if "participating_features" in entry.context:
        payload["participating_features"] = ["feature_bucket"]
    result = entry.allowed_terminals[0]
    phase = {
        "success": "committed",
        "cancelled": "cancelled",
        "no_change": "no_change",
        "interrupted": "interrupted",
    }.get(result, "interrupted")
    return EventEnvelope.from_mapping(
        {
            "schema_version": 3,
            "event_id": f"contract-{entry.catalog_id}",
            "event_type": "action_span",
            "occurred_at_utc": "2026-08-22T01:00:00.000Z",
            "local_date": "2026-08-22",
            "timezone_offset": "+08:00",
            "monotonic_ms": 100,
            "app_session_id": "app-contract",
            "project_session_id": "project-contract",
            "project_id": "project-anon",
            "feature_state_version": 1,
            "input_source": "system",
            "result": result,
            "sequence_no": 1,
            "image_id": "image-anon",
            "shape_id": "shape-anon",
            "object_episode_id": "episode-anon",
            "action_id": f"action-{entry.catalog_id}",
            "action_phase": phase,
            "action_type": entry.action,
            "started_monotonic_ms": 10,
            "ended_monotonic_ms": 100,
            "context": context,
            "payload": payload,
            "interruption_reason": (
                "termination_boundary"
                if "interruption_reason" in entry.context
                else None
            ),
        }
    )


@pytest.mark.parametrize(
    "entry",
    ACTION_CATALOG,
    ids=[entry.catalog_id for entry in ACTION_CATALOG],
)
def test_one_catalog_operation_emits_one_complete_terminal_action(
    entry: ActionCatalogEntry,
):
    """Each catalog row has one countable terminal action and full context."""
    event = _event_for(entry)
    assert event.action_id == f"action-{entry.catalog_id}"
    assert event.action_type == entry.action
    assert event.action_phase != "started"
    assert event.result in entry.allowed_terminals
    assert event.started_monotonic_ms is not None
    assert event.ended_monotonic_ms is not None
    assert event.ended_monotonic_ms >= event.started_monotonic_ms
    available = set(event.context or {})
    available.update({"action_id", "result", "input_source"})
    if event.payload and "net_change" in event.payload:
        available.add("net_change")
    if "interruption_reason" in entry.context:
        available.add("interruption_reason")
    assert set(entry.context) <= available

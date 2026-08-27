"""Tests for the versioned machine-readable action catalog."""

import pytest

from anylabeling.services.behavior_analytics import (
    ACTION_CATALOG,
    ACTION_CATALOG_VERSION,
    ActionCatalogEntry,
    action_catalog_to_dict,
    validate_action_catalog,
)


def test_action_catalog_is_versioned_and_serializable():
    """Every documented row has the required replay contract fields."""
    validate_action_catalog()
    document = action_catalog_to_dict()
    assert document["catalog_version"] == ACTION_CATALOG_VERSION
    assert len(document["entries"]) == len(ACTION_CATALOG)
    for row in document["entries"]:
        assert set(row) == {
            "catalog_id",
            "workflow",
            "entry",
            "action",
            "start_conditions",
            "allowed_terminals",
            "context",
            "expected_event_count",
            "replay_case",
        }
        assert row["expected_event_count"] == 1
        assert "action_id" in row["context"]
        assert "result" in row["context"]


def test_action_catalog_rejects_duplicate_ids_and_invalid_terminals():
    """The machine contract prevents ambiguous replay ownership."""
    row = ACTION_CATALOG[0]
    with pytest.raises(ValueError, match="duplicate catalog_id"):
        validate_action_catalog((row, row))
    invalid = ActionCatalogEntry(
        "invalid",
        "workflow",
        "entry",
        "action",
        ("started",),
        ("unknown",),
        ("action_id", "result"),
        1,
        "invalid-case",
    )
    with pytest.raises(ValueError, match="invalid terminal"):
        validate_action_catalog((invalid,))


def test_action_catalog_covers_required_workflow_families():
    """The first catalog release covers every requested workflow family."""
    workflows = {entry.workflow for entry in ACTION_CATALOG}
    assert {
        "creation",
        "geometry_edit",
        "label_attribute",
        "ai_create",
        "ai_correction",
        "inspector",
        "quality",
        "navigation",
        "persistence",
        "lifecycle",
        "history",
    } <= workflows
    actions = {entry.action for entry in ACTION_CATALOG}
    assert {"undo", "redo", "session_interrupted"} <= actions


def test_documented_matrix_actions_exist_in_machine_catalog():
    """The human matrix cannot introduce an undocumented semantic action."""
    import re
    from pathlib import Path

    document = Path("docs/behavior_analytics_coverage_matrix.md").read_text(
        encoding="utf-8"
    )
    assert "动作目录版本：`1.0`" in document
    actions = {entry.action for entry in ACTION_CATALOG}
    rows = [line for line in document.splitlines() if line.startswith("|")]
    documented = set()
    for row in rows[2:]:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) < 3:
            continue
        documented.update(re.findall(r"`([^`]+)`", cells[2]))
    assert documented <= actions

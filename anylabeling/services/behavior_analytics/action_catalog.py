"""Versioned machine-readable catalog of supported semantic user actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

ACTION_CATALOG_VERSION = "1.0"
_ALLOWED_TERMINALS = frozenset(
    {"success", "cancelled", "failed", "no_change", "interrupted"}
)
_REQUIRED_CONTEXT = frozenset({"action_id", "result"})


@dataclass(frozen=True)
class ActionCatalogEntry:
    """Contract row connecting a user workflow to one semantic action.

    Args:
        catalog_id: Stable row ID used by replay cases and drift checks.
        workflow: Human-neutral workflow category.
        entry: Stable application entry point name.
        action: Semantic action name emitted to analytics.
        start_conditions: Facts required before the action may begin.
        allowed_terminals: Terminal results permitted for the action.
        context: Privacy-safe context facts required or optionally emitted.
        expected_event_count: Expected count of final countable action events.
        replay_case: Stable controlled-replay case identifier.
    """

    catalog_id: str
    workflow: str
    entry: str
    action: str
    start_conditions: tuple[str, ...]
    allowed_terminals: tuple[str, ...]
    context: tuple[str, ...]
    expected_event_count: int
    replay_case: str

    @property
    def shape_types(self) -> tuple[str, ...]:
        """Return supported shape coverage for the catalog row.

        The original serialized catalog is kept wire-compatible; callers can
        use this property for the expanded coverage matrix without changing
        old manifests.
        """
        return (
            "polygon",
            "rectangle",
            "rotation",
            "quadrilateral",
            "point",
            "line",
            "circle",
            "linestrip",
            "cuboid",
        )

    @property
    def action_mode(self) -> str:
        """Return the recording mode implied by the catalog contract."""
        if "burst" in self.action or self.action in {"zoom", "pan"}:
            return "burst"
        if self.action in {"shape_created", "shape_deleted", "shape_restored"}:
            return "instant"
        return "span"

    @property
    def required_target(self) -> str | None:
        """Return the stable target category required by this action."""
        if self.action in {
            "geometry_adjust",
            "rectangle_adjust",
            "keypoint_adjust",
        }:
            return "move_or_vertex_or_edge"
        if self.action in {"label_edit", "attribute_edit"}:
            return "label_or_attribute"
        return None

    @property
    def applicability(self) -> dict[str, bool]:
        """Return explicit shape applicability instead of implicit gaps."""
        applicable = set(self.shape_types)
        if self.action in {"rectangle_adjust"}:
            applicable = {"rectangle"}
        if self.action in {"keypoint_adjust"}:
            applicable = {
                "point",
                "polygon",
                "rotation",
                "quadrilateral",
                "linestrip",
                "cuboid",
            }
        return {
            shape_type: shape_type in applicable
            for shape_type in self.shape_types
        }

    def validate(self) -> None:
        """Validate one catalog row against the machine contract."""
        for field_name in (
            "catalog_id",
            "workflow",
            "entry",
            "action",
            "replay_case",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not self.start_conditions:
            raise ValueError(f"{self.catalog_id}: start_conditions is empty")
        if not self.allowed_terminals:
            raise ValueError(f"{self.catalog_id}: allowed_terminals is empty")
        invalid = set(self.allowed_terminals) - _ALLOWED_TERMINALS
        if invalid:
            raise ValueError(
                f"{self.catalog_id}: invalid terminal(s): {sorted(invalid)}"
            )
        if self.expected_event_count != 1:
            raise ValueError(
                f"{self.catalog_id}: expected_event_count must be one"
            )
        missing = _REQUIRED_CONTEXT - set(self.context)
        if missing:
            raise ValueError(
                f"{self.catalog_id}: context missing {sorted(missing)}"
            )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible catalog row."""
        return asdict(self)


ACTION_CATALOG: tuple[ActionCatalogEntry, ...] = (
    ActionCatalogEntry(
        "geometry-body-drag",
        "geometry_edit",
        "canvas.drag",
        "geometry_adjust",
        ("object_selected", "drag_started"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "shape_type", "edit_target"),
        1,
        "geometry-body-drag",
    ),
    ActionCatalogEntry(
        "rectangle-edge-drag",
        "geometry_edit",
        "canvas.edge_drag",
        "rectangle_adjust",
        ("rectangle_selected", "edge_handle_pressed"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "shape_type", "edge", "size_bucket"),
        1,
        "rectangle-edge-drag",
    ),
    ActionCatalogEntry(
        "rectangle-corner-drag",
        "geometry_edit",
        "canvas.corner_drag",
        "rectangle_adjust",
        ("rectangle_selected", "corner_handle_pressed"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "shape_type", "corner", "size_bucket"),
        1,
        "rectangle-corner-drag",
    ),
    ActionCatalogEntry(
        "keypoint-drag",
        "geometry_edit",
        "canvas.vertex_drag",
        "keypoint_adjust",
        ("keypoint_selected", "vertex_pressed"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "point_count_bucket"),
        1,
        "keypoint-drag",
    ),
    ActionCatalogEntry(
        "keyboard-nudge",
        "geometry_edit",
        "labeling.keyboard",
        "keyboard_nudge",
        ("object_selected", "arrow_key_pressed"),
        ("success", "no_change", "interrupted"),
        ("action_id", "result", "input_source", "net_change"),
        1,
        "keyboard-nudge",
    ),
    ActionCatalogEntry(
        "wheel-zoom",
        "navigation",
        "canvas.wheel",
        "zoom",
        ("canvas_ready", "wheel_input"),
        ("success", "interrupted"),
        ("action_id", "result", "input_count"),
        1,
        "wheel-zoom",
    ),
    ActionCatalogEntry(
        "view-pan",
        "navigation",
        "canvas.pan",
        "pan",
        ("canvas_ready", "pan_input"),
        ("success", "interrupted"),
        ("action_id", "result", "input_count"),
        1,
        "view-pan",
    ),
    ActionCatalogEntry(
        "label-edit",
        "label_attribute",
        "label_editor.commit",
        "label_edit",
        ("object_selected", "label_commit"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "label_key"),
        1,
        "label-edit",
    ),
    ActionCatalogEntry(
        "attribute-edit",
        "label_attribute",
        "attribute_editor.commit",
        "attribute_edit",
        ("object_selected", "attribute_commit"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "attribute_category"),
        1,
        "attribute-edit",
    ),
    ActionCatalogEntry(
        "creation-intent",
        "creation",
        "creation_workflow.start",
        "creation_intent",
        ("creation_command",),
        ("success", "cancelled", "interrupted"),
        ("action_id", "result", "creation_workflow_id", "initial_source"),
        1,
        "creation-intent",
    ),
    ActionCatalogEntry(
        "creation-draw",
        "creation",
        "canvas.create_draw",
        "create_draw",
        ("creation_started", "draw_started"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "creation_workflow_id", "shape_type"),
        1,
        "creation-draw",
    ),
    ActionCatalogEntry(
        "creation-label",
        "creation",
        "label_dialog.create_label",
        "create_label",
        ("creation_started", "label_editor_open"),
        ("success", "cancelled", "failed", "interrupted"),
        ("action_id", "result", "creation_workflow_id", "shape_type"),
        1,
        "creation-label",
    ),
    ActionCatalogEntry(
        "rectangle-wheel-scale",
        "geometry_edit",
        "canvas.rectangle_wheel_body",
        "rectangle_adjust",
        ("rectangle_selected", "wheel_input"),
        ("success", "no_change", "interrupted"),
        ("action_id", "result", "shape_type", "edit_target", "input_count"),
        1,
        "rectangle-wheel-scale",
    ),
    ActionCatalogEntry(
        "rectangle-wheel-edge",
        "geometry_edit",
        "canvas.rectangle_wheel_edge",
        "rectangle_adjust",
        ("rectangle_selected", "edge_hit", "wheel_input"),
        ("success", "no_change", "interrupted"),
        ("action_id", "result", "shape_type", "edit_target", "input_count"),
        1,
        "rectangle-wheel-edge",
    ),
    ActionCatalogEntry(
        "shape-create",
        "creation",
        "shape_creation_adapter",
        "shape_created",
        ("creation_started",),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "initial_source", "shape_type"),
        1,
        "shape-create",
    ),
    ActionCatalogEntry(
        "shape-delete",
        "lifecycle",
        "delete_handler",
        "shape_deleted",
        ("object_selected", "delete_requested"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "object_identity"),
        1,
        "shape-delete",
    ),
    ActionCatalogEntry(
        "shape-restore",
        "lifecycle",
        "undo_redo_handler",
        "shape_restored",
        ("deleted_object_exists", "restore_requested"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "object_identity", "undo_of_action_id"),
        1,
        "shape-restore",
    ),
    ActionCatalogEntry(
        "labels-save",
        "persistence",
        "save_entry",
        "labels_saved",
        ("project_open", "save_requested"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "saved_after_change"),
        1,
        "labels-save",
    ),
    ActionCatalogEntry(
        "manual-shape-create",
        "creation",
        "manual_shape_tool.commit",
        "shape_created",
        ("creation_tool_active", "creation_commit"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "initial_source", "shape_type"),
        1,
        "manual-shape-create",
    ),
    ActionCatalogEntry(
        "import-shape-create",
        "creation",
        "annotation_import",
        "shape_created",
        ("import_requested", "shape_materialized"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "initial_source", "shape_type"),
        1,
        "import-shape-create",
    ),
    ActionCatalogEntry(
        "ai-shape-create",
        "ai_create",
        "ai_model.create",
        "shape_created",
        ("ai_result_available", "shape_acceptance"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "initial_source", "shape_type"),
        1,
        "ai-shape-create",
    ),
    ActionCatalogEntry(
        "ai-shape-correct",
        "ai_correction",
        "ai_model.correct",
        "ai_correct",
        ("ai_shape_selected", "correction_started"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "initial_source", "participating_features"),
        1,
        "ai-shape-correct",
    ),
    ActionCatalogEntry(
        "inspector-review",
        "inspector",
        "inspector.issue_review",
        "inspector_review",
        ("inspector_open", "issue_selected"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "issue_rule", "shape_type"),
        1,
        "inspector-review",
    ),
    ActionCatalogEntry(
        "quality-review",
        "quality",
        "quality_review_queue",
        "quality_review",
        ("quality_report_loaded", "issue_selected"),
        ("success", "cancelled", "no_change", "interrupted"),
        ("action_id", "result", "quality_rule", "shape_type"),
        1,
        "quality-review",
    ),
    ActionCatalogEntry(
        "image-navigation",
        "navigation",
        "image_list.navigate",
        "image_navigate",
        ("project_open", "navigation_requested"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "navigation_direction"),
        1,
        "image-navigation",
    ),
    ActionCatalogEntry(
        "undo-action",
        "history",
        "undo_redo_handler.undo",
        "undo",
        ("prior_action_exists", "undo_requested"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "undo_of_action_id"),
        1,
        "undo-action",
    ),
    ActionCatalogEntry(
        "redo-action",
        "history",
        "undo_redo_handler.redo",
        "redo",
        ("undone_action_exists", "redo_requested"),
        ("success", "failed", "interrupted"),
        ("action_id", "result", "redo_of_action_id"),
        1,
        "redo-action",
    ),
    ActionCatalogEntry(
        "abnormal-exit",
        "lifecycle",
        "application.close_or_crash_boundary",
        "session_interrupted",
        ("application_session_active", "termination_boundary"),
        ("interrupted", "failed"),
        ("action_id", "result", "interruption_reason"),
        1,
        "abnormal-exit",
    ),
)


def validate_action_catalog(
    entries: Iterable[ActionCatalogEntry] = ACTION_CATALOG,
) -> None:
    """Validate catalog rows and reject duplicate stable identifiers."""
    rows = tuple(entries)
    ids = [entry.catalog_id for entry in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("action catalog contains duplicate catalog_id")
    replay_cases = [entry.replay_case for entry in rows]
    if len(replay_cases) != len(set(replay_cases)):
        raise ValueError("action catalog contains duplicate replay_case")
    for entry in rows:
        entry.validate()


def action_catalog_to_dict(
    entries: Iterable[ActionCatalogEntry] = ACTION_CATALOG,
) -> dict[str, object]:
    """Return the versioned catalog in a stable serializable envelope."""
    validate_action_catalog(entries)
    return {
        "catalog_version": ACTION_CATALOG_VERSION,
        "entries": [entry.to_dict() for entry in entries],
    }


validate_action_catalog()

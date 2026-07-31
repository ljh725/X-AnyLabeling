"""Configuration codec and legacy migration for rectangle-size rules."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, Tuple

from .evaluator import RectangleSizeEvaluator
from .models import RectangleSizeRule

RULES_CONFIG_KEY = "rectangle_size_rules"
DEFAULT_LEGACY_PERSON_THRESHOLD_PX = 36.0
_RULE_KEYS = frozenset(
    {
        "label",
        "min_width_px",
        "min_height_px",
        "trigger_mode",
        "enabled",
    }
)


class RectangleSizeConfigError(ValueError):
    """Raised when persisted rectangle-size rule data is invalid.

    Attributes:
        code: Stable machine-readable error category for UI localization.
        row_index: Optional zero-based rule row associated with the error.
        field_name: Optional persisted field associated with the error.
        details: Structured values needed to format localized feedback.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_config",
        row_index: int | None = None,
        field_name: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize a descriptive error with stable localization metadata.

        Args:
            message: Developer-facing fallback message.
            code: Machine-readable error category.
            row_index: Optional zero-based rule row.
            field_name: Optional persisted field name.
            details: Optional structured formatting values.
        """
        super().__init__(message)
        self.code = code
        self.row_index = row_index
        self.field_name = field_name
        self.details = dict(details or {})


def migrate_legacy_person_rule(
    threshold_px: object = DEFAULT_LEGACY_PERSON_THRESHOLD_PX,
) -> RectangleSizeRule:
    """Convert the legacy max-edge threshold into a two-dimension rule.

    ``trigger_mode="all"`` preserves the legacy requirement that both
    dimensions must be small. The new inclusive-boundary policy intentionally
    changes equality from accepted to abnormal.

    Args:
        threshold_px: Legacy person max-edge threshold.

    Returns:
        A normalized enabled person rule.

    Raises:
        RectangleSizeConfigError: If the threshold is not positive and finite.
    """
    threshold = _parse_threshold(
        threshold_px,
        row_index=None,
        field_name="legacy_person_threshold_px",
        allow_empty=False,
    )
    return RectangleSizeRule(
        label="person",
        min_width_px=threshold,
        min_height_px=threshold,
        trigger_mode="all",
        enabled=True,
    )


def load_rectangle_size_rules(
    config: Mapping[str, Any],
    *,
    legacy_person_threshold_px: object = (DEFAULT_LEGACY_PERSON_THRESHOLD_PX),
) -> Tuple[RectangleSizeRule, ...]:
    """Load rules from an application config with missing-key migration.

    Args:
        config: Full merged or user configuration mapping.
        legacy_person_threshold_px: Threshold used only when the new rule key
            is absent.

    Returns:
        Normalized immutable rules. An explicit empty list remains empty.

    Raises:
        RectangleSizeConfigError: If the config or rule block is invalid.
    """
    if not isinstance(config, Mapping):
        raise RectangleSizeConfigError(
            "Rectangle-size configuration root must be a mapping",
            code="config_root_not_mapping",
        )
    if RULES_CONFIG_KEY not in config:
        return (migrate_legacy_person_rule(legacy_person_threshold_px),)
    return parse_rectangle_size_rules(config[RULES_CONFIG_KEY])


def parse_rectangle_size_rules(
    raw_rules: object,
) -> Tuple[RectangleSizeRule, ...]:
    """Parse persisted rule rows into validated immutable models.

    Empty strings and YAML null values become ``None`` thresholds. Duplicate
    labels are rejected even when a row is disabled so one label always maps
    to one editable configuration row.

    Args:
        raw_rules: YAML-compatible list of rule mappings.

    Returns:
        Normalized immutable rule tuple.

    Raises:
        RectangleSizeConfigError: If any row or field is invalid.
    """
    if not isinstance(raw_rules, list):
        raise RectangleSizeConfigError(
            f"{RULES_CONFIG_KEY} must be a list",
            code="rules_not_list",
        )

    rules = []
    seen_labels = set()
    for row_index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, Mapping):
            raise _row_error(
                row_index,
                "rule must be a mapping",
                code="rule_not_mapping",
            )
        unknown_keys = set(raw_rule) - _RULE_KEYS
        if unknown_keys:
            names = ", ".join(sorted(str(key) for key in unknown_keys))
            raise _row_error(
                row_index,
                f"unexpected fields: {names}",
                code="unexpected_fields",
                details={"fields": names},
            )

        label = _parse_label(raw_rule.get("label"), row_index)
        if label in seen_labels:
            raise _row_error(
                row_index,
                f"duplicate label {label!r}",
                code="duplicate_label",
                field_name="label",
                details={"label": label},
            )
        seen_labels.add(label)

        enabled = raw_rule.get("enabled", True)
        if not isinstance(enabled, bool):
            raise _row_error(
                row_index,
                "enabled must be a boolean",
                code="enabled_not_boolean",
                field_name="enabled",
            )

        trigger_mode = raw_rule.get("trigger_mode", "any")
        if trigger_mode not in ("any", "all"):
            raise _row_error(
                row_index,
                "trigger_mode must be 'any' or 'all'",
                code="invalid_trigger_mode",
                field_name="trigger_mode",
            )

        min_width_px = _parse_threshold(
            raw_rule.get("min_width_px"),
            row_index=row_index,
            field_name="min_width_px",
            allow_empty=True,
        )
        min_height_px = _parse_threshold(
            raw_rule.get("min_height_px"),
            row_index=row_index,
            field_name="min_height_px",
            allow_empty=True,
        )
        if enabled and min_width_px is None and min_height_px is None:
            raise _row_error(
                row_index,
                "enabled rule needs at least one W/H threshold",
                code="missing_threshold",
            )

        rules.append(
            RectangleSizeRule(
                label=label,
                min_width_px=min_width_px,
                min_height_px=min_height_px,
                trigger_mode=trigger_mode,
                enabled=enabled,
            )
        )

    normalized = tuple(rules)
    try:
        RectangleSizeEvaluator(normalized)
    except ValueError as exc:
        raise RectangleSizeConfigError(
            str(exc),
            code="invalid_rule_set",
        ) from exc
    return normalized


def serialize_rectangle_size_rules(
    rules: Iterable[RectangleSizeRule],
) -> List[Dict[str, Any]]:
    """Serialize rules into validated deterministic YAML-compatible rows.

    Args:
        rules: Rule models to validate and serialize.

    Returns:
        List of dictionaries suitable for ``yaml.safe_dump``.

    Raises:
        RectangleSizeConfigError: If any model contains invalid data.
    """
    raw_rows = [
        {
            "label": rule.label,
            "min_width_px": rule.min_width_px,
            "min_height_px": rule.min_height_px,
            "trigger_mode": rule.trigger_mode,
            "enabled": rule.enabled,
        }
        for rule in rules
    ]
    normalized = parse_rectangle_size_rules(raw_rows)
    return [
        {
            "label": rule.label,
            "min_width_px": rule.min_width_px,
            "min_height_px": rule.min_height_px,
            "trigger_mode": rule.trigger_mode,
            "enabled": rule.enabled,
        }
        for rule in normalized
    ]


def _parse_label(value: object, row_index: int) -> str:
    """Return one normalized non-empty exact-match label."""
    if not isinstance(value, str) or not value.strip():
        raise _row_error(
            row_index,
            "label must be a non-empty string",
            code="empty_label",
            field_name="label",
        )
    return value.strip()


def _parse_threshold(
    value: object,
    *,
    row_index: int | None,
    field_name: str,
    allow_empty: bool,
) -> float | None:
    """Parse one optional positive finite pixel threshold."""
    if allow_empty and (
        value is None or (isinstance(value, str) and not value.strip())
    ):
        return None
    if isinstance(value, bool):
        raise _threshold_error(row_index, field_name)
    try:
        threshold = float(value)
    except (TypeError, ValueError) as exc:
        raise _threshold_error(row_index, field_name) from exc
    if not math.isfinite(threshold) or threshold <= 0:
        raise _threshold_error(row_index, field_name)
    return threshold


def _threshold_error(
    row_index: int | None,
    field_name: str,
) -> RectangleSizeConfigError:
    """Build a consistent threshold validation error."""
    message = f"{field_name} must be a positive finite number"
    if row_index is None:
        return RectangleSizeConfigError(
            message,
            code="invalid_threshold",
            field_name=field_name,
        )
    return _row_error(
        row_index,
        message,
        code="invalid_threshold",
        field_name=field_name,
    )


def _row_error(
    row_index: int,
    message: str,
    *,
    code: str,
    field_name: str | None = None,
    details: Mapping[str, object] | None = None,
) -> RectangleSizeConfigError:
    """Build a one-based fallback message plus structured row metadata."""
    return RectangleSizeConfigError(
        f"Rule row {row_index + 1}: {message}",
        code=code,
        row_index=row_index,
        field_name=field_name,
        details=details,
    )


__all__ = [
    "DEFAULT_LEGACY_PERSON_THRESHOLD_PX",
    "RULES_CONFIG_KEY",
    "RectangleSizeConfigError",
    "load_rectangle_size_rules",
    "migrate_legacy_person_rule",
    "parse_rectangle_size_rules",
    "serialize_rectangle_size_rules",
]

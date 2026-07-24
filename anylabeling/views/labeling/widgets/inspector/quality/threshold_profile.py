"""
Threshold profile loader and validator.

Loads a machine-readable threshold YAML and validates:
- required top-level fields (profile_id, schema_version, rules)
- per-rule required fields (rule_id, rule_name, primary_metric, direction)
- direction enum membership
- error_requires format
- two_sided rules carry a dict-shaped warning/error threshold
"""

from __future__ import annotations

import logging
import os.path as osp
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_DIRECTIONS = {
    "higher_is_worse",
    "lower_is_worse",
    "two_sided",
    "higher_abs_is_worse",
}

VALID_SEVERITIES = {"error", "warning", "info"}

REQUIRED_RULE_FIELDS = (
    "rule_id",
    "rule_name",
    "enabled",
    "default_severity",
    "primary_metric",
    "direction",
)

# this file lives at .../anylabeling/views/labeling/widgets/inspector/quality/
# Walk up until we find the repo root (the dir containing pyproject.toml),
# then resolve anylabeling/configs/quality/l1_l2_threshold_profile_v0.yaml.
_QUALITY_PKG_DIR = osp.dirname(osp.abspath(__file__))


def _find_repo_root() -> str:
    d = _QUALITY_PKG_DIR
    for _ in range(10):
        if osp.isfile(osp.join(d, "pyproject.toml")):
            return d
        parent = osp.dirname(d)
        if parent == d:
            break
        d = parent
    # fall back to 6 parents up (matches the known layout)
    d = _QUALITY_PKG_DIR
    for _ in range(6):
        d = osp.dirname(d)
    return d


_REPO_ROOT = _find_repo_root()
DEFAULT_PROFILE_PATH = osp.join(
    _REPO_ROOT,
    "anylabeling",
    "configs",
    "quality",
    "l1_l2_threshold_profile_v0.yaml",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RuleThreshold:
    """Threshold definition for a single rule."""

    rule_id: str
    rule_name: str
    enabled: bool
    default_severity: str
    primary_metric: Optional[str]
    direction: str
    warning_threshold: Optional[Any] = None
    error_threshold: Optional[Any] = None
    error_requires: List[str] = field(default_factory=list)

    @property
    def is_two_sided(self) -> bool:
        return self.direction == "two_sided"


@dataclass
class ThresholdProfile:
    """Validated threshold profile."""

    profile_id: str
    schema_version: str
    description: str = ""
    rules: List[RuleThreshold] = field(default_factory=list)
    # auxiliary config blocks (face/head matching, body bands, ...)
    config: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def get_rule(self, rule_id: str) -> Optional[RuleThreshold]:
        """Return the RuleThreshold for ``rule_id`` or None."""
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        return None

    def get_rule_by_name(self, rule_name: str) -> Optional[RuleThreshold]:
        """Return the RuleThreshold for ``rule_name`` or None."""
        for r in self.rules:
            if r.rule_name == rule_name:
                return r
        return None

    def enabled_rules(self) -> List[RuleThreshold]:
        """Return only enabled rules, preserving order."""
        return [r for r in self.rules if r.enabled]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ThresholdProfileError(ValueError):
    """Raised when a threshold profile fails validation."""


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_threshold_profile(
    path: Optional[str] = None,
) -> ThresholdProfile:
    """Load and validate a threshold YAML profile.

    Args:
        path: Path to the YAML file. If None, uses the bundled v0 profile.

    Returns:
        A validated ``ThresholdProfile``.

    Raises:
        ThresholdProfileError: If the file is missing, malformed, or
            fails schema validation.
    """
    yaml_path = path or DEFAULT_PROFILE_PATH
    if not osp.isfile(yaml_path):
        raise ThresholdProfileError(
            f"Threshold profile not found: {yaml_path}"
        )

    try:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ThresholdProfileError(
            f"Failed to parse YAML {yaml_path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ThresholdProfileError(
            f"Profile root must be a mapping, got {type(data).__name__}"
        )

    return _validate(data, yaml_path)


def _validate(data: Dict[str, Any], source_path: str) -> ThresholdProfile:
    """Validate a parsed YAML mapping into a ThresholdProfile."""
    profile_id = data.get("profile_id")
    schema_version = data.get("schema_version")
    if not profile_id:
        raise ThresholdProfileError("Missing required field: profile_id")
    if not schema_version:
        raise ThresholdProfileError("Missing required field: schema_version")

    rules_raw = data.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ThresholdProfileError("Field 'rules' must be a non-empty list")

    seen_ids = set()
    seen_names = set()
    rules: List[RuleThreshold] = []
    for idx, rule_raw in enumerate(rules_raw):
        if not isinstance(rule_raw, dict):
            raise ThresholdProfileError(f"rules[{idx}] must be a mapping")
        rt = _validate_rule(rule_raw, idx)
        if rt.rule_id in seen_ids:
            raise ThresholdProfileError(f"Duplicate rule_id: {rt.rule_id}")
        if rt.rule_name in seen_names:
            raise ThresholdProfileError(f"Duplicate rule_name: {rt.rule_name}")
        seen_ids.add(rt.rule_id)
        seen_names.add(rt.rule_name)
        rules.append(rt)

    # auxiliary config blocks (kept as raw dict; validated by consumers)
    config = {
        k: v
        for k, v in data.items()
        if k
        not in {
            "profile_id",
            "schema_version",
            "description",
            "rules",
        }
    }

    return ThresholdProfile(
        profile_id=profile_id,
        schema_version=schema_version,
        description=data.get("description", "") or "",
        rules=rules,
        config=config,
        raw=data,
    )


def _validate_rule(rule_raw: Dict[str, Any], idx: int) -> RuleThreshold:
    """Validate one rule dict."""
    loc = f"rules[{idx}]"
    for key in REQUIRED_RULE_FIELDS:
        if key not in rule_raw:
            raise ThresholdProfileError(
                f"{loc} ({rule_raw.get('rule_id', '?')}): "
                f"missing field '{key}'"
            )

    rule_id = rule_raw["rule_id"]
    rule_name = rule_raw["rule_name"]
    if not isinstance(rule_id, str) or not rule_id:
        raise ThresholdProfileError(f"{loc}: rule_id must be non-empty str")
    if not isinstance(rule_name, str) or not rule_name:
        raise ThresholdProfileError(
            f"{loc} ({rule_id}): rule_name must be non-empty str"
        )

    severity = rule_raw["default_severity"]
    if severity not in VALID_SEVERITIES:
        raise ThresholdProfileError(
            f"{loc} ({rule_id}): invalid default_severity "
            f"{severity!r}; expected one of {sorted(VALID_SEVERITIES)}"
        )

    direction = rule_raw["direction"]
    if direction not in VALID_DIRECTIONS:
        raise ThresholdProfileError(
            f"{loc} ({rule_id}): invalid direction {direction!r}; "
            f"expected one of {sorted(VALID_DIRECTIONS)}"
        )

    primary_metric = rule_raw["primary_metric"]
    if primary_metric is not None and not isinstance(primary_metric, str):
        raise ThresholdProfileError(
            f"{loc} ({rule_id}): primary_metric must be str or null"
        )

    warning_threshold = rule_raw.get("warning_threshold")
    error_threshold = rule_raw.get("error_threshold")
    _validate_threshold_shape(
        warning_threshold, direction, rule_id, "warning_threshold"
    )
    _validate_threshold_shape(
        error_threshold, direction, rule_id, "error_threshold"
    )

    error_requires = rule_raw.get("error_requires") or []
    if not isinstance(error_requires, list):
        raise ThresholdProfileError(
            f"{loc} ({rule_id}): error_requires must be a list"
        )
    for item in error_requires:
        if not isinstance(item, str):
            raise ThresholdProfileError(
                f"{loc} ({rule_id}): error_requires items must be str"
            )

    return RuleThreshold(
        rule_id=rule_id,
        rule_name=rule_name,
        enabled=bool(rule_raw["enabled"]),
        default_severity=severity,
        primary_metric=primary_metric,
        direction=direction,
        warning_threshold=warning_threshold,
        error_threshold=error_threshold,
        error_requires=list(error_requires),
    )


def _validate_threshold_shape(
    threshold: Any,
    direction: str,
    rule_id: str,
    field_name: str,
) -> None:
    """Validate that the threshold shape matches the direction.

    two_sided thresholds must be ``{min, max}`` dicts (or null).
    Other directions accept scalars or dicts.
    """
    if threshold is None:
        return

    if direction == "two_sided":
        if isinstance(threshold, dict):
            for key in ("min", "max"):
                if key in threshold and threshold[key] is not None:
                    if not isinstance(threshold[key], (int, float)):
                        raise ThresholdProfileError(
                            f"{rule_id}: {field_name}.{key} must be numeric"
                        )
        elif not isinstance(threshold, (int, float)):
            raise ThresholdProfileError(
                f"{rule_id}: {field_name} for two_sided must be "
                "dict {min,max} or scalar"
            )
    elif direction == "higher_abs_is_worse":
        # accept dict {abs_z: x} or scalar
        if isinstance(threshold, dict):
            for v in threshold.values():
                if not isinstance(v, (int, float)):
                    raise ThresholdProfileError(
                        f"{rule_id}: {field_name} values must be numeric"
                    )
        elif not isinstance(threshold, (int, float)):
            raise ThresholdProfileError(
                f"{rule_id}: {field_name} must be numeric"
            )
    else:
        if isinstance(threshold, dict):
            for v in threshold.values():
                if not isinstance(v, (int, float)):
                    raise ThresholdProfileError(
                        f"{rule_id}: {field_name} values must be numeric"
                    )
        elif not isinstance(threshold, (int, float)):
            raise ThresholdProfileError(
                f"{rule_id}: {field_name} must be numeric"
            )


def threshold_to_snapshot(
    rule: RuleThreshold,
) -> Dict[str, Any]:
    """Render a rule threshold as the snapshot stored in report.json."""
    snap: Dict[str, Any] = {
        "primary_metric": rule.primary_metric,
        "direction": rule.direction,
    }
    if rule.warning_threshold is not None:
        snap["warning_threshold"] = rule.warning_threshold
    if rule.error_threshold is not None:
        snap["error_threshold"] = rule.error_threshold
    if rule.error_requires:
        snap["error_requires"] = list(rule.error_requires)
    return snap


# ---------------------------------------------------------------------------
# Narrow readers (do NOT depend on the full L1/L2 rules validation)
# ---------------------------------------------------------------------------
#
# ``load_threshold_profile`` validates the entire profile (all rules,
# directions, severities, error_requires...). UI consumers that only need one
# scalar (e.g. the canvas overlay threshold) must not be forced through that
# full validation: an unrelated QA rule misconfiguration should never make the
# UI silently fall back. The readers below load the YAML and validate ONLY the
# requested block.

DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX = 36.0


def read_person_small_target_threshold(
    path: Optional[str] = None,
) -> float:
    """Read ONLY the ``person_small_target.min_edge_px`` scalar.

    This loads the YAML directly and validates just the requested block. It
    deliberately avoids :func:`load_threshold_profile`, so an unrelated QA
    rule misconfiguration cannot force a UI fallback (design rev.1 §10).

    Fallback to ``36.0`` happens only when:
    - the file cannot be read or parsed;
    - the ``person_small_target`` block is missing;
    - ``min_edge_px`` is missing, non-numeric, non-finite, or ``<= 0``.

    Args:
        path: Optional explicit YAML path. Defaults to the bundled profile.

    Returns:
        The threshold in image pixels (default ``36.0`` on any fallback).
    """
    yaml_path = path or DEFAULT_PROFILE_PATH
    try:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(
            "Cannot read person_small_target from %s (%s); using default.",
            yaml_path,
            exc,
        )
        return DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX

    if not isinstance(data, dict):
        logger.warning(
            "person_small_target: profile root is not a mapping (%s); "
            "using default.",
            type(data).__name__,
        )
        return DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX

    block = data.get("person_small_target")
    if not isinstance(block, dict):
        logger.warning(
            "person_small_target block missing/invalid; using default."
        )
        return DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX

    import math

    raw = block.get("min_edge_px", DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "person_small_target.min_edge_px is not numeric (%r); "
            "using default.",
            raw,
        )
        return DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX

    if not math.isfinite(value) or value <= 0:
        logger.warning(
            "person_small_target.min_edge_px invalid (%r); using default.",
            raw,
        )
        return DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX

    return value

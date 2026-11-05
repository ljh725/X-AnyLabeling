"""Rule catalog, profile validation and built-in inspection templates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .models import (
    ALLOWED_STAGES,
    PROFILE_SCHEMA_VERSION,
    RELATION_VALUES,
    InspectionProfile,
    RuleConfig,
    RuleMeta,
    canonical_relation_key,
    utc_now_iso,
)
from .parameters import (
    RULE_PARAMETERS,
    describe_rule_parameters,
    validate_rule_parameters,
)

RuleExecutor = Callable[..., Any]


@dataclass(frozen=True)
class ProfileValidation:
    """Validation result that never silently drops a missing rule."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    missing_rule_ids: tuple[str, ...] = ()
    unknown_rule_ids: tuple[str, ...] = ()
    excluded_rules: tuple[Mapping[str, str], ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def runnable_subset(self) -> bool:
        return self.valid and not self.missing_rule_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "runnable_subset": self.runnable_subset,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "missing_rule_ids": list(self.missing_rule_ids),
            "unknown_rule_ids": list(self.unknown_rule_ids),
            "excluded_rules": [dict(item) for item in self.excluded_rules],
        }


class RuleCatalog:
    """Explicit registry of supported rules and implementation versions."""

    def __init__(self) -> None:
        self._meta: dict[str, RuleMeta] = {}
        self._executors: dict[str, RuleExecutor] = {}

    def register(self, meta: RuleMeta, executor: RuleExecutor) -> None:
        if meta.rule_id in self._meta:
            raise ValueError(f"duplicate rule registration: {meta.rule_id}")
        if meta.stage not in ALLOWED_STAGES:
            raise ValueError(f"unknown rule stage: {meta.stage}")
        self._meta[meta.rule_id] = meta
        self._executors[meta.rule_id] = executor

    def meta(self, rule_id: str) -> Optional[RuleMeta]:
        return self._meta.get(rule_id)

    def executor(self, rule_id: str) -> Optional[RuleExecutor]:
        return self._executors.get(rule_id)

    def rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._meta))

    def snapshot(self) -> dict[str, Any]:
        return {
            rule_id: self._meta[rule_id].to_dict()
            for rule_id in self.rule_ids()
        }

    def missing(self, profile: InspectionProfile) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    rule.rule_id
                    for rule in profile.rules
                    if rule.enabled and rule.rule_id not in self._meta
                }
            )
        )

    def parameter_specs(self, rule_id: str) -> Mapping[str, Any]:
        return RULE_PARAMETERS.get(rule_id, {})

    def describe_parameters(self, rule_id: str) -> tuple[Mapping[str, Any], ...]:
        return describe_rule_parameters(rule_id)


def _profile(
    profile_id: str,
    name: str,
    description: str,
    stage: str,
    rules: Sequence[RuleConfig],
    *,
    label_bindings: Optional[Mapping[str, str]] = None,
    relations: Optional[Mapping[str, str]] = None,
    exceptions: Optional[Mapping[str, Any]] = None,
) -> InspectionProfile:
    now = utc_now_iso()
    return InspectionProfile(
        profile_id=profile_id,
        name=name,
        description=description,
        stage=stage,
        rules=tuple(rules),
        label_bindings=dict(label_bindings or {}),
        relations=dict(relations or {}),
        exceptions=dict(exceptions or {}),
        builtin=True,
        created_at=now,
        updated_at=now,
    )


def _generic_rules() -> tuple[RuleConfig, ...]:
    return (
        RuleConfig("label_required"),
        RuleConfig("shape_type_binding"),
        RuleConfig("points_required"),
        RuleConfig("group_id_required"),
        RuleConfig("bbox_geometry_valid"),
        RuleConfig(
            "duplicate_boxes",
            parameters={
                "preset": "medium",
                "relations": {},
                "max_pairs": 5000,
            },
        ),
    )


DEFAULT_PROFILES = (
    _profile(
        "generic",
        "通用矩形检查",
        "不依赖特定业务假设的标签、形状、几何和疑似重复框检查。",
        "post_label",
        _generic_rules(),
    ),
    _profile(
        "screen_corners",
        "屏幕四角点检查",
        "在通用检查之外，按可信屏幕实例检查四类角点完整性。",
        "in_progress",
        _generic_rules()
        + (
            RuleConfig(
                "corner_completeness",
                parameters={
                    "corner_labels": {},
                    "screen_label": "",
                    "exceptions": {},
                },
            ),
        ),
    ),
    _profile(
        "classroom_actions",
        "课堂动作检查",
        "在通用检查之外，应用项目明确配置的动作类别互斥/共存关系。",
        "post_label",
        _generic_rules()
        + (
            RuleConfig(
                "classroom_relation",
                parameters={"relations": {}, "min_overlap": 0.2},
            ),
        ),
    ),
)


def default_profiles() -> tuple[InspectionProfile, ...]:
    """Return fresh copies of the built-in templates."""
    return tuple(
        InspectionProfile.from_dict(profile.to_dict())
        for profile in DEFAULT_PROFILES
    )


def profile_by_id(profile_id: str) -> Optional[InspectionProfile]:
    for profile in default_profiles():
        if profile.profile_id == profile_id:
            return profile
    return None


def validate_profile(
    profile: InspectionProfile, catalog: RuleCatalog
) -> ProfileValidation:
    """Validate schema, availability, parameters and relation conflicts."""
    errors: list[str] = []
    warnings: list[str] = []
    excluded: list[dict[str, str]] = []
    if profile.schema_version != PROFILE_SCHEMA_VERSION:
        errors.append(
            f"不支持方案格式 {profile.schema_version}，需要 "
            f"{PROFILE_SCHEMA_VERSION}"
        )
    if profile.stage not in ALLOWED_STAGES:
        errors.append(f"未知检查阶段: {profile.stage}")
    seen_rules: set[str] = set()
    for rule in profile.rules:
        if rule.rule_id in seen_rules:
            errors.append(f"规则重复配置: {rule.rule_id}")
        seen_rules.add(rule.rule_id)
        meta = catalog.meta(rule.rule_id)
        if meta is None:
            if rule.enabled:
                excluded.append(
                    {
                        "rule_id": rule.rule_id,
                        "reason": "本机未登记该规则",
                    }
                )
            continue
        if not isinstance(rule.parameters, Mapping):
            errors.append(f"规则 {rule.rule_id} 参数必须是对象")
            continue
        # Declared parameters are validated even when the rule is disabled:
        # a typo must stay visible instead of silently reappearing later.
        errors.extend(validate_rule_parameters(rule.rule_id, rule.parameters))
    canonical_keys: dict[str, str] = {}
    for first, second in _relation_pairs(profile.relations):
        raw_value = profile.relations.get(f"{first}|{second}")
        if raw_value is None:
            raw_value = profile.relations.get(f"{second}|{first}", "")
        value = str(raw_value)
        if value not in RELATION_VALUES:
            errors.append(f"未知类别关系 {first}|{second}: {value}")
            continue
        key = canonical_relation_key(first, second)
        previous = canonical_keys.get(key)
        if previous is not None and previous != value:
            errors.append(
                f"类别关系冲突 {first}|{second}: {previous} / {value}"
            )
        canonical_keys[key] = value
        if value == "mutually_exclusive" and first == second:
            errors.append(f"类别不能与自己互斥: {first}")
    screen = profile.label_bindings
    if profile.profile_id == "screen_corners":
        required = (
            "screen",
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right",
        )
        missing = [key for key in required if not screen.get(key)]
        if missing:
            warnings.append("屏幕四角点映射未完成: " + ", ".join(missing))
    missing_rule_ids = tuple(sorted({item["rule_id"] for item in excluded}))
    return ProfileValidation(
        errors=tuple(errors),
        warnings=tuple(warnings),
        missing_rule_ids=missing_rule_ids,
        unknown_rule_ids=missing_rule_ids,
        excluded_rules=tuple(excluded),
    )


def _relation_pairs(
    relations: Mapping[str, str],
) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for key in relations:
        if "|" not in key:
            continue
        left, right = key.split("|", 1)
        if left and right:
            result.add((left, right))
    return result


def prepare_profile(
    profile: InspectionProfile, catalog: RuleCatalog
) -> tuple[InspectionProfile, ProfileValidation]:
    """Return a runnable profile with unavailable rules explicitly disabled."""
    validation = validate_profile(profile, catalog)
    if not validation.valid:
        return profile, validation
    if not validation.missing_rule_ids:
        return profile, validation
    rules = tuple(
        RuleConfig(
            rule_id=rule.rule_id,
            enabled=(
                rule.enabled
                and rule.rule_id not in validation.missing_rule_ids
            ),
            parameters=rule.parameters,
        )
        for rule in profile.rules
    )
    prepared = InspectionProfile(
        profile_id=profile.profile_id,
        name=profile.name,
        description=profile.description,
        stage=profile.stage,
        rules=rules,
        version=profile.version,
        schema_version=profile.schema_version,
        label_bindings=profile.label_bindings,
        relations=profile.relations,
        exceptions=profile.exceptions,
        builtin=profile.builtin,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
    return prepared, validation


def effective_profile_snapshot(
    profile: InspectionProfile, catalog: RuleCatalog
) -> dict[str, Any]:
    """Freeze the effective profile and rule implementation versions.

    The digest must be stable across runs with the same configuration, so
    the wall-clock ``frozen_at`` value is excluded from it.
    """
    prepared, validation = prepare_profile(profile, catalog)
    rules: list[dict[str, Any]] = []
    for rule in prepared.rules:
        meta = catalog.meta(rule.rule_id)
        rules.append(
            {
                **rule.to_dict(),
                "implementation_version": (
                    meta.implementation_version if meta else ""
                ),
                "rule_name": meta.name if meta else rule.rule_id,
                "registered": meta is not None,
                "depends_on": list(meta.depends_on) if meta else [],
            }
        )
    frozen_profile = prepared.to_dict()
    # Wall-clock bookkeeping must not participate in the configuration
    # identity, otherwise every new process would invalidate feedback and
    # changed-file comparisons.
    frozen_profile.pop("created_at", None)
    frozen_profile.pop("updated_at", None)
    payload = {
        "profile": frozen_profile,
        "profile_fingerprint": prepared.fingerprint(),
        "rules": rules,
        "catalog": catalog.snapshot(),
        "validation": validation.to_dict(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload["snapshot_digest"] = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()
    payload["frozen_at"] = utc_now_iso()
    return payload


def copy_builtin(
    profile: InspectionProfile, new_id: str, name: str
) -> InspectionProfile:
    """Create an editable, independently versioned copy of a built-in."""
    if not new_id.strip():
        raise ValueError("new profile id must not be empty")
    now = utc_now_iso()
    return InspectionProfile(
        profile_id=new_id.strip(),
        name=name.strip() or profile.name,
        description=profile.description,
        stage=profile.stage,
        rules=profile.rules,
        version=1,
        label_bindings=profile.label_bindings,
        relations=profile.relations,
        exceptions=profile.exceptions,
        builtin=False,
        created_at=now,
        updated_at=now,
    )


def load_profile(path: str) -> InspectionProfile:
    """Load one JSON profile without executing anything from the file."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return InspectionProfile.from_dict(data)


def save_profile(path: str, profile: InspectionProfile) -> str:
    """Atomically write one profile JSON file."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    payload = json.dumps(
        profile.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
    )
    descriptor, temporary = tempfile.mkstemp(
        prefix=".inspector_profile_", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return path


def build_default_catalog() -> RuleCatalog:
    """Build the catalog with all built-in inspection rules."""
    from .rules import register_default_rules

    catalog = RuleCatalog()
    register_default_rules(catalog)
    return catalog


def import_profile(
    path: str, catalog: RuleCatalog
) -> tuple[InspectionProfile, ProfileValidation]:
    """Load and validate an external profile, preserving missing rules."""
    profile = load_profile(path)
    return profile, validate_profile(profile, catalog)


def export_profile(path: str, profile: InspectionProfile) -> str:
    """Export a profile to a portable JSON file."""
    return save_profile(path, profile)

"""Versioned feature state snapshots referenced by behavior events."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

DEFAULT_FEATURE_KEYS = (
    "edit_mode",
    "shape_type",
    "rectangle_refinement",
    "precision_editing",
    "edge_or_wheel_editing",
    "loupe_or_candidate",
    "pose_compare_navigator",
    "filter_group_focus_multiselect",
    "inspector_quality_review_queue",
    "ai_active",
    "auto_save",
    "digit_shortcut_mode",
)


@dataclass(frozen=True)
class FeatureDefinition:
    """Stable registry metadata for one behavior-affecting feature."""

    key: str


class FeatureRegistry:
    """Validate and expose the behavior feature allow-list."""

    def __init__(
        self, definitions: tuple[FeatureDefinition, ...] | None = None
    ) -> None:
        """Initialize the registry with the shipped feature definitions."""
        definitions = definitions or tuple(
            FeatureDefinition(key) for key in DEFAULT_FEATURE_KEYS
        )
        keys = [definition.key for definition in definitions]
        if len(keys) != len(set(keys)) or any(not key for key in keys):
            raise ValueError(
                "feature registry keys must be unique and non-empty"
            )
        self._definitions = definitions

    @property
    def keys(self) -> tuple[str, ...]:
        """Return feature keys in stable registry order."""
        return tuple(definition.key for definition in self._definitions)

    def filter(
        self, features: Mapping[str, FeatureState]
    ) -> dict[str, FeatureState]:
        """Keep only registered feature states for a snapshot."""
        allowed = set(self.keys)
        return {
            key: value for key, value in features.items() if key in allowed
        }


@dataclass(frozen=True)
class FeatureState:
    """The three analysis states for one behavior-affecting feature."""

    configured: bool
    active: bool
    used: bool = False
    value: Any = None


class FeatureStateTracker:
    """Maintain startup snapshots and effective state versions."""

    def __init__(self, registry: FeatureRegistry | None = None) -> None:
        """Initialize an unknown state with version zero."""
        self.registry = registry or FeatureRegistry()
        self.version = 0
        self.state_unknown = True
        self._features: dict[str, FeatureState] = {}

    @property
    def features(self) -> dict[str, FeatureState]:
        """Return a defensive copy of the current feature states."""
        return dict(self._features)

    def start_snapshot(
        self, features: Mapping[str, FeatureState] | None
    ) -> dict[str, Any]:
        """Record the initial state as version one or unknown version zero."""
        if features is None:
            self.version = 0
            self.state_unknown = True
            self._features = {}
            return self.snapshot()
        self.version = 1
        self.state_unknown = False
        self._features = self.registry.filter(features)
        return self.snapshot()

    def apply_changes(
        self, features: Mapping[str, FeatureState]
    ) -> dict[str, Any] | None:
        """Apply effective changes as one version increment and return a diff."""
        next_features = self.registry.filter(features)
        changes = {}
        all_keys = set(self._features) | set(next_features)
        for key in sorted(all_keys):
            before = self._features.get(key)
            after = next_features.get(key)
            if before != after:
                changes[key] = {
                    "before": asdict(before) if before else None,
                    "after": asdict(after) if after else None,
                }
        if not changes:
            return None
        self.version = max(1, self.version + 1)
        self.state_unknown = False
        self._features = next_features
        return {"version": self.version, "changes": changes}

    def mark_used(self, key: str) -> bool:
        """Mark a known feature as used without changing effective version."""
        state = self._features.get(key)
        if state is None or state.used:
            return False
        self._features[key] = FeatureState(
            configured=state.configured,
            active=state.active,
            used=True,
            value=state.value,
        )
        return True

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable snapshot payload and current version."""
        return {
            "version": self.version,
            "state_unknown": self.state_unknown,
            "features": {
                key: asdict(value)
                for key, value in sorted(self._features.items())
            },
        }

    def reference(self) -> dict[str, Any]:
        """Return the minimal state reference for an ordinary event."""
        return {
            "feature_state_version": self.version,
            "state_unknown": self.state_unknown,
        }

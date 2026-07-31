"""Application integration controller for rectangle-size validation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, MutableMapping
from typing import Any, Optional

from PyQt6 import QtCore

from anylabeling.views.labeling.rectangle_size.config_codec import (
    RULES_CONFIG_KEY,
    RectangleSizeConfigError,
    load_rectangle_size_rules,
    migrate_legacy_person_rule,
    serialize_rectangle_size_rules,
)
from anylabeling.views.labeling.rectangle_size.models import RectangleSizeRule

from .rectangle_size_monitor import RectangleSizeMonitor

_ENABLED_CONFIG_KEY = "show_rectangle_size_violations"


class RectangleSizeFeatureController(QtCore.QObject):
    """Connect persisted rectangle-size rules, Monitor, and Canvas."""

    rules_changed = QtCore.pyqtSignal(tuple)
    enabled_changed = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        canvas: object,
        config: MutableMapping[str, Any],
        *,
        persist_config: Callable[[MutableMapping[str, Any]], object],
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        """Initialize and activate the current-image integration.

        Invalid persisted rules fall back to the legacy-compatible person rule
        and are normalized in memory. Persistence only occurs after an explicit
        user change, so startup never writes configuration unexpectedly.

        Args:
            canvas: Canvas-like QObject exposing generic shape notifications.
            config: Shared application configuration mapping.
            persist_config: Callback used after explicit user changes.
            parent: Optional Qt object owner.

        Raises:
            TypeError: If an integration dependency has an invalid interface.
        """
        super().__init__(parent)
        if not isinstance(config, MutableMapping):
            raise TypeError("config must be a mutable mapping")
        if not callable(persist_config):
            raise TypeError("persist_config must be callable")
        self._validate_canvas(canvas)

        self.canvas = canvas
        self.config = config
        self._persist_config = persist_config
        self.startup_config_error: RectangleSizeConfigError | None = None
        self._rules = self._load_rules()
        self._enabled = self._load_enabled()

        self.monitor = RectangleSizeMonitor(
            self._rules,
            enabled=self._enabled,
            is_shape_interactive=self.canvas.is_shape_interactive,
            parent=self,
        )
        self.monitor.issues_changed.connect(self._publish_issues)
        self.canvas.shape_changed.connect(self.monitor.invalidate_shape)
        self.canvas.shapes_changed.connect(self.monitor.replace_shapes)

        self.canvas.show_rectangle_size_violations = self._enabled
        self.monitor.replace_shapes(tuple(self.canvas.shapes))
        self.canvas.update()

    @property
    def rules(self) -> tuple[RectangleSizeRule, ...]:
        """Return the active immutable rule snapshot."""
        return self._rules

    @property
    def enabled(self) -> bool:
        """Return whether proactive validation is active."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Apply and persist the proactive-validation toggle.

        Args:
            enabled: New feature state.

        Raises:
            TypeError: If ``enabled`` is not a bool.
        """
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self.canvas.show_rectangle_size_violations = enabled
        self.monitor.set_enabled(enabled)
        if not enabled:
            self.canvas.clear_rectangle_size_issues()
        self.canvas.update()
        self.config[_ENABLED_CONFIG_KEY] = enabled
        self._persist()
        self.enabled_changed.emit(enabled)

    def set_rules(
        self,
        rules: Iterable[RectangleSizeRule],
    ) -> None:
        """Atomically apply and persist a complete validated rule set.

        Args:
            rules: New rules accepted by the configuration dialog.

        Raises:
            RectangleSizeConfigError: If the complete rule set is invalid.
        """
        raw_rules = serialize_rectangle_size_rules(tuple(rules))
        normalized = load_rectangle_size_rules({RULES_CONFIG_KEY: raw_rules})
        if normalized == self._rules:
            return
        self.monitor.set_rules(normalized)
        self._rules = normalized
        self.config[RULES_CONFIG_KEY] = raw_rules
        self._persist()
        self.rules_changed.emit(normalized)

    def _load_rules(self) -> tuple[RectangleSizeRule, ...]:
        """Load rules with a safe legacy-compatible startup fallback."""
        try:
            rules = load_rectangle_size_rules(self.config)
        except RectangleSizeConfigError as error:
            self.startup_config_error = error
            rules = (migrate_legacy_person_rule(),)
        self.config[RULES_CONFIG_KEY] = serialize_rectangle_size_rules(rules)
        return rules

    def _load_enabled(self) -> bool:
        """Load a strict bool toggle and normalize malformed persisted data."""
        enabled = self.config.get(_ENABLED_CONFIG_KEY, False)
        if not isinstance(enabled, bool):
            enabled = False
        self.config[_ENABLED_CONFIG_KEY] = enabled
        return enabled

    def _publish_issues(self, issues: tuple[object, ...]) -> None:
        """Publish one Monitor snapshot with its live-shape lookup."""
        self.canvas.set_rectangle_size_issues(
            issues,
            self.monitor.shape_for_candidate,
        )

    def _persist(self) -> None:
        """Persist the shared configuration after an explicit user action."""
        self._persist_config(self.config)

    @staticmethod
    def _validate_canvas(canvas: object) -> None:
        """Validate the narrow Canvas adapter contract used by the controller."""
        required_attributes = (
            "shape_changed",
            "shapes_changed",
            "shapes",
            "set_rectangle_size_issues",
            "clear_rectangle_size_issues",
            "is_shape_interactive",
            "update",
        )
        missing = [
            name for name in required_attributes if not hasattr(canvas, name)
        ]
        if missing:
            names = ", ".join(missing)
            raise TypeError(f"canvas integration is missing: {names}")


__all__ = ["RectangleSizeFeatureController"]

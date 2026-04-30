"""
Rule Configuration Widget — enable/disable rules and edit parameters.

Phase 3 feature:
- Checkbox per rule to toggle it on/off.
- Editable parameters for rules that have them.
- Rule description and severity badge.
- Signal when configuration changes.

Signals:
    config_changed()
        Emitted whenever a rule is toggled or a parameter is edited.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from .validation_engine import (
    ValidationRule,
    ValidationEngine,
    LabelInAllowlist,
    GroupIdUniqueness,
    GroupIdKeypointIntegrity,
    RequiredFieldNotEmpty,
    AttributeConsistency,
)

logger = logging.getLogger(__name__)

# ── Severity colors ─────────────────────────────────────────────
_SEVERITY_COLORS = {
    "error": "#DC3545",
    "warning": "#FFC107",
    "info": "#0D6EFD",
}


# ── Rule descriptor (metadata for built-in rules) ───────────────
# Maps rule name → (display_name, description, param_descriptor)
#
# param_descriptor: dict of {param_name: (display_name, default_value, parser)}
_RULE_META: Dict[str, Dict[str, Any]] = {
    "label_in_allowlist": {
        "display": "标签名检查",
        "description": "每个 shape 的标签必须属于预定义列表",
        "severity": "error",
        "params": {
            "allowed_labels": (
                "标签列表",
                "",
                "csv",  # comma-separated
            ),
        },
    },
    "group_id_uniqueness": {
        "display": "Group ID 唯一性",
        "description": "同一 group_id 内 person/head/face 矩形框唯一",
        "severity": "error",
        "params": {
            "unique_types": (
                "唯一类型",
                "person,head,face",
                "csv",
            ),
        },
    },
    "group_id_keypoint_integrity": {
        "display": "关键点完整性",
        "description": "有关键点的 group 必须有 person 矩形框",
        "severity": "warning",
        "params": {},
    },
    "required_field_not_empty": {
        "display": "必填字段非空",
        "description": "label 和 points 字段不能为空",
        "severity": "error",
        "params": {},
    },
    "attribute_consistency": {
        "display": "属性一致性",
        "description": "difficult 标志和 orphan_head flag 一致性检查",
        "severity": "warning",
        "params": {},
    },
}


class RuleConfigWidget(QtWidgets.QWidget):
    """Widget for configuring validation rules.

    Each rule gets a row with:
      - Checkbox to enable/disable.
      - Rule name and description.
      - Severity badge.
      - Parameter editor (if applicable — e.g. allowed labels CSV field).

    Signals:
        config_changed()
            Emitted when any rule is toggled or parameter edited.
    """

    config_changed = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._rule_rows: Dict[str, Dict[str, QtWidgets.QWidget]] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # header
        header = QtWidgets.QLabel("规则配置")
        header.setStyleSheet("font-weight: bold; font-size: 11pt;")
        layout.addWidget(header)

        desc = QtWidgets.QLabel("勾选/取消勾选规则并调整参数，下次扫描时生效。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(desc)

        # separator
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # scroll area for rule rows
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        rules_container = QtWidgets.QWidget()
        self._rules_layout = QtWidgets.QVBoxLayout(rules_container)
        self._rules_layout.setContentsMargins(0, 0, 0, 0)
        self._rules_layout.setSpacing(4)
        self._rules_layout.addStretch()
        scroll.setWidget(rules_container)
        layout.addWidget(scroll)

    # ── Populate ─────────────────────────────────────────────────

    def populate(
        self,
        rules: List[ValidationRule],
        param_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        """Build rule rows from a list of rules.

        Args:
            rules: Current rules in the engine (used to read enabled
                   state and current parameter values).
            param_overrides: Optional dict mapping rule_name → {param_name: value}
                   to override initial parameter values (e.g. allowed_labels
                   from app config).
        """
        # clear existing rows
        while self._rules_layout.count() > 1:
            item = self._rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rule_rows.clear()

        param_overrides = param_overrides or {}

        # build rule name → instance map
        rule_map: Dict[str, ValidationRule] = {
            r.name: r for r in rules
        }

        for rname, meta in _RULE_META.items():
            rule = rule_map.get(rname)
            enabled = rule is not None
            row = self._create_rule_row(
                rname, meta, rule, enabled,
                param_overrides.get(rname, {}),
            )
            self._rules_layout.insertWidget(
                self._rules_layout.count() - 1, row
            )
            self._rule_rows[rname] = row

    def _create_rule_row(
        self,
        rule_name: str,
        meta: Dict[str, Any],
        rule: Optional[ValidationRule],
        enabled: bool,
        param_overrides: Optional[Dict[str, Any]] = None,
    ) -> QtWidgets.QWidget:
        """Create one rule configuration row."""

        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QVBoxLayout(row)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(2)

        # ── top line: checkbox + severity badge ──────────────────
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)

        cb = QtWidgets.QCheckBox(meta["display"])
        cb.setChecked(enabled)
        cb.setToolTip(meta["description"])
        cb.toggled.connect(
            lambda checked, rn=rule_name: self._on_toggle(rn, checked)
        )
        top.addWidget(cb)

        top.addStretch()

        sev = meta.get("severity", "info")
        badge = QtWidgets.QLabel(sev.upper())
        badge_color = _SEVERITY_COLORS.get(sev, "#888")
        badge.setStyleSheet(
            f"color: {badge_color}; font-size: 8pt; "
            f"font-weight: bold; padding: 0 3px;"
        )
        top.addWidget(badge)

        row_layout.addLayout(top)

        # ── description ──────────────────────────────────────────
        desc_label = QtWidgets.QLabel(meta["description"])
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #666; font-size: 8.5pt;")
        row_layout.addWidget(desc_label)

        # ── parameter editors ────────────────────────────────────
        params_meta = meta.get("params", {})
        if params_meta:
            params_widget = self._create_params_editor(
                rule_name, params_meta, rule, enabled, param_overrides
            )
            row_layout.addWidget(params_widget)

        # ── separator line ───────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
        sep.setStyleSheet("color: #ddd;")
        row_layout.addWidget(sep)

        # store references
        row._cb = cb
        row._params_meta = params_meta  # type: ignore[attr-defined]

        return row

    def _create_params_editor(
        self,
        rule_name: str,
        params_meta: Dict[str, Tuple[str, str, str]],
        rule: Optional[ValidationRule],
        enabled: bool,
        param_overrides: Optional[Dict[str, Any]] = None,
    ) -> QtWidgets.QWidget:
        """Create parameter editor fields for a rule."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(18, 0, 0, 0)
        layout.setSpacing(2)

        for pname, (display_name, default_val, ptype) in params_meta.items():
            h = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(display_name + ":")
            lbl.setStyleSheet("color: #888; font-size: 8pt;")
            h.addWidget(lbl)

            edit = QtWidgets.QLineEdit()
            edit.setEnabled(enabled)
            edit.setStyleSheet(
                "QLineEdit { padding: 1px 3px; font-size: 8.5pt; }"
            )

            if ptype == "csv":
                current_val = self._get_param_value(
                    rule, pname, default_val, param_overrides
                )
                edit.setText(
                    ",".join(sorted(current_val))
                    if isinstance(current_val, set)
                    else str(current_val)
                )
                edit.textChanged.connect(
                    lambda text, rn=rule_name, pn=pname:
                    self._on_param_changed(rn, pn, text)
                )

            h.addWidget(edit)
            layout.addLayout(h)

        return container

    # ── Event handlers ───────────────────────────────────────────

    def _on_toggle(self, rule_name: str, checked: bool) -> None:
        """Rule checkbox toggled."""
        row = self._rule_rows.get(rule_name)
        if row and hasattr(row, "_params_meta"):
            for pname in row._params_meta:  # type: ignore[attr-defined]
                # find the QLineEdit and enable/disable
                container = row.findChild(QtWidgets.QWidget)
                if container:
                    edits = container.findChildren(QtWidgets.QLineEdit)
                    for edit in edits:
                        edit.setEnabled(checked)
        self.config_changed.emit()

    def _on_param_changed(
        self, rule_name: str, param_name: str, text: str
    ) -> None:
        """Parameter value edited."""
        self.config_changed.emit()

    # ── Build / Rebuild engine ───────────────────────────────────

    def build_rules(
        self,
        existing_rules: Optional[List[ValidationRule]] = None,
    ) -> List[ValidationRule]:
        """Build a new rule list from the current UI state.

        Reads checkboxes and parameter editors to construct the
        appropriate ValidationRule instances.

        Args:
            existing_rules: Optional existing rules to preserve
                            (e.g. custom rules added programmatically).
        Returns:
            List of enabled ValidationRule instances.
        """
        rules: List[ValidationRule] = []

        for rname, meta in _RULE_META.items():
            row = self._rule_rows.get(rname)
            if row is None or not row._cb.isChecked():
                continue

            params_meta = meta.get("params", {})
            params: Dict[str, Any] = {}
            # collect param values from editors
            container = row.findChild(QtWidgets.QWidget)
            if container and params_meta:
                edits = container.findChildren(QtWidgets.QLineEdit)
                edit_list = list(edits)
                for i, pname in enumerate(params_meta):
                    if i < len(edit_list):
                        raw = edit_list[i].text().strip()
                        ptype = params_meta[pname][2]
                        if ptype == "csv":
                            params[pname] = set(
                                x.strip() for x in raw.split(",") if x.strip()
                            )

            rule = self._instantiate_rule(rname, params)
            if rule:
                rules.append(rule)

        # preserve any custom rules from the existing list
        builtin_names = set(_RULE_META.keys())
        if existing_rules:
            for r in existing_rules:
                if r.name not in builtin_names:
                    rules.append(r)

        return rules

    @staticmethod
    def _instantiate_rule(
        rule_name: str, params: Dict[str, Any]
    ) -> Optional[ValidationRule]:
        """Instantiate a rule class from name + parameters."""
        if rule_name == "label_in_allowlist":
            labels = params.get("allowed_labels", set())
            if labels:
                return LabelInAllowlist(labels)
            return None
        if rule_name == "group_id_uniqueness":
            rule = GroupIdUniqueness()
            if "unique_types" in params and params["unique_types"]:
                rule.UNIQUE_TYPES = params["unique_types"]
            return rule
        if rule_name == "group_id_keypoint_integrity":
            return GroupIdKeypointIntegrity()
        if rule_name == "required_field_not_empty":
            return RequiredFieldNotEmpty()
        if rule_name == "attribute_consistency":
            return AttributeConsistency()
        return None

    @staticmethod
    def _get_param_value(
        rule: Optional[ValidationRule],
        param_name: str,
        default: str,
        param_overrides: Optional[Dict[str, Any]] = None,
    ) -> Set[str]:
        """Extract current param value from a rule instance.

        Checks param_overrides first (e.g. from app config),
        then falls back to the rule instance, then to the default.
        """
        param_overrides = param_overrides or {}

        # 1. Override from external config
        if param_name in param_overrides:
            override = param_overrides[param_name]
            if isinstance(override, (set, list, tuple)):
                return set(override)
            if isinstance(override, str):
                return set(
                    x.strip() for x in override.split(",") if x.strip()
                )

        # 2. Rule instance value
        if rule is not None:
            if param_name == "allowed_labels":
                labels = getattr(rule, "allowed_labels", None)
                if labels:
                    return set(labels)
            if param_name == "unique_types":
                types = getattr(rule, "UNIQUE_TYPES", None)
                if types:
                    return set(types)

        # 3. Default
        return set(x.strip() for x in default.split(",") if x.strip())

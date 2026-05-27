"""
Rule Configuration Widget — shared label set + per-rule toggles & params.

Phase 3 feature (revised):
- Shared project label set editor at top (one source of truth).
- 8 rule rows with checkboxes, descriptions, and optional sub-editors.
- build_rules() constructs ValidationRule instances from UI state.

Signals:
    config_changed()
        Emitted whenever a rule is toggled or a parameter is edited.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from .validation_engine import (
    ValidationRule,
    ValidationEngine,
    LabelInAllowlist,
    GroupLabelUniqueness,
    PersonRectRequiresGroupId,
    GroupIdValid,
    HeadFaceGroupIdRequired,
    HeadFaceGroupIdUniqueness,
    LabelShapeTypeBinding,
    GroupIdUniqueness,
    GroupIdKeypointIntegrity,
    RequiredFieldNotEmpty,
    AttributeConsistency,
)

logger = logging.getLogger(__name__)

# ── Default project label set (20 labels) ───────────────────────
DEFAULT_SHARED_LABELS = ",".join(
    [
        "person", "head", "face",
        "nose", "l_eye", "r_eye", "l_ear", "r_ear",
        "l_sho", "r_sho", "l_elb", "r_elb", "l_wri", "r_wri",
        "l_hip", "r_hip", "l_knee", "r_knee", "l_ank", "r_ank",
    ]
)

# Rectangle labels default
DEFAULT_RECT_LABELS = "person,head,face"

# Point labels default (17 keypoints)
DEFAULT_POINT_LABELS = ",".join(
    [
        "nose", "l_eye", "r_eye", "l_ear", "r_ear",
        "l_sho", "r_sho", "l_elb", "r_elb", "l_wri", "r_wri",
        "l_hip", "r_hip", "l_knee", "r_knee", "l_ank", "r_ank",
    ]
)

_SEVERITY_COLORS = {"error": "#DC3545", "warning": "#FFC107", "info": "#0D6EFD"}

# ── Rule metadata ───────────────────────────────────────────────
# (rule_name, display, description, severity, enabled_by_default, params_meta)
# params_meta: {pname: (display, default, ptype)}
_RULE_REGISTRY: List[Dict[str, Any]] = [
    {
        "name": "label_in_allowlist",
        "display": "标签名检查",
        "description": "每个 shape 的标签必须在项目标签集内",
        "severity": "error",
        "default_on": True,
    },
    {
        "name": "group_label_uniqueness",
        "display": "同组标签唯一性",
        "description": "同一 group_id 内每个标签最多出现 1 次",
        "severity": "error",
        "default_on": True,
    },
    {
        "name": "person_rect_requires_group_id",
        "display": "Person 矩形 group_id 检查",
        "description": "person 矩形框必须有数字 group_id",
        "severity": "error",
        "default_on": True,
    },
    {
        "name": "group_id_valid",
        "display": "group_id 合法性检查",
        "description": "group_id 必须是非负整数",
        "severity": "error",
        "default_on": True,
    },
    {
        "name": "head_face_group_id_required",
        "display": "Head/Face group_id 检查",
        "description": "head/face 必须有合法 group_id",
        "severity": "error",
        "default_on": True,
    },
    {
        "name": "head_face_group_id_uniqueness",
        "display": "Head/Face group_id 唯一性",
        "description": "head/face 的 group_id 不应重复",
        "severity": "error",
        "default_on": True,
    },
    {
        "name": "label_shape_type_binding",
        "display": "标签形状类型绑定",
        "description": "标签必须匹配指定的 shape_type",
        "severity": "error",
        "default_on": True,
        "params": {
            "rectangle_labels": ("矩形标签", DEFAULT_RECT_LABELS, "csv"),
            "point_labels": ("关键点标签", DEFAULT_POINT_LABELS, "csv"),
        },
    },
    {
        "name": "group_id_keypoint_integrity",
        "display": "Person 主体绑定",
        "description": "person 是唯一的 pose 主体；关键点只能绑定到含 person 的 group_id，head/face 只作为同组辅助框。",
        "severity": "warning",
        "default_on": True,
    },
    {
        "name": "required_field_not_empty",
        "display": "必填字段非空",
        "description": "label 和 points 字段不能为空",
        "severity": "error",
        "default_on": True,
    },
    {
        "name": "group_id_uniqueness",
        "display": "Group ID 唯一性（自定义）",
        "description": "可配置的同一 group_id 内唯一类型检查",
        "severity": "error",
        "default_on": True,
        "params": {
            "unique_types": ("唯一类型", "", "csv"),
        },
    },
    {
        "name": "attribute_consistency",
        "display": "属性一致性",
        "description": "difficult 标志和 orphan_head flag 一致性",
        "severity": "warning",
        "default_on": False,
    },
]


class RuleConfigWidget(QtWidgets.QWidget):
    """Widget for configuring validation rules with a shared label set.

    Signals:
        config_changed()
            Emitted when any rule is toggled or parameter edited.
    """

    config_changed = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._rule_rows: Dict[str, QtWidgets.QWidget] = {}
        self._setup_ui()

    # ── UI setup ─────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # header
        header = QtWidgets.QLabel("规则配置")
        header.setStyleSheet("font-weight: bold; font-size: 11pt;")
        layout.addWidget(header)

        # ── shared label set ─────────────────────────────────────
        shared_layout = QtWidgets.QHBoxLayout()
        shared_layout.addWidget(QtWidgets.QLabel("项目标签集:"))
        self._shared_labels_edit = QtWidgets.QLineEdit()
        self._shared_labels_edit.setPlaceholderText("逗号分隔，如 person,head,face")
        self._shared_labels_edit.setText(DEFAULT_SHARED_LABELS)
        self._shared_labels_edit.textChanged.connect(self._on_shared_labels_changed)
        shared_layout.addWidget(self._shared_labels_edit)
        layout.addLayout(shared_layout)

        desc = QtWidgets.QLabel(
            "勾选规则并调整参数，下次扫描时生效。"
            "项目标签集修改后影响所有关联规则。"
        )
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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        shared_labels: Optional[Set[str]] = None,
    ) -> None:
        """Build rule rows from the current engine rules.

        Args:
            rules: Current rules in the engine (for enabled state).
            shared_labels: Optional label set to pre-fill the shared editor.
        """
        while self._rules_layout.count() > 1:
            item = self._rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rule_rows.clear()

        # pre-fill shared label editor if given
        if shared_labels:
            self._shared_labels_edit.blockSignals(True)
            self._shared_labels_edit.setText(
                ",".join(sorted(shared_labels))
            )
            self._shared_labels_edit.blockSignals(False)

        # build rule name → instance map
        rule_map: Dict[str, ValidationRule] = {r.name: r for r in rules}

        for meta in _RULE_REGISTRY:
            rname = meta["name"]
            rule = rule_map.get(rname)
            enabled = rule is not None
            row = self._create_rule_row(meta, rule, enabled)
            self._rules_layout.insertWidget(
                self._rules_layout.count() - 1, row
            )
            self._rule_rows[rname] = row

    # ── Rule row factory ─────────────────────────────────────────

    def _create_rule_row(
        self,
        meta: Dict[str, Any],
        rule: Optional[ValidationRule],
        enabled: bool,
    ) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QVBoxLayout(row)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(2)

        # top line: checkbox + severity badge
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)

        cb = QtWidgets.QCheckBox(meta["display"])
        cb.setChecked(enabled)
        cb.setToolTip(meta["description"])
        cb.toggled.connect(
            lambda checked, rn=meta["name"]: self._on_toggle(rn, checked)
        )
        top.addWidget(cb)

        top.addStretch()

        sev = meta.get("severity", "info")
        badge = QtWidgets.QLabel(sev.upper())
        color = _SEVERITY_COLORS.get(sev, "#888")
        badge.setStyleSheet(
            f"color: {color}; font-size: 8pt; font-weight: bold; padding: 0 3px;"
        )
        top.addWidget(badge)

        row_layout.addLayout(top)

        # description
        desc = QtWidgets.QLabel(meta["description"])
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; font-size: 8.5pt;")
        row_layout.addWidget(desc)

        # parameter editors
        params_meta = meta.get("params", {})
        params_widget = None
        if params_meta:
            params_widget = self._create_params_editor(
                meta["name"], params_meta, rule, enabled
            )
            row_layout.addWidget(params_widget)

        # separator
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
        sep.setStyleSheet("color: #ddd;")
        row_layout.addWidget(sep)

        # store references
        row._cb = cb  # type: ignore[attr-defined]
        if params_widget is not None:
            row._params_widget = params_widget  # type: ignore[attr-defined]

        return row

    def _create_params_editor(
        self,
        rule_name: str,
        params_meta: Dict[str, Tuple[str, str, str]],
        rule: Optional[ValidationRule],
        enabled: bool,
    ) -> QtWidgets.QWidget:
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
            edit.setStyleSheet("QLineEdit { padding: 1px 3px; font-size: 8.5pt; }")

            # read current value from rule or use default
            current_val = self._extract_rule_param(
                rule, pname, default_val
            )
            edit.setText(current_val)

            edit.textChanged.connect(
                lambda text, rn=rule_name, pn=pname:
                self._on_param_changed(rn, pn, text)
            )

            h.addWidget(edit)
            layout.addLayout(h)

        return container

    # ── Event handlers ───────────────────────────────────────────

    def _on_toggle(self, rule_name: str, checked: bool) -> None:
        row = self._rule_rows.get(rule_name)
        if row is None:
            return
        if hasattr(row, "_params_widget"):
            edits = row._params_widget.findChildren(  # type: ignore[attr-defined]
                QtWidgets.QLineEdit
            )
            for edit in edits:
                edit.setEnabled(checked)
        self.config_changed.emit()

    def _on_param_changed(
        self, _rule_name: str, _param_name: str, _text: str
    ) -> None:
        self.config_changed.emit()

    def _on_shared_labels_changed(self, _text: str) -> None:
        self.config_changed.emit()

    # ── Public helpers ───────────────────────────────────────────

    def get_shared_label_set(self) -> Set[str]:
        """Return the current shared label set as a set of strings."""
        raw = self._shared_labels_edit.text().strip()
        return set(s.strip() for s in raw.split(",") if s.strip())

    def set_shared_labels(self, labels: Set[str]) -> None:
        """Update the shared label editor (no signal emission)."""
        self._shared_labels_edit.blockSignals(True)
        self._shared_labels_edit.setText(
            ",".join(sorted(labels)) if labels else ""
        )
        self._shared_labels_edit.blockSignals(False)

    # ── Build engine ─────────────────────────────────────────────

    def build_rules(
        self,
        existing_rules: Optional[List[ValidationRule]] = None,
    ) -> List[ValidationRule]:
        """Build a new rule list from the current UI state.

        Reads checkboxes, shared label set, and parameter editors.
        """
        shared_labels = self.get_shared_label_set()
        rules: List[ValidationRule] = []
        builtin_names = {m["name"] for m in _RULE_REGISTRY}

        for meta in _RULE_REGISTRY:
            rname = meta["name"]
            row = self._rule_rows.get(rname)
            if row is None:
                enabled = meta.get("default_on", False)
            else:
                enabled = row._cb.isChecked()  # type: ignore[attr-defined]
            if not enabled:
                continue

            rule = self._instantiate_rule(rname, meta, shared_labels)
            if rule:
                rules.append(rule)

        # preserve custom rules not in the registry
        if existing_rules:
            for r in existing_rules:
                if r.name not in builtin_names:
                    rules.append(r)

        return rules

    def _instantiate_rule(
        self,
        rule_name: str,
        meta: Dict[str, Any],
        shared_labels: Set[str],
    ) -> Optional[ValidationRule]:
        """Create a ValidationRule instance from name + UI params + shared labels."""
        if rule_name == "label_in_allowlist":
            if shared_labels:
                return LabelInAllowlist(shared_labels)
            return None

        if rule_name == "group_label_uniqueness":
            if shared_labels:
                return GroupLabelUniqueness(shared_labels)
            return None

        if rule_name == "person_rect_requires_group_id":
            return PersonRectRequiresGroupId()

        if rule_name == "group_id_valid":
            return GroupIdValid()

        if rule_name == "head_face_group_id_required":
            return HeadFaceGroupIdRequired()

        if rule_name == "head_face_group_id_uniqueness":
            return HeadFaceGroupIdUniqueness()

        if rule_name == "label_shape_type_binding":
            rect_labels = self._read_param(
                rule_name, "rectangle_labels", DEFAULT_RECT_LABELS
            )
            point_labels = self._read_param(
                rule_name, "point_labels", DEFAULT_POINT_LABELS
            )
            return LabelShapeTypeBinding(rect_labels, point_labels)

        if rule_name == "group_id_keypoint_integrity":
            return GroupIdKeypointIntegrity()

        if rule_name == "required_field_not_empty":
            return RequiredFieldNotEmpty()

        if rule_name == "group_id_uniqueness":
            unique_str = self._read_param(rule_name, "unique_types", "")
            rule = GroupIdUniqueness()
            if unique_str:
                rule.UNIQUE_TYPES = set(unique_str)
            return rule

        if rule_name == "attribute_consistency":
            return AttributeConsistency()

        return None

    def _read_param(
        self, rule_name: str, param_name: str, default: str
    ) -> Set[str]:
        """Read a CSV param from the UI, parse to a set of strings."""
        row = self._rule_rows.get(rule_name)
        if row is None:
            return set(s.strip() for s in default.split(",") if s.strip())
        edits = getattr(row, "_params_widget", None)  # type: ignore[arg-type]
        if edits is None:
            return set(s.strip() for s in default.split(",") if s.strip())
        children = edits.findChildren(QtWidgets.QLineEdit)
        params_meta = next(
            (m["params"] for m in _RULE_REGISTRY if m["name"] == rule_name),
            {},
        )
        for idx, pn in enumerate(params_meta):
            if pn == param_name and idx < len(children):
                raw = children[idx].text().strip()
                return set(s.strip() for s in raw.split(",") if s.strip())
        return set(s.strip() for s in default.split(",") if s.strip())

    @staticmethod
    def _extract_rule_param(
        rule: Optional[ValidationRule],
        param_name: str,
        default: str,
    ) -> str:
        """Extract a parameter value from a live rule instance as CSV string."""
        if rule is None:
            return default
        if param_name == "unique_types":
            types = getattr(rule, "UNIQUE_TYPES", set())
            return ",".join(sorted(types)) if types else default
        if param_name == "rectangle_labels":
            labels = getattr(rule, "rectangle_labels", None)
            return ",".join(sorted(labels)) if labels else default
        if param_name == "point_labels":
            labels = getattr(rule, "point_labels", None)
            return ",".join(sorted(labels)) if labels else default
        return default

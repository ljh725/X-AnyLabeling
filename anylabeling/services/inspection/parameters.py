"""Declarative parameter contracts for registered inspection rules.

The registry is the single source of truth used by profile validation and by
the Inspector UI when it renders editable rule parameters.  Validation never
executes a rule and never rewrites the profile: it collects explicit errors so
an out-of-range or mistyped value cannot silently reach the runner.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .models import RELATION_VALUES

CORNER_KEYS = ("top_left", "top_right", "bottom_left", "bottom_right")


@dataclass(frozen=True)
class ParameterSpec:
    """One declared parameter with type, range and semantics."""

    kind: str
    description: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    values: tuple[str, ...] = ()
    required: bool = False
    item_values: tuple[str, ...] = ()
    item_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "values": list(self.values),
            "required": bool(self.required),
            "item_values": list(self.item_values),
            "item_keys": list(self.item_keys),
        }


_RULE_PARAMETERS: dict[str, dict[str, ParameterSpec]] = {
    "label_required": {},
    "points_required": {},
    "bbox_geometry_valid": {},
    "shape_type_binding": {
        "expected_types": ParameterSpec(
            "mapping_of_str",
            "标签到期望 shape_type 的映射；值为空表示未配置。",
        ),
    },
    "group_id_required": {
        "labels": ParameterSpec(
            "list_of_str", "必须具有非负 group_id 的标签列表。"
        ),
    },
    "duplicate_boxes": {
        "preset": ParameterSpec(
            "enum",
            "几何阈值预设；与 thresholds 同时给出时 thresholds 生效。",
            values=("low", "medium", "high"),
        ),
        "thresholds": ParameterSpec(
            "duplicate_thresholds",
            "完整的高级阈值对象，必须包含全部字段且通过范围/交叉校验。",
            required=False,
        ),
        "relations": ParameterSpec(
            "mapping_of_str",
            "类别对（A|B）到允许关系的映射。",
            item_values=RELATION_VALUES,
        ),
        "max_pairs": ParameterSpec(
            "int",
            "单次运行保留的候选对上限；达到上限记录截断。",
            minimum=1,
            maximum=100000,
        ),
    },
    "legacy_same_group_duplicate": {
        "edge_tolerance_px": ParameterSpec(
            "float",
            "旧 L2-13 边缘容差（像素），必须为非负有限数。",
            minimum=0.0,
            maximum=100000.0,
        ),
    },
    "corner_completeness": {
        "corner_labels": ParameterSpec(
            "mapping_of_str",
            "四角点角色到标签的映射，只接受四个固定角色。",
            item_keys=CORNER_KEYS,
        ),
        "screen_label": ParameterSpec("str", "屏幕主体标签。"),
        "exceptions": ParameterSpec(
            "mapping_of_str",
            "角点标签到遮挡/不可见属性名的映射。",
        ),
    },
    "classroom_relation": {
        "relations": ParameterSpec(
            "mapping_of_str",
            "课堂动作类别对到关系的映射。",
            item_values=RELATION_VALUES,
        ),
        "min_overlap": ParameterSpec(
            "float",
            "判定互斥重叠所需的最小比例（0-1）。",
            minimum=0.0,
            maximum=1.0,
        ),
    },
    "group_completeness": {
        "groups": ParameterSpec(
            "mapping_of_str_list",
            "分组触发标签到必要成员标签列表的映射。",
        ),
    },
    "count_constraint": {
        "counts": ParameterSpec(
            "counts_mapping",
            "标签到 {min,max,scope} 的数量约束。",
        ),
    },
}

RULE_PARAMETERS: Mapping[str, Mapping[str, ParameterSpec]] = {
    rule_id: dict(specs) for rule_id, specs in _RULE_PARAMETERS.items()
}


def supported_rule_ids() -> tuple[str, ...]:
    return tuple(sorted(_RULE_PARAMETERS))


def describe_rule_parameters(rule_id: str) -> tuple[Mapping[str, Any], ...]:
    """Return serializable parameter metadata for UI display."""
    specs = _RULE_PARAMETERS.get(rule_id, {})
    return tuple(
        {"name": name, **spec.to_dict()} for name, spec in sorted(specs.items())
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_int(
    name: str, spec: ParameterSpec, value: Any, errors: list[str]
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"参数 {name} 必须是整数，当前为 {type(value).__name__}")
        return
    if spec.minimum is not None and value < spec.minimum:
        errors.append(
            f"参数 {name} 不能小于 {int(spec.minimum)}，当前为 {value}"
        )
    if spec.maximum is not None and value > spec.maximum:
        errors.append(
            f"参数 {name} 不能大于 {int(spec.maximum)}，当前为 {value}"
        )


def _check_float(
    name: str, spec: ParameterSpec, value: Any, errors: list[str]
) -> None:
    if not _is_number(value):
        errors.append(
            f"参数 {name} 必须是数值，当前为 {type(value).__name__}"
        )
        return
    number = float(value)
    if not math.isfinite(number):
        errors.append(f"参数 {name} 必须是有限数值，当前为 {number!r}")
        return
    if spec.minimum is not None and number < spec.minimum:
        errors.append(f"参数 {name} 不能小于 {spec.minimum:g}，当前为 {number:g}")
    if spec.maximum is not None and number > spec.maximum:
        errors.append(f"参数 {name} 不能大于 {spec.maximum:g}，当前为 {number:g}")


def _check_str(
    name: str, spec: ParameterSpec, value: Any, errors: list[str]
) -> None:
    if not isinstance(value, str):
        errors.append(f"参数 {name} 必须是字符串")
        return
    if spec.values and value not in spec.values:
        errors.append(
            f"参数 {name} 取值必须是 {', '.join(spec.values)} 之一，"
            f"当前为 {value!r}"
        )


def _check_mapping_of_str(
    name: str, spec: ParameterSpec, value: Any, errors: list[str]
) -> None:
    if not isinstance(value, Mapping):
        errors.append(f"参数 {name} 必须是对象（键值映射）")
        return
    for key, item in value.items():
        if not isinstance(key, str) or not str(key).strip():
            errors.append(f"参数 {name} 的键必须是非空字符串")
            continue
        if spec.item_keys and key not in spec.item_keys:
            errors.append(
                f"参数 {name} 含未知键 {key!r}；允许 "
                f"{', '.join(spec.item_keys)}"
            )
        if not isinstance(item, str):
            errors.append(f"参数 {name}[{key}] 的值必须是字符串")
            continue
        if spec.item_values and item not in spec.item_values:
            errors.append(
                f"参数 {name}[{key}] 的值必须是 "
                f"{', '.join(spec.item_values)} 之一，当前为 {item!r}"
            )


def _check_list_of_str(
    name: str, spec: ParameterSpec, value: Any, errors: list[str]
) -> None:
    if isinstance(value, (str, bytes)) or not isinstance(
        value, Sequence
    ):
        errors.append(f"参数 {name} 必须是字符串列表")
        return
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"参数 {name} 只能包含非空字符串")


def _check_mapping_of_str_list(
    name: str, spec: ParameterSpec, value: Any, errors: list[str]
) -> None:
    if not isinstance(value, Mapping):
        errors.append(f"参数 {name} 必须是对象（键值映射）")
        return
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            errors.append(f"参数 {name} 的键必须是非空字符串")
            continue
        if isinstance(item, (str, bytes)) or not isinstance(item, Sequence):
            errors.append(f"参数 {name}[{key}] 必须是字符串列表")
            continue
        for member in item:
            if not isinstance(member, str) or not member.strip():
                errors.append(f"参数 {name}[{key}] 只能包含非空字符串")


def _check_thresholds(
    name: str, spec: ParameterSpec, value: Any, errors: list[str]
) -> None:
    from .duplicate import thresholds_from_mapping

    if not isinstance(value, Mapping):
        errors.append(f"参数 {name} 必须是完整阈值对象")
        return
    try:
        thresholds_from_mapping(value)
    except (TypeError, ValueError) as error:
        errors.append(f"参数 {name} 无效: {error}")


def _check_counts(
    name: str, spec: ParameterSpec, value: Any, errors: list[str]
) -> None:
    if not isinstance(value, Mapping):
        errors.append(f"参数 {name} 必须是对象（标签到约束的映射）")
        return
    for label, rules in value.items():
        if not isinstance(label, str) or not label.strip():
            errors.append(f"参数 {name} 的键必须是非空标签")
            continue
        if not isinstance(rules, Mapping):
            errors.append(f"参数 {name}[{label}] 必须是对象")
            continue
        unknown = set(rules).difference({"min", "max", "scope"})
        if unknown:
            errors.append(
                f"参数 {name}[{label}] 含未知字段: {', '.join(sorted(unknown))}"
            )
        minimum = rules.get("min")
        maximum = rules.get("max")
        if minimum is not None:
            _check_int(f"{name}[{label}].min", ParameterSpec(
                "int", minimum=0), minimum, errors)
        if maximum is not None:
            _check_int(f"{name}[{label}].max", ParameterSpec(
                "int", minimum=0), maximum, errors)
        if (
            isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and minimum > maximum
        ):
            errors.append(
                f"参数 {name}[{label}] 的 min 不能大于 max"
            )
        scope = rules.get("scope", "image")
        if scope not in ("image", "group"):
            errors.append(
                f"参数 {name}[{label}].scope 只能是 image 或 group"
            )


_CHECKERS = {
    "int": _check_int,
    "float": _check_float,
    "str": _check_str,
    "enum": _check_str,
    "mapping_of_str": _check_mapping_of_str,
    "list_of_str": _check_list_of_str,
    "mapping_of_str_list": _check_mapping_of_str_list,
    "duplicate_thresholds": _check_thresholds,
    "counts_mapping": _check_counts,
}


def validate_rule_parameters(
    rule_id: str, parameters: Mapping[str, Any]
) -> tuple[str, ...]:
    """Validate declared parameters for one rule.

    Unknown rule ids are ignored here (profile validation reports them as
    unavailable rules); unknown parameter names are always errors so a typo
    cannot be silently ignored.
    """
    specs = _RULE_PARAMETERS.get(rule_id)
    if specs is None:
        return ()
    errors: list[str] = []
    if not isinstance(parameters, Mapping):
        return (f"规则 {rule_id} 参数必须是对象",)
    unknown = set(parameters).difference(specs)
    for name in sorted(unknown):
        allowed = ", ".join(sorted(specs)) or "无"
        errors.append(
            f"规则 {rule_id} 含未知参数 {name!r}；允许参数: {allowed}"
        )
    for name, spec in specs.items():
        if name not in parameters:
            if spec.required:
                errors.append(f"规则 {rule_id} 缺少必需参数 {name}")
            continue
        checker = _CHECKERS[spec.kind]
        checker(f"规则 {rule_id} 参数 {name}", spec, parameters[name], errors)
    return tuple(errors)

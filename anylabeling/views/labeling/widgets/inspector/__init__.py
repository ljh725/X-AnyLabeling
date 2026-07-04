"""Lazy exports for the Inspector package."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict

_LAZY_IMPORTS: Dict[str, str] = {
    "AttributeConsistency": "validation_engine",
    "FlatIndex": "flat_index",
    "FlattenedRecord": "flat_index",
    "GroupIdKeypointIntegrity": "validation_engine",
    "GroupIdUniqueness": "validation_engine",
    "GroupIdValid": "validation_engine",
    "GroupLabelUniqueness": "validation_engine",
    "HeadFaceGroupIdRequired": "validation_engine",
    "HeadFaceGroupIdUniqueness": "validation_engine",
    "InspectorPanel": "inspector_panel",
    "Issue": "validation_engine",
    "IssueListWidget": "issue_list_widget",
    "LabelInAllowlist": "validation_engine",
    "LabelShapeTypeBinding": "validation_engine",
    "PersonRectRequiresGroupId": "validation_engine",
    "RequiredFieldNotEmpty": "validation_engine",
    "ValidationEngine": "validation_engine",
    "ValidationRule": "validation_engine",
}

__all__ = tuple(_LAZY_IMPORTS)


def __getattr__(name: str) -> Any:
    """Import Inspector symbols only when they are requested."""
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value

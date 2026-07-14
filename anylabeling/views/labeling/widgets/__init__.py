"""Lazy exports for labeling widgets.

Keeping this package import-light lets pure-Python subpackages such as
``widgets.inspector.quality`` be imported without loading PyQt widgets.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict

_LAZY_IMPORTS: Dict[str, str] = {
    "AboutDialog": "about_dialog",
    "AutoLabelingWidget": "auto_labeling",
    "BrightnessContrastDialog": "brightness_contrast_dialog",
    "Canvas": "canvas",
    "CompareViewManager": "compare_view",
    "CompareViewSlider": "compare_view",
    "ChatbotDialog": "chatbot_dialog",
    "ClassifierDialog": "classifier_dialog",
    "CrosshairSettingsDialog": "crosshair_settings_dialog",
    "DigitRenameManager": "digit_rename_manager",
    "DigitRenameShortcutDialog": "digit_rename_manager",
    "DigitBindDrawManager": "digit_bind_draw_manager",
    "DigitShortcutDialog": "label_dialog",
    "DigitShortcutPageManager": "digit_shortcut_page_manager",
    "FileDialogPreview": "file_dialog_preview",
    "GroupIDFilterComboBox": "filter_label_widget",
    "GroupIDModifyDialog": "label_dialog",
    "InspectorPanel": "inspector",
    "KeypointFillMode": "keypoint_fill_mode",
    "KeypointToolWindow": "keypoint_tool_window",
    "LabelDialog": "label_dialog",
    "LabelFilterComboBox": "filter_label_widget",
    "LabelListWidget": "label_list_widget",
    "LabelListWidgetItem": "label_list_widget",
    "LabelModifyDialog": "label_dialog",
    "LabelQLineEdit": "label_dialog",
    "NavigatorDialog": "navigator_widget",
    "OverviewDialog": "overview_dialog",
    "PPOCRDialog": "ppocr_dialog",
    "PolygonSidesDialog": "polygon_sides_dialog",
    "Popup": "popup",
    "SearchBar": "model_dropdown_widget",
    "ShapeModifyDialog": "shape_dialog",
    "ShapeTypeFilterComboBox": "filter_label_widget",
    "ToolBar": "toolbar",
    "UniqueLabelQListWidget": "unique_label_qlist_widget",
    "ViewportController": "viewport_controller",
    "VQADialog": "vqa_dialog",
    "ZoomWidget": "zoom_widget",
}

__all__ = tuple(_LAZY_IMPORTS)


def __getattr__(name: str) -> Any:
    """Import widget symbols only when they are requested."""
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value

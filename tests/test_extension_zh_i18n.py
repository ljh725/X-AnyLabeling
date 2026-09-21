"""Regression checks for Simplified Chinese text in fork UI extensions."""

from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TRANSLATION_PATH = _REPO_ROOT / "anylabeling/resources/translations/zh_CN.ts"
_SOURCE_PATHS = (
    "anylabeling/views/labeling/label_widget.py",
    "anylabeling/views/labeling/widgets/behavior_analytics_dialog.py",
    "anylabeling/views/labeling/widgets/dataset_thumbnail/advanced_controls.py",
    "anylabeling/views/labeling/widgets/dataset_thumbnail/browser.py",
    "anylabeling/views/labeling/widgets/dataset_thumbnail/history_browser.py",
    "anylabeling/views/labeling/widgets/dataset_thumbnail/history_flow.py",
    "anylabeling/views/labeling/widgets/dataset_thumbnail/history_panel.py",
    "anylabeling/views/labeling/widgets/dataset_thumbnail/incremental.py",
    "anylabeling/views/labeling/widgets/dataset_thumbnail/preview.py",
    "anylabeling/views/labeling/widgets/dataset_thumbnail/review_state.py",
    "anylabeling/views/labeling/widgets/density_round_review.py",
    "anylabeling/views/labeling/widgets/digit_bind_draw_manager.py",
    "anylabeling/views/labeling/widgets/digit_rename_manager.py",
    "anylabeling/views/labeling/widgets/inspector/dataset_review_widget.py",
    "anylabeling/views/labeling/widgets/inspector/inspector_panel.py",
    "anylabeling/views/labeling/widgets/inspector/quality_review_widget.py",
    "anylabeling/views/labeling/widgets/inspector/quality_scan_worker.py",
    "anylabeling/views/labeling/widgets/inspector/virtual_review_widget.py",
    "anylabeling/views/labeling/widgets/keypoint_tool_window.py",
    "anylabeling/views/labeling/widgets/object_field_edit_dialog.py",
    "anylabeling/views/labeling/widgets/object_relabel_dialog.py",
    "anylabeling/views/labeling/widgets/pose_label/pose_color_panel.py",
    "anylabeling/views/labeling/widgets/pose_label/pose_settings_panel.py",
    "anylabeling/views/labeling/widgets/pose_label/pose_view_panel.py",
    "anylabeling/views/labeling/widgets/rect_edge_click_controller.py",
    "anylabeling/views/labeling/widgets/rectangle_creation.py",
    "anylabeling/views/labeling/widgets/rectangle_size_rule_dialog.py",
)
_LATIN_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class _TranslationVisitor(ast.NodeVisitor):
    """Collect literal ``self.tr`` calls under their Qt class context."""

    def __init__(self) -> None:
        """Initialize the class stack and collected context/source pairs."""
        self.class_stack: list[str] = []
        self.messages: set[tuple[str, str]] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track the nearest class, which Qt uses as the translation context."""
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        """Record literal ``self.tr`` sources and ignore dynamic expressions."""
        function = node.func
        if (
            self.class_stack
            and isinstance(function, ast.Attribute)
            and function.attr == "tr"
            and isinstance(function.value, ast.Name)
            and function.value.id == "self"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            source = node.args[0].value
            if _LATIN_RE.search(source) and not _CJK_RE.search(source):
                self.messages.add((self.class_stack[-1], source))
        elif (
            isinstance(function, ast.Attribute)
            and function.attr == "translate"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            context = node.args[0].value
            source = node.args[1].value
            if _LATIN_RE.search(source) and not _CJK_RE.search(source):
                self.messages.add((context, source))
        self.generic_visit(node)


def _source_messages() -> set[tuple[str, str]]:
    """Extract English-source Qt messages from the fork's UI modules."""
    visitor = _TranslationVisitor()
    for relative_path in _SOURCE_PATHS:
        source_path = _REPO_ROOT / relative_path
        visitor.visit(ast.parse(source_path.read_text(encoding="utf-8")))
    return visitor.messages


def _finished_translations() -> set[tuple[str, str]]:
    """Return context/source pairs with non-empty Chinese translations."""
    root = ET.parse(_TRANSLATION_PATH).getroot()
    finished: set[tuple[str, str]] = set()
    for context in root.findall("context"):
        name = context.findtext("name", default="")
        for message in context.findall("message"):
            source = message.findtext("source", default="")
            translation = message.findtext("translation", default="")
            if translation.strip():
                finished.add((name, source))
    return finished


def test_extension_english_sources_have_chinese_translations() -> None:
    """Every English source in the audited fork UI has Chinese text."""
    missing = sorted(_source_messages() - _finished_translations())
    assert not missing, "Missing zh_CN translations:\n" + "\n".join(
        f"{context}: {source}" for context, source in missing
    )


def test_compiled_extension_chinese_translations(
    qapp: QtWidgets.QApplication,
) -> None:
    """The embedded QM resolves menu and independent-window contexts."""
    import anylabeling.resources.resources  # noqa: F401

    expected = {
        ("LabelingWidget", "Data Inspector"): "数据检查",
        ("LabelingWidget", "Cross-Image Object Marking"): "跨图对象标记",
        ("BehaviorAnalyticsDialog", "Local Behavior Analytics"): (
            "本地行为分析"
        ),
        ("KeypointToolWindow", "Keypoint Fill Tool"): "关键点补标工具",
        ("HistoryPanel", "Operation history"): "操作历史",
    }
    translator = QtCore.QTranslator()
    assert translator.load(":/languages/translations/zh_CN.qm")
    qapp.installTranslator(translator)
    try:
        for (context, source), translation in expected.items():
            assert (
                QtCore.QCoreApplication.translate(context, source)
                == translation
            )
    finally:
        qapp.removeTranslator(translator)

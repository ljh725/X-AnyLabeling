"""Translation-source coverage tests for rectangle-size validation UI."""

from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Dict, Set

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIALOG_SOURCE = (
    _REPO_ROOT
    / "anylabeling"
    / "views"
    / "labeling"
    / "widgets"
    / "rectangle_size_rule_dialog.py"
)
_TRANSLATION_DIR = _REPO_ROOT / "anylabeling" / "resources" / "translations"
_LANGUAGES = ("en_US", "zh_CN", "ja_JP", "ko_KR")
_DIALOG_CONTEXTS = ("RectangleSizeRuleTable", "RectangleSizeRuleDialog")
_LABELING_WIDGET_SOURCES = {
    "Show Rectangle Size Violations",
    "Show proactive warnings for configured rectangle size rules",
    "Configure Rectangle Size Rules",
    "Edit category-specific rectangle width and height thresholds",
}
_PLACEHOLDER_PATTERN = re.compile(r"\{[0-9]+\}|%(?:\.\d+)?[a-zA-Z]")


def _class_translation_sources(path: Path) -> Dict[str, Set[str]]:
    """Extract literal ``self.tr`` sources grouped by Python class."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sources: Dict[str, Set[str]] = {}
    for class_node in (
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ):
        class_sources = set()
        for node in ast.walk(class_node):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func
            if not (
                isinstance(function, ast.Attribute)
                and function.attr == "tr"
                and isinstance(function.value, ast.Name)
                and function.value.id == "self"
            ):
                continue
            source = node.args[0]
            if isinstance(source, ast.Constant) and isinstance(
                source.value,
                str,
            ):
                class_sources.add(source.value)
        if class_sources:
            sources[class_node.name] = class_sources
    return sources


def _context_translations(path: Path, context_name: str) -> Dict[str, str]:
    """Return source-to-translation text for one Qt TS context."""
    root = ElementTree.parse(path).getroot()
    for context in root.findall("context"):
        if context.findtext("name") != context_name:
            continue
        return {
            message.findtext("source", default=""): message.findtext(
                "translation",
                default="",
            )
            for message in context.findall("message")
        }
    return {}


@pytest.mark.parametrize("language", _LANGUAGES)
def test_all_dialog_sources_have_finished_translations(language: str) -> None:
    """Every literal dialog source must exist with non-empty translated text."""
    expected = _class_translation_sources(_DIALOG_SOURCE)
    translation_path = _TRANSLATION_DIR / f"{language}.ts"

    for context_name in _DIALOG_CONTEXTS:
        translations = _context_translations(translation_path, context_name)
        missing = expected[context_name] - translations.keys()
        empty = {
            source
            for source in expected[context_name]
            if not translations.get(source)
        }

        assert not missing, f"{language}/{context_name} missing: {missing}"
        assert not empty, f"{language}/{context_name} empty: {empty}"


@pytest.mark.parametrize("language", _LANGUAGES)
def test_dialog_translations_preserve_format_placeholders(
    language: str,
) -> None:
    """Translated runtime templates must preserve every source placeholder."""
    expected = _class_translation_sources(_DIALOG_SOURCE)
    translation_path = _TRANSLATION_DIR / f"{language}.ts"

    for context_name in _DIALOG_CONTEXTS:
        translations = _context_translations(translation_path, context_name)
        for source in expected[context_name]:
            source_placeholders = set(_PLACEHOLDER_PATTERN.findall(source))
            translated_placeholders = set(
                _PLACEHOLDER_PATTERN.findall(translations[source])
            )
            assert translated_placeholders == source_placeholders, (
                f"{language}/{context_name}/{source!r}: "
                f"{translated_placeholders} != {source_placeholders}"
            )


@pytest.mark.parametrize("language", _LANGUAGES)
def test_existing_canvas_pixel_overlay_sources_remain_translated(
    language: str,
) -> None:
    """The shared legacy/proactive overlay must retain its translated text."""
    translations = _context_translations(
        _TRANSLATION_DIR / f"{language}.ts",
        "Canvas",
    )
    expected = {
        "W %.1f px  H %.1f px",
        "Max edge %.1f px < %g px",
    }

    assert expected <= translations.keys()
    assert all(translations[source] for source in expected)


@pytest.mark.parametrize("language", _LANGUAGES)
def test_main_flow_actions_have_finished_translations(language: str) -> None:
    """Stage-ten menu actions must be present in every shipped language."""
    translations = _context_translations(
        _TRANSLATION_DIR / f"{language}.ts",
        "LabelingWidget",
    )

    assert _LABELING_WIDGET_SOURCES <= translations.keys()
    assert all(translations[source] for source in _LABELING_WIDGET_SOURCES)


@pytest.mark.parametrize("language", _LANGUAGES)
def test_main_flow_action_sources_are_not_duplicated(language: str) -> None:
    """Each feature action should compile from exactly one context message."""
    root = ElementTree.parse(_TRANSLATION_DIR / f"{language}.ts").getroot()
    messages = [
        message.findtext("source", default="")
        for context in root.findall("context")
        if context.findtext("name") == "LabelingWidget"
        for message in context.findall("message")
    ]

    for source in _LABELING_WIDGET_SOURCES:
        assert messages.count(source) == 1

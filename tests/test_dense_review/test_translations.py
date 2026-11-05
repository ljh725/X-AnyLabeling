"""Compiled translation coverage for the dense-review workflow."""

import os
import ast
import re
import unittest
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QTranslator

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS_DIR = REPO_ROOT / "anylabeling" / "resources" / "translations"
LANGUAGES = ("en_US", "zh_CN", "ja_JP", "ko_KR")

DENSE_REVIEW_CONTEXTS = (
    "DenseReviewWorkspace",
    "DenseReviewConfigDialog",
)

# Strings added for the redo action and the dense-review shortcut labels.
NEW_STRINGS = (
    ("LabelingWidget", "Redo"),
    ("LabelingWidget", "Redo the last undone shape edit"),
    ("SettingsDialog", "Redo"),
    ("SettingsDialog", "Open Dense Review Workspace"),
    ("SettingsDialog", "Dense Review: Complete Batch and Next"),
    ("SettingsDialog", "Dense Review: Complete Object and Next"),
    ("SettingsDialog", "Dense Review: Skip Object"),
    ("SettingsDialog", "Dense Review: Mark Difficult"),
    ("SettingsDialog", "Dense Review: Toggle Full Image View"),
)

_APPLICATION = None


def application():
    """Return one shared QCoreApplication for translator installation."""
    global _APPLICATION
    if _APPLICATION is None:
        _APPLICATION = QCoreApplication.instance() or QCoreApplication([])
    return _APPLICATION


def translate(language, context, source):
    """Load and install one .qm file, translate a message, uninstall it."""
    path = TRANSLATIONS_DIR / f"{language}.qm"
    if not path.is_file():
        raise AssertionError(f"compiled translation is missing: {path}")
    translator = QTranslator()
    if not translator.load(str(path)):
        raise AssertionError(f"cannot load compiled translation: {path}")
    instance = application()
    instance.installTranslator(translator)
    try:
        return instance.translate(context, source)
    finally:
        instance.removeTranslator(translator)


@lru_cache(maxsize=4)
def zh_messages(context):
    """Return the zh_CN <message> elements of one translation context."""
    tree = ET.parse(TRANSLATIONS_DIR / "zh_CN.ts")
    for node in tree.getroot().findall("context"):
        if node.findtext("name") == context:
            return {
                message.findtext("source"): message
                for message in node.findall("message")
            }
    raise AssertionError(f"context not found in zh_CN.ts: {context}")


def unfinished_reason(message):
    """Return why a message is not finished, or None when it is."""
    translation = message.find("translation")
    if message.get("type") == "unfinished":
        return "unfinished"
    if translation.get("type") == "unfinished":
        return "unfinished translation"
    if not (translation.text or "").strip():
        return "empty translation"
    return None


class TestDenseReviewTranslations(unittest.TestCase):
    def test_runtime_states_and_rules_are_localized(self):
        from anylabeling.services.dense_review.session import (
            DenseReviewSession,
        )
        from .conftest import make_config, make_shape

        session = DenseReviewSession.from_shapes(
            make_config(), [make_shape("id", "A")], "image", 100, 100
        )
        for language in LANGUAGES:
            translator = QTranslator()
            self.assertTrue(
                translator.load(str(TRANSLATIONS_DIR / f"{language}.qm"))
            )
            app = application()
            app.installTranslator(translator)
            try:

                def tr(source):
                    return app.translate("DenseReviewWorkspace", source)

                status = session.completion_status(tr)
                rules = session.rule_summary("A", tr)
                expected = tr("对象 #{index}（{label}）类别待审").format(
                    index=1, label="A"
                )
                self.assertIn(expected, status.reasons)
                self.assertIn(tr("未填写类别规则说明"), rules)
                if language != "zh_CN":
                    self.assertNotIn("类别待审", expected)
                    self.assertNotIn("未填写类别规则说明", rules)
            finally:
                app.removeTranslator(translator)

    def test_literal_messages_in_all_runtime_contexts_and_resources(self):
        """Check actual source contexts, not just representative messages."""
        from anylabeling.resources import resources  # noqa: F401

        entries = []
        folder = REPO_ROOT / "anylabeling/views/labeling/dense_review"
        for filename in ("workspace.py", "config_dialog.py"):
            tree = ast.parse((folder / filename).read_text(encoding="utf-8"))
            for cls in tree.body:
                if not isinstance(cls, ast.ClassDef):
                    continue
                for node in ast.walk(cls):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "tr"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        context = cls.name
                        if context == "_CardModel":
                            context = "DenseReviewWorkspace"
                        entries.append((context, node.args[0].value))
        for language in LANGUAGES:
            tree = ET.parse(TRANSLATIONS_DIR / f"{language}.ts")
            catalog = {
                node.findtext("name"): {
                    message.findtext("source"): message
                    for message in node.findall("message")
                }
                for node in tree.getroot().findall("context")
            }
            disk = QTranslator()
            embedded = QTranslator()
            self.assertTrue(
                disk.load(str(TRANSLATIONS_DIR / f"{language}.qm"))
            )
            self.assertTrue(
                embedded.load(f":/languages/translations/{language}.qm")
            )
            for context, source in set(entries):
                with self.subTest(
                    language=language, context=context, source=source
                ):
                    message = catalog.get(context, {}).get(source)
                    self.assertIsNotNone(message)
                    self.assertIsNone(unfinished_reason(message))
                    # QTranslator.translate exposes const char* and rejects
                    # non-ASCII Python str sources. The application uses
                    # QCoreApplication.translate, which encodes UTF-8.
                    app = application()
                    app.installTranslator(disk)
                    try:
                        translated = app.translate(context, source)
                    finally:
                        app.removeTranslator(disk)
                    self.assertTrue(translated)
                    app.installTranslator(embedded)
                    try:
                        actual = app.translate(context, source)
                    finally:
                        app.removeTranslator(embedded)
                    self.assertEqual(actual, translated)
                    self.assertEqual(
                        set(re.findall(r"\{\w+\}", translated)),
                        set(re.findall(r"\{\w+\}", source)),
                    )

    def test_every_language_loads(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                self.assertTrue(translate(language, "LabelingWidget", "Redo"))

    def test_en_us_keeps_source_text(self):
        self.assertEqual(translate("en_US", "LabelingWidget", "Redo"), "Redo")
        self.assertEqual(
            translate(
                "en_US",
                "LabelingWidget",
                "Redo the last undone shape edit",
            ),
            "Redo the last undone shape edit",
        )

    def test_redo_strings_are_translated(self):
        expected = {
            "zh_CN": ("重做", "重做上一步已撤销的形状编辑"),
            "ja_JP": ("やり直す", "元に戻した図形編集をやり直す"),
            "ko_KR": (
                "다시 실행",
                "실행 취소한 도형 편집을 다시 실행합니다",
            ),
        }
        for language, (label, tooltip) in expected.items():
            with self.subTest(language=language):
                self.assertEqual(
                    translate(language, "LabelingWidget", "Redo"), label
                )
                self.assertEqual(
                    translate(
                        language,
                        "LabelingWidget",
                        "Redo the last undone shape edit",
                    ),
                    tooltip,
                )
                # The settings dialog renders the same shortcut label.
                self.assertEqual(
                    translate(language, "SettingsDialog", "Redo"), label
                )

    def test_dense_review_strings_are_translated_for_chinese(self):
        cases = (
            (
                "DenseReviewWorkspace",
                "Dense Annotation Review",
                "密集标注复核",
            ),
            ("DenseReviewConfigDialog", "Batch name", "批次名称"),
            (
                "LabelingWidget",
                "Please open an image before opening dense review.",
                "请先打开图片，再打开密集复核。",
            ),
        )
        for context, source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(translate("zh_CN", context, source), expected)

    def test_workspace_messages_are_finished_in_chinese(self):
        unfinished = []
        for context in DENSE_REVIEW_CONTEXTS:
            for source, message in zh_messages(context).items():
                reason = unfinished_reason(message)
                if reason is not None:
                    unfinished.append(f"{context}: {source} ({reason})")
        self.assertEqual(unfinished, [])

    def test_new_strings_are_finished_in_chinese(self):
        missing = []
        for context, source in NEW_STRINGS:
            message = zh_messages(context).get(source)
            if message is None:
                missing.append(f"{context}: {source} (absent)")
                continue
            reason = unfinished_reason(message)
            if reason is not None:
                missing.append(f"{context}: {source} ({reason})")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()

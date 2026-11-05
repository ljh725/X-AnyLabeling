"""Translation wiring, shortcut scope and small-window usability."""

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from tests.test_inspection.test_inspector_dialog import (  # noqa: F401
    _prepare_image,
    _wait_until,
    window,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TS_DIR = REPO_ROOT / "anylabeling" / "resources" / "translations"
INSPECTOR_CONTEXT = "InspectorDialog"


def _catalog_sources(language: str) -> set:
    text = (TS_DIR / f"{language}.ts").read_text(encoding="utf-8")
    block = text.split(f"<name>{INSPECTOR_CONTEXT}</name>", 1)
    assert len(block) == 2, "Inspector context missing from catalog"
    body = block[1].split("</context>", 1)[0]
    return set(re.findall(r"<source>(.*?)</source>", body, re.S))


def _open(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    assert widget.load_file(_prepare_image(tmp_path))
    widget.open_inspector()
    dialog = widget.inspector_dialog
    return app, widget, dialog


def test_new_inspector_strings_are_in_the_translation_catalogs(window, tmp_path):
    _app, _widget, dialog = _open(window, tmp_path)
    sources = _catalog_sources("en_US")
    required = [
        "保留两者",
        "疑难暂存",
        "批量删除问题框",
        "按类别批量重标",
        "撤销上次修改",
        "交接密集复核",
        "调整后接受",
        "批量接受",
        "F5 开始检查 · Enter 定位选中问题",
    ]
    missing = [item for item in required if item not in sources]
    assert missing == []
    # Every shipped language must at least carry the same source strings so
    # the normal translation build can translate them.
    for language in ("zh_CN", "ja_JP", "ko_KR"):
        catalog = _catalog_sources(language)
        assert set(required).issubset(catalog), language
    # The buttons really go through Qt translation, not literal text.
    assert dialog.keep_both_button.text() == dialog.tr("保留两者")
    assert dialog.batch_delete_button.text() == dialog.tr("批量删除问题框")


def test_shortcut_hint_and_scope_do_not_take_canvas_keys(window, tmp_path):
    app, widget, dialog = _open(window, tmp_path)
    existing = widget.existing_shortcut_sequences()
    assert "F5" not in existing
    for sequence in (dialog.start_shortcut.key().toString(),
                     dialog.locate_shortcut.key().toString()):
        assert sequence not in existing
    assert dialog.start_shortcut.context() == (
        QtCore.Qt.ShortcutContext.WindowShortcut
    )
    assert dialog.locate_shortcut.context() == (
        QtCore.Qt.ShortcutContext.WidgetShortcut
    )
    assert "F5" in dialog.start_button.toolTip()
    assert "F5" in dialog.shortcut_hint.text()
    assert "Enter" in dialog.shortcut_hint.text()


def test_small_window_with_long_chinese_labels_stays_usable(
    window, tmp_path
):
    app, widget, dialog = _open(window, tmp_path)
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    dialog.resize(dialog.minimumSize())
    app.processEvents()
    assert dialog.width() >= dialog.minimumWidth()
    for button in (
        dialog.start_button,
        dialog.cancel_button,
        dialog.delete_button,
        dialog.batch_delete_button,
        dialog.batch_relabel_button,
        dialog.undo_button,
        dialog.handoff_button,
    ):
        assert not button.text().strip() == ""
        assert button.isVisibleTo(dialog)
    # Long Chinese labels must elide instead of forcing the table wider.
    long_label = "极长中文类别名称示例用于验证省略显示不会撑破小窗口布局"
    assert len(long_label) > 20
    dialog.issue_table.setRowCount(0)
    dialog.issue_table.insertRow(0)
    item = QtWidgets.QTableWidgetItem(long_label)
    item.setToolTip(long_label)
    dialog.issue_table.setItem(0, 2, item)
    app.processEvents()
    assert dialog.issue_table.textElideMode() == (
        QtCore.Qt.TextElideMode.ElideRight
    )
    assert dialog.issue_table.width() <= dialog.width()

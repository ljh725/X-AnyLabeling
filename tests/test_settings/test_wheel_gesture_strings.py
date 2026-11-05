"""Wheel gesture copy: settings text, catalogs and embedded resources.

The canvas mapping is ``Alt+Wheel`` for brush/rectangle editing,
``Alt+Shift+Wheel`` for the compare divider and ``Ctrl+Wheel`` for zoom.
The settings description, the four ``.ts`` catalogs and the compiled
``.qm`` files embedded in ``resources.py`` must all say the same thing:
a packaged build without the on-disk translations falls back to the
embedded copy, so a stale embedded catalog is a real user-visible defect.
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import SETTING_FIELD_MAP

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS_DIR = REPO_ROOT / "anylabeling" / "resources" / "translations"
LANGUAGES = ("en_US", "zh_CN", "ja_JP", "ko_KR")
CONTEXT = "SettingsDialog"
SOURCE = (
    "Use Alt+Wheel to adjust rectangle geometry while editing; "
    "Ctrl+Wheel always zooms. Disabled by default."
)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def translations_for(language, source, *, embedded):
    """Return ``source`` translated from the disk or embedded catalog."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    translator = QtCore.QTranslator()
    path = (
        ":/languages/translations/" + language + ".qm"
        if embedded
        else str(TRANSLATIONS_DIR / f"{language}.qm")
    )
    assert translator.load(path), path
    app.installTranslator(translator)
    try:
        return app.translate(CONTEXT, source)
    finally:
        app.removeTranslator(translator)


def test_rectangle_wheel_setting_describes_the_alt_gesture():
    field = SETTING_FIELD_MAP["canvas.wheel_rectangle_editing.enable"]
    assert "Alt+Wheel" in field.description
    assert "Ctrl+Wheel always zooms" in field.description
    assert "Ctrl+Wheel to adjust rectangle" not in field.description


@pytest.mark.parametrize("language", LANGUAGES)
def test_catalog_has_a_finished_translation(language):
    tree = ET.parse(TRANSLATIONS_DIR / f"{language}.ts")
    matches = [
        message
        for message in tree.getroot().iter("message")
        if (message.findtext("source") or "") == SOURCE
    ]
    assert len(matches) == 1
    message = matches[0]
    translation = message.find("translation")
    assert message.get("type") != "unfinished"
    assert translation.get("type") != "unfinished"
    assert (translation.text or "").strip()


@pytest.mark.parametrize("language", LANGUAGES)
def test_embedded_catalog_matches_the_disk_catalog(app, language):
    disk = translations_for(language, SOURCE, embedded=False)
    embedded = translations_for(language, SOURCE, embedded=True)
    assert embedded == disk
    assert "Alt" in embedded


def test_user_guides_describe_the_current_gestures():
    zh = (REPO_ROOT / "docs" / "zh_cn" / "user_guide.md").read_text(
        encoding="utf-8"
    )
    en = (REPO_ROOT / "docs" / "en" / "user_guide.md").read_text(
        encoding="utf-8"
    )

    assert "`Alt + 滚轮` 可调整笔刷大小" in zh
    assert "`Alt + Shift + 滚轮`" in zh
    assert "`Ctrl + 滚轮` 可调整笔刷大小" not in zh
    assert "按住 `Shift` 键并滚动鼠标滚轮" not in zh

    assert "`Alt + Wheel` to resize the brush" in en
    assert "`Alt + Shift + Wheel`" in en
    assert "`Ctrl + Wheel` to resize the brush" not in en
    assert "hold `Shift` while scrolling the mouse wheel" not in en

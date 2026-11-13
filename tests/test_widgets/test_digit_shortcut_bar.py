"""The hint strip stays compact and delegates to the existing shortcuts."""

import pytest
from PyQt6 import QtCore

from anylabeling.views.labeling.widgets.digit_shortcut_bar import (
    DigitShortcutBar,
)
from anylabeling.views.labeling.utils.theme import get_mode, init_theme


@pytest.fixture
def bar(qt_application):
    widget = DigitShortcutBar()
    widget.set_mappings(
        {
            0: {"mode": "rectangle", "label": "hidden zero"},
            1: {"mode": "rectangle", "label": "Pen/Pencil"},
            "2": {
                "mode": "polygon",
                "label": "很长的类别名称，需要显示省略号",
            },
            3: {"mode": "unsupported", "label": "invalid"},
        }
    )
    widget.set_interactions_enabled(True)
    yield widget
    widget.close()
    widget.deleteLater()
    qt_application.processEvents()


@pytest.mark.parametrize("width", [480, 720, 1024, 1280, 1600])
@pytest.mark.parametrize("font_scale", [1.0, 1.5, 2.0])
def test_nine_equal_cards_stay_on_one_row(
    bar, qt_application, width, font_scale
):
    font = bar.font()
    font.setPointSizeF(font.pointSizeF() * font_scale)
    bar.setFont(font)
    bar.resize(width, bar.sizeHint().height())
    bar.show()
    qt_application.processEvents()

    rectangles = [button.geometry() for button in bar.buttons.values()]
    assert list(bar.buttons) == list(range(1, 10))
    assert bar.width() == width
    assert len({rect.y() for rect in rectangles}) == 1
    assert (
        max(rect.width() for rect in rectangles)
        - min(rect.width() for rect in rectangles)
        <= 1
    )
    assert all(rect.width() > 0 for rect in rectangles)
    assert all(
        left.right() < right.left()
        for left, right in zip(rectangles, rectangles[1:])
    )
    assert rectangles[-1].right() < bar.width()
    assert bar.height() == bar.buttons[1].height() + 10
    assert bar.buttons[2].toolTip() == "2 很长的类别名称，需要显示省略号"
    assert not bar.grab().isNull()


def test_binding_updates_and_disabled_entries(bar):
    assert bar.buttons[1].isEnabled()
    assert bar.buttons[2].isEnabled()
    assert not bar.buttons[3].isEnabled()
    assert not bar.buttons[9].isEnabled()
    bar.set_active_digit(1)
    bar.set_mappings({2: {"mode": "rectangle", "label": "Book"}})
    assert not bar.buttons[1].isEnabled()
    assert not bar.buttons[1].isChecked()
    assert bar.buttons[2].label == "Book"
    assert bar.buttons[2].isEnabled()


def test_chinese_menu_and_unbound_labels(bar, qt_application):
    from anylabeling.app import load_translator

    translator = load_translator("zh_CN")
    assert translator is not None
    qt_application.installTranslator(translator)
    try:
        bar.set_mappings({})
        assert bar.buttons[1].label == "未绑定"
        assert bar.buttons[1].text() == "1 未绑定"
        assert QtCore.QCoreApplication.translate(
            "LabelingWidget", "Digit Key Hints"
        ) == "数字键提示"
    finally:
        qt_application.removeTranslator(translator)


def test_click_delegates_without_selecting_an_ignored_action(bar):
    calls = []
    bar.digit_activated.connect(calls.append)
    bar.buttons[1].click()
    assert calls == [1]
    assert not bar.buttons[1].isChecked()
    bar.set_active_digit(1)
    assert bar.buttons[1].isChecked()
    bar.set_interactions_enabled(False)
    bar.buttons[2].click()
    assert calls == [1]
    assert not any(button.isEnabled() for button in bar.buttons.values())
    assert all(
        button.focusPolicy() == QtCore.Qt.FocusPolicy.NoFocus
        for button in bar.buttons.values()
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_active_hint_uses_the_current_theme(bar, qt_application, theme):
    previous = get_mode()
    try:
        init_theme(theme)
        bar.resize(900, bar.sizeHint().height())
        bar.show()
        qt_application.processEvents()
        normal = bar.buttons[1].grab().toImage()
        bar.set_active_digit(1)
        active = bar.buttons[1].grab().toImage()
        assert normal != active
    finally:
        init_theme(previous)


def test_shared_resolver_handles_legacy_entries():
    from anylabeling.views.labeling.widgets.digit_shortcut_bar import (
        resolve_digit_mapping,
    )

    mappings = {
        1: {"mode": "rectangle"},
        "2": {"mode": "polygon", "label": "Car"},
        3: {"mode": "rectangle", "label": "  "},
        4: {"mode": "nope", "label": "x"},
        0: {"mode": "point", "label": "zero"},
    }
    assert resolve_digit_mapping(mappings, 1) == ("object", "rectangle")
    assert resolve_digit_mapping(mappings, 2) == ("Car", "polygon")
    assert resolve_digit_mapping(mappings, 3) == ("object", "rectangle")
    assert resolve_digit_mapping(mappings, 4) is None
    assert resolve_digit_mapping(mappings, 5) is None
    assert resolve_digit_mapping(mappings, 0) == ("zero", "point")
    assert resolve_digit_mapping(None, 1) is None


def test_mode_only_mapping_uses_default_label(bar):
    bar.set_mappings({1: {"mode": "rectangle"}})
    assert bar.buttons[1].label == "object"
    assert bar.buttons[1].isEnabled()
    assert list(bar.buttons) == list(range(1, 10))


def test_identical_inputs_skip_refresh_but_label_change_refreshes(bar):
    mapping = {1: {"mode": "rectangle", "label": "A"}}
    bar.set_mappings(mapping)
    bar.set_active_digit(1)
    calls = []
    original = bar._refresh_buttons
    bar._refresh_buttons = lambda: (calls.append(1), original())
    bar.set_mappings({"1": {"mode": "rectangle", "label": "A"}})
    bar.set_interactions_enabled(True)
    bar.set_active_digit(1)
    assert calls == []
    bar.set_mappings({1: {"mode": "rectangle", "label": "B"}})
    assert calls == [1]
    button = bar.buttons[1]
    assert button.text() == "1 B"
    assert button.toolTip() == "1 B"
    assert button.accessibleName() == "1 B"
    assert button.isChecked()


def test_embedded_translation_covers_digit_hints(qt_application):
    from anylabeling.resources import resources  # noqa: F401

    translator = QtCore.QTranslator()
    assert translator.load(":/languages/translations/zh_CN.qm")
    assert translator.translate("DigitShortcutBar", "Unbound") == "未绑定"
    assert (
        translator.translate("LabelingWidget", "Digit Key Hints")
        == "数字键提示"
    )

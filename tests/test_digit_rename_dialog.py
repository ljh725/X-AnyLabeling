"""Regression checks for digit rename editor geometry and interaction."""

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.views.labeling.utils.theme import get_app_stylesheet
from anylabeling.views.labeling.widgets.digit_rename_manager import (
    DigitRenameShortcutDialog,
)


@pytest.fixture
def dialog(
    qapp: QtWidgets.QApplication,
) -> Iterator[DigitRenameShortcutDialog]:
    """Show a populated dialog using the application's real stylesheet."""
    previous_style = qapp.styleSheet()
    qapp.setStyleSheet(get_app_stylesheet())
    parent = QtWidgets.QWidget()
    parent.digit_rename_manager = SimpleNamespace(
        rename_shortcuts={
            0: {"label": "person_abcdefghijklmnopqrstuvwxyz_0123456789"},
            1: {"label": "中文标签_head"},
            9: {"label": "last_label"},
        }
    )
    widget = DigitRenameShortcutDialog(parent)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    parent.close()
    widget.deleteLater()
    parent.deleteLater()
    qapp.processEvents()
    qapp.setStyleSheet(previous_style)


def _text_rect(editor: QtWidgets.QLineEdit) -> QtCore.QRect:
    """Return the styled area available for rendering the input text."""
    option = QtWidgets.QStyleOptionFrame()
    editor.initStyleOption(option)
    return editor.style().subElementRect(
        QtWidgets.QStyle.SubElement.SE_LineEditContents, option, editor
    )


def test_loaded_labels_fit(dialog: DigitRenameShortcutDialog) -> None:
    """Keep glyphs and ordinary long labels visible at initial size."""
    for row in (0, 1, 9):
        editor = dialog._table.cellWidget(row, 1)
        assert _text_rect(editor).height() >= editor.fontMetrics().height()
        assert editor.height() >= editor.sizeHint().height()
        assert editor.cursorPosition() == 0
    editor = dialog._table.cellWidget(0, 1)
    assert _text_rect(editor).width() > editor.fontMetrics().horizontalAdvance(
        editor.text()
    )


def test_focus_preserves_text_geometry(
    dialog: DigitRenameShortcutDialog, qapp: QtWidgets.QApplication
) -> None:
    """Changing focus must not shift the content rectangle."""
    editor = dialog._table.cellWidget(0, 1)
    dialog._table.cellWidget(1, 1).setFocus()
    qapp.processEvents()
    before = _text_rect(editor)
    editor.setFocus()
    qapp.processEvents()
    assert _text_rect(editor) == before


def test_drag_selection_survives_mouse_movement(
    dialog: DigitRenameShortcutDialog, qapp: QtWidgets.QApplication
) -> None:
    """Keep the drag selection after releasing and moving between rows."""
    editor = dialog._table.cellWidget(0, 1)
    rect = _text_rect(editor)
    start = QtCore.QPoint(rect.left() + 5, rect.center().y())
    end = QtCore.QPoint(rect.left() + 100, rect.center().y())
    QtTest.QTest.mousePress(
        editor, QtCore.Qt.MouseButton.LeftButton, pos=start
    )
    move = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        QtCore.QPointF(end),
        QtCore.QPointF(editor.mapToGlobal(end)),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(editor, move)
    QtTest.QTest.mouseRelease(
        editor, QtCore.Qt.MouseButton.LeftButton, pos=end
    )
    selection = (editor.selectionStart(), editor.selectedText())
    assert selection[1]
    QtTest.QTest.mouseMove(
        dialog._table.cellWidget(1, 1), QtCore.QPoint(15, 10)
    )
    QtTest.QTest.mouseMove(editor, start)
    qapp.processEvents()
    assert (editor.selectionStart(), editor.selectedText()) == selection
    assert editor.hasFocus()


@pytest.mark.parametrize("row", [0, 9])
def test_enter_moves_without_accepting(
    dialog: DigitRenameShortcutDialog,
    qapp: QtWidgets.QApplication,
    row: int,
) -> None:
    """Enter advances or wraps and never submits the dialog."""
    editor = dialog._table.cellWidget(row, 1)
    editor.setFocus()
    QtTest.QTest.keyClick(editor, QtCore.Qt.Key.Key_Return)
    qapp.processEvents()
    following = dialog._table.cellWidget((row + 1) % 10, 1)
    assert following.hasFocus()
    assert following.selectedText() == following.text()
    assert dialog.isVisible()


def test_tab_order_and_editing(dialog: DigitRenameShortcutDialog) -> None:
    """Tab traverses rows and editing updates mappings without resetting text."""
    first = dialog._table.cellWidget(0, 1)
    second = dialog._table.cellWidget(1, 1)
    first.setFocus()
    QtTest.QTest.keyClick(first, QtCore.Qt.Key.Key_Tab)
    assert second.hasFocus()
    QtTest.QTest.keyClick(
        second, QtCore.Qt.Key.Key_Tab, QtCore.Qt.KeyboardModifier.ShiftModifier
    )
    assert first.hasFocus()
    QtTest.QTest.keyClick(
        first, QtCore.Qt.Key.Key_A, QtCore.Qt.KeyboardModifier.ControlModifier
    )
    QtTest.QTest.keyClicks(first, "new_label ")
    assert first.text() == "new_label "
    assert first.cursorPosition() == len("new_label ")
    assert dialog.rename_shortcuts[0] == {"label": "new_label"}
    assert "new_label " in first.toolTip()


@pytest.mark.parametrize("point_size", [14, 20])
def test_large_font_and_overlong_label(
    qapp: QtWidgets.QApplication, point_size: int
) -> None:
    """Fit taller fonts and cap long-label windows to the available screen."""
    parent = QtWidgets.QWidget()
    font = parent.font()
    font.setPointSize(point_size)
    parent.setFont(font)
    label = "中文长标签_<head>&" * 40
    parent.digit_rename_manager = SimpleNamespace(
        rename_shortcuts={0: {"label": label}}
    )
    widget = DigitRenameShortcutDialog(parent)
    try:
        widget.show()
        qapp.processEvents()
        editor = widget._table.cellWidget(0, 1)
        assert editor.text() == label
        assert editor.cursorPosition() == 0
        assert "&lt;head&gt;&amp;" in editor.toolTip()
        assert _text_rect(editor).height() >= editor.fontMetrics().height()
        available = widget.screen().availableGeometry()
        assert widget.width() <= available.width() * 0.9
        assert widget.height() <= available.height() * 0.9
    finally:
        widget.close()
        parent.close()
        widget.deleteLater()
        parent.deleteLater()
        qapp.processEvents()

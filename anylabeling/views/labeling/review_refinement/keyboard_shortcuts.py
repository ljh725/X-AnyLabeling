"""Shared Qt key normalization and audited rectangle shortcut scopes."""

from PyQt6 import QtCore, QtGui

from .keyboard_fitting import BOUNDARY_KEYS

BOUNDARY_PATHS = {f"shortcuts.{name}" for name in BOUNDARY_KEYS}
REUSED_ACTIONS = {
    "Q": "shortcuts.auto_labeling_add_point",
    "W": "shortcuts.show_hidden_polygons",
    "E": "shortcuts.auto_labeling_remove_point",
    "R": "shortcuts.create_rectangle",
}


def key_sequence(event: QtGui.QKeyEvent) -> str:
    """Normalize keypad digits while preserving meaningful modifiers."""
    modifiers = event.modifiers() & ~QtCore.Qt.KeyboardModifier.KeypadModifier
    return QtGui.QKeySequence(event.key() | modifiers.value).toString(
        QtGui.QKeySequence.SequenceFormat.PortableText
    )


def boundary_key_valid(sequence: str) -> bool:
    """Reject task control keys and multi-stroke sequences."""
    key = QtGui.QKeySequence(sequence)
    if key.count() != 1:
        return False
    reserved = {
        QtCore.Qt.Key.Key_Return,
        QtCore.Qt.Key.Key_Enter,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.Key.Key_Backspace,
        QtCore.Qt.Key.Key_Tab,
        QtCore.Qt.Key.Key_Backtab,
        QtCore.Qt.Key.Key_Left,
        QtCore.Qt.Key.Key_Right,
        QtCore.Qt.Key.Key_Up,
        QtCore.Qt.Key.Key_Down,
        QtCore.Qt.Key.Key_Delete,
        QtCore.Qt.Key.Key_unknown,
    }
    return key[0].key() not in reserved and sequence not in (
        "Ctrl+Z",
        "Ctrl+Shift+Z",
        "Ctrl+Y",
    )


def controlled_reuse(sequence: str, paths: list[str]) -> bool:
    """Allow only one boundary key and its audited ordinary action."""
    boundary = set(paths) & BOUNDARY_PATHS
    other = set(paths) - BOUNDARY_PATHS
    return len(boundary) == 1 and other == {REUSED_ACTIONS.get(sequence)}

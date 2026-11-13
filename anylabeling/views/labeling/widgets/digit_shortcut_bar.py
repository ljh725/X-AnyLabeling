"""Compact, single-row hints for the existing digit shortcut mappings."""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ..shape import Shape
from ..utils.theme import get_theme

DEFAULT_DIGIT_LABEL = "object"


def resolve_digit_mapping(mappings, digit):
    """Return ``(label, mode)`` for one digit, or ``None`` when unbound.

    Shared by the physical keys and the hint cards. Integer and string keys
    are both accepted; an entry with only a ``mode`` (older configs) uses the
    default label ``object``.
    """
    if not isinstance(mappings, dict):
        return None
    data = mappings.get(digit)
    if data is None:
        data = mappings.get(str(digit))
    if not isinstance(data, dict):
        return None
    mode = data.get("mode")
    if mode not in Shape.get_supported_shape():
        return None
    label = data.get("label")
    if not isinstance(label, str) or not label.strip():
        label = DEFAULT_DIGIT_LABEL
    return label, mode


class DigitShortcutButton(QtWidgets.QAbstractButton):
    def __init__(self, digit, parent=None):
        super().__init__(parent)
        self.digit = digit
        self.label = ""
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.setMinimumWidth(0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QtCore.QSize(120, max(32, self.fontMetrics().height() + 12))

    def minimumSizeHint(self):
        return QtCore.QSize(0, self.sizeHint().height())

    def paintEvent(self, event):
        theme = get_theme()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        active = self.isChecked() and self.isEnabled()
        background = QtGui.QColor(theme["background"])
        if active:
            tint = QtGui.QColor(theme["primary"])
            tint.setAlpha(22)
            painter.fillRect(self.rect(), background)
            background = tint
        elif self.underMouse() and self.isEnabled():
            background = QtGui.QColor(theme["surface_hover"])
        painter.setPen(
            QtGui.QColor(theme["primary"] if active else theme["border"])
        )
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 5, 5)

        metrics = self.fontMetrics()
        # All coordinates are Qt logical pixels, including on scaled displays.
        padding = 6 if self.width() >= 80 else 3
        badge_width = metrics.horizontalAdvance(str(self.digit)) + 12
        badge_height = metrics.height() + 4
        badge = QtCore.QRectF(
            padding,
            (self.height() - badge_height) / 2,
            badge_width,
            badge_height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QtGui.QColor(theme["primary"] if active else theme["surface"])
        )
        painter.drawRoundedRect(badge, 3, 3)
        painter.setPen(
            QtGui.QColor(
                theme["selection_text"] if active else theme["text_secondary"]
            )
        )
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self.digit))

        label_rect = QtCore.QRectF(
            badge.right() + 5,
            0,
            max(0, self.width() - badge.right() - 5 - padding),
            self.height(),
        )
        painter.setPen(
            QtGui.QColor(
                theme["text"] if self.isEnabled() else theme["text_secondary"]
            )
        )
        text = metrics.elidedText(
            self.label, Qt.TextElideMode.ElideRight, int(label_rect.width())
        )
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )


class DigitShortcutBar(QtWidgets.QFrame):
    digit_activated = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("digitShortcutBar")
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.setMinimumWidth(0)
        self._mappings = None
        self._interactions_enabled = False
        self._active_digit = None
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(5)
        self.buttons = {}
        for digit in range(1, 10):
            button = DigitShortcutButton(digit, self)
            button.clicked.connect(
                lambda _checked, digit=digit: self._activate(digit)
            )
            layout.addWidget(button, 1)
            self.buttons[digit] = button
        self.set_mappings({})

    def set_mappings(self, mappings):
        normalized = {}
        for digit in range(1, 10):
            entry = resolve_digit_mapping(mappings, digit)
            if entry is not None:
                normalized[digit] = entry
        if normalized == self._mappings:
            return
        self._mappings = normalized
        if self._active_digit not in normalized:
            self._active_digit = None
        for digit, button in self.buttons.items():
            entry = normalized.get(digit)
            label = entry[0] if entry else self.tr("Unbound")
            text = f"{digit} {label}"
            button.label = label
            button.setText(text)
            button.setAccessibleName(text)
            button.setToolTip(text)
        self._refresh_buttons()

    def set_interactions_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._interactions_enabled:
            return
        self._interactions_enabled = enabled
        self._refresh_buttons()

    def set_active_digit(self, digit):
        digit = digit if digit in (self._mappings or {}) else None
        if digit == self._active_digit:
            return
        self._active_digit = digit
        self._refresh_buttons()

    def _refresh_buttons(self):
        mappings = self._mappings or {}
        for digit, button in self.buttons.items():
            button.setEnabled(self._interactions_enabled and digit in mappings)
            button.setChecked(digit == self._active_digit)
            button.update()

    def _activate(self, digit):
        # The host's existing shortcut handler decides whether this action
        # may run (unfinished geometry and locked selections stay protected).
        self._refresh_buttons()
        self.digit_activated.emit(digit)

    def paintEvent(self, event):
        theme = get_theme()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QColor(theme["border"]))
        painter.setBrush(QtGui.QColor(theme["surface"]))
        painter.drawRoundedRect(
            QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9
        )

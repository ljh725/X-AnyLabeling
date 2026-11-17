"""Small wrapping rows for dock controls on narrow screens."""

from PyQt6 import QtCore, QtWidgets


class WrappingRow(QtWidgets.QLayout):
    """Wrap controls while retaining tab order and their full tooltips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self.setSpacing(8)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < self.count() else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < self.count() else None

    def addStretch(self, stretch=0):
        """Wrapping rows use natural widths rather than horizontal spacers."""

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QtCore.QRect(0, 0, width, 0), True)

    def minimumSize(self):
        size = QtCore.QSize(0, 0)
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, False)

    def _arrange(self, rect, measure):
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            size.setWidth(min(size.width(), max(1, area.width())))
            if x + size.width() > area.right() + 1 and line:
                x, y, line = area.x(), y + line + self.spacing(), 0
            if not measure:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), size))
            x += size.width() + self.spacing()
            line = max(line, size.height())
        return y + line - rect.y() + bottom

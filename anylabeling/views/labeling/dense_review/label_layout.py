"""Bounded screen-space label placement with stable drag anchors."""

from collections import OrderedDict

from PyQt6 import QtCore


class ReviewLabelLayout:
    """Place finite label candidates using a small spatial collision index."""

    def __init__(self):
        self._measurements = OrderedDict()
        self._placements = {}
        self._frame = None
        self._dragging = False
        self._cells = {}
        self.fallback_ids = set()

    def measure(self, font, dpi, text, metrics):
        """Cache screen text metrics by font, DPI and complete text."""
        key = (font.toString(), dpi, text)
        if key not in self._measurements:
            self._measurements[key] = (
                metrics.tightBoundingRect(text).width() + 8,
                metrics.height() + 4,
            )
        self._measurements.move_to_end(key)
        while len(self._measurements) > 512:
            self._measurements.popitem(last=False)
        return self._measurements[key]

    @staticmethod
    def _keys(rect):
        for x in range(rect.left() // 64, rect.right() // 64 + 1):
            for y in range(rect.top() // 64, rect.bottom() // 64 + 1):
                yield x, y

    def _block(self, rect):
        for key in self._keys(rect):
            self._cells.setdefault(key, []).append(rect)

    def begin(self, frame, dragging, handles):
        """Retain placements for unchanged frames and freeze drag offsets."""
        if not dragging and (frame != self._frame or self._dragging):
            self._placements.clear()
        self._frame, self._dragging = frame, dragging
        self._cells.clear()
        self.fallback_ids.clear()
        for rect in handles:
            self._block(rect)

    def place(self, shape_id, rect, viewport, current=False):
        """Return a collision-free label rectangle, or request a number."""
        origin = rect.topLeft()
        cached = self._placements.get(shape_id)
        if cached is not None:
            offset, fallback = cached
            result = QtCore.QRect(rect)
            result.moveTopLeft(origin + offset)
            if fallback:
                self.fallback_ids.add(shape_id)
            self._block(result)
            return result, fallback
        width, height = rect.width(), rect.height()
        offsets = (
            (0, 0),
            (width + 10, 0),
            (-width - 10, 0),
            (0, height + 18),
            (0, -height - 8),
            (width + 10, height + 18),
            (-width - 10, height + 18),
        )
        for dx, dy in offsets:
            candidate = rect.translated(dx, dy)
            collisions = any(
                candidate.intersects(other)
                for key in self._keys(candidate)
                for other in self._cells.get(key, ())
            )
            if viewport.contains(candidate) and not collisions:
                self._placements[shape_id] = (
                    candidate.topLeft() - origin,
                    False,
                )
                self._block(candidate)
                return candidate, False
        result = QtCore.QRect(rect)
        fallback = not current
        if fallback:
            result.setWidth(min(48, result.width()))
            self.fallback_ids.add(shape_id)
        result.moveLeft(
            max(
                viewport.left(),
                min(result.left(), viewport.right() - result.width()),
            )
        )
        result.moveTop(
            max(
                viewport.top(),
                min(result.top(), viewport.bottom() - result.height()),
            )
        )
        self._placements[shape_id] = (result.topLeft() - origin, fallback)
        self._block(result)
        return result, fallback

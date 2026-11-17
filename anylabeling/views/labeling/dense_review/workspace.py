"""Non-modal dense annotation review workspace."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.services.dense_review.models import (
    NEW_PENDING_BATCH_ID,
    OTHER_BATCH_ID,
    REVIEW_DIMENSIONS,
    CoverageSettings,
)

from ..correction_metrics.hooks import notify_metrics
from ..utils.qt import themed_icon
from ..utils.style import blend_hex, get_dialog_style, get_workbench_qss
from ..utils.theme import get_theme
from .config_dialog import DenseReviewConfigDialog
from .thumbnails import ThumbnailProvider

STATUS_COLORS = {
    "done": "success",
    "difficult": "warning",
    "skipped": "primary",
    "pending": "border_light",
}


class _BatchDelegate(QtWidgets.QStyledItemDelegate):
    """Card-like rows for the category batches."""

    ROW_HEIGHT = 70

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter, option, index):
        theme = get_theme()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(option.rect).adjusted(1, 3, -1, -3)
        selected = bool(
            option.state & QtWidgets.QStyle.StateFlag.State_Selected
        )
        background = (
            blend_hex(theme["primary"], theme["background"], 0.10)
            if selected
            else theme["background"]
        )
        border = theme["primary"] if selected else theme["border_light"]
        painter.setPen(QtGui.QPen(QtGui.QColor(border), 1))
        painter.setBrush(QtGui.QColor(background))
        painter.drawRoundedRect(rect, 10, 10)

        total = int(index.data(QtCore.Qt.ItemDataRole.UserRole + 1) or 0)
        category = int(index.data(QtCore.Qt.ItemDataRole.UserRole + 2) or 0)
        geometry = int(index.data(QtCore.Qt.ItemDataRole.UserRole + 3) or 0)

        name_font = QtGui.QFont(option.font)
        name_font.setPixelSize(13)
        name_font.setWeight(QtGui.QFont.Weight.Medium)
        painter.setFont(name_font)
        painter.setPen(QtGui.QColor(theme["text"]))
        name_rect = QtCore.QRectF(
            rect.left() + 10, rect.top() + 7, rect.width() - 46, 18
        )
        name = str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")
        metrics = QtGui.QFontMetrics(name_font)
        painter.drawText(
            name_rect,
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(
                name,
                QtCore.Qt.TextElideMode.ElideRight,
                int(name_rect.width()),
            ),
        )

        count_font = QtGui.QFont(option.font)
        count_font.setPixelSize(11)
        painter.setFont(count_font)
        painter.setPen(QtGui.QColor(theme["text_secondary"]))
        painter.drawText(
            QtCore.QRectF(rect.right() - 40, rect.top() + 7, 30, 18),
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            str(total),
        )

        track = QtCore.QRectF(
            rect.left() + 10, rect.top() + 34, rect.width() - 20, 4
        )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(theme["border"]))
        painter.drawRoundedRect(track, 2, 2)
        if total:
            ratio = (category + geometry) / (2.0 * total)
            fill = QtCore.QRectF(track)
            fill.setWidth(track.width() * ratio)
            painter.setBrush(QtGui.QColor(theme["primary"]))
            painter.drawRoundedRect(fill, 2, 2)

        painter.setPen(QtGui.QColor(theme["text_secondary"]))
        painter.drawText(
            QtCore.QRectF(
                rect.left() + 10, rect.top() + 44, rect.width() - 20, 16
            ),
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "类别 {}/{} · 框 {}/{}".format(category, total, geometry, total),
        )
        painter.restore()


class _CardModel(QtCore.QAbstractListModel):
    """Virtualized card rows.

    ``QListView`` asks this model only for the rows it paints, so a 300
    object batch never materializes 300 widgets or 300 QIcons.  The bounded
    icon cache and the explicit ``retain_icons`` call keep graphical
    resources proportional to the visible (plus prefetch) cards; text-only
    state refreshes emit ``dataChanged`` and never re-crop source pixels.
    """

    ICON_LIMIT = 48
    ROLE_SHAPE_ID = QtCore.Qt.ItemDataRole.UserRole
    ROLE_TITLE = QtCore.Qt.ItemDataRole.UserRole + 1
    ROLE_STATUS = QtCore.Qt.ItemDataRole.UserRole + 2
    ROLE_MARKERS = QtCore.Qt.ItemDataRole.UserRole + 3
    ROLE_STATE = QtCore.Qt.ItemDataRole.UserRole + 4

    TEXT_ROLES = (
        QtCore.Qt.ItemDataRole.DisplayRole,
        QtCore.Qt.ItemDataRole.ToolTipRole,
        QtCore.Qt.ItemDataRole.AccessibleTextRole,
        ROLE_TITLE,
        ROLE_STATUS,
        ROLE_MARKERS,
        ROLE_STATE,
    )

    def __init__(self, host: Any, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._ids: list[str] = []
        self._rows: dict[str, int] = {}
        self._states: dict[str, Any] = {}
        self._icons: OrderedDict[str, QtGui.QIcon] = OrderedDict()
        self._failed: set[str] = set()
        self._placeholder = QtGui.QIcon(self._placeholder_pixmap())

    @staticmethod
    def _placeholder_pixmap() -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(180, 120)
        pixmap.fill(QtGui.QColor("#EEF1F4"))
        return pixmap

    # -- rows ----------------------------------------------------------

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._ids)

    def shape_ids(self) -> tuple[str, ...]:
        return tuple(self._ids)

    def row_for(self, shape_id: str) -> int:
        return self._rows.get(shape_id, -1)

    def state_at(self, row: int):
        if 0 <= row < len(self._ids):
            return self._states.get(self._ids[row])
        return None

    def set_rows(self, states: Iterable[Any], failed: Iterable[str]) -> None:
        rows = list(states)
        self.beginResetModel()
        self._ids = [item.shape_id for item in rows]
        self._rows = {shape_id: row for row, shape_id in enumerate(self._ids)}
        self._states = {item.shape_id: item for item in rows}
        self._failed = set(failed)
        self._icons.clear()
        self.endResetModel()

    def update_states(
        self, states: Iterable[Any], failed: Iterable[str]
    ) -> None:
        rows = list(states)
        if [item.shape_id for item in rows] != self._ids:
            self.set_rows(rows, failed)
            return
        self._states = {item.shape_id: item for item in rows}
        changed_failure = set(failed) != self._failed
        self._failed = set(failed)
        roles = list(self.TEXT_ROLES)
        if changed_failure:
            roles.append(QtCore.Qt.ItemDataRole.DecorationRole)
        if self._ids:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._ids) - 1, 0), roles
            )

    # -- icons ---------------------------------------------------------

    def set_icon(self, shape_id: str, icon: QtGui.QIcon) -> None:
        self._icons[shape_id] = icon
        self._icons.move_to_end(shape_id)
        while len(self._icons) > self.ICON_LIMIT:
            self._icons.popitem(last=False)
        row = self.row_for(shape_id)
        if row >= 0:
            index = self.index(row, 0)
            self.dataChanged.emit(
                index,
                index,
                [QtCore.Qt.ItemDataRole.DecorationRole],
            )

    def icon_for(self, shape_id: str) -> Optional[QtGui.QIcon]:
        icon = self._icons.get(shape_id)
        if icon is not None:
            self._icons.move_to_end(shape_id)
        return icon

    def retain_icons(self, keep: Iterable[str]) -> None:
        keep = set(keep)
        for shape_id in [key for key in self._icons if key not in keep]:
            del self._icons[shape_id]

    def clear_icon(self, shape_id: str) -> None:
        if self._icons.pop(shape_id, None) is None:
            return
        row = self.row_for(shape_id)
        if row >= 0:
            index = self.index(row, 0)
            self.dataChanged.emit(
                index,
                index,
                [QtCore.Qt.ItemDataRole.DecorationRole],
            )

    def icon_count(self) -> int:
        return len(self._icons)

    def set_failed(self, shape_id: str, reason: str) -> None:
        self._failed.add(shape_id)
        self._notify_text(shape_id)

    def clear_failed(self, shape_id: str) -> None:
        if shape_id in self._failed:
            self._failed.discard(shape_id)
            self._notify_text(shape_id)

    def _notify_text(self, shape_id: str) -> None:
        row = self.row_for(shape_id)
        if row >= 0:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, list(self.TEXT_ROLES))

    # -- data ----------------------------------------------------------

    def _markers(self, item) -> tuple[str, str]:
        tr = self._host.tr
        markers = []
        if item.confirmed("category"):
            markers.append(tr("类别✓"))
        if item.confirmed("geometry"):
            markers.append(tr("框✓"))
        return " · ".join(markers) or tr("待审"), ""

    def _state(self, item) -> str:
        if item.confirmed("category") and item.confirmed("geometry"):
            return "done"
        if item.difficult:
            return "difficult"
        if item.skipped:
            return "skipped"
        return "pending"

    def _text(self, item) -> str:
        tr = self._host.tr
        suffix, _ = self._markers(item)
        failed = tr("图块加载失败") if item.shape_id in self._failed else ""
        lines = [
            f"#{item.display_index} {item.label}",
            f"{self._host.tr(item.status_text())} · {suffix}",
        ]
        if failed:
            lines.append(failed)
        return "\n".join(lines)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._ids)):
            return None
        shape_id = self._ids[index.row()]
        if role == self.ROLE_SHAPE_ID:
            return shape_id
        item = self._states.get(shape_id)
        if item is None:
            return None
        if role in (
            QtCore.Qt.ItemDataRole.DisplayRole,
            QtCore.Qt.ItemDataRole.AccessibleTextRole,
        ):
            return self._text(item)
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            tr = self._host.tr
            text = tr("对象 {shape_id}\n{status}").format(
                shape_id=shape_id, status=self._host.tr(item.status_text())
            )
            if shape_id in self._failed:
                text += "\n" + tr("图块加载失败")
            return text
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            icon = self.icon_for(shape_id)
            return icon if icon is not None else self._placeholder
        if role == self.ROLE_TITLE:
            return f"#{item.display_index} {item.label}"
        if role == self.ROLE_STATUS:
            return self._host.tr(item.status_text())
        if role == self.ROLE_MARKERS:
            return self._markers(item)[0]
        if role == self.ROLE_STATE:
            return self._state(item)
        return None


class _CardDelegate(QtWidgets.QStyledItemDelegate):
    """Object cards with a status bar, thumbnail and two text lines."""

    def sizeHint(self, option, index):
        view = option.widget
        if isinstance(view, QtWidgets.QListView):
            grid = view.gridSize()
            if grid.isValid():
                return grid
        return super().sizeHint(option, index)

    def paint(self, painter, option, index):
        theme = get_theme()
        view = option.widget
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(option.rect).adjusted(4, 4, -4, -6)
        selected = bool(
            option.state & QtWidgets.QStyle.StateFlag.State_Selected
        )
        status = str(
            index.data(QtCore.Qt.ItemDataRole.UserRole + 4) or "pending"
        )
        accent = theme[STATUS_COLORS.get(status, "border_light")]

        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.setClipPath(path)
        painter.fillRect(rect, QtGui.QColor(accent))
        body = QtCore.QRectF(
            rect.left(), rect.top() + 3, rect.width(), rect.height() - 3
        )
        painter.fillRect(body, QtGui.QColor(theme["background"]))
        painter.setClipping(False)
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(
                    theme["primary"] if selected else theme["border_light"]
                ),
                2 if selected else 1,
            )
        )
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 10, 10)

        image_height = getattr(view, "card_image_height", 320)
        well = QtCore.QRectF(
            rect.left() + 10,
            rect.top() + 12,
            rect.width() - 20,
            max(1.0, float(image_height)),
        )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(theme["surface"]))
        painter.drawRoundedRect(well, 6, 6)

        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            pixmap = icon.pixmap(
                QtCore.QSize(int(well.width()), int(well.height()))
            )
            if not pixmap.isNull():
                painter.drawPixmap(
                    QtCore.QPointF(
                        well.center().x() - pixmap.width() / 2.0,
                        well.center().y() - pixmap.height() / 2.0,
                    ),
                    pixmap,
                )

        title_font = QtGui.QFont(option.font)
        title_font.setPixelSize(12)
        title_font.setWeight(QtGui.QFont.Weight.Medium)
        painter.setFont(title_font)
        painter.setPen(QtGui.QColor(theme["text"]))
        title = str(index.data(QtCore.Qt.ItemDataRole.UserRole + 1) or "")
        title_rect = QtCore.QRectF(
            rect.left() + 10, rect.bottom() - 38, rect.width() - 20, 16
        )
        metrics = QtGui.QFontMetrics(title_font)
        painter.drawText(
            title_rect,
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(
                title,
                QtCore.Qt.TextElideMode.ElideRight,
                int(title_rect.width()),
            ),
        )

        meta_font = QtGui.QFont(option.font)
        meta_font.setPixelSize(10)
        painter.setFont(meta_font)
        painter.setPen(QtGui.QColor(theme["text_secondary"]))
        painter.drawText(
            QtCore.QRectF(
                rect.left() + 10, rect.bottom() - 20, rect.width() / 2, 14
            ),
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            str(index.data(QtCore.Qt.ItemDataRole.UserRole + 2) or ""),
        )
        painter.drawText(
            QtCore.QRectF(
                rect.center().x(),
                rect.bottom() - 20,
                rect.width() / 2 - 10,
                14,
            ),
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            str(index.data(QtCore.Qt.ItemDataRole.UserRole + 3) or ""),
        )
        painter.restore()


class _RegionDelegate(QtWidgets.QStyledItemDelegate):
    """Compact rows for the spatial coverage regions."""

    ROW_HEIGHT = 38

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter, option, index):
        theme = get_theme()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(option.rect)
        selected = bool(
            option.state & QtWidgets.QStyle.StateFlag.State_Selected
        )
        if selected:
            painter.fillRect(
                rect,
                QtGui.QColor(
                    blend_hex(theme["primary"], theme["background"], 0.12)
                ),
            )
        painter.setPen(QtGui.QPen(QtGui.QColor(theme["border"]), 1))
        painter.drawLine(
            rect.bottomLeft().toPoint(), rect.bottomRight().toPoint()
        )

        state = str(
            index.data(QtCore.Qt.ItemDataRole.UserRole + 2) or "pending"
        )
        colors = {
            "done": theme["success"],
            "difficult": theme["warning"],
            "skipped": theme["primary"],
            "pending": theme["border_light"],
        }
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(
            QtGui.QColor(colors.get(state, theme["border_light"]))
        )
        painter.drawEllipse(
            QtCore.QRectF(rect.left() + 8, rect.center().y() - 3, 6, 6)
        )

        font = QtGui.QFont(option.font)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(theme["text"]))
        painter.drawText(
            QtCore.QRectF(
                rect.left() + 22, rect.top(), rect.width() - 120, rect.height()
            ),
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            str(index.data(QtCore.Qt.ItemDataRole.UserRole + 1) or ""),
        )

        small = QtGui.QFont(option.font)
        small.setPixelSize(11)
        painter.setFont(small)
        painter.setPen(QtGui.QColor(theme["text_secondary"]))
        painter.drawText(
            QtCore.QRectF(rect.right() - 96, rect.top(), 88, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""),
        )
        painter.restore()


class _CoverageGrid(QtWidgets.QWidget):
    """Spatial overview of the coverage plan drawn from region geometry."""

    region_clicked = QtCore.pyqtSignal(str)
    MARGIN = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan = None
        self._current = ""
        self._hover = ""
        self.setMinimumSize(220, 170)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

    def sizeHint(self):
        return QtCore.QSize(340, 240)

    def set_plan(self, plan, current: str = "") -> None:
        self._plan = plan
        self._current = current or ""
        self.update()

    def set_current(self, region_id: str) -> None:
        region_id = region_id or ""
        if region_id == self._current:
            return
        self._current = region_id
        self.update()

    def _content_rect(self) -> QtCore.QRectF:
        area = QtCore.QRectF(self.rect()).adjusted(
            self.MARGIN,
            self.MARGIN,
            -self.MARGIN,
            -self.MARGIN,
        )
        plan = self._plan
        width = getattr(plan, "image_width", 0) or 0
        height = getattr(plan, "image_height", 0) or 0
        if area.width() <= 1 or area.height() <= 1:
            return QtCore.QRectF()
        if width <= 0 or height <= 0:
            return area
        scale = min(area.width() / width, area.height() / height)
        scaled = QtCore.QSizeF(width * scale, height * scale)
        return QtCore.QRectF(
            area.center().x() - scaled.width() / 2,
            area.center().y() - scaled.height() / 2,
            scaled.width(),
            scaled.height(),
        )

    def _cell_rect(self, region, content: QtCore.QRectF) -> QtCore.QRectF:
        plan = self._plan
        width = plan.image_width or 1
        height = plan.image_height or 1
        x1, y1, x2, y2 = region.rect
        return QtCore.QRectF(
            content.left() + x1 * content.width() / width,
            content.top() + y1 * content.height() / height,
            max(0.0, x2 - x1) * content.width() / width,
            max(0.0, y2 - y1) * content.height() / height,
        )

    def _hit(self, point) -> Optional[object]:
        plan = self._plan
        if plan is None or not plan.regions:
            return None
        content = self._content_rect()
        if content.isEmpty():
            return None
        point = QtCore.QPointF(point)
        for region in reversed(plan.regions):
            if self._cell_rect(region, content).contains(point):
                return region
        return None

    @staticmethod
    def _state(region) -> str:
        if region.difficult:
            return "difficult"
        if region.skipped:
            return "skipped"
        if region.completed:
            return "done"
        return "pending"

    def _state_label(self, state: str) -> str:
        labels = {
            "done": self.tr("已完成"),
            "difficult": self.tr("疑难"),
            "skipped": self.tr("暂跳"),
            "pending": self.tr("待查"),
        }
        return labels.get(state, self.tr("待查"))

    def _fill_color(self, state: str):
        theme = get_theme()
        mapping = {
            "done": theme["success"],
            "difficult": theme["warning"],
            "skipped": theme["primary"],
            "pending": theme["surface"],
        }
        color = mapping.get(state, theme["surface"])
        if state == "pending":
            color = blend_hex(color, theme["background"], 0.85)
        return QtGui.QColor(color)

    def paintEvent(self, event):  # noqa: N802
        theme = get_theme()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        outer = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QtGui.QPen(QtGui.QColor(theme["border"]), 1))
        painter.setBrush(QtGui.QColor(theme["background"]))
        painter.drawRoundedRect(outer, 8, 8)

        plan = self._plan
        content = self._content_rect()
        font = QtGui.QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        if plan is None or not plan.regions or content.isEmpty():
            painter.setPen(QtGui.QColor(theme["text_secondary"]))
            painter.drawText(
                outer,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                self.tr("尚无区域计划\n点「重建区域计划」后显示"),
            )
            painter.end()
            return

        painter.save()
        painter.setClipRect(outer)
        for region in plan.regions:
            rect = self._cell_rect(region, content)
            state = self._state(region)
            painter.setBrush(self._fill_color(state))
            selected = region.region_id == self._current
            pen = theme["primary"] if selected else theme["border"]
            painter.setPen(
                QtGui.QPen(QtGui.QColor(pen), 2.0 if selected else 1.0)
            )
            painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
            if rect.width() < 30 or rect.height() < 18:
                continue
            index = region.row * plan.columns + region.column + 1
            text_color = (
                theme["text_secondary"]
                if state == "pending"
                else theme["selection_text"]
            )
            painter.setPen(QtGui.QColor(text_color))
            painter.drawText(
                rect,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                str(index),
            )
        if self._hover:
            hovered = next(
                (
                    region
                    for region in plan.regions
                    if region.region_id == self._hover
                ),
                None,
            )
            if hovered is not None:
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor(theme["primary"]), 1))
                painter.drawRect(self._cell_rect(hovered, content))
        painter.restore()
        painter.end()

    def mouseMoveEvent(self, event):  # noqa: N802
        region = self._hit(event.position())
        hover = region.region_id if region is not None else ""
        if hover != self._hover:
            self._hover = hover
            self.update()
        if region is None:
            self.setToolTip("")
        else:
            self.setToolTip(
                self.tr("区域 {region} · {state}").format(
                    region=region.region_id,
                    state=self._state_label(self._state(region)),
                )
            )
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if self._hover:
            self._hover = ""
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            region = self._hit(event.position())
            if region is not None:
                self.region_clicked.emit(region.region_id)
                return
        super().mousePressEvent(event)


class _CompareDialog(QtWidgets.QDialog):
    """Side-by-side comparison that follows asynchronous card results.

    The old implementation read the thumbnail cache once when it opened,
    so a cold or evicted cache left a permanent "preparing" label.  This
    dialog requests the current content, updates when the provider delivers
    it, shows failures, offers a retry, and ignores results after closing.
    """

    def __init__(
        self,
        workspace,
        shape_ids: Iterable[str],
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent or workspace)
        self.workspace = workspace
        self.shape_ids = [str(shape_id) for shape_id in shape_ids]
        self._closed = False
        self._image_labels: dict[str, QtWidgets.QLabel] = {}
        self._status_labels: dict[str, QtWidgets.QLabel] = {}
        self.setWindowTitle(self.tr("并排比较"))
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        self.resize(780, 430)
        layout = QtWidgets.QHBoxLayout(self)
        session = workspace.session
        for shape_id in self.shape_ids:
            item = session.object(shape_id) if session is not None else None
            panel = QtWidgets.QWidget()
            panel_layout = QtWidgets.QVBoxLayout(panel)
            title = QtWidgets.QLabel(
                (
                    f"#{item.display_index} {item.label} · "
                    f"{workspace.tr(item.status_text())}"
                    if item is not None
                    else shape_id
                )
            )
            title.setWordWrap(True)
            image = QtWidgets.QLabel()
            image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            image.setMinimumSize(320, 240)
            image.setText(self.tr("图块准备中…"))
            status = QtWidgets.QLabel()
            status.setWordWrap(True)
            status.setObjectName("fieldLabel")
            retry = QtWidgets.QPushButton(self.tr("重试"))
            retry.clicked.connect(
                lambda _checked=False, sid=shape_id: workspace.retry_compare(
                    sid, self
                )
            )
            retry_row = QtWidgets.QHBoxLayout()
            retry_row.addStretch(1)
            retry_row.addWidget(retry)
            panel_layout.addWidget(title)
            panel_layout.addWidget(image, 1)
            panel_layout.addWidget(status)
            panel_layout.addLayout(retry_row)
            layout.addWidget(panel, 1)
            self._image_labels[shape_id] = image
            self._status_labels[shape_id] = status
        footer = QtWidgets.QVBoxLayout()
        note = QtWidgets.QLabel(self.tr("比较不会复制标注或改变对象身份。"))
        note.setWordWrap(True)
        close_button = QtWidgets.QPushButton(self.tr("关闭"))
        close_button.clicked.connect(self.close)
        footer.addWidget(note)
        footer.addStretch(1)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    def set_pending(self, shape_id: str) -> None:
        label = self._image_labels.get(shape_id)
        if label is None:
            return
        label.clear()
        label.setText(self.tr("图块准备中…"))
        status = self._status_labels.get(shape_id)
        if status is not None:
            status.setText("")

    def set_image(self, shape_id: str, image) -> None:
        label = self._image_labels.get(shape_id)
        if label is None or self._closed:
            return
        pixmap = QtGui.QPixmap.fromImage(image)
        if pixmap.isNull():
            self.set_failed(shape_id, self.tr("图块加载失败"))
            return
        target = label.size()
        if target.width() > 0 and target.height() > 0:
            pixmap = pixmap.scaled(
                target,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        label.setPixmap(pixmap)
        status = self._status_labels.get(shape_id)
        if status is not None:
            status.setText(self.tr("图块已就绪"))

    def set_failed(self, shape_id: str, reason: str) -> None:
        label = self._image_labels.get(shape_id)
        if label is None or self._closed:
            return
        label.clear()
        label.setText(self.tr("图块加载失败"))
        status = self._status_labels.get(shape_id)
        if status is not None:
            status.setText(reason)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closed = True
        self.workspace._on_compare_closed(self)
        super().closeEvent(event)


class DenseReviewWorkspace(QtWidgets.QDockWidget):
    """Batch, card and spatial-review controls docked beside the canvas.

    The panel is a real dock so the single editable canvas stays visible and
    the whole thing can float to a second screen and re-dock.  Everything
    that used to live on the dialog (card model, region panel, thumbnail
    provider, comparison windows) is unchanged; only the container moved,
    so ``dense_review_workspace`` keeps its previous call contract
    (WL-01, WL-02).
    """

    #: Stable name used by the main window when registering the dock and by
    #: the layout restore path.
    DOCK_OBJECT_NAME = "denseReviewDock"

    #: Task ids are stable and independent of the widget order.
    TASK_CATEGORY = "category"
    TASK_BOX_POINTS = "box-points"
    TASK_COVERAGE = "coverage"
    TASK_IDS = (TASK_CATEGORY, TASK_BOX_POINTS, TASK_COVERAGE)
    #: Which page of the stacked content each task shows.
    TASK_PAGE = {TASK_CATEGORY: 0, TASK_BOX_POINTS: 0, TASK_COVERAGE: 1}
    #: Display preset applied when a task becomes active.
    TASK_DISPLAY_MODE = {
        TASK_CATEGORY: "focus",
        TASK_BOX_POINTS: "focus",
        TASK_COVERAGE: "coverage",
    }

    #: Card image-area height in logical pixels (OC-07).
    DEFAULT_IMAGE_HEIGHT = 320
    MIN_IMAGE_HEIGHT = 160
    MAX_IMAGE_HEIGHT = 640
    #: Space reserved below the image for title and meta lines.
    CARD_TEXT_HEIGHT = 66
    CARD_MIN_WIDTH = 178

    def __init__(
        self,
        host: Any,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(host.tr("密集复核"), parent or host)
        self.host = host
        self.thumbnails = ThumbnailProvider(self)
        self.thumbnails.set_defer_predicate(self._defer_background_cards)
        self.thumbnails.capacity_available.connect(
            self._schedule_visible_thumbnails
        )
        self._updating = False
        self._generation = 0
        self._cards_signature = None
        self._card_model = _CardModel(self, self)
        self._region_items: dict[str, QtWidgets.QListWidgetItem] = {}
        self._failed_ids: set[str] = set()
        self._card_request_keys: dict[str, tuple] = {}
        self._compare_request_keys: dict[str, tuple] = {}
        self._compare_dialogs: list[_CompareDialog] = []
        self._batches_visible = True
        self._cards_visible = True
        self._card_image_height = self.DEFAULT_IMAGE_HEIGHT
        self._last_thumb_generation = -1
        self._view_ready = False
        #: True while the review view owns the canvas overlay.  Floating and
        #: re-docking also emit hide/show pairs, so the flag (not the Qt
        #: visibility event alone) decides whether the overlay must be
        #: released or re-installed.
        self._review_view_open = False
        #: True only while the dock is moving between docked and floating.
        self._float_transition = False
        self._switching_task = False
        self._task_id = self.TASK_CATEGORY
        # Per-image, per-task lightweight navigation state (memory only).
        self._task_views: dict[str, dict] = {}
        self._task_state_image = ""
        self._display_mode = "focus"
        self._full_image = False
        self._shortcuts: list[QtGui.QShortcut] = []
        self._shortcut_warnings: list[str] = []
        self.setWindowTitle(self.tr("Dense Annotation Review"))
        self.setObjectName(self.DOCK_OBJECT_NAME)
        self.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        # Movable, closable and floatable: closing the panel must keep the
        # session and the edit history alive (WL-01, WL-02).
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._build_ui()
        self.setStyleSheet(get_dialog_style() + get_workbench_qss())
        self._connect()
        self._install_shortcuts()
        self._apply_icons()
        self.refresh_all(initial=True)

    @property
    def session(self):
        return getattr(self.host, "dense_review_session", None)

    # -- UI ------------------------------------------------------------

    def _build_ui(self) -> None:
        # The dock owns a single inner widget; all existing layout code keeps
        # targeting ``layout`` exactly as before.
        self.content = QtWidgets.QWidget(self)
        self.setWidget(self.content)
        layout = QtWidgets.QVBoxLayout(self.content)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        toolbar = QtWidgets.QFrame(self)
        toolbar.setObjectName("workbenchToolbar")
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(10)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedSize(150, 6)
        self.summary_label = QtWidgets.QLabel()
        self.summary_label.setWordWrap(False)
        self.start_button = QtWidgets.QPushButton(self.tr("开始/重建本轮"))
        self.config_button = QtWidgets.QPushButton(self.tr("复核配置"))
        self.config_button.setProperty("variant", "quiet")
        self.refresh_button = QtWidgets.QPushButton(self.tr("刷新"))
        self.refresh_button.setProperty("variant", "quiet")
        self.close_button = QtWidgets.QPushButton(self.tr("关闭"))
        self.close_button.setProperty("variant", "quiet")

        toolbar_layout.addWidget(self.progress_bar)
        toolbar_layout.addWidget(self.summary_label, 1)
        toolbar_layout.addWidget(self.start_button)
        toolbar_layout.addWidget(self.config_button)
        toolbar_layout.addWidget(self.refresh_button)
        toolbar_layout.addWidget(self.close_button)
        layout.addWidget(toolbar)

        statusline = QtWidgets.QFrame(self)
        statusline.setObjectName("workbenchStatus")
        status_layout = QtWidgets.QHBoxLayout(statusline)
        status_layout.setContentsMargins(10, 5, 10, 5)
        status_layout.setSpacing(12)
        self.completion_label = QtWidgets.QLabel()
        self.completion_label.setWordWrap(False)
        self.config_label = QtWidgets.QLabel()
        self.config_label.setObjectName("fieldLabel")
        self.config_label.setWordWrap(False)
        status_layout.addWidget(self.completion_label)
        status_layout.addWidget(self.config_label, 1)
        layout.addWidget(statusline)

        task_row = QtWidgets.QHBoxLayout()
        task_row.setSpacing(8)
        self.task_caption = QtWidgets.QLabel(self.tr("当前任务"))
        self.task_caption.setObjectName("fieldLabel")
        self.task_selector = QtWidgets.QComboBox()
        self.task_selector.setAccessibleName(self.tr("复核任务"))
        self.task_selector.setToolTip(
            self.tr("切换任务只改变视图与导航，不改变确认状态。")
        )
        self.task_selector.addItem(self.tr("类别核对"), self.TASK_CATEGORY)
        self.task_selector.addItem(
            self.tr("框与关键点观察"), self.TASK_BOX_POINTS
        )
        self.task_selector.addItem(self.tr("空间查漏"), self.TASK_COVERAGE)
        task_row.addWidget(self.task_caption)
        task_row.addWidget(self.task_selector, 1)
        layout.addLayout(task_row)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_object_tab(), self.tr("对象复核"))
        self.tabs.addTab(self._build_coverage_tab(), self.tr("空间查漏"))
        layout.addWidget(self.tabs, 1)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(False)
        self.status_label.setObjectName("fieldLabel")
        layout.addWidget(self.status_label)
        for button in self.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    def _build_object_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(tab)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)

        aux_bar = QtWidgets.QHBoxLayout()
        aux_bar.setSpacing(8)
        self.batches_toggle_button = QtWidgets.QPushButton(
            self.tr("隐藏类别批次栏")
        )
        self.batches_toggle_button.setCheckable(True)
        self.batches_toggle_button.setChecked(True)
        self.batches_toggle_button.setProperty("variant", "quiet")
        self.batches_toggle_button.setAccessibleName(
            self.tr("类别批次栏显示开关")
        )
        self.batches_toggle_button.setToolTip(
            self.tr(
                "小窗口时可单独收起类别批次栏；主画布、待处理数量和批次操作保留。"
            )
        )
        self.cards_toggle_button = QtWidgets.QPushButton(
            self.tr("隐藏对象卡片栏")
        )
        self.cards_toggle_button.setCheckable(True)
        self.cards_toggle_button.setChecked(True)
        self.cards_toggle_button.setProperty("variant", "quiet")
        self.cards_toggle_button.setAccessibleName(
            self.tr("对象卡片栏显示开关")
        )
        self.cards_toggle_button.setToolTip(
            self.tr(
                "小窗口时可单独收起对象卡片栏；主画布、待处理数量和批次操作保留。"
            )
        )
        aux_bar.addWidget(self.batches_toggle_button)
        aux_bar.addWidget(self.cards_toggle_button)
        aux_bar.addStretch(1)
        outer.addLayout(aux_bar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(True)
        self.object_splitter = splitter

        left = QtWidgets.QWidget()
        left.setMinimumWidth(232)
        left.setMaximumWidth(300)
        self.batches_panel = left
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(6)
        batch_caption = QtWidgets.QLabel(self.tr("类别批次"))
        batch_caption.setObjectName("fieldLabel")
        left_layout.addWidget(batch_caption)
        self.batch_list = QtWidgets.QListWidget()
        self.batch_list.setItemDelegate(_BatchDelegate(self.batch_list))
        self.batch_list.setSpacing(0)
        self.batch_list.setUniformItemSizes(True)
        self.batch_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.batch_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        left_layout.addWidget(self.batch_list, 1)
        dimension_row = QtWidgets.QHBoxLayout()
        dimension_row.setSpacing(6)
        dimension_row.addWidget(QtWidgets.QLabel(self.tr("审核范围")))
        self.dimension_combo = QtWidgets.QComboBox()
        self.dimension_combo.addItem(
            self.tr("类别 + 框"), ("category", "geometry")
        )
        self.dimension_combo.addItem(self.tr("仅类别"), ("category",))
        self.dimension_combo.addItem(self.tr("仅框"), ("geometry",))
        dimension_row.addWidget(self.dimension_combo, 1)
        left_layout.addLayout(dimension_row)
        self.per_object_checkbox = QtWidgets.QCheckBox(
            self.tr("逐框模式（完成并下一个 / 暂跳下一个）")
        )
        self.per_object_checkbox.setChecked(False)
        left_layout.addWidget(self.per_object_checkbox)
        self.per_object_checkbox.toggled.connect(self._on_per_object_toggled)
        self.batch_note_label = QtWidgets.QLabel()
        self.batch_note_label.setWordWrap(True)
        self.batch_note_label.setObjectName("fieldLabel")
        left_layout.addWidget(self.batch_note_label)
        splitter.addWidget(left)

        right = QtWidgets.QWidget()
        self.cards_panel = right
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        header_row = QtWidgets.QHBoxLayout()
        header_row.setSpacing(8)
        self.current_object_label = QtWidgets.QLabel()
        self.current_object_label.setWordWrap(False)
        self.rule_label = QtWidgets.QLabel()
        self.rule_label.setWordWrap(False)
        self.rule_label.setObjectName("fieldLabel")
        header_row.addWidget(self.current_object_label, 1)
        header_row.addWidget(self.rule_label)
        right_layout.addLayout(header_row)

        reason_row = QtWidgets.QHBoxLayout()
        reason_row.setSpacing(6)
        self.exclusion_reason_label = QtWidgets.QLabel()
        self.exclusion_reason_label.setObjectName("fieldLabel")
        self.exclusion_reason_label.setWordWrap(False)
        self.temporary_show_button = QtWidgets.QPushButton(self.tr("临时显示"))
        self.temporary_show_button.setProperty("variant", "quiet")
        self.temporary_show_button.setAccessibleName(
            self.tr("临时显示当前对象")
        )
        self.temporary_show_button.setToolTip(
            self.tr("仅临时观察被手动隐藏或过滤的当前对象，不改变确认资格。")
        )
        self.temporary_show_button.setVisible(False)
        reason_row.addWidget(self.exclusion_reason_label, 1)
        reason_row.addWidget(self.temporary_show_button)
        right_layout.addLayout(reason_row)

        context_row = QtWidgets.QHBoxLayout()
        context_row.setSpacing(6)
        context_row.addWidget(QtWidgets.QLabel(self.tr("卡片上下文")))
        self.context_spin = QtWidgets.QSpinBox()
        self.context_spin.setRange(0, 150)
        self.context_spin.setValue(35)
        self.context_spin.setSuffix("%")
        context_row.addWidget(self.context_spin)
        self.apply_context_button = QtWidgets.QPushButton(self.tr("应用"))
        self.apply_context_button.setProperty("variant", "quiet")
        context_row.addWidget(self.apply_context_button)
        context_row.addStretch(1)
        right_layout.addLayout(context_row)

        height_row = QtWidgets.QHBoxLayout()
        height_row.setSpacing(6)
        height_label = QtWidgets.QLabel(self.tr("图像高度"))
        height_label.setObjectName("fieldLabel")
        self.image_height_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal
        )
        self.image_height_slider.setRange(
            self.MIN_IMAGE_HEIGHT, self.MAX_IMAGE_HEIGHT
        )
        self.image_height_slider.setSingleStep(20)
        self.image_height_slider.setPageStep(80)
        self.image_height_slider.setValue(self._card_image_height)
        self.image_height_slider.setAccessibleName(self.tr("卡片图像高度"))
        self.image_height_slider.setToolTip(
            self.tr("调整卡片图像区高度，只改变大小不改变裁切上下文。")
        )
        self.image_height_label = QtWidgets.QLabel(
            str(self._card_image_height)
        )
        self.image_height_label.setObjectName("fieldLabel")
        self.image_height_label.setMinimumWidth(34)
        height_row.addWidget(height_label)
        height_row.addWidget(self.image_height_slider, 1)
        height_row.addWidget(self.image_height_label)
        right_layout.addLayout(height_row)

        self.card_list = QtWidgets.QListView()
        self.card_list.setModel(self._card_model)
        self.card_list.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.card_list.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.card_list.setMovement(QtWidgets.QListView.Movement.Static)
        self.card_list.setWrapping(True)
        self.card_list.setWordWrap(False)
        self.card_list.setUniformItemSizes(True)
        self.card_list.setSpacing(0)
        self.card_list.setIconSize(QtCore.QSize(196, self._card_image_height))
        self.card_list.setGridSize(
            QtCore.QSize(216, self._card_image_height + self.CARD_TEXT_HEIGHT)
        )
        self.card_list.setItemDelegate(_CardDelegate(self.card_list))
        self.card_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.card_list.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.card_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.card_list.setAccessibleName(self.tr("对象卡片列表"))
        self.card_list.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        right_layout.addWidget(self.card_list, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 980])
        outer.addWidget(splitter, 1)

        action_bar = QtWidgets.QFrame()
        action_bar.setObjectName("workbenchStatus")
        bar = QtWidgets.QHBoxLayout(action_bar)
        bar.setContentsMargins(10, 6, 10, 6)
        bar.setSpacing(8)
        display_caption = QtWidgets.QLabel(self.tr("画布"))
        display_caption.setObjectName("fieldLabel")
        self.display_combo = QtWidgets.QComboBox()
        self.display_combo.addItem(self.tr("聚焦当前目标"), "focus")
        self.display_combo.addItem(self.tr("显示全部标注"), "all")
        self.display_combo.addItem(self.tr("原图（无标注）"), "original")
        self.full_image_button = QtWidgets.QPushButton(self.tr("看全图"))
        self.full_image_button.setProperty("variant", "quiet")
        self.hold_original_button = QtWidgets.QPushButton(
            self.tr("按住看原图")
        )
        self.hold_original_button.setProperty("variant", "quiet")
        self.hold_original_button.setAccessibleName(self.tr("按住看原图"))
        self.hold_original_button.setToolTip(
            self.tr("按住期间只显示原图；松开恢复当前显示策略。")
        )
        self.more_button = QtWidgets.QPushButton(self.tr("更多"))
        self.more_button.setObjectName("moreButton")
        self.more_button.setProperty("variant", "quiet")
        self.more_button.setFixedWidth(76)
        self.compact_batch_combo = QtWidgets.QComboBox()
        self.compact_batch_combo.setMinimumWidth(150)
        self.compact_batch_combo.setAccessibleName(self.tr("批次快捷切换"))
        self.compact_batch_combo.setToolTip(
            self.tr("收起类别批次栏后仍可直接切换批次。")
        )
        self.compact_batch_combo.setVisible(False)

        self.complete_batch_button = QtWidgets.QPushButton(
            self.tr("完成本批并进入下一批")
        )
        self.complete_batch_button.setProperty("variant", "primary")
        self.complete_object_button = QtWidgets.QPushButton(
            self.tr("完成并下一个")
        )
        self.skip_button = QtWidgets.QPushButton(self.tr("暂跳下一个"))
        self.difficult_button = QtWidgets.QPushButton(self.tr("标记疑难"))
        self.clear_difficult_button = QtWidgets.QPushButton(
            self.tr("解除疑难")
        )
        self.unskip_button = QtWidgets.QPushButton(self.tr("取消暂跳"))
        self.add_to_batch_button = QtWidgets.QPushButton(
            self.tr("加入当前批次")
        )
        self.members_button = QtWidgets.QPushButton(self.tr("查看成员"))
        self.rebuild_button = QtWidgets.QPushButton(self.tr("重建剩余队列"))
        self.compare_button = QtWidgets.QPushButton(self.tr("并排比较"))

        menu = QtWidgets.QMenu(self.more_button)
        for button in (
            self.clear_difficult_button,
            self.unskip_button,
            self.add_to_batch_button,
            self.members_button,
            self.rebuild_button,
            self.compare_button,
        ):
            button.setVisible(False)
            button.setParent(self)
        menu.addAction(self.tr("解除疑难"), self.clear_difficult_button.click)
        menu.addAction(self.tr("取消暂跳"), self.unskip_button.click)
        menu.addAction(self.tr("加入当前批次"), self.add_to_batch_button.click)
        menu.addSeparator()
        menu.addAction(self.tr("查看成员"), self.members_button.click)
        menu.addAction(self.tr("重建剩余队列"), self.rebuild_button.click)
        menu.addAction(self.tr("并排比较"), self.compare_button.click)
        self.more_button.setMenu(menu)

        bar.addWidget(display_caption)
        bar.addWidget(self.display_combo)
        bar.addWidget(self.full_image_button)
        bar.addWidget(self.hold_original_button)
        bar.addWidget(self.more_button)
        bar.addWidget(self.compact_batch_combo)
        bar.addStretch(1)
        bar.addWidget(self.skip_button)
        bar.addWidget(self.difficult_button)
        bar.addWidget(self.complete_object_button)
        bar.addWidget(self.complete_batch_button)
        outer.addWidget(action_bar)
        return tab

    def _build_coverage_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(0, 6, 0, 0)
        settings_row = QtWidgets.QHBoxLayout()
        settings_row.addWidget(QtWidgets.QLabel(self.tr("列")))
        self.columns_spin = QtWidgets.QSpinBox()
        self.columns_spin.setRange(1, 24)
        settings_row.addWidget(self.columns_spin)
        settings_row.addWidget(QtWidgets.QLabel(self.tr("行")))
        self.rows_spin = QtWidgets.QSpinBox()
        self.rows_spin.setRange(1, 24)
        settings_row.addWidget(self.rows_spin)
        settings_row.addWidget(QtWidgets.QLabel(self.tr("重叠")))
        self.overlap_spin = QtWidgets.QSpinBox()
        self.overlap_spin.setRange(0, 75)
        self.overlap_spin.setSuffix("%")
        settings_row.addWidget(self.overlap_spin)
        self.rebuild_plan_button = QtWidgets.QPushButton(
            self.tr("重建区域计划")
        )
        settings_row.addWidget(self.rebuild_plan_button)
        settings_row.addStretch(1)
        layout.addLayout(settings_row)
        self.coverage_stats_label = QtWidgets.QLabel()
        self.coverage_stats_label.setWordWrap(True)
        layout.addWidget(self.coverage_stats_label)
        self.region_list = QtWidgets.QListWidget()
        self.region_list.setItemDelegate(_RegionDelegate(self.region_list))
        self.region_list.setSpacing(0)
        self.region_list.setUniformItemSizes(True)
        self.region_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.region_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.coverage_grid = _CoverageGrid()
        coverage_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        coverage_split.setChildrenCollapsible(False)
        coverage_split.addWidget(self.coverage_grid)
        coverage_split.addWidget(self.region_list)
        coverage_split.setStretchFactor(0, 3)
        coverage_split.setStretchFactor(1, 2)
        coverage_split.setSizes([420, 280])
        layout.addWidget(coverage_split, 1)
        buttons = QtWidgets.QHBoxLayout()
        self.complete_region_button = QtWidgets.QPushButton(
            self.tr("完成区域并下一区")
        )
        self.complete_region_button.setProperty("variant", "primary")
        self.region_difficult_button = QtWidgets.QPushButton(
            self.tr("区域疑难")
        )
        self.clear_region_difficult_button = QtWidgets.QPushButton(
            self.tr("解除区域疑难")
        )
        self.region_skip_button = QtWidgets.QPushButton(self.tr("区域暂跳"))
        self.clear_region_skip_button = QtWidgets.QPushButton(
            self.tr("取消区域暂跳")
        )
        self.current_region_button = QtWidgets.QPushButton(
            self.tr("定位当前区域")
        )
        for button in (
            self.complete_region_button,
            self.region_difficult_button,
            self.clear_region_difficult_button,
            self.region_skip_button,
            self.clear_region_skip_button,
            self.current_region_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        hint = QtWidgets.QLabel(
            self.tr(
                "查漏区域覆盖整幅图像。平移、缩放或浏览不会记为完成；"
                "新增框进入新增待处理，不会随区域完成而自动确认。"
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return tab

    def _connect(self) -> None:
        self.start_button.clicked.connect(self._start_round)
        self.config_button.clicked.connect(self._edit_config)
        self.refresh_button.clicked.connect(self._refresh_from_host)
        self.close_button.clicked.connect(self.close)
        self.temporary_show_button.clicked.connect(self._toggle_temporary_show)
        canvas = getattr(self.host, "canvas", None)
        if canvas is not None:
            canvas.dense_review_display_changed.connect(
                self._refresh_exclusion_hint
            )
        self.batch_list.currentItemChanged.connect(self._on_batch_selected)
        self.batches_toggle_button.clicked.connect(self._on_batches_toggle)
        self.cards_toggle_button.clicked.connect(self._on_cards_toggle)
        self.compact_batch_combo.activated.connect(
            self._on_compact_batch_activated
        )
        self.dimension_combo.currentIndexChanged.connect(
            self._on_dimensions_changed
        )
        self.card_list.selectionModel().selectionChanged.connect(
            self._on_card_selection_changed
        )
        self.card_list.verticalScrollBar().valueChanged.connect(
            self._schedule_visible_thumbnails
        )
        self.apply_context_button.clicked.connect(self._on_context_changed)
        self.image_height_slider.valueChanged.connect(
            self._on_card_height_changed
        )
        self.display_combo.currentIndexChanged.connect(
            self._on_display_mode_changed
        )
        self.full_image_button.clicked.connect(self._toggle_full_image)
        self.hold_original_button.pressed.connect(self._begin_hold_original)
        self.hold_original_button.released.connect(self._end_hold_original)
        self.complete_batch_button.clicked.connect(self._complete_batch)
        self.complete_object_button.clicked.connect(
            self._complete_current_object
        )
        self.skip_button.clicked.connect(self._skip_current)
        self.difficult_button.clicked.connect(self._mark_current_difficult)
        self.clear_difficult_button.clicked.connect(
            self._clear_current_difficult
        )
        self.unskip_button.clicked.connect(self._clear_current_skipped)
        self.add_to_batch_button.clicked.connect(self._add_current_to_batch)
        self.members_button.clicked.connect(self._show_members)
        self.rebuild_button.clicked.connect(self._rebuild_queue)
        self.compare_button.clicked.connect(self._compare_selected)
        self.task_selector.currentIndexChanged.connect(self._on_task_selected)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.region_list.currentItemChanged.connect(self._on_region_selected)
        self.coverage_grid.region_clicked.connect(self._on_grid_region_clicked)
        self.rebuild_plan_button.clicked.connect(self._rebuild_coverage)
        self.complete_region_button.clicked.connect(
            self._complete_current_region
        )
        self.region_difficult_button.clicked.connect(
            lambda: self._set_current_region_state("difficult", True)
        )
        self.clear_region_difficult_button.clicked.connect(
            lambda: self._set_current_region_state("difficult", False)
        )
        self.region_skip_button.clicked.connect(
            lambda: self._set_current_region_state("skipped", True)
        )
        self.clear_region_skip_button.clicked.connect(
            lambda: self._set_current_region_state("skipped", False)
        )
        self.current_region_button.clicked.connect(self._show_current_region)
        self.card_list.viewport().installEventFilter(self)
        self.thumbnails.ready.connect(self._on_thumbnail_ready)
        self.thumbnails.failed.connect(self._on_thumbnail_failed)

    # -- action helpers ------------------------------------------------

    def _dimensions(self) -> tuple[str, ...]:
        value = self.dimension_combo.currentData()
        if isinstance(value, tuple):
            return tuple(value)
        return REVIEW_DIMENSIONS

    def _current_batch_id(self) -> str:
        """Return the session batch, never a stale list selection.

        ``refresh_all`` rebuilds the list from the session.  Reading the
        current list row here used to let the previous batch override a
        programmatic navigation (OpenSpec DR-01), so the session is the
        single source of truth; the list is only a fallback while the
        session has no batch yet.
        """
        session = self.session
        if session is not None and session.state.current_batch:
            return session.state.current_batch
        item = self.batch_list.currentItem()
        if item is not None:
            batch_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if batch_id:
                return str(batch_id)
        return ""

    def _current_shape_id(self) -> str:
        session = self.session
        return session.state.current_object if session else ""

    def _exclusions(self) -> tuple[set[str], set[str], set[str]]:
        manual, filtered = self.host.dense_review_exclusion_ids()
        return manual, filtered, set(self._failed_ids)

    def _scope(self):
        session = self.session
        if session is None:
            return None
        manual, filtered, failed = self._exclusions()
        return session.candidate_scope(
            self._current_batch_id(),
            self._dimensions(),
            manual_hidden_ids=manual,
            filtered_ids=filtered,
            failed_ids=failed,
        )

    def _visible_candidate_count(self, candidate_ids: Iterable[str]) -> int:
        rect = self.card_list.viewport().rect()
        visible = 0
        for shape_id in candidate_ids:
            row = self._card_model.row_for(shape_id)
            if row < 0:
                continue
            index = self._card_model.index(row, 0)
            if self.card_list.visualRect(index).intersects(rect):
                visible += 1
        return visible

    def _visible_shape_ids(self, prefetch_rows: int = 1) -> list[str]:
        """Return visible card ids plus a bounded prefetch window.

        The view is virtualized, so this never scans every member.  It reads
        the top and bottom laid-out indexes and expands by at most one screen
        row.  When the view is hidden (collapsed cards), only the current
        object is considered.
        """
        count = self._card_model.rowCount()
        if count == 0 or not self.card_list.isVisible():
            return []
        viewport = self.card_list.viewport().rect()
        if viewport.width() <= 1 or viewport.height() <= 1:
            return []
        rows: list[int] = []
        for x in (2, viewport.width() // 2, viewport.width() - 2):
            for y in (2, viewport.height() // 2, viewport.height() - 2):
                index = self.card_list.indexAt(QtCore.QPoint(x, y))
                if index.isValid():
                    rows.append(index.row())
        if not rows:
            return []
        grid = self.card_list.gridSize()
        columns = max(1, viewport.width() // max(1, grid.width()))
        expand = max(0, int(prefetch_rows)) * columns
        first_row = max(0, min(rows) - expand)
        last_row = min(count - 1, max(rows) + expand)
        ids = self._card_model.shape_ids()
        return [ids[row] for row in range(first_row, last_row + 1)]

    def _selected_shape_ids(self) -> list[str]:
        selection = self.card_list.selectionModel()
        if selection is None:
            return []
        indexes = sorted(
            (
                index
                for index in selection.selectedIndexes()
                if index.isValid()
            ),
            key=lambda index: index.row(),
        )
        return [
            shape_id
            for shape_id in (
                self._card_model.data(index, _CardModel.ROLE_SHAPE_ID)
                for index in indexes
            )
            if shape_id
        ]

    def _select_shape_id(self, shape_id: str) -> None:
        row = self._card_model.row_for(shape_id)
        selection = self.card_list.selectionModel()
        if row < 0 or selection is None:
            return
        index = self._card_model.index(row, 0)
        selection.setCurrentIndex(
            index,
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
        self.card_list.scrollTo(
            index,
            QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible,
        )

    def _toggle_temporary_show(self) -> None:
        """Reveal or hide the current object for observation only."""
        shape_id = self._current_shape_id()
        if not shape_id:
            return
        if shape_id in self.host.dense_review_temporary_ids():
            self.host.dense_review_end_temporary([shape_id])
        else:
            self.host.dense_review_show_temporarily([shape_id])
        self._refresh_exclusion_hint()

    def _refresh_exclusion_hint(self) -> None:
        """Update only the reason text and its button.

        Bound to ``canvas.dense_review_display_changed``; it must stay cheap
        and never call ``refresh_all()`` from inside a display signal, or the
        rebuild would re-enter the same signal (DP-11, DP-12).
        """
        label = getattr(self, "exclusion_reason_label", None)
        button = getattr(self, "temporary_show_button", None)
        if label is None or button is None:
            return
        session = self.session
        shape_id = self._current_shape_id()
        if session is None or not shape_id:
            label.setText("")
            button.setVisible(False)
            return
        display = self.host.dense_review_display_entry(shape_id)
        reason = self.host.dense_review_exclusion_reason(shape_id)
        temporary = shape_id in self.host.dense_review_temporary_ids()
        revealable = bool(
            display is not None
            and display.reason in ("manual-hidden", "label-hidden", "filtered")
        )
        if display is not None and display.drawable and display.temporary:
            label.setText(self.tr("已临时显示 · 确认资格仍按排除来源计算"))
        else:
            label.setText(
                self.tr("未显示：{reason}").format(reason=reason)
                if reason
                else ""
            )
        if temporary:
            button.setText(self.tr("结束临时显示"))
        elif revealable:
            button.setText(self.tr("临时显示"))
        button.setVisible(temporary or revealable)

    def _status(self, text: str) -> None:
        self.status_label.setText(text)

    # -- round lifecycle ----------------------------------------------

    def _start_round(self) -> None:
        force = False
        if self.session is not None:
            answer = QtWidgets.QMessageBox.question(
                self,
                self.tr("重建本轮"),
                self.tr(
                    "重建本轮会按当前配置和当前对象重新建立队列；"
                    "已保存的内容确认会尽量保留。是否继续？"
                ),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            force = True
        ok, message = self.host.dense_review_start_round(force_new=force)
        if not ok:
            self._status(message)
            return
        self._status(message or self.tr("本轮已开始"))
        self._generation += 1
        self.thumbnails.start_generation(self._generation)
        self._failed_ids.clear()
        self._compare_request_keys.clear()
        self._close_compare_dialogs()
        self.refresh_all(force_cards=True)
        self._focus_current()

    def _refresh_from_host(self, *, new_generation: bool = True) -> None:
        """Re-read host data.

        ``new_generation=False`` keeps the current thumbnail generation, used
        by re-open/show paths that must not look like a new round (R1).
        """
        if new_generation:
            self._generation += 1
            self.thumbnails.start_generation(self._generation)
            self._failed_ids.clear()
            self._card_request_keys.clear()
        self._compare_request_keys.clear()
        self._close_compare_dialogs()
        self.refresh_all(force_cards=True)

    def _edit_config(self) -> None:
        labels = self.host.dense_review_available_labels()
        config = self.host.dense_review_load_config()[0]
        dialog = DenseReviewConfigDialog(labels, config, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        config = dialog.config()
        ok, message = self.host.dense_review_save_config(config)
        if not ok:
            self._status(message)
            return
        if self.session is not None:
            ok, message = self.host.dense_review_apply_config(config)
            if not ok:
                self._status(message)
                return
        else:
            ok, message = self.host.dense_review_start_round(force_new=False)
            if not ok:
                self._status(message)
                self.refresh_all(force_cards=True)
                return
        self._status(message or self.tr("复核配置已保存"))
        self.refresh_all(force_cards=True)
        self._focus_current()

    # -- object review refresh ----------------------------------------

    def refresh_all(self, initial: bool = False, force_cards: bool = False):
        session = self.session
        if self._last_thumb_generation != self.thumbnails.generation:
            self._last_thumb_generation = self.thumbnails.generation
            self._failed_ids.clear()
            self._card_request_keys.clear()
        self._updating = True
        try:
            if session is None:
                self._set_empty_state()
                return
            self._update_summary()
            self._refresh_batches()
            self._refresh_cards(force=force_cards)
            self._refresh_coverage()
            self._sync_list_enabled()
        finally:
            self._updating = False
        # The canvas overlay is derived from the same session state; rebuild
        # it on every refresh so the painted roles never lag the panel
        # (DP-01, DP-08).
        self.host.refresh_dense_review_display()
        QtCore.QTimer.singleShot(0, self._request_visible_thumbnails)
        # One dispatch point: the active task decides the navigation.  A
        # plain refresh must not move the coverage viewport - the user may be
        # inspecting a detail inside the region - so only the region overlay
        # and list highlight are re-synced here (R2, SN-06).
        if self._task_id == self.TASK_COVERAGE:
            self._sync_current_region_display()
        if not initial:
            self._update_action_labels()

    def _set_empty_state(self) -> None:
        for widget in (
            self.complete_batch_button,
            self.complete_object_button,
            self.skip_button,
            self.difficult_button,
            self.clear_difficult_button,
            self.unskip_button,
            self.add_to_batch_button,
            self.members_button,
            self.rebuild_button,
            self.compare_button,
            self.complete_region_button,
            self.region_difficult_button,
            self.clear_region_difficult_button,
            self.region_skip_button,
            self.clear_region_skip_button,
            self.current_region_button,
            self.rebuild_plan_button,
        ):
            widget.setEnabled(False)
        # The lists keep the same empty/ready contract as the buttons so a
        # session that becomes valid later restores them through
        # ``_sync_list_enabled`` (WL-05, WL-06).
        self.batch_list.setEnabled(False)
        self.card_list.setEnabled(False)
        self.region_list.setEnabled(False)
        self.summary_label.setText(self.tr("尚未开始本轮复核。"))
        self.progress_bar.setValue(0)
        self.completion_label.setText("")
        self.config_label.setText("")
        self.current_object_label.setText("")
        self.rule_label.setText("")
        self.exclusion_reason_label.setText("")
        self.temporary_show_button.setVisible(False)
        self.batch_note_label.setText("")
        self.coverage_stats_label.setText("")

    def _update_summary(self) -> None:
        session = self.session
        counts = session.counts()
        completion = session.completion_status(self.tr)
        pending_total = counts["total"] - counts["confirmed_both"]
        total = counts["total"] or 1
        self.progress_bar.setValue(
            round(counts["confirmed_both"] * 100 / total)
        )
        self.progress_bar.setToolTip(
            self.tr("已确认 {done}/{total}").format(
                done=counts["confirmed_both"], total=counts["total"]
            )
        )
        self.summary_label.setText(
            self.tr(
                "对象 {total} · 全图待审 {pending} · 类别已确认 "
                "{category} · 框已确认 {geometry} · 疑难 {difficult} · "
                "暂跳 {skipped} · 新增待处理 {new_pending}"
            ).format(
                total=counts["total"],
                pending=pending_total,
                category=counts["category_confirmed"],
                geometry=counts["geometry_confirmed"],
                difficult=counts["difficult"],
                skipped=counts["skipped"],
                new_pending=counts["new_pending"],
            )
        )
        coverage = session.state.coverage
        coverage_text = self.tr("查漏尚未开始")
        if coverage is not None:
            completed = sum(
                1 for region in coverage.regions if region.completed
            )
            coverage_text = self.tr("查漏 {done}/{total}").format(
                done=completed, total=len(coverage.regions)
            )
        unsaved = bool(getattr(self.host, "dirty", False) or session.dirty)
        self.completion_label.setText(
            self.tr("{status} · {coverage}{unsaved}").format(
                status=self.tr(completion.label),
                coverage=coverage_text,
                unsaved=(self.tr(" · 复核进度待保存") if unsaved else ""),
            )
        )
        if completion.complete:
            self.completion_label.setStyleSheet(
                "color: #22A06B; font-weight: 600;"
            )
        else:
            self.completion_label.setStyleSheet("")
        reasons = self.tr("；").join(completion.reasons[:6])
        if reasons:
            self.completion_label.setToolTip(reasons)
        current = session.current_object()
        if current is not None:
            category = (
                self.tr("类别✓")
                if current.confirmed("category")
                else self.tr("类别待审")
            )
            geometry = (
                self.tr("框✓")
                if current.confirmed("geometry")
                else self.tr("框待审")
            )
            self.current_object_label.setText(
                self.tr(
                    "#{index} {label} · {status} · {category} · " "{geometry}"
                ).format(
                    index=current.display_index,
                    label=current.label,
                    status=self.tr(current.status_text()),
                    category=category,
                    geometry=geometry,
                )
            )
            self.rule_label.setText(
                self.tr("本类规则：{rules}").format(
                    rules=session.rule_summary(current.label, self.tr)
                )
            )
        else:
            self.current_object_label.setText(self.tr("本批没有对象"))
            self.rule_label.setText("")
        labels = session.label_counts()
        stats = " · ".join(
            f"{label} {count}" for label, count in labels.items()
        )
        self.config_label.setText(
            self.tr("{batches} 批 · {labels} 类").format(
                batches=len(session.state.batches), labels=len(labels)
            )
        )
        self.config_label.setToolTip(
            self.tr(
                "固定数字映射下仍可改为任意类别。当前类别统计：{stats}"
            ).format(stats=stats or self.tr("无"))
        )
        self._set_controls_enabled(True)
        self._refresh_exclusion_hint()

    def _sync_list_enabled(self) -> None:
        """Enable the three lists only when their backing content exists.

        ``_set_empty_state`` disables batches, cards and regions together
        with every action, but nothing re-enabled the lists, so a session
        opened after the empty state left them inert (WL-05, WL-06).  Each
        gate below mirrors what the list currently holds, which keeps the
        rendered content and the operability in sync.
        """
        session = self.session
        ready = session is not None
        self.batch_list.setEnabled(bool(ready and self.batch_list.count()))
        self.card_list.setEnabled(bool(ready and self._card_model.rowCount()))
        coverage = session.state.coverage if ready else None
        has_regions = bool(coverage is not None and coverage.regions)
        self.region_list.setEnabled(has_regions)
        # Region actions depend on a plan, so they follow the same gate
        # instead of the coarser "session exists" one.
        for widget in (
            self.complete_region_button,
            self.region_difficult_button,
            self.clear_region_difficult_button,
            self.region_skip_button,
            self.clear_region_skip_button,
            self.current_region_button,
        ):
            widget.setEnabled(has_regions)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.complete_batch_button,
            self.complete_object_button,
            self.skip_button,
            self.difficult_button,
            self.clear_difficult_button,
            self.unskip_button,
            self.members_button,
            self.rebuild_button,
            self.compare_button,
            self.complete_region_button,
            self.region_difficult_button,
            self.clear_region_difficult_button,
            self.region_skip_button,
            self.clear_region_skip_button,
            self.current_region_button,
            self.rebuild_plan_button,
        ):
            widget.setEnabled(enabled)
        self.add_to_batch_button.setEnabled(
            enabled
            and self.session is not None
            and self._current_shape_id() in self.session.state.new_pending
        )

    def _refresh_batches(self) -> None:
        session = self.session
        if session is None:
            return
        current = session.state.current_batch
        self.batch_list.blockSignals(True)
        self.batch_list.clear()
        entries = [
            (
                batch.batch_id,
                (
                    self.tr(batch.name)
                    if batch.batch_id == OTHER_BATCH_ID
                    else batch.name
                ),
                list(batch.member_ids),
            )
            for batch in session.state.batches
        ]
        if session.state.new_pending:
            entries.append(
                (
                    NEW_PENDING_BATCH_ID,
                    self.tr("新增待处理"),
                    list(session.state.new_pending),
                )
            )
        selected_row = -1
        names: list[str] = []
        for row, (batch_id, name, members) in enumerate(entries):
            counts = self._batch_counts(session, members)
            item = QtWidgets.QListWidgetItem(name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, batch_id)
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, counts["total"])
            item.setData(
                QtCore.Qt.ItemDataRole.UserRole + 2, counts["category"]
            )
            item.setData(
                QtCore.Qt.ItemDataRole.UserRole + 3, counts["geometry"]
            )
            if batch_id == current:
                selected_row = row
            names.append(name)
            self.batch_list.addItem(item)
        if selected_row < 0 and entries:
            # The session cursor is authoritative; if it no longer exists
            # (for example after an explicit queue rebuild) adopt the first
            # entry instead of highlighting one batch and showing another.
            session.set_current(entries[0][0])
            selected_row = 0
            current = entries[0][0]
        if entries:
            self.batch_list.setCurrentRow(selected_row)
        self.batch_list.blockSignals(False)
        self._sync_compact_batches(current)

    def _sync_compact_batches(self, current: str) -> None:
        combo = getattr(self, "compact_batch_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        for row in range(self.batch_list.count()):
            item = self.batch_list.item(row)
            batch_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            combo.addItem(item.text(), batch_id)
            if batch_id == current:
                combo.setCurrentIndex(row)
        combo.blockSignals(False)

    def _on_compact_batch_activated(self, index: int) -> None:
        if self._updating or index < 0 or self.session is None:
            return
        batch_id = self.compact_batch_combo.itemData(index)
        if not batch_id:
            return
        for row in range(self.batch_list.count()):
            item = self.batch_list.item(row)
            if item.data(QtCore.Qt.ItemDataRole.UserRole) == batch_id:
                if row == self.batch_list.currentRow():
                    self._activate_batch(str(batch_id))
                else:
                    self.batch_list.setCurrentRow(row)
                return

    @staticmethod
    def _batch_counts(session, members) -> dict[str, int]:
        items = [
            session.state.objects[shape_id]
            for shape_id in members
            if shape_id in session.state.objects
        ]
        return {
            "total": len(items),
            "category": sum(1 for item in items if item.confirmed("category")),
            "geometry": sum(1 for item in items if item.confirmed("geometry")),
        }

    def _refresh_cards(self, force: bool = False) -> None:
        session = self.session
        if session is None:
            return
        batch_id = self._current_batch_id()
        members = session.state.member_ids(batch_id)
        signature = (batch_id, tuple(members))
        current_shape = self._current_shape_id()
        states = [
            session.object(shape_id)
            for shape_id in members
            if session.object(shape_id) is not None
        ]
        if force or signature != self._cards_signature:
            self._card_model.set_rows(states, self._failed_ids)
            self._cards_signature = signature
            if current_shape:
                self._select_shape_id(current_shape)
            keep = set(self._visible_shape_ids())
            if current_shape:
                keep.add(current_shape)
            self._card_model.retain_icons(keep)
        else:
            self._card_model.update_states(states, self._failed_ids)
        self._update_action_labels()

    def _update_action_labels(self) -> None:
        session = self.session
        if session is None:
            return
        scope = self._scope()
        if scope is None:
            return
        visible = self._visible_candidate_count(scope.candidate_ids)
        offscreen = max(0, len(scope.candidate_ids) - visible)
        self.batch_note_label.setText(
            self.tr(
                "本批成员 {total} · 可确认 {candidate} · 排除 {excluded} · "
                "屏外候选 {offscreen}"
            ).format(
                total=scope.total,
                candidate=len(scope.candidate_ids),
                excluded=scope.excluded_count,
                offscreen=offscreen,
            )
        )
        self.complete_batch_button.setText(
            self.tr("完成本批并进入下一批（确认 {n}，保留 {m}）").format(
                n=len(scope.candidate_ids),
                m=scope.excluded_count,
            )
        )
        self.complete_batch_button.setEnabled(bool(scope.candidate_ids))
        current = session.current_object()
        if current is None:
            return
        self.clear_difficult_button.setEnabled(current.difficult)
        self.unskip_button.setEnabled(current.skipped)
        self.difficult_button.setEnabled(not current.difficult)
        per_object = self.per_object_checkbox.isChecked()
        self.complete_object_button.setEnabled(
            per_object and not current.difficult and not current.skipped
        )
        self.skip_button.setEnabled(per_object and not current.skipped)
        self.add_to_batch_button.setEnabled(
            current.shape_id in session.state.new_pending
        )

    # -- thumbnails ----------------------------------------------------

    def _schedule_visible_thumbnails(self, *_args) -> None:
        QtCore.QTimer.singleShot(0, self._request_visible_thumbnails)

    def _thumbnail_source(self):
        image_path, image_bytes = self.host.dense_review_image_source()
        source_version = self.host.dense_review_image_info()[0]
        margin = self.context_spin.value() / 100.0
        return (
            image_path,
            image_bytes,
            source_version,
            margin,
            self._thumbnail_target_pixels(),
        )

    def _request_visible_thumbnails(self) -> None:
        if self.session is None:
            return
        if not self.card_list.isVisible():
            self._ensure_compare_requests()
            return
        image_path, image_bytes, source_version, margin, target = (
            self._thumbnail_source()
        )
        generation = self.thumbnails.generation
        current = self._current_shape_id()
        requested = self._visible_shape_ids(prefetch_rows=1)
        if current and current not in requested:
            requested.append(current)
        self._card_model.retain_icons(requested)
        for shape_id in requested:
            item = self.session.object(shape_id)
            if item is None:
                continue
            key = self.thumbnails.request_key(
                shape_id,
                generation,
                item.bounds,
                margin,
                target,
                source_version,
            )
            if self._card_request_keys.get(shape_id) != key:
                self.thumbnails.invalidate_shape(shape_id)
                self._failed_ids.discard(shape_id)
                self._card_request_keys[shape_id] = key
                self._card_model.clear_icon(shape_id)
                self._card_model.clear_failed(shape_id)
            cached = self.thumbnails.cached_image(
                shape_id,
                item.bounds,
                margin,
                target,
                source_version,
            )
            if cached is not None:
                self._card_model.set_icon(
                    shape_id, QtGui.QIcon(QtGui.QPixmap.fromImage(cached))
                )
                continue
            if shape_id in self._failed_ids:
                continue
            self.thumbnails.request(
                shape_id,
                item.bounds,
                margin,
                target,
                image_path,
                image_bytes,
                source_version,
            )
        self._ensure_compare_requests()

    def _on_thumbnail_ready(self, shape_id: str, image) -> None:
        self._failed_ids.discard(shape_id)
        self._card_model.clear_failed(shape_id)
        self._card_model.set_icon(
            shape_id, QtGui.QIcon(QtGui.QPixmap.fromImage(image))
        )
        self._update_compare_dialogs(shape_id, image=image)
        self._schedule_action_labels()

    def _defer_background_cards(self) -> bool:
        """Report whether the canvas is being manipulated right now."""
        canvas = getattr(self.host, "canvas", None)
        if canvas is None:
            return False
        return bool(
            getattr(canvas, "is_pointer_down", False)
            or getattr(canvas, "moving_shape", False)
        )

    def _schedule_action_labels(self) -> None:
        """Coalesce card-driven label updates into one per event-loop turn.

        A thumbnail batch can deliver dozens of ready signals in one timer
        tick; recomputing the candidate scope for each of them blocked drag
        frames measurably (OpenSpec 10.1/10.2).
        """
        if getattr(self, "_labels_update_pending", False):
            return
        self._labels_update_pending = True
        QtCore.QTimer.singleShot(0, self._flush_action_labels)

    def _flush_action_labels(self) -> None:
        self._labels_update_pending = False
        self._update_action_labels()

    def _on_thumbnail_failed(self, shape_id: str, reason: str) -> None:
        self._failed_ids.add(shape_id)
        self._card_model.set_failed(shape_id, reason)
        self._update_compare_dialogs(shape_id, reason=reason)
        self._schedule_action_labels()

    # -- side-by-side comparison ---------------------------------------

    def _compare_key(self, shape_id: str, item):
        _, _, source_version, margin, target = self._thumbnail_source()
        return self.thumbnails.request_key(
            shape_id,
            self.thumbnails.generation,
            item.bounds,
            margin,
            target,
            source_version,
        )

    def _ensure_compare_requests(self) -> None:
        for dialog in list(self._compare_dialogs):
            for shape_id in dialog.shape_ids:
                self._ensure_compare_thumbnail(shape_id, dialog)

    def _ensure_compare_thumbnail(self, shape_id: str, dialog=None) -> None:
        session = self.session
        if session is None:
            return
        item = session.object(shape_id)
        if item is None:
            if dialog is not None:
                dialog.set_failed(shape_id, self.tr("对象不存在"))
            return
        key = self._compare_key(shape_id, item)
        previous = self._compare_request_keys.get(shape_id)
        if previous is not None and previous != key:
            self._failed_ids.discard(shape_id)
            self._card_model.clear_failed(shape_id)
            self.thumbnails.invalidate_shape(shape_id)
        if self._failed_ids and shape_id in self._failed_ids:
            if dialog is not None:
                dialog.set_failed(shape_id, self.tr("图块加载失败"))
            return
        cached = self.thumbnails.cached_image(
            shape_id,
            item.bounds,
            self.context_spin.value() / 100.0,
            (360, 240),
            self.host.dense_review_image_info()[0],
        )
        if cached is not None:
            self._compare_request_keys[shape_id] = key
            if dialog is not None:
                dialog.set_image(shape_id, cached)
            return
        if (
            self._compare_request_keys.get(shape_id) == key
            and shape_id in self.thumbnails._pending
        ):
            return
        if dialog is not None:
            dialog.set_pending(shape_id)
        self._compare_request_keys[shape_id] = key
        image_path, image_bytes, _, margin, target = self._thumbnail_source()
        image = self.thumbnails.request(
            shape_id,
            item.bounds,
            margin,
            target,
            image_path,
            image_bytes,
            self.host.dense_review_image_info()[0],
        )
        if image is not None and dialog is not None:
            dialog.set_image(shape_id, image)

    def _update_compare_dialogs(
        self, shape_id: str, image=None, reason: str = ""
    ) -> None:
        for dialog in list(self._compare_dialogs):
            if shape_id not in dialog.shape_ids:
                continue
            if reason:
                dialog.set_failed(shape_id, reason)
            elif image is not None:
                dialog.set_image(shape_id, image)

    def _on_compare_closed(self, dialog) -> None:
        if dialog in self._compare_dialogs:
            self._compare_dialogs.remove(dialog)

    def _close_compare_dialogs(self) -> None:
        for dialog in list(self._compare_dialogs):
            self._compare_dialogs.remove(dialog)
            dialog.close()

    def _on_card_height_changed(self, value: int) -> None:
        """Apply the slider height without fighting the user's drag.

        Requests are coalesced through the provider's bounded queue, so
        dragging the slider does not schedule one crop per pixel
        (OC-07, OC-18).
        """
        self.image_height_label.setText(str(int(value)))
        self.set_card_image_height(int(value))

    def _thumbnail_target_pixels(self) -> tuple:
        """Return the cached thumbnail size for the current card geometry.

        The target follows the displayed image area multiplied by the device
        pixel ratio, so a 200% screen gets a sharp crop instead of an
        upscaled 1x image (OC-09, OC-17).
        """
        cell = self._card_cell_size()
        width = max(1, cell.width() - 20)
        height = max(1, self._card_image_height)
        ratio = float(self.devicePixelRatioF() or 1.0)
        return (int(round(width * ratio)), int(round(height * ratio)))

    def _on_context_changed(self) -> None:
        self._generation += 1
        self.thumbnails.start_generation(self._generation)
        self._failed_ids.clear()
        self._compare_request_keys.clear()
        self._close_compare_dialogs()
        self._refresh_cards(force=True)
        self._request_visible_thumbnails()
        self._focus_current()

    # -- object actions ------------------------------------------------

    def _on_batch_selected(self, current, _previous) -> None:
        if self._updating or current is None or self.session is None:
            return
        batch_id = current.data(QtCore.Qt.ItemDataRole.UserRole)
        if not batch_id:
            return
        self._activate_batch(str(batch_id))

    def _activate_batch(self, batch_id: str) -> None:
        session = self.session
        if session is None:
            return
        if session.state.current_batch != batch_id:
            session.set_current(batch_id)
        self._cards_signature = None
        self.refresh_all(force_cards=True)
        self._focus_current()

    def _on_dimensions_changed(self, *_args) -> None:
        if self._updating or self.session is None:
            return
        self.session.set_dimensions(self._dimensions())
        self._update_action_labels()
        self._refresh_batches()

    def _on_card_selection_changed(self, _selected, _deselected) -> None:
        self._on_card_selected()

    def _on_card_selected(self) -> None:
        if self._updating or self.session is None:
            return
        selected = self._selected_shape_ids()
        if not selected:
            return
        self.session.set_current(self._current_batch_id(), selected[0])
        self._update_summary()
        self._update_action_labels()
        self.host.refresh_dense_review_display()
        self._focus_current()

    def _on_per_object_toggled(self, _checked) -> None:
        self._update_action_labels()

    def _focus_current(self) -> None:
        session = self.session
        if session is None or self._full_image:
            return
        shape_id = self._current_shape_id()
        if shape_id:
            self.host.dense_review_focus_object(shape_id)

    def _navigate_to(self, batch_id: str, shape_id: str) -> None:
        if not shape_id:
            return
        self.session.set_current(
            batch_id or self._current_batch_id(), shape_id
        )
        self._cards_signature = None
        self.refresh_all(force_cards=True)
        self._focus_current()

    def _complete_batch(self) -> None:
        session = self.session
        scope = self._scope()
        if session is None or scope is None:
            return
        manual, filtered, failed = self._exclusions()
        result = session.confirm_batch(
            scope.batch_id,
            scope.dimensions,
            expected_fingerprint=scope.fingerprint,
            manual_hidden_ids=manual,
            filtered_ids=filtered,
            failed_ids=failed,
        )
        if result.conflict:
            self._status(
                self.tr("确认期间对象或范围发生变化，已刷新；请重新确认。")
            )
            self.refresh_all(force_cards=True)
            return
        if result.status == "empty":
            self._status(self.tr("本批没有可确认对象；请先处理排除项。"))
            self.refresh_all(force_cards=True)
            return
        notify_metrics(
            self.host,
            "review_event",
            "review-confirm",
            affected_ids=list(result.confirmed_ids),
        )
        self.host.dense_review_after_progress_change()
        if result.next_object_id:
            self._navigate_to(result.next_batch_id, result.next_object_id)
        else:
            self.refresh_all(force_cards=True)
        self._status(
            self.tr("已确认 {n} 个；保留待处理 {m} 个。").format(
                n=len(result.confirmed_ids), m=len(result.excluded)
            )
        )

    def _complete_current_object(self) -> None:
        session = self.session
        if session is None:
            return
        shape_id = self._current_shape_id()
        if not shape_id:
            return
        if session.confirm_object(shape_id, self._dimensions()):
            notify_metrics(
                self.host,
                "review_event",
                "review-confirm",
                affected_ids=[shape_id],
            )
            self._advance_object(shape_id)
            self.host.dense_review_after_progress_change()
            self._status(self.tr("当前对象已完成并前进。"))
        else:
            self._status(self.tr("当前对象没有新的可确认内容。"))

    def _skip_current(self) -> None:
        session = self.session
        if session is None:
            return
        shape_id = self._current_shape_id()
        if not shape_id:
            return
        session.mark_skipped(shape_id)
        self._advance_object(shape_id)
        self.host.dense_review_after_progress_change()
        self._status(self.tr("当前对象已暂跳，仍保持待审。"))

    def _advance_object(self, shape_id: str) -> None:
        """Advance within a batch, then across batches without confirming.

        Move the cursor before autosave so the saved progress and the
        visible next object refer to the same transaction.
        """
        session = self.session
        batch_id = self._current_batch_id()
        next_id = session.next_pending_object(
            batch_id, self._dimensions(), after=shape_id
        )
        if not next_id:
            next_batch = session.next_pending_batch(
                self._dimensions(), after=batch_id
            )
            if next_batch is not None:
                batch_id = next_batch
                next_id = session.next_pending_object(
                    batch_id, self._dimensions()
                )
        if next_id:
            self._navigate_to(batch_id, next_id)
        else:
            self.refresh_all(force_cards=True)

    def _mark_current_difficult(self) -> None:
        session = self.session
        if session is None:
            return
        shape_id = self._current_shape_id()
        if not shape_id:
            return
        reason, accepted = QtWidgets.QInputDialog.getText(
            self,
            self.tr("标记疑难"),
            self.tr("疑难原因（可留空）："),
        )
        if not accepted:
            return
        self._apply_difficult(shape_id, reason)

    def _mark_current_difficult_quick(self) -> None:
        if self.session is None:
            return
        shape_id = self._current_shape_id()
        if shape_id:
            self._apply_difficult(shape_id, "")

    def _apply_difficult(self, shape_id: str, reason: str) -> None:
        self.session.mark_difficult(shape_id, self._dimensions(), reason)
        self.host.dense_review_after_progress_change()
        self.refresh_all(force_cards=True)
        self._status(self.tr("当前对象已标记疑难；解除前不会自动确认。"))

    def _clear_current_difficult(self) -> None:
        if self.session is None:
            return
        if self.session.clear_difficult(self._current_shape_id()):
            self.host.dense_review_after_progress_change()
            self.refresh_all(force_cards=True)
            self._status(self.tr("已解除疑难；请重新确认相关维度。"))

    def _clear_current_skipped(self) -> None:
        if self.session is None:
            return
        if self.session.clear_skipped(self._current_shape_id()):
            self.host.dense_review_after_progress_change()
            self.refresh_all(force_cards=True)
            self._status(self.tr("已取消暂跳；请重新确认相关维度。"))

    def _add_current_to_batch(self) -> None:
        session = self.session
        if session is None:
            return
        shape_id = self._current_shape_id()
        if shape_id not in session.state.new_pending:
            return
        batches = [batch for batch in session.state.batches]
        if not batches:
            self._status(self.tr("没有可加入的批次。"))
            return
        names = [batch.name for batch in batches]
        name, accepted = QtWidgets.QInputDialog.getItem(
            self,
            self.tr("加入当前批次"),
            self.tr("选择目标批次："),
            names,
            0,
            False,
        )
        if not accepted:
            return
        batch_id = batches[names.index(name)].batch_id
        if session.add_to_batch(shape_id, batch_id):
            self.host.dense_review_after_progress_change()
            self.refresh_all(force_cards=True)
            self._status(self.tr("新增对象已加入批次；确认范围已更新。"))

    def _rebuild_queue(self) -> None:
        if self.session is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("重建剩余队列"),
            self.tr(
                "将按当前类别和配置重新分配全部存活对象。"
                "已有内容确认会保留，但新增待处理队列会被清空。是否继续？"
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.session.rebuild_queue(self.host.dense_review_shapes())
        self.host.dense_review_after_progress_change()
        self.refresh_all(force_cards=True)
        self._status(self.tr("剩余队列已按当前类别显式重建。"))

    def _show_members(self) -> None:
        session = self.session
        if session is None:
            return
        members = session.state.member_ids(self._current_batch_id())
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("本批成员"))
        dialog.resize(680, 480)
        layout = QtWidgets.QVBoxLayout(dialog)
        table = QtWidgets.QTableWidget(len(members), 5)
        table.setHorizontalHeaderLabels(
            [
                self.tr("短编号"),
                self.tr("对象 ID"),
                self.tr("类别"),
                self.tr("状态"),
                self.tr("疑难原因"),
            ]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        for row, shape_id in enumerate(members):
            item = session.object(shape_id)
            values = (
                f"#{item.display_index}" if item else "?",
                shape_id,
                item.label if item else "",
                self.tr(item.status_text()) if item else self.tr("缺失"),
                item.difficulty_reason if item else "",
            )
            for column, value in enumerate(values):
                table.setItem(
                    row,
                    column,
                    QtWidgets.QTableWidgetItem(str(value)),
                )
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        close_button = QtWidgets.QPushButton(self.tr("关闭"))
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()

    def _compare_selected(self) -> None:
        session = self.session
        if session is None:
            return
        ids = self._selected_shape_ids()
        if len(ids) != 2:
            self._status(self.tr("请用 Ctrl 选择两个对象后再比较。"))
            return
        self._open_compare(ids)

    def _open_compare(self, shape_ids: Iterable[str]) -> _CompareDialog:
        self._close_compare_dialogs()
        dialog = _CompareDialog(self, shape_ids, self)
        self._compare_dialogs.append(dialog)
        for shape_id in dialog.shape_ids:
            self._ensure_compare_thumbnail(shape_id, dialog)
        dialog.show()
        dialog.raise_()
        self._status(self.tr("比较不会复制标注或改变对象身份。"))
        return dialog

    def retry_compare(self, shape_id: str, dialog) -> None:
        self._failed_ids.discard(shape_id)
        self._card_model.clear_failed(shape_id)
        self._compare_request_keys.pop(shape_id, None)
        self.thumbnails.invalidate_shape(shape_id)
        dialog.set_pending(shape_id)
        self._ensure_compare_thumbnail(shape_id, dialog)

    # -- display and view ---------------------------------------------

    def _on_display_mode_changed(self, *_args) -> None:
        if self._updating:
            return
        previous = self._display_mode
        self._display_mode = str(self.display_combo.currentData())
        self.host.dense_review_set_display_mode(self._display_mode)
        # Switching into or out of the source comparison must not re-centre
        # the canvas: that would turn a display switch into a navigation and
        # throw away the user's zoom (DP-13).  Ordinary object navigation
        # keeps its original entry point.
        if "original" in (previous, self._display_mode):
            return
        self._focus_current()

    def _begin_hold_original(self) -> None:
        """Start the held source-image comparison from the toolbar button."""
        self.host.dense_review_begin_hold_original()

    def _end_hold_original(self) -> None:
        """End the held comparison when the button is released."""
        self.host.dense_review_end_hold_original()

    def _toggle_full_image(self) -> None:
        self._full_image = self.host.dense_review_toggle_full_image()
        self.full_image_button.setText(
            self.tr("返回局部") if self._full_image else self.tr("看全图")
        )
        if not self._full_image:
            self.host.dense_review_set_display_mode(self._display_mode)

    # -- coverage ------------------------------------------------------

    def _task_for_page(self, index: int) -> str:
        return self.TASK_COVERAGE if index == 1 else self.TASK_CATEGORY

    def _on_tab_changed(self, index) -> None:
        """Treat a page click as a task request.

        The tab widget stays as the visible page container, but navigation is
        driven only by the task entry point so the old tabs and the new
        selector can never disagree (WL-07).
        """
        if self._switching_task or self.session is None:
            return
        task_id = self._task_for_page(index)
        if task_id == self._task_id:
            return
        target = self.TASK_COVERAGE
        if task_id != self.TASK_COVERAGE:
            current = self.task_selector.currentData()
            target = (
                current
                if current in (self.TASK_CATEGORY, self.TASK_BOX_POINTS)
                else self.TASK_CATEGORY
            )
        self.set_task(target)

    def _on_task_selected(self, _index: int) -> None:
        if self._switching_task:
            return
        task_id = self.task_selector.currentData()
        if not task_id or task_id == self._task_id:
            return
        self.set_task(str(task_id))

    # -- task switching ------------------------------------------------

    @property
    def task_id(self) -> str:
        """Return the stable id of the active task view."""
        return self._task_id

    def _task_view_key(self, task_id: str) -> str:
        return f"{(self.host.filename or '')}|{task_id}"

    def _task_state_for(self, task_id: str) -> dict:
        """Return the per-image navigation state for one task."""
        image = self.host.filename or ""
        if image != self._task_state_image:
            # A new image must never inherit the previous one's targets.
            self._task_views = {}
            self._task_state_image = image
        return self._task_views.setdefault(self._task_view_key(task_id), {})

    def _capture_task_view(self, task_id: str) -> None:
        state = self._task_state_for(task_id)
        state["viewport"] = self.host.dense_review_capture_view()
        if task_id == self.TASK_COVERAGE:
            coverage = self.session.state.coverage if self.session else None
            state["region"] = coverage.current_region if coverage else ""
            return
        state["batch"] = self._current_batch_id()
        state["shape"] = self._current_shape_id()

    def set_task(self, task_id: str, *, restore_view: bool = True) -> bool:
        """Switch the active task view.

        No edit history, confirmation state or object content changes here:
        only the view preset and the navigation target.  A pending edit is
        settled first through the existing boundary, and a rejected settle
        keeps the previous task and viewport (WL-07, WL-08).
        """
        if task_id not in self.TASK_IDS or self.session is None:
            return False
        if task_id == self._task_id and self._view_ready:
            return True
        if not self._settle_edit_boundary():
            return False
        if self._task_id:
            self._capture_task_view(self._task_id)

        self._switching_task = True
        try:
            self._task_id = task_id
            self._apply_task_display(task_id)
            self._show_task_page(task_id)
        finally:
            self._switching_task = False

        self._restore_task_target(task_id)
        if restore_view:
            self._restore_task_viewport(task_id)
        self._refresh_task_selector()
        return True

    def _settle_edit_boundary(self) -> bool:
        """Settle a live edit before the view switches."""
        self.host._dense_review_cancel_pending_edit()
        self.host.canvas.suspend_active_editing()
        return True

    def _apply_task_display(self, task_id: str) -> None:
        if task_id == self.TASK_COVERAGE:
            self.session.ensure_coverage()
            self._refresh_coverage()
            self._set_display_mode_widget("all")
            self.host.dense_review_apply_task_preset(self.TASK_COVERAGE)
            return
        self._set_display_mode_widget("focus")
        preset = (
            self.TASK_BOX_POINTS
            if task_id == self.TASK_BOX_POINTS
            else self.TASK_CATEGORY
        )
        self.host.dense_review_apply_task_preset(preset)

    def _set_display_mode_widget(self, mode: str) -> None:
        combo = self.display_combo
        index = combo.findData(mode)
        if index < 0:
            return
        self._display_mode = mode
        if combo.currentIndex() == index:
            self.host.dense_review_set_display_mode(mode)
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self.host.dense_review_set_display_mode(mode)

    def _show_task_page(self, task_id: str) -> None:
        page = self.TASK_PAGE[task_id]
        if self.tabs.currentIndex() == page:
            return
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(page)
        self.tabs.blockSignals(False)

    def _refresh_task_selector(self) -> None:
        index = self.task_selector.findData(self._task_id)
        if index < 0 or self.task_selector.currentIndex() == index:
            return
        self.task_selector.blockSignals(True)
        self.task_selector.setCurrentIndex(index)
        self.task_selector.blockSignals(False)

    def _restore_task_target(
        self, task_id: str, *, focus: bool = True
    ) -> bool:
        """Restore a task's target; return whether a stored target existed.

        ``focus`` controls whether the canvas is re-centred on that target.
        An explicit task switch navigates to it; re-opening the panel after a
        hide only re-applies the target and leaves the viewport alone (R4).
        """
        state = self._task_state_for(task_id)
        session = self.session
        if session is None:
            return False
        if task_id == self.TASK_COVERAGE:
            coverage = session.ensure_coverage()
            region_id = str(state.get("region") or "")
            if region_id and coverage.region(region_id) is not None:
                session.set_current_region(region_id)
                self._refresh_coverage()
                if focus:
                    self._show_current_region()
                else:
                    self._sync_current_region_display()
                return True
            self._refresh_coverage()
            if focus:
                self._show_current_region()
            else:
                self._sync_current_region_display()
            return False
        shape_id = str(state.get("shape") or "")
        batch_id = str(state.get("batch") or "")
        if shape_id and session.object(shape_id) is not None:
            session.set_current(batch_id or self._current_batch_id(), shape_id)
        # Rebuild the cards once.  Centring on the object is the caller's
        # decision: an explicit task switch navigates, while re-opening the
        # panel keeps whatever viewport the user currently has (R4).
        self._cards_signature = None
        self.refresh_all(force_cards=True)
        if focus:
            self._focus_current()
        return bool(shape_id and session.object(shape_id) is not None)

    def _restore_task_view(
        self, *, restore_viewport: bool = True, focus: bool = True
    ) -> None:
        """Restore the active task's target (and optionally its viewport)."""
        task_id = self._task_id
        self._switching_task = True
        try:
            self._apply_task_display(task_id)
            self._show_task_page(task_id)
        finally:
            self._switching_task = False
        self._restore_task_target(task_id, focus=focus)
        if restore_viewport:
            self._restore_task_viewport(task_id)
        self._refresh_task_selector()

    def _restore_task_viewport(self, task_id: str) -> bool:
        state = self._task_state_for(task_id)
        viewport = state.get("viewport")
        if not viewport:
            return False
        return self.host.dense_review_restore_view(viewport)

    def _refresh_coverage(self) -> None:
        session = self.session
        if session is None:
            return
        plan = session.state.coverage
        self.region_list.blockSignals(True)
        self.region_list.clear()
        self._region_items = {}
        if plan is None:
            self.coverage_stats_label.setText(
                self.tr("查漏计划尚未建立；重建区域计划后可开始。")
            )
            self.coverage_grid.set_plan(None)
            self.region_list.blockSignals(False)
            return
        self.columns_spin.blockSignals(True)
        self.rows_spin.blockSignals(True)
        self.overlap_spin.blockSignals(True)
        self.columns_spin.setValue(plan.columns)
        self.rows_spin.setValue(plan.rows)
        self.overlap_spin.setValue(round(plan.overlap * 100))
        self.columns_spin.blockSignals(False)
        self.rows_spin.blockSignals(False)
        self.overlap_spin.blockSignals(False)
        selected_row = 0
        for row, region in enumerate(plan.regions):
            if region.difficult:
                status = self.tr("疑难")
            elif region.skipped:
                status = self.tr("暂跳")
            elif region.completed:
                status = self.tr("已完成")
            else:
                status = self.tr("待查")
            item = QtWidgets.QListWidgetItem(status)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, region.region_id)
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, region.region_id)
            item.setData(
                QtCore.Qt.ItemDataRole.UserRole + 2,
                (
                    "difficult"
                    if region.difficult
                    else (
                        "skipped"
                        if region.skipped
                        else "done" if region.completed else "pending"
                    )
                ),
            )
            self.region_list.addItem(item)
            self._region_items[region.region_id] = item
            if region.region_id == plan.current_region:
                selected_row = row
        self.region_list.setCurrentRow(selected_row)
        self.region_list.blockSignals(False)
        self.coverage_grid.set_plan(plan, plan.current_region)
        completed = sum(1 for region in plan.regions if region.completed)
        difficult = sum(1 for region in plan.regions if region.difficult)
        skipped = sum(1 for region in plan.regions if region.skipped)
        self.coverage_stats_label.setText(
            self.tr(
                "区域 {done}/{total} 已完成 · 疑难 {difficult} · "
                "暂跳 {skipped}。区域完成只代表用户检查声明，"
                "不代表机器保证无漏标。"
            ).format(
                done=completed,
                total=len(plan.regions),
                difficult=difficult,
                skipped=skipped,
            )
        )

    def _on_region_selected(self, current, _previous) -> None:
        if self._updating or current is None or self.session is None:
            return
        region_id = current.data(QtCore.Qt.ItemDataRole.UserRole)
        if not region_id:
            return
        self.session.set_current_region(str(region_id))
        self.host.dense_review_show_coverage_region(str(region_id))
        self.coverage_grid.set_current(str(region_id))

    def _on_grid_region_clicked(self, region_id: str) -> None:
        item = self._region_items.get(region_id)
        if item is not None:
            self.region_list.setCurrentItem(item)
            return
        if self.session is None:
            return
        self.session.set_current_region(region_id)
        self.host.dense_review_show_coverage_region(region_id)
        self.coverage_grid.set_current(region_id)

    def _sync_current_region_display(self) -> None:
        """Re-sync the region overlay and list highlight without moving.

        Keeps the region rectangle drawn while leaving zoom and pan exactly
        where the user put them (R2).
        """
        session = self.session
        if session is None or session.state.coverage is None:
            return
        region_id = session.state.coverage.current_region
        if not region_id:
            return
        region = session.state.coverage.region(region_id)
        if region is not None:
            self.host.dense_review_refresh_coverage_region(region.rect)
        self.coverage_grid.set_current(region_id)
        item = self._region_items.get(region_id)
        if item is not None and self.region_list.currentItem() is not item:
            self.region_list.blockSignals(True)
            self.region_list.setCurrentItem(item)
            self.region_list.blockSignals(False)

    def _show_current_region(self) -> None:
        session = self.session
        if session is None or session.state.coverage is None:
            return
        region_id = session.state.coverage.current_region
        if not region_id:
            return
        self.session.set_current_region(region_id)
        self.host.dense_review_show_coverage_region(region_id)
        self.coverage_grid.set_current(region_id)
        item = self._region_items.get(region_id)
        if item is not None:
            self.region_list.setCurrentItem(item)

    def _complete_current_region(self) -> None:
        session = self.session
        if session is None or session.state.coverage is None:
            return
        region_id = session.state.coverage.current_region
        if not session.complete_region(region_id):
            self._status(self.tr("当前区域仍有疑难或暂跳，不能记为完成。"))
            return
        self.host.dense_review_after_progress_change()
        self._refresh_coverage()
        self._show_current_region()
        self._status(self.tr("当前区域已完成；新框仍需单独确认。"))

    def _set_current_region_state(self, kind: str, value: bool) -> None:
        session = self.session
        if session is None or session.state.coverage is None:
            return
        region_id = session.state.coverage.current_region
        if kind == "difficult":
            changed = session.mark_region_difficult(region_id, value)
        else:
            changed = session.mark_region_skipped(region_id, value)
        if changed:
            self.host.dense_review_after_progress_change()
            self._refresh_coverage()
            self._show_current_region()

    def _rebuild_coverage(self) -> None:
        session = self.session
        if session is None:
            return
        if session.state.coverage is not None:
            answer = QtWidgets.QMessageBox.question(
                self,
                self.tr("重建区域计划"),
                self.tr("重建会清除现有区域完成记录，是否继续？"),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        settings = CoverageSettings(
            columns=self.columns_spin.value(),
            rows=self.rows_spin.value(),
            overlap=self.overlap_spin.value() / 100.0,
        )
        session.rebuild_coverage(settings)
        self.host.dense_review_after_progress_change()
        self._refresh_coverage()
        self._show_current_region()

    # -- shortcuts and lifecycle --------------------------------------

    def _install_shortcuts(self) -> None:
        host = self.host
        existing = set()
        get_shortcuts = getattr(host, "existing_shortcut_sequences", None)
        if callable(get_shortcuts):
            existing = set(get_shortcuts())
        specs = (
            (
                "dense_review_complete_batch",
                "Ctrl+Return",
                self._complete_batch,
            ),
            (
                "dense_review_complete_object",
                "Alt+Return",
                self._complete_current_object,
            ),
            ("dense_review_skip", "Alt+N", self._skip_current),
            (
                "dense_review_difficult",
                "Alt+X",
                self._mark_current_difficult_quick,
            ),
            (
                "dense_review_toggle_view",
                "Alt+V",
                self._toggle_full_image,
            ),
        )
        for config_key, default, slot in specs:
            sequence = host.dense_review_shortcut(config_key, default)
            if not sequence:
                continue
            if sequence in existing:
                self._shortcut_warnings.append(
                    self.tr("快捷键 {key} 与现有操作冲突，已禁用。").format(
                        key=sequence
                    )
                )
                continue
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
            # Dock-scoped: a panel action fires only while the panel or one
            # of its children has focus, so the canvas keeps its own keys and
            # one press can never trigger the action twice (WL-09 tracking;
            # the full canvas/floating rules stay with task 9.5).
            shortcut.setContext(
                QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            shortcut.activated.connect(slot)
            shortcut.setEnabled(False)
            self._shortcuts.append(shortcut)
        if self._shortcut_warnings:
            self.status_label.setText("；".join(self._shortcut_warnings))
        self._apply_shortcut_hints()

    def _apply_icons(self) -> None:
        theme = get_theme()
        icons = (
            (self.start_button, "play", theme["selection_text"]),
            (self.complete_batch_button, "check", theme["selection_text"]),
            (
                self.complete_object_button,
                "circle-check",
                theme["text_secondary"],
            ),
            (self.full_image_button, "eye", theme["text_secondary"]),
        )
        for button, name, color in icons:
            button.setIcon(themed_icon(name, color))
            button.setIconSize(QtCore.QSize(15, 15))

    def _apply_shortcut_hints(self) -> None:
        hints = (
            (
                self.complete_batch_button,
                "dense_review_complete_batch",
                "Ctrl+Return",
            ),
            (
                self.complete_object_button,
                "dense_review_complete_object",
                "Alt+Return",
            ),
            (self.skip_button, "dense_review_skip", "Alt+N"),
            (self.difficult_button, "dense_review_difficult", "Alt+X"),
            (
                self.full_image_button,
                "dense_review_toggle_view",
                "Alt+V",
            ),
        )
        for button, config_key, default in hints:
            sequence = self.host.dense_review_shortcut(config_key, default)
            if not sequence:
                continue
            button.setToolTip(
                self.tr("{action}（{key}）").format(
                    action=button.text(),
                    key=sequence,
                )
            )

    # -- auxiliary panels ---------------------------------------------

    def _on_batches_toggle(self, checked: bool) -> None:
        self.set_batches_visible(bool(checked))

    def _on_cards_toggle(self, checked: bool) -> None:
        self.set_cards_visible(bool(checked))

    def set_batches_visible(self, visible: bool) -> None:
        self._batches_visible = bool(visible)
        self.batches_panel.setVisible(self._batches_visible)
        self.batches_toggle_button.setChecked(self._batches_visible)
        self.batches_toggle_button.setText(
            self.tr("隐藏类别批次栏")
            if self._batches_visible
            else self.tr("显示类别批次栏")
        )
        self.compact_batch_combo.setVisible(not self._batches_visible)
        if not self._batches_visible:
            self._sync_compact_batches(self._current_batch_id())
        if self._cards_visible:
            self.card_list.setFocus()

    def set_cards_visible(self, visible: bool) -> None:
        self._cards_visible = bool(visible)
        self.cards_panel.setVisible(self._cards_visible)
        self.cards_toggle_button.setChecked(self._cards_visible)
        self.cards_toggle_button.setText(
            self.tr("隐藏对象卡片栏")
            if self._cards_visible
            else self.tr("显示对象卡片栏")
        )
        if self._cards_visible:
            self._request_visible_thumbnails()
            self.card_list.setFocus()

    def card_resource_stats(self) -> dict[str, int]:
        """Bounded graphical resources owned by the card view."""
        return {
            "rows": self._card_model.rowCount(),
            "icons": self._card_model.icon_count(),
            "provider_cache": len(self.thumbnails._cache),
            "pending_requests": len(self.thumbnails._pending),
            "queued_results": self.thumbnails._queue.qsize(),
            "compare_dialogs": len(self._compare_dialogs),
        }

    @property
    def card_image_height(self) -> int:
        """Current card image-area height in logical pixels."""
        return int(self._card_image_height)

    def set_card_image_height(self, height: int) -> None:
        """Set the card image-area height within the allowed range.

        Height is independent from the crop context: widening the panel only
        changes the column count, never the height the user picked
        (OC-07, OC-08).
        """
        height = max(
            self.MIN_IMAGE_HEIGHT, min(self.MAX_IMAGE_HEIGHT, int(height))
        )
        if height == self._card_image_height:
            return
        self._card_image_height = height
        self._relayout_cards()
        self._card_model.layoutChanged.emit()
        self._schedule_visible_thumbnails()

    def _card_cell_size(self) -> QtCore.QSize:
        """Return the grid cell size for the current image height."""
        text = self.CARD_TEXT_HEIGHT
        return QtCore.QSize(
            max(self.CARD_MIN_WIDTH, self.card_list.gridSize().width()),
            self._card_image_height + text,
        )

    def _relayout_cards(self) -> None:
        viewport = self.card_list.viewport().width()
        if viewport <= 0:
            return
        minimum, gap, right_pad = self.CARD_MIN_WIDTH, 12, 8
        available = max(minimum, viewport - right_pad)
        columns = max(1, (available + gap) // (minimum + gap))
        while columns > 1 and available // columns < minimum:
            columns -= 1
        cell = available // columns
        size = QtCore.QSize(
            cell, self._card_image_height + self.CARD_TEXT_HEIGHT
        )
        if self.card_list.gridSize() != size:
            self.card_list.setGridSize(size)
            self.card_list.doItemsLayout()
        icon = QtCore.QSize(max(1, cell - 20), max(1, self._card_image_height))
        if self.card_list.iconSize() != icon:
            self.card_list.setIconSize(icon)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_cards()

    def changeEvent(self, event) -> None:  # noqa: N802
        """End a held source-image comparison when focus leaves.

        ``DP-14`` requires the held state to die on blur; otherwise the panel
        would stay in source-only mode until the user pressed again.
        """
        if event.type() == QtCore.QEvent.Type.ActivationChange:
            if not self.isActiveWindow():
                self.host.dense_review_end_hold_on_blur()
        super().changeEvent(event)

    def eventFilter(self, watched, event):
        if (
            watched is self.card_list.viewport()
            and event.type() == QtCore.QEvent.Type.Resize
        ):
            self._relayout_cards()
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        for shortcut in self._shortcuts:
            shortcut.setEnabled(True)
        if self._review_view_open:
            # Float/re-dock cycles also emit show events.  The review view is
            # already installed, so only re-affirm the active policy instead
            # of re-navigating or rebuilding the round.
            self.host.refresh_dense_review_display()
            return
        if not self._view_ready:
            self._view_ready = True
            self._refresh_from_host()
            mode = self.display_combo.currentData() or "focus"
            self.host.dense_review_set_display_mode(mode)
            if mode == "original":
                self._review_view_open = True
                return
            self._review_view_open = True
            self._restore_task_view()
            return
        # Re-opening after a real hide: the temporary overlay was released,
        # so the active task preset and its target have to be applied again
        # (R3, WL-07).  The *viewport* is deliberately not restored here -
        # the user may have zoomed elsewhere in between, and re-opening must
        # not silently undo that (R4).
        self._review_view_open = True
        # Re-sync the data without bumping the thumbnail generation: a
        # hide/show pair from floating or re-docking is not a new round, and
        # re-cropping every card there would be wasted work (R1, WL-02).
        self._refresh_from_host(new_generation=False)
        self._restore_task_view(restore_viewport=False, focus=False)

    def hideEvent(self, event) -> None:  # noqa: N802
        """Release the review overlay when the panel really goes away.

        ``hide()``, closing the panel and a window-level hide all land here.
        Floating/re-docking emits a hide followed immediately by a show, so
        the release is idempotent and the following ``showEvent`` restores
        the same policy (R1, DP-17, WL-12).
        """
        super().hideEvent(event)
        if not self._review_view_open:
            return
        self._review_view_open = False
        self._end_review_view()

    def closeEvent(self, event) -> None:
        """End the review *view*, keeping session and edit history.

        A QDockWidget is hidden rather than destroyed here, and the same
        handler runs when the user closes the panel and when the layout
        changes it.  It therefore only releases the temporary review state
        (held comparison, overlay, comparison windows, panel shortcuts);
        ``DenseReviewSession``, the card model and the undo history survive
        so re-opening continues the round (WL-01, WL-02).
        """
        self._review_view_open = False
        self._end_review_view()
        super().closeEvent(event)

    def _end_review_view(self) -> None:
        """Release temporary review state without touching the session."""
        self.host.dense_review_end_hold_on_blur()
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
        self._close_compare_dialogs()
        self.host.dense_review_workspace_closed()

    def shutdown(self) -> None:
        """Release worker resources when the main window really exits."""
        self._end_review_view()
        self.thumbnails.shutdown()

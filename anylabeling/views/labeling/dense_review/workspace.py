"""Non-modal dense annotation review workspace."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.services.dense_review.models import (
    NEW_PENDING_BATCH_ID,
    REVIEW_DIMENSIONS,
    CoverageSettings,
)

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

        well = QtCore.QRectF(
            rect.left() + 10, rect.top() + 12, rect.width() - 20, 108
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


class DenseReviewWorkspace(QtWidgets.QDialog):
    """Batch, card and spatial-review controls over the existing canvas."""

    def __init__(
        self,
        host: Any,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent or host)
        self.host = host
        self.thumbnails = ThumbnailProvider(self)
        self._updating = False
        self._generation = 0
        self._cards_signature = None
        self._shape_items: dict[str, QtWidgets.QListWidgetItem] = {}
        self._region_items: dict[str, QtWidgets.QListWidgetItem] = {}
        self._failed_ids: set[str] = set()
        self._card_request_keys: dict[str, tuple] = {}
        self._last_thumb_generation = -1
        self._display_mode = "focus"
        self._full_image = False
        self._shortcuts: list[QtGui.QShortcut] = []
        self._shortcut_warnings: list[str] = []
        self.setWindowTitle(self.tr("Dense Annotation Review"))
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setObjectName("denseReviewWorkspace")
        self.resize(1280, 860)
        self._build_ui()
        self.setStyleSheet(get_dialog_style() + get_workbench_qss())
        self._connect()
        self._install_shortcuts()
        self.refresh_all(initial=True)

    @property
    def session(self):
        return getattr(self.host, "dense_review_session", None)

    # -- UI ------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
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

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QtWidgets.QWidget()
        left.setMinimumWidth(232)
        left.setMaximumWidth(300)
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

        self.card_list = QtWidgets.QListWidget()
        self.card_list.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.card_list.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.card_list.setMovement(QtWidgets.QListView.Movement.Static)
        self.card_list.setWrapping(True)
        self.card_list.setWordWrap(False)
        self.card_list.setUniformItemSizes(True)
        self.card_list.setSpacing(0)
        self.card_list.setIconSize(QtCore.QSize(180, 108))
        self.card_list.setGridSize(QtCore.QSize(216, 176))
        self.card_list.setItemDelegate(_CardDelegate(self.card_list))
        self.card_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
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
        self.more_button = QtWidgets.QPushButton(self.tr("更多"))
        self.more_button.setObjectName("moreButton")
        self.more_button.setProperty("variant", "quiet")
        self.more_button.setFixedWidth(76)

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
        bar.addWidget(self.more_button)
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
        layout.addWidget(self.region_list, 1)
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
        self.batch_list.currentItemChanged.connect(self._on_batch_selected)
        self.dimension_combo.currentIndexChanged.connect(
            self._on_dimensions_changed
        )
        self.card_list.itemSelectionChanged.connect(self._on_card_selected)
        self.card_list.verticalScrollBar().valueChanged.connect(
            self._schedule_visible_thumbnails
        )
        self.apply_context_button.clicked.connect(self._on_context_changed)
        self.display_combo.currentIndexChanged.connect(
            self._on_display_mode_changed
        )
        self.full_image_button.clicked.connect(self._toggle_full_image)
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
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.region_list.currentItemChanged.connect(self._on_region_selected)
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
        item = self.batch_list.currentItem()
        if item is not None:
            batch_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if batch_id:
                return str(batch_id)
        session = self.session
        return session.state.current_batch if session else ""

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
        visible = set()
        for shape_id in candidate_ids:
            item = self._shape_items.get(shape_id)
            if item is None:
                continue
            if self.card_list.visualItemRect(item).intersects(rect):
                visible.add(shape_id)
        return len(visible)

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
        self.refresh_all(force_cards=True)
        self._focus_current()

    def _refresh_from_host(self) -> None:
        self._generation += 1
        self.thumbnails.start_generation(self._generation)
        self._failed_ids.clear()
        self._card_request_keys.clear()
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
        finally:
            self._updating = False
        QtCore.QTimer.singleShot(0, self._request_visible_thumbnails)
        if not initial:
            self._update_action_labels()

    def _set_empty_state(self) -> None:
        for widget in (
            self.batch_list,
            self.card_list,
            self.region_list,
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
        self.summary_label.setText(self.tr("尚未开始本轮复核。"))
        self.progress_bar.setValue(0)
        self.completion_label.setText("")
        self.config_label.setText("")
        self.current_object_label.setText("")
        self.rule_label.setText("")
        self.batch_note_label.setText("")
        self.coverage_stats_label.setText("")

    def _update_summary(self) -> None:
        session = self.session
        counts = session.counts()
        completion = session.completion_status()
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
                status=completion.label,
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
                    status=current.status_text(),
                    category=category,
                    geometry=geometry,
                )
            )
            self.rule_label.setText(
                self.tr("本类规则：{rules}").format(
                    rules=session.rule_summary(current.label)
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
        current = self._current_batch_id() or session.state.current_batch
        self.batch_list.blockSignals(True)
        self.batch_list.clear()
        entries = [
            (batch.batch_id, batch.name, list(batch.member_ids))
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
        selected_row = 0
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
            self.batch_list.addItem(item)
        self.batch_list.setCurrentRow(selected_row)
        self.batch_list.blockSignals(False)

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
        if force or signature != self._cards_signature:
            selected = current_shape
            self.card_list.blockSignals(True)
            self.card_list.clear()
            self._shape_items = {}
            for shape_id in members:
                item = session.object(shape_id)
                if item is None:
                    continue
                card = QtWidgets.QListWidgetItem(self._card_text(item))
                card.setData(QtCore.Qt.ItemDataRole.UserRole, shape_id)
                self._apply_card_roles(card, item)
                card.setIcon(self._placeholder_icon())
                card.setToolTip(
                    self.tr("对象 {shape_id}\n{status}").format(
                        shape_id=shape_id, status=item.status_text()
                    )
                )
                self.card_list.addItem(card)
                self._shape_items[shape_id] = card
            self._cards_signature = signature
            self.card_list.blockSignals(False)
            if selected in self._shape_items:
                self._shape_items[selected].setSelected(True)
                self.card_list.scrollToItem(self._shape_items[selected])
        else:
            for shape_id, card in self._shape_items.items():
                item = session.object(shape_id)
                if item is not None:
                    card.setText(self._card_text(item))
                    self._apply_card_roles(card, item)
                    card.setToolTip(
                        self.tr("对象 {shape_id}\n{status}").format(
                            shape_id=shape_id,
                            status=item.status_text(),
                        )
                    )
        self._update_action_labels()

    def _card_text(self, item) -> str:
        markers = []
        if item.confirmed("category"):
            markers.append(self.tr("类别✓"))
        if item.confirmed("geometry"):
            markers.append(self.tr("框✓"))
        suffix = " · ".join(markers) or self.tr("待审")
        failed = (
            "\n" + self.tr("图块加载失败")
            if item.shape_id in self._failed_ids
            else ""
        )
        return "#{index} {label}\n{status} · {suffix}{failed}".format(
            index=item.display_index,
            label=item.label,
            status=item.status_text(),
            suffix=suffix,
            failed=failed,
        )

    def _placeholder_icon(self) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(180, 120)
        pixmap.fill(QtGui.QColor("#EEF1F4"))
        return QtGui.QIcon(pixmap)

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

    def _request_visible_thumbnails(self) -> None:
        if self.session is None or not self.card_list.isVisible():
            return
        image_path, image_bytes = self.host.dense_review_image_source()
        source_version = self.host.dense_review_image_info()[0]
        margin = self.context_spin.value() / 100.0
        target = (360, 240)
        generation = self.thumbnails.generation
        rect = self.card_list.viewport().rect()
        current = self._current_shape_id()
        for shape_id, card in self._shape_items.items():
            item = self.session.object(shape_id)
            if item is None:
                continue
            visible = self.card_list.visualItemRect(card).intersects(rect)
            if not visible and shape_id != current:
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
                card.setIcon(self._placeholder_icon())
                card.setText(self._card_text(item))
            cached = self.thumbnails.cached_image(
                shape_id,
                item.bounds,
                margin,
                target,
                source_version,
            )
            if cached is not None:
                card.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(cached)))
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

    def _on_thumbnail_ready(self, shape_id: str, image) -> None:
        card = self._shape_items.get(shape_id)
        if card is None:
            return
        self._failed_ids.discard(shape_id)
        card.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(image)))
        item = self.session.object(shape_id) if self.session else None
        if item is not None:
            card.setText(self._card_text(item))
        self._update_action_labels()

    def _on_thumbnail_failed(self, shape_id: str, reason: str) -> None:
        self._failed_ids.add(shape_id)
        card = self._shape_items.get(shape_id)
        if card is not None:
            card.setIcon(self._placeholder_icon())
            card.setToolTip(
                self.tr("对象 {shape_id} 图块加载失败：{reason}").format(
                    shape_id=shape_id, reason=reason
                )
            )
            item = self.session.object(shape_id) if self.session else None
            if item is not None:
                card.setText(self._card_text(item))
        self._update_action_labels()

    def _on_context_changed(self) -> None:
        self._generation += 1
        self.thumbnails.start_generation(self._generation)
        self._failed_ids.clear()
        self._refresh_cards(force=True)
        self._request_visible_thumbnails()
        self._focus_current()

    # -- object actions ------------------------------------------------

    def _on_batch_selected(self, current, _previous) -> None:
        if self._updating or current is None or self.session is None:
            return
        batch_id = current.data(QtCore.Qt.ItemDataRole.UserRole)
        self.session.set_current(str(batch_id))
        self._cards_signature = None
        self._refresh_cards(force=True)
        self._focus_current()
        self._update_summary()

    def _on_dimensions_changed(self, *_args) -> None:
        if self._updating or self.session is None:
            return
        self.session.set_dimensions(self._dimensions())
        self._update_action_labels()
        self._refresh_batches()

    def _on_card_selected(self) -> None:
        if self._updating or self.session is None:
            return
        selected = self.card_list.selectedItems()
        if not selected:
            return
        shape_id = selected[0].data(QtCore.Qt.ItemDataRole.UserRole)
        if not shape_id:
            return
        self.session.set_current(self._current_batch_id(), str(shape_id))
        self._update_summary()
        self._update_action_labels()
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
            self.host.dense_review_after_progress_change()
            next_id = session.next_pending_object(
                self._current_batch_id(),
                self._dimensions(),
                after=shape_id,
            )
            if next_id:
                self._navigate_to(self._current_batch_id(), next_id)
            else:
                self.refresh_all(force_cards=True)
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
        self.host.dense_review_after_progress_change()
        next_id = session.next_pending_object(
            self._current_batch_id(),
            self._dimensions(),
            after=shape_id,
        )
        if next_id:
            self._navigate_to(self._current_batch_id(), next_id)
        else:
            self.refresh_all(force_cards=True)
        self._status(self.tr("当前对象已暂跳，仍保持待审。"))

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
                item.status_text() if item else "缺失",
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
        items = self.card_list.selectedItems()
        if len(items) != 2:
            self._status(self.tr("请用 Ctrl 选择两个对象后再比较。"))
            return
        ids = [
            str(item.data(QtCore.Qt.ItemDataRole.UserRole)) for item in items
        ]
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("并排比较"))
        dialog.resize(760, 420)
        layout = QtWidgets.QHBoxLayout(dialog)
        for shape_id in ids:
            item = session.object(shape_id)
            panel = QtWidgets.QWidget()
            panel_layout = QtWidgets.QVBoxLayout(panel)
            label = QtWidgets.QLabel(
                f"#{item.display_index} {item.label} · "
                f"{item.status_text()}"
                if item
                else shape_id
            )
            image_label = QtWidgets.QLabel()
            image = self.thumbnails.cached_latest(shape_id)
            if image is not None:
                image_label.setPixmap(
                    QtGui.QPixmap.fromImage(image).scaled(
                        340,
                        260,
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                        QtCore.Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                image_label.setText(self.tr("图块准备中…"))
            panel_layout.addWidget(label)
            panel_layout.addWidget(image_label, 1)
            layout.addWidget(panel, 1)
        close_button = QtWidgets.QPushButton(self.tr("关闭"))
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self._status(self.tr("比较不会复制标注或改变对象身份。"))

    # -- display and view ---------------------------------------------

    def _on_display_mode_changed(self, *_args) -> None:
        if self._updating:
            return
        self._display_mode = str(self.display_combo.currentData())
        self.host.dense_review_set_display_mode(self._display_mode)
        self._focus_current()

    def _toggle_full_image(self) -> None:
        self._full_image = self.host.dense_review_toggle_full_image()
        self.full_image_button.setText(
            self.tr("返回局部") if self._full_image else self.tr("看全图")
        )
        if not self._full_image:
            self.host.dense_review_set_display_mode(self._display_mode)

    # -- coverage ------------------------------------------------------

    def _on_tab_changed(self, index) -> None:
        if index != 1 or self.session is None:
            return
        self.session.ensure_coverage()
        self._refresh_coverage()
        self._show_current_region()

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

    def _show_current_region(self) -> None:
        session = self.session
        if session is None or session.state.coverage is None:
            return
        region_id = session.state.coverage.current_region
        if not region_id:
            return
        self.session.set_current_region(region_id)
        self.host.dense_review_show_coverage_region(region_id)
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
            shortcut.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(slot)
            shortcut.setEnabled(False)
            self._shortcuts.append(shortcut)
        if self._shortcut_warnings:
            self.status_label.setText("；".join(self._shortcut_warnings))

    def _apply_card_roles(self, card, item) -> None:
        markers = []
        if item.confirmed("category"):
            markers.append(self.tr("类别✓"))
        if item.confirmed("geometry"):
            markers.append(self.tr("框✓"))
        card.setData(
            QtCore.Qt.ItemDataRole.UserRole + 1,
            "#{index} {label}".format(
                index=item.display_index, label=item.label
            ),
        )
        card.setData(QtCore.Qt.ItemDataRole.UserRole + 2, item.status_text())
        card.setData(QtCore.Qt.ItemDataRole.UserRole + 3, " · ".join(markers))
        if item.confirmed("category") and item.confirmed("geometry"):
            status = "done"
        elif item.difficult:
            status = "difficult"
        elif item.skipped:
            status = "skipped"
        else:
            status = "pending"
        card.setData(QtCore.Qt.ItemDataRole.UserRole + 4, status)

    def _relayout_cards(self) -> None:
        viewport = self.card_list.viewport().width()
        if viewport <= 0:
            return
        minimum, gap, right_pad = 178, 12, 8
        available = max(minimum, viewport - right_pad)
        columns = max(1, (available + gap) // (minimum + gap))
        while columns > 1 and available // columns < minimum:
            columns -= 1
        cell = available // columns
        size = QtCore.QSize(cell, 176)
        if self.card_list.gridSize() != size:
            self.card_list.setGridSize(size)
            self.card_list.doItemsLayout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_cards()

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
        self._refresh_from_host()
        mode = self.display_combo.currentData() or "focus"
        self.host.dense_review_set_display_mode(mode)
        self._focus_current()

    def closeEvent(self, event) -> None:
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
        self.host.dense_review_workspace_closed()
        super().closeEvent(event)

    def shutdown(self) -> None:
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
        self.thumbnails.shutdown()

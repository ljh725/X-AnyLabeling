"""
文件视图 - 显示文件列表，支持搜索和跳转

功能：
- 显示文件列表
- 搜索过滤
- 双击跳转到文件
"""

import natsort
from typing import Dict, List, Optional
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QPushButton, QLabel
)


class NaturalSortTableWidgetItem(QTableWidgetItem):
    """支持自然排序的 TableWidgetItem"""
    
    def __lt__(self, other):
        # 使用 natsort 的排序键进行比较
        return natsort.natsort_keygen()(self.text()) < natsort.natsort_keygen()(other.text())


class FileView(QWidget):
    """文件视图"""
    
    # 信号
    file_jump_requested = pyqtSignal(str)  # 请求跳转到文件
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_stats = {}
        self._filtered_files = []
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("搜索文件名..."))
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setClearButtonEnabled(True)
        search_layout.addWidget(self.search_input)
        
        self.result_label = QLabel()
        search_layout.addWidget(self.result_label)
        
        layout.addLayout(search_layout)
        
        # 文件表格
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([
            self.tr("文件名"),
            self.tr("标注数"),
            self.tr("标签")
        ])
        
        # 表格设置
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        
        # 列宽
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        
        # 双击跳转
        self.table.doubleClicked.connect(self._on_double_click)
        
        layout.addWidget(self.table)
        
        # 底部操作栏
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        
        self.jump_btn = QPushButton(self.tr("跳转到选中文件"))
        self.jump_btn.clicked.connect(self._on_jump_clicked)
        action_layout.addWidget(self.jump_btn)
        
        action_layout.addStretch()
        
        self.selected_label = QLabel()
        action_layout.addWidget(self.selected_label)
        
        layout.addLayout(action_layout)
        
        # 选择变化时更新状态
        self.table.itemSelectionChanged.connect(self._update_selection_status)
    
    def set_data(self, file_stats: dict):
        """设置文件数据"""
        self._file_stats = file_stats
        self._apply_filter()
    
    def _apply_filter(self):
        """应用搜索过滤"""
        search_text = self.search_input.text().lower().strip()
        
        if search_text:
            self._filtered_files = [
                path for path, stats in self._file_stats.items()
                if search_text in stats.filename.lower()
            ]
        else:
            self._filtered_files = list(self._file_stats.keys())
        
        # 按文件名自然排序（使用 natsort，与系统一致）
        self._filtered_files = natsort.natsorted(
            self._filtered_files,
            key=lambda p: self._file_stats[p].filename
        )
        
        self._refresh_table()
        self._update_result_label()
    
    def _refresh_table(self):
        """刷新表格显示"""
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._filtered_files))
        
        for row, path in enumerate(self._filtered_files):
            stats = self._file_stats.get(path)
            if not stats:
                continue
            
            # 文件名 - 使用自然排序 Item，支持表头点击排序
            name_item = NaturalSortTableWidgetItem(stats.filename)
            name_item.setData(Qt.UserRole, path)  # 存储完整路径
            self.table.setItem(row, 0, name_item)
            
            # 标注数
            count_item = QTableWidgetItem()
            count_item.setData(Qt.DisplayRole, stats.label_count)
            count_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, count_item)
            
            # 标签列表
            labels_text = ", ".join(sorted(stats.labels)[:5])
            if len(stats.labels) > 5:
                labels_text += f" (+{len(stats.labels) - 5})"
            labels_item = QTableWidgetItem(labels_text)
            self.table.setItem(row, 2, labels_item)
        
        self.table.setSortingEnabled(True)
        # 默认按文件名升序排序
        self.table.sortByColumn(0, Qt.AscendingOrder)
    
    def _update_result_label(self):
        """更新搜索结果标签"""
        total = len(self._file_stats)
        filtered = len(self._filtered_files)
        
        if self.search_input.text():
            self.result_label.setText(
                self.tr("找到 {filtered}/{total} 个文件").format(
                    filtered=filtered, total=total
                )
            )
        else:
            self.result_label.setText(
                self.tr("共 {total} 个文件").format(total=total)
            )
    
    def _update_selection_status(self):
        """更新选择状态"""
        selected = len(self.table.selectedItems()) // self.table.columnCount()
        if selected > 0:
            self.selected_label.setText(
                self.tr("已选择 {count} 个文件").format(count=selected)
            )
        else:
            self.selected_label.setText("")
    
    def _on_search_changed(self, text: str):
        """搜索文本变化"""
        self._apply_filter()
    
    def _on_double_click(self, index):
        """双击跳转"""
        row = index.row()
        item = self.table.item(row, 0)
        if item:
            path = item.data(Qt.UserRole)
            if path:
                self.file_jump_requested.emit(path)
    
    def _on_jump_clicked(self):
        """点击跳转按钮"""
        selected = self.table.selectedItems()
        if selected:
            # 跳转到第一个选中的文件
            row = selected[0].row()
            item = self.table.item(row, 0)
            if item:
                path = item.data(Qt.UserRole)
                if path:
                    self.file_jump_requested.emit(path)

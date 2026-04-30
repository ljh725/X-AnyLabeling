"""
对象视图 - 显示所有标注对象，支持筛选和跳转

功能：
- 显示所有图片中的标注对象
- 按标签筛选
- 双击跳转到文件并选中对象
- 批量操作（P3）
"""

import os
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QObject, QModelIndex, QAbstractTableModel
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QTableView, QHeaderView, QAbstractItemView, 
    QPushButton, QLabel, QComboBox, QProgressBar,
    QApplication
)


@dataclass
class ObjectInfo:
    """标注对象信息"""
    file_path: str          # 图片路径
    filename: str           # 文件名
    shape_idx: int          # shape 在文件中的索引
    label: str              # 标签名
    shape_type: str         # 形状类型
    group_id: Optional[int] # 组 ID
    difficult: bool         # 是否困难样本
    points_count: int       # 点数量


class ObjectLoaderWorker(QObject):
    """后台加载对象的工作线程"""
    
    progress = pyqtSignal(int, int)  # current, total
    object_loaded = pyqtSignal(object)  # ObjectInfo
    finished = pyqtSignal()
    
    def __init__(self, file_list: List[str], output_dir: Optional[str] = None):
        super().__init__()
        self.file_list = file_list
        self.output_dir = output_dir
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        """执行加载"""
        total = len(self.file_list)
        
        for i, image_path in enumerate(self.file_list):
            if self._cancelled:
                return
            
            json_path = self._get_json_path(image_path)
            
            if json_path and os.path.exists(json_path):
                try:
                    self._parse_json(json_path, image_path)
                except Exception:
                    pass
            
            # 每 50 个文件发送一次进度
            if i % 50 == 0 or i == total - 1:
                self.progress.emit(i + 1, total)
        
        self.finished.emit()
    
    def _get_json_path(self, image_path: str) -> Optional[str]:
        """获取图片对应的 JSON 标注文件路径"""
        if self.output_dir:
            filename = os.path.basename(image_path)
            base_name = os.path.splitext(filename)[0]
            return os.path.join(self.output_dir, base_name + '.json')
        else:
            base_name = os.path.splitext(image_path)[0]
            return base_name + '.json'
    
    def _parse_json(self, json_path: str, image_path: str):
        """解析单个 JSON 文件"""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        shapes = data.get('shapes', [])
        filename = os.path.basename(image_path)
        
        for idx, shape in enumerate(shapes):
            obj = ObjectInfo(
                file_path=image_path,
                filename=filename,
                shape_idx=idx,
                label=shape.get('label', ''),
                shape_type=shape.get('shape_type', ''),
                group_id=shape.get('group_id'),
                difficult=shape.get('difficult', False),
                points_count=len(shape.get('points', []))
            )
            self.object_loaded.emit(obj)


class ObjectTableModel(QAbstractTableModel):
    """对象表格模型 - 支持大数据量"""
    
    COLUMNS = ['文件名', '标签', '类型', 'Group ID', '困难', '点数']
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._objects: List[ObjectInfo] = []
        self._filtered_objects: List[ObjectInfo] = []
        self._label_filter: str = ''
        self._search_filter: str = ''
    
    def rowCount(self, parent=QModelIndex()):
        return len(self._filtered_objects)
    
    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)
    
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None
    
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        
        obj = self._filtered_objects[index.row()]
        col = index.column()
        
        if role == Qt.DisplayRole:
            if col == 0:
                return obj.filename
            elif col == 1:
                return obj.label
            elif col == 2:
                return obj.shape_type
            elif col == 3:
                return str(obj.group_id) if obj.group_id is not None else ''
            elif col == 4:
                return '是' if obj.difficult else ''
            elif col == 5:
                return obj.points_count
        
        elif role == Qt.UserRole:
            # 返回完整对象信息
            return obj
        
        elif role == Qt.BackgroundRole:
            # 困难样本高亮
            if obj.difficult:
                return QBrush(QColor(255, 235, 235))
        
        return None
    
    def add_object(self, obj: ObjectInfo):
        """添加单个对象"""
        self._objects.append(obj)
        
        # 检查是否符合过滤条件
        if self._matches_filter(obj):
            row = len(self._filtered_objects)
            self.beginInsertRows(QModelIndex(), row, row)
            self._filtered_objects.append(obj)
            self.endInsertRows()
    
    def clear(self):
        """清空所有数据"""
        self.beginResetModel()
        self._objects.clear()
        self._filtered_objects.clear()
        self.endResetModel()
    
    def set_label_filter(self, label: str):
        """设置标签过滤"""
        self._label_filter = label
        self._apply_filter()
    
    def set_search_filter(self, text: str):
        """设置搜索过滤"""
        self._search_filter = text.lower()
        self._apply_filter()
    
    def _matches_filter(self, obj: ObjectInfo) -> bool:
        """检查对象是否符合过滤条件"""
        # 标签过滤
        if self._label_filter and obj.label != self._label_filter:
            return False
        
        # 搜索过滤（文件名或标签）
        if self._search_filter:
            if (self._search_filter not in obj.filename.lower() and
                self._search_filter not in obj.label.lower()):
                return False
        
        return True
    
    def _apply_filter(self):
        """应用过滤条件"""
        self.beginResetModel()
        self._filtered_objects = [
            obj for obj in self._objects
            if self._matches_filter(obj)
        ]
        self.endResetModel()
    
    def get_all_labels(self) -> List[str]:
        """获取所有标签列表"""
        labels = set(obj.label for obj in self._objects if obj.label)
        return sorted(labels)
    
    def get_object_at(self, row: int) -> Optional[ObjectInfo]:
        """获取指定行的对象"""
        if 0 <= row < len(self._filtered_objects):
            return self._filtered_objects[row]
        return None


class ObjectView(QWidget):
    """对象视图"""
    
    # 信号：请求跳转到文件并选中对象
    focus_object_requested = pyqtSignal(str, int)  # file_path, shape_idx
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[ObjectLoaderWorker] = None
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 顶部过滤栏
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)
        
        # 标签过滤
        filter_layout.addWidget(QLabel(self.tr("标签筛选:")))
        self.label_combo = QComboBox()
        self.label_combo.setMinimumWidth(150)
        self.label_combo.addItem(self.tr("全部"), '')
        self.label_combo.currentIndexChanged.connect(self._on_label_filter_changed)
        filter_layout.addWidget(self.label_combo)
        
        filter_layout.addSpacing(16)
        
        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("搜索文件名或标签..."))
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setClearButtonEnabled(True)
        filter_layout.addWidget(self.search_input)
        
        layout.addLayout(filter_layout)
        
        # 进度条
        self.progress_widget = QWidget()
        progress_layout = QHBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        
        self.progress_label = QLabel(self.tr("正在加载对象..."))
        progress_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(16)
        progress_layout.addWidget(self.progress_bar)
        
        layout.addWidget(self.progress_widget)
        self.progress_widget.hide()
        
        # 对象表格
        self.model = ObjectTableModel(self)
        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        
        # 表格设置
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(True)
        self.table_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        # 列宽
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # 文件名
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # 标签
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # 类型
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Group ID
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # 困难
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # 点数
        
        # 双击跳转
        self.table_view.doubleClicked.connect(self._on_double_click)
        
        layout.addWidget(self.table_view)
        
        # 底部状态栏
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)
        
        self.jump_btn = QPushButton(self.tr("跳转到选中对象"))
        self.jump_btn.clicked.connect(self._on_jump_clicked)
        status_layout.addWidget(self.jump_btn)
        
        status_layout.addStretch()
        
        self.status_label = QLabel()
        status_layout.addWidget(self.status_label)
        
        layout.addLayout(status_layout)
        
        # 选择变化时更新状态
        self.table_view.selectionModel().selectionChanged.connect(
            self._update_selection_status
        )
    
    def load_data(self, file_list: List[str], output_dir: Optional[str] = None):
        """加载数据"""
        # 取消之前的加载
        self.cancel_loading()
        
        # 清空现有数据
        self.model.clear()
        self.label_combo.clear()
        self.label_combo.addItem(self.tr("全部"), '')
        
        if not file_list:
            self._update_status_label()
            return
        
        # 启动后台加载
        self._thread = QThread()
        self._worker = ObjectLoaderWorker(file_list, output_dir)
        self._worker.moveToThread(self._thread)
        
        # 连接信号
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.object_loaded.connect(self._on_object_loaded)
        self._worker.finished.connect(self._on_loading_finished)
        
        # 显示进度
        self.progress_widget.show()
        self.progress_bar.setValue(0)
        
        self._thread.start()
    
    def cancel_loading(self):
        """取消加载"""
        if self._worker:
            self._worker.cancel()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        self._thread = None
        self._worker = None
    
    def _on_progress(self, current: int, total: int):
        """进度更新"""
        percent = int(current * 100 / total) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(
            self.tr("正在加载... {current}/{total}").format(
                current=current, total=total
            )
        )
    
    def _on_object_loaded(self, obj: ObjectInfo):
        """单个对象加载完成"""
        self.model.add_object(obj)
    
    def _on_loading_finished(self):
        """加载完成"""
        self.progress_widget.hide()
        
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        
        # 更新标签下拉框
        labels = self.model.get_all_labels()
        for label in labels:
            self.label_combo.addItem(label, label)
        
        self._update_status_label()
    
    def _on_label_filter_changed(self, index: int):
        """标签过滤变化"""
        label = self.label_combo.currentData()
        self.model.set_label_filter(label or '')
        self._update_status_label()
    
    def _on_search_changed(self, text: str):
        """搜索文本变化"""
        self.model.set_search_filter(text)
        self._update_status_label()
    
    def _on_double_click(self, index: QModelIndex):
        """双击跳转"""
        obj = self.model.get_object_at(index.row())
        if obj:
            self.focus_object_requested.emit(obj.file_path, obj.shape_idx)
    
    def _on_jump_clicked(self):
        """点击跳转按钮"""
        indexes = self.table_view.selectionModel().selectedRows()
        if indexes:
            obj = self.model.get_object_at(indexes[0].row())
            if obj:
                self.focus_object_requested.emit(obj.file_path, obj.shape_idx)
    
    def _update_selection_status(self):
        """更新选择状态"""
        count = len(self.table_view.selectionModel().selectedRows())
        if count > 0:
            self.status_label.setText(
                self.tr("已选择 {count} 个对象").format(count=count)
            )
        else:
            self._update_status_label()
    
    def _update_status_label(self):
        """更新状态标签"""
        total = len(self.model._objects)
        filtered = self.model.rowCount()
        
        if self.label_combo.currentIndex() > 0 or self.search_input.text():
            self.status_label.setText(
                self.tr("显示 {filtered}/{total} 个对象").format(
                    filtered=filtered, total=total
                )
            )
        else:
            self.status_label.setText(
                self.tr("共 {total} 个对象").format(total=total)
            )

"""
标签视图 - 显示标签统计，支持重命名、删除、改色

功能：
- 显示标签列表和统计
- 重命名标签
- 删除标签
- 修改颜色
- 批量操作
"""

import os
import json
from typing import Dict, List, Optional, Tuple
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QPushButton, QLabel, QMenu,
    QMessageBox, QColorDialog, QInputDialog, QProgressDialog,
    QApplication
)


class LabelView(QWidget):
    """标签视图"""
    
    # 信号
    label_renamed = pyqtSignal(str, str)  # old_name, new_name
    label_deleted = pyqtSignal(str)       # label_name
    label_color_changed = pyqtSignal(str, tuple)  # label_name, rgb
    data_modified = pyqtSignal()          # 数据已修改，需要刷新
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._label_stats = {}
        self._filtered_labels = []
        self._output_dir = None  # 标注文件输出目录
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("搜索标签..."))
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setClearButtonEnabled(True)
        search_layout.addWidget(self.search_input)
        
        self.result_label = QLabel()
        search_layout.addWidget(self.result_label)
        
        layout.addLayout(search_layout)
        
        # 标签表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            self.tr("标签名"),
            self.tr("颜色"),
            self.tr("实例数"),
            self.tr("文件数")
        ])
        
        # 表格设置
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        
        # 列宽
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        
        layout.addWidget(self.table)
        
        # 底部操作栏
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        
        self.rename_btn = QPushButton(self.tr("重命名"))
        self.rename_btn.clicked.connect(self._on_rename_clicked)
        action_layout.addWidget(self.rename_btn)
        
        self.color_btn = QPushButton(self.tr("修改颜色"))
        self.color_btn.clicked.connect(self._on_color_clicked)
        action_layout.addWidget(self.color_btn)
        
        self.delete_btn = QPushButton(self.tr("删除"))
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.setStyleSheet("QPushButton { color: #d32f2f; }")
        action_layout.addWidget(self.delete_btn)
        
        action_layout.addStretch()
        
        self.selected_label = QLabel()
        action_layout.addWidget(self.selected_label)
        
        layout.addLayout(action_layout)
        
        # 选择变化时更新状态
        self.table.itemSelectionChanged.connect(self._update_selection_status)
        self._update_button_states()
    
    def set_data(self, label_stats: dict, output_dir: Optional[str] = None):
        """设置标签数据"""
        self._label_stats = label_stats
        self._output_dir = output_dir
        self._apply_filter()
    
    def _apply_filter(self):
        """应用搜索过滤"""
        search_text = self.search_input.text().lower().strip()
        
        if search_text:
            self._filtered_labels = [
                name for name in self._label_stats.keys()
                if search_text in name.lower()
            ]
        else:
            self._filtered_labels = list(self._label_stats.keys())
        
        self._refresh_table()
        self._update_result_label()
    
    def _refresh_table(self):
        """刷新表格显示"""
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._filtered_labels))
        
        for row, name in enumerate(self._filtered_labels):
            stats = self._label_stats.get(name)
            if not stats:
                continue
            
            # 标签名
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, name)
            self.table.setItem(row, 0, name_item)
            
            # 颜色
            color_item = QTableWidgetItem("  ██  ")
            if stats.color:
                color = QColor(*stats.color)
                color_item.setBackground(QBrush(color))
                color_item.setData(Qt.UserRole, stats.color)
            color_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, color_item)
            
            # 实例数
            count_item = QTableWidgetItem()
            count_item.setData(Qt.DisplayRole, stats.instance_count)
            count_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, count_item)
            
            # 文件数
            file_count_item = QTableWidgetItem()
            file_count_item.setData(Qt.DisplayRole, stats.file_count)
            file_count_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, file_count_item)
        
        self.table.setSortingEnabled(True)
    
    def _update_result_label(self):
        """更新搜索结果标签"""
        total = len(self._label_stats)
        filtered = len(self._filtered_labels)
        
        # 计算总实例数
        total_instances = sum(s.instance_count for s in self._label_stats.values())
        
        if self.search_input.text():
            self.result_label.setText(
                self.tr("找到 {filtered}/{total} 个标签").format(
                    filtered=filtered, total=total
                )
            )
        else:
            self.result_label.setText(
                self.tr("共 {total} 个标签, {instances} 个实例").format(
                    total=total, instances=total_instances
                )
            )
    
    def _update_selection_status(self):
        """更新选择状态"""
        selected_rows = self._get_selected_rows()
        if selected_rows:
            self.selected_label.setText(
                self.tr("已选择 {count} 个标签").format(count=len(selected_rows))
            )
        else:
            self.selected_label.setText("")
        self._update_button_states()
    
    def _update_button_states(self):
        """更新按钮状态"""
        has_selection = len(self._get_selected_rows()) > 0
        self.rename_btn.setEnabled(has_selection)
        self.color_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
    
    def _get_selected_rows(self) -> List[int]:
        """获取选中的行"""
        return list(set(item.row() for item in self.table.selectedItems()))
    
    def _get_selected_labels(self) -> List[str]:
        """获取选中的标签名"""
        labels = []
        for row in self._get_selected_rows():
            item = self.table.item(row, 0)
            if item:
                labels.append(item.data(Qt.UserRole))
        return labels
    
    def _on_search_changed(self, text: str):
        """搜索文本变化"""
        self._apply_filter()
    
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        if not self.table.selectedItems():
            return
        
        menu = QMenu(self)
        
        rename_action = menu.addAction(self.tr("重命名"))
        rename_action.triggered.connect(self._on_rename_clicked)
        
        color_action = menu.addAction(self.tr("修改颜色"))
        color_action.triggered.connect(self._on_color_clicked)
        
        menu.addSeparator()
        
        delete_action = menu.addAction(self.tr("删除"))
        delete_action.triggered.connect(self._on_delete_clicked)
        
        menu.exec_(self.table.mapToGlobal(pos))
    
    def _on_rename_clicked(self):
        """重命名标签"""
        labels = self._get_selected_labels()
        if not labels:
            return
        
        if len(labels) > 1:
            QMessageBox.warning(
                self, 
                self.tr("提示"),
                self.tr("请只选择一个标签进行重命名")
            )
            return
        
        old_name = labels[0]
        new_name, ok = QInputDialog.getText(
            self,
            self.tr("重命名标签"),
            self.tr("新标签名:"),
            text=old_name
        )
        
        if ok and new_name and new_name != old_name:
            # 检查是否已存在
            if new_name in self._label_stats:
                QMessageBox.warning(
                    self,
                    self.tr("错误"),
                    self.tr("标签 '{name}' 已存在").format(name=new_name)
                )
                return
            
            # 执行重命名
            self._rename_label_in_files(old_name, new_name)
    
    def _on_color_clicked(self):
        """修改颜色"""
        labels = self._get_selected_labels()
        if not labels:
            return
        
        # 获取当前颜色
        current_color = Qt.white
        if labels[0] in self._label_stats:
            stats = self._label_stats[labels[0]]
            if stats.color:
                current_color = QColor(*stats.color)
        
        color = QColorDialog.getColor(current_color, self, self.tr("选择颜色"))
        if color.isValid():
            rgb = (color.red(), color.green(), color.blue())
            for label in labels:
                self.label_color_changed.emit(label, rgb)
    
    def _on_delete_clicked(self):
        """删除标签"""
        labels = self._get_selected_labels()
        if not labels:
            return
        
        # 统计影响
        total_instances = sum(
            self._label_stats[l].instance_count 
            for l in labels if l in self._label_stats
        )
        total_files = len(set().union(*(
            self._label_stats[l].files 
            for l in labels if l in self._label_stats
        )))
        
        # 确认对话框
        msg = self.tr(
            "确定要删除以下标签吗？\n\n"
            "标签: {labels}\n"
            "将删除 {instances} 个实例，影响 {files} 个文件\n\n"
            "此操作不可撤销！"
        ).format(
            labels=", ".join(labels),
            instances=total_instances,
            files=total_files
        )
        
        reply = QMessageBox.warning(
            self,
            self.tr("确认删除"),
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._delete_labels_in_files(labels)
    
    def _rename_label_in_files(self, old_name: str, new_name: str):
        """在所有文件中重命名标签"""
        if old_name not in self._label_stats:
            return
        
        files = list(self._label_stats[old_name].files)
        if not files:
            return
        
        # 进度对话框
        progress = QProgressDialog(
            self.tr("正在重命名标签..."),
            self.tr("取消"),
            0, len(files),
            self
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)
        
        modified_count = 0
        
        for i, image_path in enumerate(files):
            if progress.wasCanceled():
                break
            
            json_path = self._get_json_path(image_path)
            if json_path and os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    modified = False
                    for shape in data.get('shapes', []):
                        if shape.get('label') == old_name:
                            shape['label'] = new_name
                            modified = True
                    
                    if modified:
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        modified_count += 1
                except Exception as e:
                    pass
            
            progress.setValue(i + 1)
            QApplication.processEvents()
        
        progress.close()
        
        # 发送信号
        self.label_renamed.emit(old_name, new_name)
        self.data_modified.emit()
        
        QMessageBox.information(
            self,
            self.tr("完成"),
            self.tr("已在 {count} 个文件中将 '{old}' 重命名为 '{new}'").format(
                count=modified_count, old=old_name, new=new_name
            )
        )
    
    def _delete_labels_in_files(self, labels: List[str]):
        """在所有文件中删除标签"""
        # 收集所有受影响的文件
        all_files = set()
        for label in labels:
            if label in self._label_stats:
                all_files.update(self._label_stats[label].files)
        
        if not all_files:
            return
        
        files = list(all_files)
        
        # 进度对话框
        progress = QProgressDialog(
            self.tr("正在删除标签..."),
            self.tr("取消"),
            0, len(files),
            self
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)
        
        deleted_count = 0
        
        for i, image_path in enumerate(files):
            if progress.wasCanceled():
                break
            
            json_path = self._get_json_path(image_path)
            if json_path and os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    original_count = len(data.get('shapes', []))
                    data['shapes'] = [
                        s for s in data.get('shapes', [])
                        if s.get('label') not in labels
                    ]
                    
                    if len(data['shapes']) < original_count:
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        deleted_count += 1
                except Exception as e:
                    pass
            
            progress.setValue(i + 1)
            QApplication.processEvents()
        
        progress.close()
        
        # 发送信号
        for label in labels:
            self.label_deleted.emit(label)
        self.data_modified.emit()
        
        QMessageBox.information(
            self,
            self.tr("完成"),
            self.tr("已从 {count} 个文件中删除标签").format(count=deleted_count)
        )
    
    def _get_json_path(self, image_path: str) -> Optional[str]:
        """获取图片对应的 JSON 标注文件路径"""
        if self._output_dir:
            filename = os.path.basename(image_path)
            base_name = os.path.splitext(filename)[0]
            return os.path.join(self._output_dir, base_name + '.json')
        else:
            base_name = os.path.splitext(image_path)[0]
            return base_name + '.json'

"""
数据管理中心对话框

提供统一的数据管理界面，包含：
- 文件视图：搜索、跳转
- 标签视图：统计、重命名、删除、改色
"""

from typing import Optional, List
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QProgressBar, QPushButton, QWidget,
    QMessageBox
)

from .data_scanner import DataScanner
from .file_view import FileView
from .label_view import LabelView
from .object_view import ObjectView


class DataManagerDialog(QDialog):
    """数据管理中心对话框"""
    
    def __init__(self, parent=None):
        """
        初始化数据管理对话框
        
        Args:
            parent: LabelingWidget 实例
        """
        super().__init__(parent)
        self.labeling_widget = parent
        self.scanner = DataScanner(self)
        
        self._init_ui()
        self._connect_signals()
        
        # 启动扫描
        self._start_scan()
    
    def _init_ui(self):
        """初始化 UI"""
        self.setWindowTitle(self.tr("数据管理中心"))
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)
        
        # 设置窗口标志：非模态、允许最大化/最小化
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowCloseButtonHint
        )
        # 设置为非模态，允许与主窗口同时交互
        self.setModal(False)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # 顶部信息栏
        self._create_header(layout)
        
        # 加载进度条（初始显示）
        self._create_progress_bar(layout)
        
        # Tab 容器
        self.tab_widget = QTabWidget()
        
        # 文件视图
        self.file_view = FileView()
        self.tab_widget.addTab(self.file_view, self.tr("📁 文件视图"))
        
        # 标签视图
        self.label_view = LabelView()
        self.tab_widget.addTab(self.label_view, self.tr("🏷️ 标签视图"))
        
        # 对象视图
        self.object_view = ObjectView()
        self.tab_widget.addTab(self.object_view, self.tr("📦 对象视图"))
        
        layout.addWidget(self.tab_widget)
        
        # 底部按钮栏
        self._create_footer(layout)
        
        # 应用样式
        self._apply_styles()
    
    def _create_header(self, layout: QVBoxLayout):
        """创建顶部信息栏"""
        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)
        
        # 项目信息
        self.project_label = QLabel()
        self._update_project_label()
        header_layout.addWidget(self.project_label)
        
        header_layout.addStretch()
        
        # 刷新按钮
        self.refresh_btn = QPushButton(self.tr("🔄 刷新"))
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
    
    def _create_progress_bar(self, layout: QVBoxLayout):
        """创建进度条"""
        self.progress_widget = QWidget()
        progress_layout = QHBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        
        self.progress_label = QLabel(self.tr("正在扫描文件..."))
        progress_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        progress_layout.addWidget(self.progress_bar)
        
        layout.addWidget(self.progress_widget)
    
    def _create_footer(self, layout: QVBoxLayout):
        """创建底部按钮栏"""
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(8)
        
        footer_layout.addStretch()
        
        self.close_btn = QPushButton(self.tr("关闭"))
        self.close_btn.clicked.connect(self.close)
        footer_layout.addWidget(self.close_btn)
        
        layout.addLayout(footer_layout)
    
    def _apply_styles(self):
        """应用样式"""
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f7;
            }
            QTabWidget::pane {
                border: 1px solid #d2d2d7;
                border-radius: 8px;
                background-color: white;
            }
            QTabBar::tab {
                padding: 8px 16px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                background-color: #e5e5e5;
            }
            QTabBar::tab:selected {
                background-color: white;
                border: 1px solid #d2d2d7;
                border-bottom: none;
            }
            QTableWidget {
                border: none;
                background-color: white;
                gridline-color: #e5e5e5;
            }
            QTableWidget::item {
                padding: 4px 8px;
            }
            QTableWidget::item:selected {
                background-color: #0071e3;
                color: white;
            }
            QTableView {
                border: none;
                background-color: white;
                gridline-color: #e5e5e5;
            }
            QTableView::item {
                padding: 4px 8px;
            }
            QTableView::item:selected {
                background-color: #0071e3;
                color: white;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #d2d2d7;
                font-weight: bold;
            }
            QPushButton {
                padding: 6px 16px;
                border: 1px solid #d2d2d7;
                border-radius: 6px;
                background-color: white;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
            QLineEdit {
                padding: 6px 12px;
                border: 1px solid #d2d2d7;
                border-radius: 6px;
                background-color: white;
            }
            QLineEdit:focus {
                border-color: #0071e3;
            }
            QProgressBar {
                border: 1px solid #d2d2d7;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #0071e3;
                border-radius: 3px;
            }
        """)
    
    def _connect_signals(self):
        """连接信号"""
        # 扫描器信号
        self.scanner.scan_started.connect(self._on_scan_started)
        self.scanner.scan_progress.connect(self._on_scan_progress)
        self.scanner.scan_finished.connect(self._on_scan_finished)
        self.scanner.scan_error.connect(self._on_scan_error)
        
        # 文件视图信号
        self.file_view.file_jump_requested.connect(self._on_file_jump_requested)
        
        # 标签视图信号
        self.label_view.label_renamed.connect(self._on_label_renamed)
        self.label_view.label_deleted.connect(self._on_label_deleted)
        self.label_view.label_color_changed.connect(self._on_label_color_changed)
        self.label_view.data_modified.connect(self._on_data_modified)
        
        # 对象视图信号
        self.object_view.focus_object_requested.connect(self._on_focus_object_requested)
    
    def _update_project_label(self):
        """更新项目信息标签"""
        if self.labeling_widget and self.labeling_widget.filename:
            import os
            dir_path = os.path.dirname(self.labeling_widget.filename)
            dir_name = os.path.basename(dir_path) or dir_path
            file_count = self.labeling_widget.file_list_widget.count()
            self.project_label.setText(
                self.tr("📂 {dir} | {count} 个文件").format(
                    dir=dir_name, count=file_count
                )
            )
        else:
            self.project_label.setText(self.tr("未打开项目"))
    
    def _get_file_list(self) -> List[str]:
        """获取文件列表"""
        if not self.labeling_widget:
            return []
        
        files = []
        for i in range(self.labeling_widget.file_list_widget.count()):
            item = self.labeling_widget.file_list_widget.item(i)
            if item:
                files.append(item.text())
        return files
    
    def _get_output_dir(self) -> Optional[str]:
        """获取标注输出目录"""
        if self.labeling_widget:
            return self.labeling_widget.output_dir
        return None
    
    def _start_scan(self):
        """开始扫描"""
        file_list = self._get_file_list()
        if not file_list:
            self.progress_widget.hide()
            return
        
        output_dir = self._get_output_dir()
        self.scanner.scan(file_list, output_dir)
    
    def _on_refresh_clicked(self):
        """刷新按钮点击"""
        self.scanner.invalidate_cache()
        self._start_scan()
    
    def _on_scan_started(self):
        """扫描开始"""
        self.progress_widget.show()
        self.progress_bar.setValue(0)
        self.refresh_btn.setEnabled(False)
    
    def _on_scan_progress(self, current: int, total: int):
        """扫描进度更新"""
        percent = int(current * 100 / total) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(
            self.tr("正在扫描... {current}/{total}").format(
                current=current, total=total
            )
        )
    
    def _on_scan_finished(self):
        """扫描完成"""
        self.progress_widget.hide()
        self.refresh_btn.setEnabled(True)
        
        # 更新视图数据
        self.file_view.set_data(self.scanner.file_stats)
        self.label_view.set_data(
            self.scanner.label_stats,
            self._get_output_dir()
        )
        
        # 加载对象视图数据（独立加载，因为数据量可能很大）
        file_list = self._get_file_list()
        self.object_view.load_data(file_list, self._get_output_dir())
    
    def _on_scan_error(self, error_msg: str):
        """扫描错误"""
        self.progress_widget.hide()
        self.refresh_btn.setEnabled(True)
        QMessageBox.warning(self, self.tr("扫描错误"), error_msg)
    
    def _on_file_jump_requested(self, file_path: str):
        """处理文件跳转请求"""
        if not self.labeling_widget:
            return
        
        # 查找文件索引
        for i in range(self.labeling_widget.file_list_widget.count()):
            item = self.labeling_widget.file_list_widget.item(i)
            if item and item.text() == file_path:
                # 选中并加载文件
                self.labeling_widget.file_list_widget.setCurrentRow(i)
                # 激活主窗口，但保持数据管理中心打开
                self.labeling_widget.activateWindow()
                self.labeling_widget.raise_()
                return
        
        QMessageBox.warning(
            self,
            self.tr("未找到文件"),
            self.tr("文件 '{path}' 不在当前列表中").format(path=file_path)
        )
    
    def _on_label_renamed(self, old_name: str, new_name: str):
        """标签重命名后的处理"""
        if not self.labeling_widget:
            return
        
        # 更新 label_info
        if old_name in self.labeling_widget.label_info:
            self.labeling_widget.label_info[new_name] = \
                self.labeling_widget.label_info.pop(old_name)
        
        # 如果当前文件受影响，重新加载
        if self.labeling_widget.filename:
            self.labeling_widget.load_file(self.labeling_widget.filename)
    
    def _on_label_deleted(self, label_name: str):
        """标签删除后的处理"""
        if not self.labeling_widget:
            return
        
        # 从 label_info 中移除
        if label_name in self.labeling_widget.label_info:
            del self.labeling_widget.label_info[label_name]
        
        # 如果当前文件受影响，重新加载
        if self.labeling_widget.filename:
            self.labeling_widget.load_file(self.labeling_widget.filename)
    
    def _on_label_color_changed(self, label_name: str, rgb: tuple):
        """标签颜色变更后的处理"""
        if not self.labeling_widget:
            return
        
        # 更新 label_info
        if label_name not in self.labeling_widget.label_info:
            self.labeling_widget.label_info[label_name] = {}
        self.labeling_widget.label_info[label_name]['color'] = list(rgb)
        
        # 更新 unique_label_list 显示
        self.labeling_widget.unique_label_list.update_item_color(
            label_name, rgb, 128
        )
        
        # 刷新画布
        if self.labeling_widget.canvas:
            self.labeling_widget.canvas.update()
    
    def _on_data_modified(self):
        """数据被修改后刷新"""
        # 使缓存失效并重新扫描
        self.scanner.invalidate_cache()
        self._start_scan()
    
    def _on_focus_object_requested(self, file_path: str, shape_idx: int):
        """处理对象跳转请求 - 跳转到文件并选中指定对象"""
        if not self.labeling_widget:
            return
        
        # 查找文件索引
        file_index = -1
        for i in range(self.labeling_widget.file_list_widget.count()):
            item = self.labeling_widget.file_list_widget.item(i)
            if item and item.text() == file_path:
                file_index = i
                break
        
        if file_index < 0:
            QMessageBox.warning(
                self,
                self.tr("未找到文件"),
                self.tr("文件 '{path}' 不在当前列表中").format(path=file_path)
            )
            return
        
        # 跳转到文件
        self.labeling_widget.file_list_widget.setCurrentRow(file_index)
        
        # 等待文件加载完成后选中对象
        # 使用 QTimer 延迟执行，确保文件已加载
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, lambda: self._select_shape(shape_idx))
        
        # 激活主窗口，但保持数据管理中心打开
        self.labeling_widget.activateWindow()
        self.labeling_widget.raise_()
    
    def _select_shape(self, shape_idx: int):
        """选中指定索引的 shape"""
        if not self.labeling_widget or not self.labeling_widget.canvas:
            return
        
        shapes = self.labeling_widget.canvas.shapes
        if 0 <= shape_idx < len(shapes):
            shape = shapes[shape_idx]
            # 选中 shape
            self.labeling_widget.canvas.select_shapes([shape])
            # 在 label_list 中也选中对应项（LabelListWidget 是 QListView）
            label_list = self.labeling_widget.label_list
            model = label_list.model()
            if model:
                label_list.clearSelection()
                for i in range(model.rowCount()):
                    item = model.item(i)
                    if item and item.data(Qt.UserRole) == shape:
                        index = model.index(i, 0)
                        label_list.setCurrentIndex(index)
                        label_list.scrollTo(index)
                        break
    
    def closeEvent(self, event):
        """关闭事件"""
        # 取消正在进行的扫描
        self.scanner.cancel()
        # 取消对象视图的加载
        self.object_view.cancel_loading()
        super().closeEvent(event)

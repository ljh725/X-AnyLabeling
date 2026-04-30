"""
数据扫描器 - 扫描 JSON 标注文件并统计信息

职责：
- 扫描目录下所有 JSON 文件
- 统计标签信息
- 缓存结果避免重复扫描
"""

import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from PyQt5.QtCore import QObject, pyqtSignal, QThread


@dataclass
class LabelStats:
    """标签统计信息"""
    name: str
    color: Optional[tuple] = None
    instance_count: int = 0  # 实例总数
    file_count: int = 0      # 出现的文件数
    files: Set[str] = field(default_factory=set)  # 所在文件列表


@dataclass 
class FileStats:
    """文件统计信息"""
    path: str
    filename: str
    label_count: int = 0     # 标注数量
    labels: Set[str] = field(default_factory=set)  # 包含的标签


class ScanWorker(QObject):
    """后台扫描工作线程"""
    
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(dict, dict)  # label_stats, file_stats
    error = pyqtSignal(str)
    
    def __init__(self, file_list: List[str], label_dir: Optional[str] = None):
        super().__init__()
        self.file_list = file_list
        self.label_dir = label_dir
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        """执行扫描"""
        label_stats: Dict[str, LabelStats] = {}
        file_stats: Dict[str, FileStats] = {}
        
        total = len(self.file_list)
        
        for i, image_path in enumerate(self.file_list):
            if self._cancelled:
                return
            
            # 计算对应的 JSON 文件路径
            json_path = self._get_json_path(image_path)
            
            if json_path and os.path.exists(json_path):
                try:
                    self._parse_json(json_path, image_path, label_stats, file_stats)
                except Exception as e:
                    # 跳过解析失败的文件
                    pass
            
            # 每 100 个文件发送一次进度
            if i % 100 == 0 or i == total - 1:
                self.progress.emit(i + 1, total)
        
        self.finished.emit(label_stats, file_stats)
    
    def _get_json_path(self, image_path: str) -> Optional[str]:
        """获取图片对应的 JSON 标注文件路径"""
        if self.label_dir:
            filename = os.path.basename(image_path)
            base_name = os.path.splitext(filename)[0]
            return os.path.join(self.label_dir, base_name + '.json')
        else:
            base_name = os.path.splitext(image_path)[0]
            return base_name + '.json'
    
    def _parse_json(self, json_path: str, image_path: str,
                    label_stats: Dict[str, LabelStats],
                    file_stats: Dict[str, FileStats]):
        """解析单个 JSON 文件"""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        shapes = data.get('shapes', [])
        filename = os.path.basename(image_path)
        
        # 初始化文件统计
        if image_path not in file_stats:
            file_stats[image_path] = FileStats(
                path=image_path,
                filename=filename
            )
        
        file_stat = file_stats[image_path]
        file_stat.label_count = len(shapes)
        
        for shape in shapes:
            label = shape.get('label', '')
            if not label:
                continue
            
            # 更新标签统计
            if label not in label_stats:
                # 尝试获取颜色
                color = None
                shape_color = shape.get('shape_color')
                if shape_color and len(shape_color) >= 3:
                    color = tuple(shape_color[:3])
                
                label_stats[label] = LabelStats(name=label, color=color)
            
            label_stats[label].instance_count += 1
            label_stats[label].files.add(image_path)
            file_stat.labels.add(label)
        
        # 更新文件数
        for label in file_stat.labels:
            if label in label_stats:
                label_stats[label].file_count = len(label_stats[label].files)


class DataScanner(QObject):
    """数据扫描器 - 管理扫描任务"""
    
    scan_started = pyqtSignal()
    scan_progress = pyqtSignal(int, int)  # current, total
    scan_finished = pyqtSignal()
    scan_error = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[ScanWorker] = None
        
        # 缓存
        self._label_stats: Dict[str, LabelStats] = {}
        self._file_stats: Dict[str, FileStats] = {}
        self._is_cached = False
    
    @property
    def label_stats(self) -> Dict[str, LabelStats]:
        return self._label_stats
    
    @property
    def file_stats(self) -> Dict[str, FileStats]:
        return self._file_stats
    
    @property
    def is_cached(self) -> bool:
        return self._is_cached
    
    def scan(self, file_list: List[str], label_dir: Optional[str] = None, 
             force: bool = False):
        """
        开始扫描
        
        Args:
            file_list: 图片文件列表
            label_dir: 标注文件目录（可选）
            force: 强制重新扫描，忽略缓存
        """
        if self._is_cached and not force:
            self.scan_finished.emit()
            return
        
        # 取消正在进行的扫描
        self.cancel()
        
        self._thread = QThread()
        self._worker = ScanWorker(file_list, label_dir)
        self._worker.moveToThread(self._thread)
        
        # 连接信号
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        
        self.scan_started.emit()
        self._thread.start()
    
    def cancel(self):
        """取消扫描"""
        if self._worker:
            self._worker.cancel()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        self._thread = None
        self._worker = None
    
    def invalidate_cache(self):
        """使缓存失效"""
        self._is_cached = False
        self._label_stats.clear()
        self._file_stats.clear()
    
    def _on_progress(self, current: int, total: int):
        self.scan_progress.emit(current, total)
    
    def _on_finished(self, label_stats: dict, file_stats: dict):
        self._label_stats = label_stats
        self._file_stats = file_stats
        self._is_cached = True
        
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        
        self.scan_finished.emit()
    
    def _on_error(self, error_msg: str):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        
        self.scan_error.emit(error_msg)

"""
数据管理中心模块

提供统一的数据管理界面，支持：
- 文件视图：搜索、跳转、批量操作
- 标签视图：统计、重命名、删除、改色
- 对象视图：多属性管理（P3）
"""

from .data_manager_dialog import DataManagerDialog

__all__ = ['DataManagerDialog']

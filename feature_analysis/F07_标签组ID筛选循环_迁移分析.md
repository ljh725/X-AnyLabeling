# 功能7：标签/组ID筛选循环 + FilterController — 迁移分析报告

- **难度**: ⭐⭐⭐ | **影响级别**: 🟢 直接迁移
- **源文件**: `widgets/filter_controller.py` (20,508B), `labeling/filter_state_manager.py` (14,215B)
- **嵌入代码**: label_widget.py (~60行初始化+委托调用), `filter_label_widget.py` (+1,590B修改)
- **快捷键**: F2(标签循环), F3(GID循环)

---

## 1. 依赖与导入调整

### 独立模块文件
| 文件 | 位置 | 大小 | 操作 |
|------|------|------|------|
| `widgets/filter_controller.py` | widgets/ | 20,508B | 直接复制到3.3.8 `widgets/` |
| `filter_state_manager.py` | labeling/ | 14,215B (376行) | 直接复制到3.3.8 `labeling/` |

### filter_state_manager.py 详细结构
位于 `labeling/filter_state_manager.py`（非widgets/目录），包含5个类+1个工厂函数:
- `OptimizedFilterState` — 状态数据类(`__slots__`优化)
- `LRUCache` — LRU缓存(maxsize=100)
- `FilterStatePersistence` — JSON原子化持久化
- `FilterPerformanceMonitor` — 性能监控(save/restore计时+缓存命中率)
- `FilterStateManager` — 核心管理器(save_state/restore_state/smart_match)
- `get_filter_state_manager()` — 单例工厂函数

### 导入变更
- 新增导入（`widgets/__init__.py`）:
  ```python
  from .filter_controller import FilterController
  ```
- `filter_controller.py` 内部可能引用 `filter_state_manager`:
  ```python
  from ..filter_state_manager import get_filter_state_manager
  ```

### 外部依赖
- 无第三方依赖（仅用标准库 `os`, `json`, `time`, `collections`, `logging`）

---

## 2. 集成点分析

### label_widget.py
- **`__init__`**: 初始化 `self._filter_controller = FilterController(self)`
- **委托调用**: 原有的 `text_selection_changed()` / `gid_selection_changed()` 改为通过FilterController:
  ```
  # 替代原有的直接处理:
  self._filter_controller.on_label_filter_changed(index)
  self._filter_controller.on_gid_filter_changed(index)
  ```
- **快捷键处理**:
  - F2 → `self._filter_controller.cycle_label_filter()`
  - F3 → `self._filter_controller.cycle_gid_filter()`
- **图片切换时**: 调用 `self._filter_controller.save_state()` / `restore_state()`

### filter_label_widget.py
- **3.3.8当前版本**: 44行，基本的 `LabelFilterComboBox` + `GroupIDFilterComboBox`
- **需修改**: 扩展两个ComboBox以支持循环筛选功能(+1,590B)
- **迁移策略**: 直接用源版本的修改后文件替换3.3.8版本

---

## 3. Canvas API 兼容性

| 旧API调用 | 3.3.8适配方式 | 状态 |
|-----------|-------------|------|
| `self.canvas.set_shape_visible(shape, bool)` | adapter方法 → `ShapeManager.set_shape_visible()` → `VisibilityController` | ✅ 兼容 |
| `self.canvas.shapes` | adapter Property proxy | ✅ 兼容 |
| `self.canvas.update()` | adapter方法（触发视口刷新） | ✅ 兼容 |

**此功能主要在label_widget层操作，通过adapter的set_shape_visible()控制可见性，完全兼容。**

---

## 4. 独立文件拆解建议

| 文件 | 状态 | 操作 |
|------|------|------|
| `widgets/filter_controller.py` | ✅ 已独立 | 直接复制 |
| `labeling/filter_state_manager.py` | ✅ 已独立 | 直接复制到labeling/目录 |
| `widgets/filter_label_widget.py` | 需patch | 用源版本替换（44行→~90行） |

### 注意事项
- `filter_state_manager.py` 的导入路径：位于 `labeling/` 层级而非 `widgets/`，`filter_controller.py` 导入时需确认相对路径正确
- 持久化路径：`FilterStatePersistence` 写入 `filter_states.json` 到 `config_dir`，确认3.3.8的配置目录

### 迁移工作量估算
- 复制文件：2个
- 修改/替换文件：1个（filter_label_widget.py）
- 修改文件：1个（label_widget.py）
- 新增代码：~60行（label_widget集成）
- 预计耗时：2-3小时

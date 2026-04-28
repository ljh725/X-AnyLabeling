# 功能1：Ctrl+双击定点放大 — 迁移分析报告

- **难度**: ⭐⭐ | **影响级别**: 🟡 适配
- **源文件**: `widgets/quick_zoom_manager.py` (6,412B)
- **嵌入代码**: canvas.py (~5行信号+事件), label_widget.py (~30行初始化+回调), navigator_widget.py (~30行配置UI)

---

## 1. 依赖与导入调整

### 独立模块文件
| 文件 | 大小 | 操作 |
|------|------|------|
| `widgets/quick_zoom_manager.py` | 6,412B | 直接复制到3.3.8 `widgets/` |

### 导入变更
- PyQt5导入：**无需修改**（3.3.8仍用PyQt5）
- 新增导入（`widgets/__init__.py`）:
  ```python
  from .quick_zoom_manager import QuickZoomManager
  ```

### 外部依赖
- 无第三方依赖
- 内部依赖：`label_widget.py`（parent引用）、`canvas` 信号

---

## 2. 集成点分析

### canvas_adapter.py
- **新增信号**: `quick_zoom_requested = pyqtSignal(QPointF)` — 在信号定义区域添加
- **信号转接**: 在 `_connect_signals()` 中将 `_view` 的信号转接到adapter

### canvas_graphics_view.py
- **修改方法**: `mouseDoubleClickEvent()` — 添加 Ctrl 修饰键检测
  ```
  if event.modifiers() & Qt.ControlModifier:
      scene_pos = self.mapToScene(event.pos())
      → 发射 quick_zoom_requested 信号
      event.accept()
      return
  ```
- **新增信号**: `quick_zoom_requested = pyqtSignal(QPointF)` 在 CanvasGraphicsView 类中

### label_widget.py
- **`__init__`**: 初始化 `self._quick_zoom_manager = QuickZoomManager(self)`
- **信号连接**: `self.canvas.quick_zoom_requested.connect(self._on_quick_zoom_requested)`
- **新增方法**:
  - `_on_quick_zoom_requested(scene_pos: QPointF)` — 调用 QuickZoomManager
  - `_on_quick_zoom_level_changed(level: int)` — 缩放级别变化回调

### navigator_widget.py
- **新增UI**: 快速缩放级别配置（QSlider/QSpinBox），约30行
- **配置项**: `quick_zoom_level` (100-1000, 默认400)

---

## 3. Canvas API 兼容性

| 旧API调用 | 3.3.8适配方式 | 状态 |
|-----------|-------------|------|
| `canvas.quick_zoom_requested` 信号 | 需在adapter新增 | ❌ 待添加 |
| `canvas.scale` | adapter Property proxy | ✅ 兼容 |
| `canvas.adjustSize()` | adapter已有，内部用 `_view.resetTransform()` + `_view.scale()` | ✅ 兼容 |
| `event.pos()` 获取双击坐标 | 需改为 `self.mapToScene(event.pos())` 获取场景坐标 | ⚠️ 需适配 |
| scrollbar定位 | adapter已有 `_zoom_center_scene_pos` 机制 | ✅ 可利用 |

### 坐标系注意事项
- 旧版 `mouseDoubleClickEvent` 中 `event.pos()` 返回widget坐标
- 新版 QGraphicsView 中需用 `self.mapToScene(event.pos())` 转换为场景坐标
- QuickZoomManager 内部的缩放+居中逻辑需适配 `_zoom_center_scene_pos` 机制

---

## 4. 独立文件拆解建议

| 文件 | 状态 | 操作 |
|------|------|------|
| `widgets/quick_zoom_manager.py` | ✅ 已独立 | 直接复制 |

**无需重构**。模块已完全独立，接口清晰。

### 迁移工作量估算
- 复制文件：1个
- 修改文件：4个（canvas_adapter, canvas_graphics_view, label_widget, navigator_widget）
- 新增代码：~80行
- 预计耗时：1-2小时

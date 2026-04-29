# Viewport 状态管理技术说明

## 1. 功能概述

X-AnyLabeling 的 Viewport（视口）状态管理功能用于在切换图片时保持用户的视图状态（包括缩放比例和视图位置）。该功能通过 `ViewportController` 类实现，将每张图片的视口状态存储在内存字典中，并在图片切换时按策略恢复。

当前版本除自动保存/恢复外，还支持用户手动重置视图状态，用于在批量浏览图片时快速丢弃缓存的缩放和视口位置，回到默认视图。

## 2. 核心组件

### 2.1 ViewportController 类

**文件位置**: `anylabeling/views/labeling/widgets/viewport_controller.py`

**核心属性**:
- `_states: dict[str, ViewportState]` - 存储每张图片的视口状态
- `_last_loaded: str | None` - 最近成功加载的图片文件名

**状态数据结构** (`ViewportState`):
```python
@dataclass
class ViewportState:
    zoom_mode: int      # 0=FIT_WINDOW, 1=FIT_WIDTH, 2=MANUAL_ZOOM
    zoom_value: int     # 缩放百分比，如 150 表示 150%
    center_x: float     # 视图中心点在图像坐标系中的 X 坐标
    center_y: float     # 视图中心点在图像坐标系中的 Y 坐标
```

### 2.2 状态保存、恢复与重置流程

**保存时机** (`on_file_leaving` 方法):
- 在 `LabelWidget.load_file()` 开始时调用（第 5623-5629 行）
- 无条件保存当前图片的视口状态到 `_states` 字典

**恢复时机** (`on_file_loaded` 方法):
- 在 `LabelWidget.load_file()` 结束时调用（第 5766-5777 行）
- 根据策略选择最佳可用状态并应用到画布

**重置时机**（手动命令）:
- 用户可通过顶部 `View` 菜单手动重置视图状态
- 用户可通过文件列表右键菜单按文件范围重置视图状态
- 用户可通过画布右键菜单直接重置当前/后续/全部图像视图状态

## 3. 状态保持策略

### 3.1 策略优先级

在 `ViewportController._resolve()` 方法中，状态恢复遵循以下优先级：

1. **精确匹配**（最高优先级）
   - 如果目标图片在 `_states` 中有历史记录，直接恢复该状态
   - 适用于：用户之前查看过该图片并调整了视图

2. **继承上一张图片**（条件触发）
   - 如果 `keep_prev_viewport=True` 且目标图片无历史记录
   - 继承 `_last_loaded`（上一张图片）的视口状态
   - 适用于：批量处理同尺寸图片时保持统一视图

3. **无状态**（默认回退）
   - 返回 `None`
   - 调用方回退到 `adjust_scale(initial=True)` 使用默认缩放

### 3.2 配置选项

**配置文件**: `anylabeling/configs/xanylabeling_config.yaml`

```yaml
keep_prev_viewport: false  # 默认关闭
```

**UI 控制**:
- 菜单路径: View → Keep Previous Viewport
- 代码位置: `label_widget.py` 第 1162-1171 行

### 3.3 手动重置策略

当前支持 3 种重置范围：

1. **重置当前图像视图**
   - 清除当前图片的视口状态缓存
   - 如果当前图片正在显示，立即恢复默认视图

2. **重置从当前到末尾图像视图**
   - 以当前图片在 `image_list` 中的位置为起点
   - 清除从当前图片到列表末尾的全部视图状态缓存
   - 如果当前图片在范围内，立即恢复默认视图

3. **重置所有图像视图**
   - 清除当前会话中所有图片的视图状态缓存
   - 当前图片如正在显示，也会立即恢复默认视图

这里的“视图状态”不是单一字典，而是 3 份缓存的组合：

1. `viewport_controller._states`
2. `LabelWidget.zoom_values`
3. `LabelWidget.scroll_values`

重置操作会同步清理这三处数据，避免清掉 `_states` 后又从旧的 `zoom_values` 或 `scroll_values` 回退恢复。

## 4. 坐标转换机制

### 4.1 保存时的坐标转换

在 `_capture()` 方法中：

1. **获取滚动条值**: 从 `QScrollArea` 获取水平和垂直滚动条当前值
2. **计算视口中心**（控件坐标系）:
   ```
   widget_cx = h_bar.value() + viewport_w / 2.0
   widget_cy = v_bar.value() + viewport_h / 2.0
   ```
3. **转换为图像坐标**:
   ```
   center_x = widget_cx / scale - offset.x()
   center_y = widget_cy / scale - offset.y()
   ```

### 4.2 恢复时的坐标转换

在 `_apply()` 方法中：

1. **图像坐标转控件坐标**:
   ```
   widget_cx = (center_x + offset.x()) * scale
   widget_cy = (center_y + offset.y()) * scale
   ```
2. **计算滚动条目标值**:
   ```
   target_h = widget_cx - viewport_w / 2.0
   target_v = widget_cy - viewport_h / 2.0
   ```
3. **限制在有效范围内**:
   ```
   target_h = max(minimum, min(maximum, target_h))
   ```

### 4.3 设计优势

- **跨尺寸兼容**: 使用图像坐标系而非像素值，适应不同尺寸图片
- **抗窗口 resize**: 视图中心点相对图像位置不变，窗口大小变化不影响
- **精确恢复**: 返回图片时恢复到离开时的精确视图位置

## 5. 代码调用链路

### 5.1 图片切换时的完整流程

```
LabelWidget.load_file(filename)
├── 1. 保存当前视口状态 (第 5623 行)
│   └── viewport_controller.on_file_leaving(...)
│       └── _capture() → 保存到 _states[当前图片]
│
├── 2. 加载新图片
│   └── canvas.load_pixmap(image)
│
└── 3. 恢复目标图片视口 (第 5766 行)
    └── viewport_controller.on_file_loaded(...)
        ├── _resolve() → 选择最佳状态
        └── _apply() → 应用到画布
```

### 5.2 关键代码位置

| 功能 | 文件 | 行号 |
|------|------|------|
| 状态保存 | `label_widget.py` | 5623-5629 |
| 状态恢复 | `label_widget.py` | 5766-5777 |
| 单文件状态清理 | `viewport_controller.py` | 197-208 |
| 批量状态清理 | `viewport_controller.py` | 210-219 |
| 策略解析 | `viewport_controller.py` | 286-300 |
| 坐标捕获 | `viewport_controller.py` | 225-284 |
| 坐标应用 | `viewport_controller.py` | 302-359 |
| View 菜单动作定义 | `label_widget.py` | 1195-1211 |
| View 菜单注册 | `label_widget.py` | 2172-2227 |
| 画布右键菜单注册 | `label_widget.py` | 2235-2270 |
| 文件列表右键菜单 | `label_widget.py` | 3763-3795 |
| 统一重置入口 | `label_widget.py` | 5993-6090 |

## 6. 边界情况处理

### 6.1 无有效 Pixmap
- `_capture()` 检查 `pixmap is None or pixmap.isNull()`
- 无效时返回 `None`，不保存状态

### 6.2 找不到 QScrollArea
- 遍历父控件链查找 `QScrollArea`
- 找不到时返回 `None`，状态保存/恢复失败

### 6.3 滚动条值越界
- `_apply()` 中使用 `max(minimum, min(maximum, target))` 限制
- 防止设置无效滚动值导致异常

### 6.4 首次加载
- `is_initial_load = not self.zoom_values`
- 首次加载或无状态时调用 `adjust_scale(initial=True)`

### 6.5 手动重置但没有历史缓存
- 即使当前图片此前没有缓存的视口状态，只要用户执行“重置当前图像视图”，仍会立即恢复默认视图
- 这样可以保证菜单操作有可见反馈，而不是因为“没有可删缓存”而表现为无变化

## 7. 与其他功能的交互

### 7.1 与 Keep Previous Scale 的关系
- `keep_prev_scale`: 仅保持缩放比例（旧逻辑）
- `keep_prev_viewport`: 保持缩放比例 + 视图位置（新逻辑）
- 两者独立，可同时开启

### 7.2 与 Legacy Scroll Values 的关系
- 当 `ViewportController` 无状态时，回退到旧版滚动值
- 代码位置: `label_widget.py` 第 5784-5791 行

### 7.2 与手动重置的关系
- 手动重置时会同步清除 `zoom_values` 和 `scroll_values`
- 这样后续再次加载图片时，不会回退到旧的缩放值或滚动条位置

### 7.3 与 Navigator Widget 的关系
- 视口变化时更新导航器视口矩形
- 代码位置: `label_widget.py` 第 5180-5206 行

## 8. UI 入口

### 8.1 顶部菜单

顶部 `View` 菜单中新增子菜单：

1. `重置图像视图`
2. `重置当前图像视图`
3. `重置从当前到末尾图像视图`
4. `重置所有图像视图`

### 8.2 文件列表右键菜单

在文件列表中右键某个文件项时，菜单会新增：

1. `重置该图像视图`
2. `重置从该图像到末尾的视图`
3. `重置所有图像视图`

文件列表空白区域不会弹出这些重置项，必须作用于具体文件项。

### 8.3 画布右键菜单

当鼠标位于图像画布区域并点击右键时，菜单中也会新增：

1. `重置当前图像视图`
2. `重置从当前到末尾图像视图`
3. `重置所有图像视图`

无论当前是否选中了 shape，这 3 个入口都会出现在画布右键菜单中。

## 9. 调试与监控

### 9.1 查看当前状态

```python
# 在控制台或日志中查看
print(viewport_controller.states)
print(viewport_controller.last_loaded)
```

### 9.2 常见问题排查

| 问题 | 可能原因 | 排查方法 |
|------|----------|----------|
| 切换图片后视图未恢复 | 状态未保存或恢复失败 | 检查 `_capture()` 返回值 |
| 视图位置偏移 | 图像尺寸变化导致坐标映射错误 | 检查坐标转换公式 |
| 滚动条未更新 | QScrollArea 查找失败 | 检查父控件链 |
| 点击重置后无变化 | 当前图片没有回到默认视图 | 检查 `_reset_image_views_for_files()` 是否命中当前文件 |
| 文件列表右键没有重置项 | 右键位置不在具体文件项上 | 确认点击的是文件项而非空白区域 |
| 画布右键没有重置项 | 使用了不同菜单分支 | 检查 `self.canvas.menus[0]` 和 `self.canvas.menus[1]` 是否都已注册 |

## 10. 当前实现说明

### 10.1 默认恢复行为

当前图片被手动重置时，恢复逻辑为：

1. 将 `zoom_mode` 设为 `FIT_WINDOW`
2. 调用 `adjust_scale(initial=True)` 恢复默认缩放
3. 将水平/垂直滚动条恢复到最小值
4. 调用 `paint_canvas()` 刷新画面与导航器视口

因此，用户执行“重置当前图像视图”后，通常会看到画面缩放回适应窗口，并回到默认起始位置。

### 10.2 状态反馈

重置操作不会弹出确认框，而是通过状态栏显示中文提示，例如：

1. `已重置当前图像的 1 个图像视图状态`
2. `已重置从当前到末尾的 12 个图像视图状态`
3. `已重置全部的 84 个图像视图状态`

## 11. 版本历史

- **v4.0.0-beta.4**: 引入 `ViewportController` 类，替代旧版滚动值保存逻辑
- **改进**: 使用图像坐标系，支持跨尺寸图片和窗口 resize
- **2026-04-29**: 新增手动重置图像视图能力，支持顶部菜单、文件列表右键菜单和画布右键菜单

---

*文档版本: 1.1*  
*适用版本: X-AnyLabeling 4.0.0-beta.4+*  
*最后更新: 2026-04-29*

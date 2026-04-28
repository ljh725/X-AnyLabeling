# Viewport 状态管理技术说明

## 1. 功能概述

X-AnyLabeling 的 Viewport（视口）状态管理功能用于在切换图片时保持用户的视图状态（包括缩放比例和视图位置）。该功能通过 `ViewportController` 类实现，将每张图片的视口状态存储在内存字典中，实现前后图片之间窗口状态的持久化。

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

### 2.2 状态保存与恢复流程

**保存时机** (`on_file_leaving` 方法):
- 在 `LabelWidget.load_file()` 开始时调用（第 5623-5629 行）
- 无条件保存当前图片的视口状态到 `_states` 字典

**恢复时机** (`on_file_loaded` 方法):
- 在 `LabelWidget.load_file()` 结束时调用（第 5766-5777 行）
- 根据策略选择最佳可用状态并应用到画布

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
| 策略解析 | `viewport_controller.py` | 262-276 |
| 坐标捕获 | `viewport_controller.py` | 201-260 |
| 坐标应用 | `viewport_controller.py` | 278-335 |
| UI 菜单 | `label_widget.py` | 1162-1171 |
| 菜单注册 | `label_widget.py` | 2148 |

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

## 7. 与其他功能的交互

### 7.1 与 Keep Previous Scale 的关系
- `keep_prev_scale`: 仅保持缩放比例（旧逻辑）
- `keep_prev_viewport`: 保持缩放比例 + 视图位置（新逻辑）
- 两者独立，可同时开启

### 7.2 与 Legacy Scroll Values 的关系
- 当 `ViewportController` 无状态时，回退到旧版滚动值
- 代码位置: `label_widget.py` 第 5784-5791 行

### 7.3 与 Navigator Widget 的关系
- 视口变化时更新导航器视口矩形
- 代码位置: `label_widget.py` 第 5180-5206 行

## 8. 扩展性设计

### 8.1 添加新的清除功能

如需添加清除视口状态的功能（如清除当前/所有/后续图片的状态）：

1. **在 `ViewportController` 中添加方法**:
   ```python
   def clear_state(self, filename: str) -> None:
       """清除指定图片的视口状态"""
       self._states.pop(filename, None)
   
   def clear_all_states(self) -> None:
       """清除所有视口状态"""
       self._states.clear()
   
   def clear_states_from(self, filename: str, image_list: list[str]) -> None:
       """清除从指定图片开始及之后的所有状态"""
       if filename in image_list:
           idx = image_list.index(filename)
           for img in image_list[idx:]:
               self._states.pop(img, None)
   ```

2. **在 `LabelWidget` 中添加菜单项**:
   - 在 View 菜单下添加子菜单
   - 绑定到上述方法

### 8.2 持久化存储

当前状态仅保存在内存中，关闭程序后丢失。如需持久化：

1. 在 `LabelWidget.closeEvent()` 中保存 `_states` 到配置文件
2. 在启动时从配置文件加载
3. 注意：状态数据量可能较大，需考虑性能

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

## 10. 版本历史

- **v4.0.0-beta.4**: 引入 `ViewportController` 类，替代旧版滚动值保存逻辑
- **改进**: 使用图像坐标系，支持跨尺寸图片和窗口 resize

---

*文档版本: 1.0*  
*适用版本: X-AnyLabeling 4.0.0-beta.4+*  
*最后更新: 2026-04-23*

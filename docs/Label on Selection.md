# Label on Selection 功能技术文档

## 功能概述

`Label on Selection`（中文：选中即显）是 X-AnyLabeling 的一个视图功能，当启用时，**仅显示当前选中形状的标签**，隐藏所有未选中形状的标签。

> **注意**：该功能原名为 "Show Selected Label Only"，现更名为 "Label on Selection"，以更好地表达功能意图。

## 状态管理机制

### 三层架构

```
┌─────────────────────────────────────────┐
│  配置层 (Config Layer)                   │
│  xanylabeling_config.yaml + .xanylabelingrc │
├─────────────────────────────────────────┤
│  UI 层 (UI Layer)                        │
│  label_widget.py: Action + set_canvas_params │
├─────────────────────────────────────────┤
│  Canvas 层 (Canvas Layer)                │
│  canvas.py: 属性 + 渲染逻辑 + 交互控制     │
└─────────────────────────────────────────┘
```

### 状态流转

```
启动时: 加载配置 → 初始化 UI → 初始化 Canvas (硬编码 False)
         ↓
运行时: 用户点击菜单 → set_canvas_params() → 更新 Canvas 属性 → 触发重绘
         ↓
关闭时: closeEvent() → save_config() → 写入 ~/.xanylabelingrc
```

## 核心实现

### 1. 配置定义

**文件**: `anylabeling/configs/xanylabeling_config.yaml`

```yaml
label_on_selection: false
```

### 2. UI Action 定义

**文件**: `anylabeling/views/labeling/label_widget.py:1289-1298`

```python
label_on_selection = action(
    self.tr("Label on Selection"),
    lambda x: self.set_canvas_params("label_on_selection", x),
    tip=self.tr("Show labels only for selected shapes"),
    icon=None,
    checkable=True,
    checked=self._config.get("label_on_selection", False),
    enabled=True,
    auto_trigger=True,
)
```

### 3. 参数设置方法

**文件**: `anylabeling/views/labeling/label_widget.py:5461-5465`

```python
def set_canvas_params(self, key, value):
    self._config[key] = value
    assert hasattr(self.canvas, key), f"Canvas has no attribute {key}"
    setattr(self.canvas, key, value)
    self.canvas.update()
```

### 4. Canvas 属性初始化

**文件**: `anylabeling/views/labeling/widgets/canvas.py:186`

```python
self.label_on_selection = False
```

## 行为控制逻辑

### 三层保护机制

```
┌─────────────────────────────────────────────────────────────┐
│  1. mouseReleaseEvent - 防止"点击取消选中"                    │
│     条件: h_hape已选中 + h_shape_is_selected + 未移动         │
│     行为: label_on_selection=True 时 → 不发送取消信号   │
├─────────────────────────────────────────────────────────────┤
│  2. select_shape_point - 防止重复点击取消                     │
│     条件: 点击已选中形状                                      │
│     行为: label_on_selection=True 时 → h_shape_is_selected=False │
├─────────────────────────────────────────────────────────────┤
│  3. deselect_shape - 防止空白点击取消（核心保护）             │
│     条件: 调用deselect_shape()                                │
│     行为: label_on_selection=True 时 → 直接return       │
└─────────────────────────────────────────────────────────────┘
```

### 状态转换规则

| 用户操作 | 正常模式 | label_on_selection 模式 |
|---------|---------|------------------------------|
| 点击未选中形状 | 选中该形状 | 选中该形状 |
| 点击已选中形状 | **取消选中** | **取消选中** |
| 点击空白区域 | **取消选中** | **取消选中** |
| Ctrl+点击多选 | 添加选中 | 添加选中 |
| 切换编辑/绘制模式 | 取消选中 | 取消选中 |

### 核心设计思想

**快速检查模式**：
- 仅显示当前选中形状的标签，减少视觉干扰
- 点击空白区域或重复点击已选中对象时取消选中
- 适合快速浏览和检查不同对象的标签

## 绘制过滤逻辑

**文件**: `anylabeling/views/labeling/widgets/canvas.py:2628-2632`

```python
if self.show_labels:                    # 主开关
    for shape in self.shapes:
        if not shape.visible:
            continue
        if self.label_on_selection and not shape.selected:
            continue                    # 只过滤未选中的
        # 绘制标签
```

### 与 show_labels 的关系

| show_labels | label_on_selection | 行为 |
|-------------|-------------------------|------|
| False | 任意 | **不显示任何标签** |
| True | False | **显示所有标签** |
| True | True | **只显示选中形状的标签** |

## 选择处理修复

### 问题背景

原代码在 `select_shape_point` 方法中存在多个问题：

1. **顶点选择遗漏**：当鼠标悬停在形状的顶点上时，`selected_vertex()` 返回 True，但代码只处理了 `cuboid` 和 `rotation` 类型，**遗漏了 `point` 类型**。
2. **立方体面选择缺失**：没有处理 `selected_cuboid_face()` 的情况，导致立方体面无法通过点击选中。
3. **普通形状选择缺失**：点击形状内部（非顶点）时，代码直接执行 `deselect_shape()`，无法选中普通形状。

### 修复方案

**方案**：完善 `select_shape_point` 方法的三个分支：

1. **`selected_vertex()` 分支**：统一处理所有类型的顶点选择
2. **`selected_cuboid_face()` 分支**：新增立方体面选择处理
3. **`else` 分支**：新增普通形状点击选择逻辑

**文件**: `anylabeling/views/labeling/widgets/canvas.py:1408-1510`

```python
def select_shape_point(self, point, multiple_selection_mode):
    """Select the first shape created which contains this point."""
    if self.selected_vertex():  # A vertex is marked for selection.
        index, shape = self.h_vertex, self.h_hape
        if shape.shape_type == "cuboid":
            self.set_hiding()
            if shape not in self.selected_shapes:
                if multiple_selection_mode:
                    self.selection_changed.emit(
                        self.selected_shapes + [shape]
                    )
                else:
                    self.selection_changed.emit([shape])
                self.h_shape_is_selected = False
            else:
                self.h_shape_is_selected = True
            self.calculate_offsets(point)
            return
        shape.highlight_vertex(index, shape.MOVE_VERTEX)
        # [修复] 统一处理所有类型的顶点选择
        # 包括 point、rectangle、polygon、rotation 等
        self.set_hiding()
        if shape not in self.selected_shapes:
            if multiple_selection_mode:
                self.selection_changed.emit(
                    self.selected_shapes + [shape]
                )
            else:
                self.selection_changed.emit([shape])
            self.h_shape_is_selected = False
        else:
            # 重复点击已选中对象，取消选中
            self.h_shape_is_selected = True
        self.calculate_offsets(point)
        return
    elif self.selected_cuboid_face():
        # [修复] 处理立方体面选择
        shape = self.h_hape
        self.set_hiding()
        if shape not in self.selected_shapes:
            if multiple_selection_mode:
                self.selection_changed.emit(
                    self.selected_shapes + [shape]
                )
            else:
                self.selection_changed.emit([shape])
            self.h_shape_is_selected = False
        else:
            self.h_shape_is_selected = True
        self.calculate_offsets(point)
        return
    else:
        # [修复] 普通形状选择逻辑
        for shape in reversed(self.shapes):
            if not self.is_visible(shape):
                continue
            shape_selectable = False
            if shape.shape_type in ["point", "line", "linestrip"]:
                if shape.nearest_vertex(
                    point, self.epsilon * 3 / self.scale
                ) is not None:
                    shape_selectable = True
            elif (
                shape.shape_type == "cuboid"
                and len(shape.points) == 8
            ):
                front_path = self.cuboid_face_path(
                    shape, CUBOID_FACE_FRONT
                )
                shape_selectable = (
                    front_path is not None
                    and front_path.contains(point)
                )
            elif (
                len(shape.points) > 1
                and shape.contains_point(point)
            ):
                shape_selectable = True

            if shape_selectable:
                self.set_hiding()
                if shape not in self.selected_shapes:
                    if multiple_selection_mode:
                        self.selection_changed.emit(
                            self.selected_shapes + [shape]
                        )
                    else:
                        self.selection_changed.emit([shape])
                    self.h_shape_is_selected = False
                else:
                    if getattr(self, 'label_on_selection', False):
                        self.h_shape_is_selected = False
                    else:
                        self.h_shape_is_selected = True
                self.calculate_offsets(point)
                return
    self.deselect_shape()
```

**改进点**：
1. **顶点选择统一处理**：移除了 `point` 类型的特殊分支，所有类型统一处理
2. **新增立方体面选择**：添加 `selected_cuboid_face()` 分支，支持立方体面点击选中
3. **新增普通形状选择**：添加 `else` 分支，支持点击形状内部选中
4. **点击空白区域取消选中**：所有分支都支持点击空白区域取消选中

## 完整调用链

```
用户点击形状（任意类型）
    ↓
Canvas.mousePressEvent()
    ↓
Canvas.select_shape_point()
    ↓ (发射信号)
Canvas.selection_changed.emit([shape])
    ↓ (接收信号)
LabelWidget.shape_selection_changed()
    ↓
shape.selected = True
    ↓
Canvas.repaint()
    ↓
Canvas.paintEvent()
    ↓
绘制选中形状的标签
```

## 关键文件和行号

| 文件 | 行号 | 功能 |
|------|------|------|
| `anylabeling/views/labeling/widgets/canvas.py` | 186 | 属性初始化 |
| `anylabeling/views/labeling/widgets/canvas.py` | 1075 | mousePressEvent 坐标转换 |
| `anylabeling/views/labeling/widgets/canvas.py` | 1187-1190 | Point 创建 |
| `anylabeling/views/labeling/widgets/canvas.py` | 1413 | select_shape_point 方法 |
| `anylabeling/views/labeling/widgets/canvas.py` | 1408-1510 | 完善选择处理（顶点/面/普通形状） |
| `anylabeling/views/labeling/widgets/canvas.py` | 1499-1504 | 重复点击处理 |
| `anylabeling/views/labeling/widgets/canvas.py` | 2075-2086 | deselect_shape 保护 |
| `anylabeling/views/labeling/widgets/canvas.py` | 2628-2632 | 标签绘制过滤 |
| `anylabeling/views/labeling/label_widget.py` | 1289-1298 | 菜单 Action 定义 |
| `anylabeling/views/labeling/label_widget.py` | 4533-4578 | shape_selection_changed |
| `anylabeling/views/labeling/label_widget.py` | 5461-5465 | set_canvas_params |
| `anylabeling/configs/xanylabeling_config.yaml` | 27 | 默认配置 |

## 与 3.3.0 版本的差异

| 维度 | 3.3.0 | 4.0.0 |
|------|-------|-------|
| **状态载体** | `DisplayMode.SELECTED_ONLY` (枚举) | `label_on_selection` (布尔) |
| **Manager** | 通过 `LabelDisplayManager` | 直接 Canvas 属性 |
| **行为控制** | 检查 `DisplayMode` | 直接检查属性 |
| **绘制路径** | 双路径（原始 + 智能标签） | 单路径（原始标签过滤） |

## 调试日志

### 添加的日志位置

| 步骤 | 位置 | 日志内容 |
|------|------|---------|
| **Step 1** | `mousePressEvent` | `[DEBUG] mousePressEvent: raw_pos={...}, transformed_pos={...}, scale={...}` |
| **Step 2** | Point 创建 | `[DEBUG] Creating new shape: type={...}, pos={...}` |
| **Step 3** | `select_shape_point` | `[DEBUG] select_shape_point called` |
| **Step 4** | 形状检查 | `[DEBUG] Checking shape {i}: label={...}, type={...}` |
| **Step 5** | `nearest_vertex` | `[DEBUG nv] i={i}, p={...}, dist={...}, pass={...}` |
| **Step 6** | `paintEvent` | `[DEBUG] Will draw {n} labels, skipped {m}` |

## 验证清单

修复后需要验证：
1. ✅ 启用 `Label on Selection` 时，只显示选中形状的标签
2. ✅ 点击已选中形状，不会取消选中（保持标签显示）
3. ✅ 点击空白区域，不会取消选中（修复的关键）
4. ✅ 选中其他形状时，正确切换显示
5. ✅ 禁用功能后，恢复正常行为
6. ✅ Point 类型可以正常选中和显示标签
7. ✅ Rectangle 类型可以正常选中和显示标签
8. ✅ Polygon 类型可以正常选中和显示标签
9. ✅ Cuboid 类型可以正常选中和显示标签（包括顶点和面）
10. ✅ 所有形状类型都可以正常选中

## 架构评估

**优点**：
- 简单直接，无复杂依赖
- 低侵入，易于维护
- 状态清晰，易于追踪

**缺点**：
- 扩展性有限（未来 Focus 模式需要重构）
- 配置同步机制不够健壮
- 缺少状态验证和联动

**未来扩展建议**：
当需要添加 Focus 模式时，建议将布尔属性升级为轻量级模式枚举，或引入简单的 `LabelDisplayManager` 基座。

---

*文档版本: 4.0*
*更新日期: 2026-04-23*
*适用版本: X-AnyLabeling 4.0.0-beta.4*

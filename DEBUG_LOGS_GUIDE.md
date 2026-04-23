# 调试日志添加说明

## 添加位置及目的

### 1. `anylabeling/views/labeling/widgets/canvas.py`

#### a. `deselect_shape()` 方法 (第2067行)
**目的**: 追踪何时以及为何取消选择所有形状
```python
print(f"[DEBUG] deselect_shape called, clearing {len(self.selected_shapes)} shapes")
import traceback
traceback.print_stack(limit=8)
```

#### b. `select_shape_point()` 方法 (第1485行)
**目的**: 追踪形状选择过程
```python
print(f"[DEBUG] select_shape_point: found selectable shape {shape.label} (type={shape.shape_type})")
print(f"[DEBUG] select_shape_point: emitting single selection [{shape.label}]")
print(f"[DEBUG] select_shape_point: no shape found, calling deselect_shape")
```

#### c. `mouseMoveEvent()` 方法 (第967行)
**目的**: 追踪鼠标悬停时的自动选择
```python
print(f"[DEBUG] mouseMoveEvent: hovering over {shape.label}, calling select_shape_point")
```

#### d. `mousePressEvent()` 方法 (第1264行)
**目的**: 追踪鼠标点击时的选择
```python
print(f"[DEBUG] mousePressEvent (LeftButton): calling select_shape_point at ({pos.x()}, {pos.y()})")
```

#### e. `restore_shape()` 方法 (第427行)
**目的**: 追踪撤销操作时的选择清除
```python
print(f"[DEBUG] restore_shape: setting {shape.label}.selected = False")
```

#### f. `end_move()` 方法 (第1323行)
**目的**: 追踪移动结束时的选择状态变化
```python
print(f"[DEBUG] end_move: setting {self.selected_shapes[i].label}.selected = False")
```

#### g. `paintEvent()` 方法 (第2627行)
**目的**: 追踪绘制时的状态快照
```python
print(f"[DEBUG] ===== paintEvent label draw =====")
print(f"[DEBUG] show_selected_label_only={self.show_selected_label_only}")
print(f"[DEBUG] total shapes={len(self.shapes)}")
print(f"[DEBUG] selected_shapes (count={len(self.selected_shapes)}): {selected_info}")
print(f"[DEBUG] all_shapes selected status: {all_shapes_info}")
print(f"[DEBUG] SKIP shape(id={id(shape)}, label={shape.label}) because selected=False (show_selected_label_only=True)")
```

### 2. `anylabeling/views/labeling/label_widget.py`

#### a. `shape_selection_changed()` 方法 (第4533行)
**目的**: 追踪选择状态同步过程
```python
print(f"[DEBUG] shape_selection_changed called with {len(selected_shapes)} shapes")
import traceback
traceback.print_stack(limit=8)
print(f"[DEBUG] Clearing old selection: {shape.label} (type={shape.shape_type})")
print(f"[DEBUG] Setting new selection: {shape.label} (type={shape.shape_type})")
```

#### b. `scroll_to_item()` 方法 (第3329行)
**目的**: 追踪滚动到项目时的选择清除
```python
print(f"[DEBUG] scroll_to_item: setting {shape.label}.selected = False")
```

#### c. `add_label()` 方法 (第5096行)
**目的**: 追踪添加标签时的选择设置
```python
print(f"[DEBUG] add_label: setting {shape.label}.selected = True")
```

## 预期输出示例

### 正常选择流程
```
[DEBUG] mousePressEvent (LeftButton): calling select_shape_point at (100.0, 200.0)
[DEBUG] select_shape_point: found selectable shape nose (type=point)
[DEBUG] select_shape_point: emitting single selection [nose]
[DEBUG] shape_selection_changed called with 1 shapes
[DEBUG] Setting new selection: nose (type=point)
[DEBUG] ===== paintEvent label draw =====
[DEBUG] show_selected_label_only=True
[DEBUG] selected_shapes (count=1): [(2088295980576, 'nose', True, True)]
```

### 问题场景（选择被清除）
```
[DEBUG] mousePressEvent (LeftButton): calling select_shape_point at (100.0, 200.0)
[DEBUG] select_shape_point: found selectable shape nose (type=point)
[DEBUG] select_shape_point: emitting single selection [nose]
[DEBUG] shape_selection_changed called with 1 shapes
[DEBUG] Setting new selection: nose (type=point)
[DEBUG] deselect_shape called, clearing 1 shapes
  File "...", line XXX, in mouseMoveEvent
    self.deselect_shape()
[DEBUG] ===== paintEvent label draw =====
[DEBUG] selected_shapes (count=0): []
```

## 测试步骤

1. 启动应用，打开包含关键点的图像
2. 开启 "Show Selected Label Only" 功能
3. 测试场景：
   - **场景A**: 普通编辑模式下点击关键点
   - **场景B**: 关键点填充模式下点击关键点A，然后点击关键点B
4. 观察控制台输出，特别关注：
   - `deselect_shape` 是否在不应该的时候被调用
   - `shape_selection_changed` 是否被多次调用
   - `paintEvent` 中的 `selected_shapes` 是否为空

## 常见问题分析

### 如果看到 `deselect_shape` 在 `shape_selection_changed` 之后立即被调用
**可能原因**: 
- `mouseMoveEvent` 中的 `h_shape_is_hovered` 逻辑触发了额外的选择
- 某些事件处理程序在不应该的时候清除了选择

### 如果 `shape_selection_changed` 被调用但 `selected_shapes` 仍为空
**可能原因**:
- `shape_selection_changed` 被多次调用，其中某次传入了空列表
- 存在竞争条件

### 如果 `paintEvent` 显示所有 shapes 的 `selected=False`
**可能原因**:
- 选择状态被某个事件处理程序清除了
- `shape_selection_changed` 没有被正确调用

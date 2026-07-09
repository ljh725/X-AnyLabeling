# 缩放中心飘移修复技术实现文档

> 目标：修复 600x800 等竖图在 Ctrl+滚轮缩放时，鼠标下图像点不能稳定保持在鼠标位置的问题。
> 范围：本文档只描述实现方案和需要修改的代码，不直接修改业务代码。

## 1. 当前问题结论

现有滚轮缩放逻辑位于：

- `anylabeling/views/labeling/label_widget.py:6942-6963`
- `anylabeling/views/labeling/widgets/canvas.py:3676-3679`

`Canvas.wheelEvent()` 将 Ctrl+Wheel 转为 `zoom_request(delta, pos)` 信号，其中 `pos` 是鼠标在 canvas widget 坐标系中的位置。

`LabelingWidget.zoom_request()` 当前逻辑是：

```python
canvas_width_old = self.canvas.width()
self.add_zoom(units)
canvas_width_new = self.canvas.width()
if canvas_width_old != canvas_width_new:
    canvas_scale_factor = canvas_width_new / canvas_width_old
    x_shift = round(pos.x() * canvas_scale_factor - pos.x())
    y_shift = round(pos.y() * canvas_scale_factor - pos.y())
    ...
```

问题点：

1. 只用 `canvas.width()` 判断是否需要补偿。竖图在 `setWidgetResizable(True)` 下经常宽度被视口钳制，缩放后 width 不变，但 height 和 scale 已经变化，导致补偿分支被跳过。
2. 即使进入补偿，x/y 都共用 width 比例。竖图高度方向变化更明显，y 方向补偿会失真。
3. 算法没有使用 `Canvas.offset_to_center()`。实际绘制坐标不是简单的 `image * scale`，而是：

```text
widget_pos = (image_pos + offset_to_center) * scale
```

相关代码：

- `anylabeling/views/labeling/widgets/canvas.py:2365-2367`
- `anylabeling/views/labeling/widgets/canvas.py:3429-3443`
- `anylabeling/views/labeling/widgets/viewport_controller.py:273-277`
- `anylabeling/views/labeling/widgets/viewport_controller.py:345-352`

因此，单纯使用 `scale` 比值或 `canvas.width()` 比值都不能完整表达缩放前后的坐标关系。

## 2. 正确的坐标模型

`Canvas.paintEvent()` 中的核心绘制变换：

```python
offset = self.offset_to_center()
p.scale(self.scale, self.scale)
p.translate(offset)
p.drawPixmap(0, 0, self.pixmap)
```

`Canvas.transform_pos()` 的反向换算：

```python
return point / self.scale - self.offset_to_center()
```

因此：

```text
image_pos_before = old_widget_pos / old_scale - old_offset
new_widget_pos = (image_pos_before + new_offset) * new_scale
scroll_delta = new_widget_pos - old_widget_pos
```

滚动条表示 viewport 左上角在 canvas widget 坐标系中的位置，所以缩放后应设置：

```text
new_scroll = old_scroll + scroll_delta
```

符号验证：

```text
screen_pos = widget_pos - scroll_value

old_screen = old_widget_pos - old_scroll
new_screen = new_widget_pos - new_scroll

要求 old_screen == new_screen：
old_widget_pos - old_scroll == new_widget_pos - new_scroll
new_scroll = old_scroll + (new_widget_pos - old_widget_pos)
new_scroll = old_scroll + scroll_delta
```

数值例子：

```text
old_widget_pos = 300
old_scroll = 100
old_screen = 200

new_widget_pos = 330
scroll_delta = 30

若使用 +：
new_scroll = 130
new_screen = 330 - 130 = 200  # 稳定

若使用 -：
new_scroll = 70
new_screen = 330 - 70 = 260   # 反向漂移
```

因此 `+` 是正确符号。编码前仍建议保留一个小的纯数值验证或临时日志，防止实现时把 `delta` 定义反过来。

注意：如果某个方向的图像小于视口，滚动条最大值为 0，则该方向无法通过滚动条保持任意鼠标点稳定。此时只能保持居中布局，鼠标点锚定会被 scrollbar clamp 限制。这不是计算公式错误，而是当前 `QScrollArea + centered offset` 架构的自然限制。实现时应先把目标滚动值 clamp 到 scrollbar 的有效范围，再调用 `set_scroll()`，避免 `set_scroll()` 把超出范围的原始目标值写入 `scroll_values`。

## 3. 必须修改的代码

### 3.1 新增公共锚点缩放 helper

建议在 `LabelingWidget` 中新增一个私有方法，统一处理“围绕 canvas widget 坐标点缩放”。

位置建议：

- 放在 `set_scroll()` / `set_zoom()` / `add_zoom()` 附近，即 `label_widget.py:6916` 之后。

建议方法签名：

```python
def _zoom_around_canvas_pos(
    self,
    canvas_pos: QtCore.QPoint | QtCore.QPointF,
    apply_zoom: Callable[[], None],
) -> None:
    """Apply zoom while keeping the image point under canvas_pos stable."""
```

如果不想引入 `Callable` 类型导入，也可以拆成更具体的方法：

```python
def _set_zoom_around_canvas_pos(
    self,
    zoom_value: int,
    canvas_pos: QtCore.QPoint | QtCore.QPointF,
) -> None:
    ...

def _add_zoom_around_canvas_pos(
    self,
    increment: float,
    canvas_pos: QtCore.QPoint | QtCore.QPointF,
) -> None:
    ...
```

更推荐第一种，因为导航器缩放和滚轮缩放可以复用同一个锚点补偿逻辑。

核心伪代码：

```python
def _zoom_around_canvas_pos(self, canvas_pos, apply_zoom):
    if self.canvas.pixmap is None or self.canvas.pixmap.isNull():
        apply_zoom()
        return

    self.canvas.adjustSize()

    old_scale = self.canvas.scale
    old_offset = self.canvas.offset_to_center()
    old_pos = QtCore.QPointF(canvas_pos)
    image_pos = old_pos / old_scale - old_offset

    h_bar = self.scroll_bars[Qt.Orientation.Horizontal]
    v_bar = self.scroll_bars[Qt.Orientation.Vertical]
    old_h = h_bar.value()
    old_v = v_bar.value()

    apply_zoom()

    new_scale = self.canvas.scale
    new_offset = self.canvas.offset_to_center()
    new_pos = (image_pos + new_offset) * new_scale
    delta = new_pos - old_pos

    target_h = _clamp_scroll_value(h_bar, old_h + delta.x())
    target_v = _clamp_scroll_value(v_bar, old_v + delta.y())

    self.set_scroll(Qt.Orientation.Horizontal, target_h)
    self.set_scroll(Qt.Orientation.Vertical, target_v)
```

实现注意：

- `apply_zoom()` 必须触发 `paint_canvas()` 或等效逻辑，使 `self.canvas.scale` 和 `self.canvas.adjustSize()` 在计算 `new_offset` 前完成更新。
- 当前 `add_zoom()` 调用 `set_zoom()`，`set_zoom()` 通过 `zoom_widget.setValue()` 触发 `paint_canvas()`；这条路径可继续复用。
- 如果未来某条缩放路径 block 了 `zoom_widget` 信号，则必须手动调用 `paint_canvas()` 后再计算 `new_offset`。
- `old_offset` 依赖 `Canvas.offset_to_center()`，而该函数内部读取当前 widget size。捕获 old 值前调用 `self.canvas.adjustSize()`，确保当前 scale 下的 sizeHint 已同步。`self.canvas.update()` 只会排队重绘，不是同步布局手段。
- `_clamp_scroll_value()` 可以是一个小的私有 helper，也可以在 `_zoom_around_canvas_pos()` 内联实现：

```python
def _clamp_scroll_value(scroll_bar, value):
    return max(scroll_bar.minimum(), min(scroll_bar.maximum(), value))
```

- 当 `scroll_bar.maximum() == 0` 时，clamp 后目标值就是 0，相当于主动跳过该方向补偿。这样既保留居中 offset 的自然行为，也避免把不可达的滚动值写入 `scroll_values`。
- `set_scroll()` 内部会 round 并更新 navigator viewport，保留即可，但传入值应已在有效范围内。

### 3.2 替换 `zoom_request()`

位置：

- `anylabeling/views/labeling/label_widget.py:6942-6963`

当前逻辑应从 width-based 补偿改为 image-anchor 补偿。

建议改为：

```python
def zoom_request(self, delta, pos):
    units = 1.1
    if delta < 0:
        units = 0.9

    self._zoom_around_canvas_pos(
        pos,
        lambda: self.add_zoom(units),
    )
```

收益：

- 不再依赖 `canvas.width()` 是否变化。
- x/y 分别由真实坐标变换推导，不会用 width 比例套 y 方向。
- 自动纳入 `offset_to_center()`，适配图像小于视口时的居中偏移变化。

## 4. 第二阶段：navigator 坐标模型

滚轮缩放不是唯一使用 width-only 补偿的路径。导航器缩放中也有两段重复逻辑。

但 navigator 相关代码目前同时存在“图像比例”和“canvas widget 比例”两套隐含模型。如果只改其中一处，例如只改 `_convert_navigator_pos_to_canvas()`，可能造成 navigator 点击位置、viewport 框显示、主视图滚动位置三者不一致。

因此建议将 navigator 作为第二阶段整组处理；第一阶段只修复 Ctrl+滚轮缩放。

### 4.1 `on_navigator_zoom_changed()` 中带 mouse_pos 的路径

位置：

- `anylabeling/views/labeling/label_widget.py:6739-6776`

当前流程：

1. `_convert_navigator_pos_to_canvas(mouse_pos)`
2. 记录 `canvas_width_old`
3. 设置 zoom
4. `paint_canvas()`
5. 用 `canvas_width_new / canvas_width_old` 计算滚动补偿

建议改为：

```python
canvas_pos = self._convert_navigator_pos_to_canvas(mouse_pos)
if canvas_pos:
    self._zoom_around_canvas_pos(
        canvas_pos,
        lambda: self._set_navigator_zoom_value(zoom_percentage),
    )
    return
```

其中 `_set_navigator_zoom_value()` 可以抽出当前重复的三行：

```python
def _set_navigator_zoom_value(self, zoom_percentage: int) -> None:
    self.zoom_widget.setValue(zoom_percentage)
    self.zoom_mode = self.MANUAL_ZOOM
    self.zoom_values[self.filename] = (self.zoom_mode, zoom_percentage)
    self.paint_canvas()
```

如果不想新增该 helper，也可以在 lambda 中调用一个局部闭包。

### 4.2 `on_navigator_zoom_changed()` 中使用 viewport center 的路径

位置：

- `anylabeling/views/labeling/label_widget.py:6798-6836`

当前也复制了 width-only 补偿逻辑。应使用同一个 `_zoom_around_canvas_pos()` 替换。

建议流程：

```python
canvas_pos = self._convert_navigator_pos_to_canvas(
    QtCore.QPoint(int(nav_rect_center_x), int(nav_rect_center_y))
)
if canvas_pos:
    self._zoom_around_canvas_pos(
        canvas_pos,
        lambda: self._set_navigator_zoom_value(zoom_percentage),
    )
    return
```

### 4.3 修正 `_convert_navigator_pos_to_canvas()`

位置：

- `anylabeling/views/labeling/label_widget.py:6848-6883`

当前实现：

```python
canvas_x = int(x_ratio * self.canvas.width())
canvas_y = int(y_ratio * self.canvas.height())
```

这个写法把 navigator 中的图像比例映射到了整个 canvas widget，而 canvas widget 可能包含居中留白。更准确的换算应基于 pixmap 尺寸、scale 和 offset：

```python
offset = self.canvas.offset_to_center()
scale = self.canvas.scale
pixmap = self.canvas.pixmap

canvas_x = (x_ratio * pixmap.width() + offset.x()) * scale
canvas_y = (y_ratio * pixmap.height() + offset.y()) * scale
return QtCore.QPoint(int(canvas_x), int(canvas_y))
```

这样 navigator 上点击图像中心，才会对应 canvas 中真实绘制的图像中心，而不是 canvas widget 的几何中心。

重要边界：不要只改这一处。若修正 `_convert_navigator_pos_to_canvas()`，必须同步修正 `update_navigator_viewport()`、`on_navigator_request()`，以及最好同步修正 `_center_on_shape()`。否则 navigator 的输入映射使用新模型，而 viewport 框仍用旧 `canvas.size()` 比例模型，会进入“半新半旧”的不一致状态。

## 5. 相关但不建议混入本次最小修复的代码

以下代码也使用 `canvas.size()` 做比例换算，可能在图像小于视口、存在居中 offset 时产生偏差。但它们属于 navigator/定位一致性问题，不是 Ctrl+滚轮缩放中心飘移的最小修复路径。

如果进入第二阶段，建议与第 4.3 节一起整组处理：

- `anylabeling/views/labeling/label_widget.py:5245-5278`，`_center_on_shape()`
- `anylabeling/views/labeling/label_widget.py:6668-6683`，`on_navigator_request()`
- `anylabeling/views/labeling/label_widget.py:6685-6714`，`update_navigator_viewport()`

这些函数也应从“canvas widget 比例”切换为“image coordinate + offset_to_center + scale”模型。

例如 `_center_on_shape()` 的目标坐标不应是：

```python
target_x = x_ratio * canvas_size.width() - viewport_width / 2
```

而应是：

```python
offset = self.canvas.offset_to_center()
scale = self.canvas.scale
target_x = (cx + offset.x()) * scale - viewport_width / 2
target_y = (cy + offset.y()) * scale - viewport_height / 2
```

## 6. 验证方案

### 6.1 日志验证

在修复前后临时打印以下值：

```python
print(
    "[zoom-anchor]",
    "old_scale=", old_scale,
    "new_scale=", new_scale,
    "old_offset=", old_offset,
    "new_offset=", new_offset,
    "old_pos=", old_pos,
    "image_pos=", image_pos,
    "new_pos=", new_pos,
    "delta=", delta,
    "h=", old_h, self.scroll_bars[Qt.Orientation.Horizontal].maximum(),
    "v=", old_v, self.scroll_bars[Qt.Orientation.Vertical].maximum(),
)
```

重点看：

- 600x800 竖图缩放时，即使 `canvas.width()` 不变，也会产生正确的 vertical delta。
- 鼠标下的 `image_pos` 在缩放前后应保持接近不变。
- 如果水平 scrollbar maximum 为 0，水平 target 被 clamp 到 0 是预期行为，且 `scroll_values` 不应保存非 0 的不可达目标值。
- 任一方向若 `new_widget_pos - target_scroll` 与 `old_widget_pos - old_scroll` 差异很大，优先检查 `delta` 符号是否被写反，或 `old_offset/new_offset` 是否使用了 stale widget size。

### 6.2 手工场景

必须验证：

1. 600x800 竖图，Fit Window 后 Ctrl+滚轮放大/缩小。
2. 800x600 横图，Fit Window 后 Ctrl+滚轮放大/缩小。
3. 鼠标分别放在图像中心、上半部、下半部、靠近图像边缘。
4. 放大到出现双向滚动条后，鼠标下图像点应稳定。
5. 缩小到图像小于视口时，能保持居中；无滚动条方向允许有受限漂移，但不应出现纵向明显跳动。
6. 第一阶段未改 navigator 时，navigator 缩放按钮/滑条行为不作为本次修复验收项；若进入第二阶段，则必须验证 navigator 缩放、点击定位和 viewport 框一致性。

### 6.3 回归风险点

需要重点观察：

- `keep_prev_viewport`：已有 `ViewportController` 使用正确的 image coordinate 模型，理论上不应受负面影响。
- `fit_window` / `fit_width`：不走 `zoom_request()`，不应改变行为。
- navigator viewport 框：第一阶段不要半改 navigator 坐标换算；如果本次同时修正 navigator 坐标模型，需要确认 viewport 框和主视图位置仍一致。
- `set_scroll()` 会更新 `scroll_values`，锚点缩放仍会保存最新滚动位置，这是符合现有行为的。

## 7. 推荐实施顺序

1. 新增 `_zoom_around_canvas_pos()` helper。
2. 在 helper 中加入 `adjustSize()`、`+ delta` 符号验证注释、目标滚动值 clamp。
3. 用 helper 替换 `zoom_request()`。
4. 手工验证 600x800 和 800x600 Ctrl+滚轮缩放。
5. 若只做第一阶段，到此停止，不改 navigator 映射。
6. 若进入第二阶段，将 `on_navigator_zoom_changed()` 的两段 width-only 补偿替换为 helper。
7. 同步修正 `_convert_navigator_pos_to_canvas()`、`on_navigator_request()`、`update_navigator_viewport()`、`_center_on_shape()` 的 offset/scale 映射。
8. 再验证 navigator 缩放、点击定位和 viewport 框。

## 8. 最小代码改动摘要

最小可交付修复：

- 修改 `LabelingWidget.zoom_request()`。
- 新增一个 image-anchor 缩放 helper。

推荐完整修复：

- 修改 `LabelingWidget.zoom_request()`。
- 修改 `LabelingWidget.on_navigator_zoom_changed()` 中两段重复补偿。
- 修改 `LabelingWidget._convert_navigator_pos_to_canvas()`。
- 修改 `LabelingWidget.on_navigator_request()`。
- 修改 `LabelingWidget.update_navigator_viewport()`。
- 修改 `LabelingWidget._center_on_shape()`。
- 可选新增 `_set_navigator_zoom_value()` 去重。

暂不建议改：

- `scroll_area.setWidgetResizable(True)`：副作用大，会影响居中布局。
- `Canvas.offset_to_center()`：当前模型本身合理，问题在调用方没有把 offset 纳入缩放补偿。
- `Canvas.minimumSizeHint()`：它只暴露 scale 后 pixmap 的理想尺寸，不是根因。

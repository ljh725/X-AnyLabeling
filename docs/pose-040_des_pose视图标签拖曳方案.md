# 姿态标签框拖拽功能实现方案（逻辑实例化与偏移量记忆）

本方案旨在允许用户自由拖拽标签框以解决手动微调遮挡问题，且不创建额外的标注形状污染原始数据。核心思路是将标签框视为关键点 `Shape` 的附属属性，记录偏移量。

## 1. 为关键点 Shape 增加偏移量属性

在创建或加载关键点 `Shape` 时，为其动态添加或读取偏移量属性：

```python
# 假设你有一个 shape 对象代表关键点
shape.label_offset = [0.0, 0.0]  # [dx, dy]
```

## 2. 渲染器缓存标签位置并应用偏移

修改 `pose_renderer.py`，让 `PoseRenderer` 暴露当前画面上所有标签框的坐标，供 `Canvas` 鼠标事件使用。

在 `PoseRenderer` 的 `__init__` 中初始化缓存：

```python
class PoseRenderer:
    def __init__(self, config: PoseDisplayConfig):
        self.config = config
        # 新增：缓存 { shape_id: (QRectF, shape_ref) }
        self.label_rect_cache = {}
```

在 `_draw_labels` 方法中，记录最终绘制的 `rect`（应用偏移后的）：

```python
def _draw_labels(self, painter, items, cfg, scale):
    self.label_rect_cache.clear()  # 清空旧缓存
    if not items:
        return

    # ... 原有字体设置 ...

    for item in items:
        shape = item.shape_ref
        if not getattr(shape, "visible", True):
            continue

        # 应用用户手动拖拽的偏移量
        offset = getattr(shape, "label_offset", [0.0, 0.0])
        final_rect = item.rect.translated(offset[0], offset[1])

        # 缓存当前 shape 的标签框绝对位置，供 Canvas 交互用
        self.label_rect_cache[id(shape)] = (final_rect, shape)

        # ... 后面绘制 final_rect 替代 item.rect ...
        painter.drawRoundedRect(final_rect, 3, 3)
        # 记得引线的终点也要加上偏移量，否则线和框会脱节
        leader_end = item.leader_end + QtCore.QPointF(offset[0], offset[1])
```

## 3. 在 Canvas 中拦截鼠标事件实现拖动

在 `Canvas.py`（继承自 `QWidget` 的画布类）中，增加对标签框的命中测试和拖拽逻辑。

在 `mousePressEvent` 中：

```python
def mousePressEvent(self, ev):
    # 1. 检查是否点击了姿态标签框
    if self.pose_renderer and ev.button() == Qt.LeftButton:
        # 将鼠标屏幕坐标转为图像坐标
        pos = self.transformPos(ev.position())

        # 遍历当前缓存的标签框，看有没有被点中
        for shape_id, (rect, shape) in (
            self.pose_renderer.label_rect_cache.items()
        ):
            if rect.contains(pos):
                # 选中了这个标签！
                self.selected_label_shape = shape
                self.prev_pos = pos
                self.setCursor(Qt.OpenHandCursor)
                return  # 拦截事件，不执行后续 Canvas 默认逻辑

    self.selected_label_shape = None  # 没点中标签
    super().mousePressEvent(ev)
```

在 `mouseMoveEvent` 中处理拖动：

```python
def mouseMoveEvent(self, ev):
    if self.selected_label_shape:
        pos = self.transformPos(ev.position())
        delta = pos - self.prev_pos

        # 累加偏移量到 shape 的属性上
        offset = getattr(
            self.selected_label_shape, "label_offset", [0.0, 0.0]
        )
        self.selected_label_shape.label_offset = [
            offset[0] + delta.x(),
            offset[1] + delta.y(),
        ]

        self.prev_pos = pos
        self.update()  # 触发重绘
        return

    super().mouseMoveEvent(ev)
```

在 `mouseReleaseEvent` 中释放：

```python
def mouseReleaseEvent(self, ev):
    if self.selected_label_shape:
        self.selected_label_shape = None
        self.setCursor(Qt.ArrowCursor)
        self.update()
        return
    super().mouseReleaseEvent(ev)
```

## 4. 保存与加载偏移量

当你保存标注文件时，需要把 `label_offset` 一起存入 JSON。在 `Shape` 转 `dict` 的地方：

```python
# 假设这是 shape 的 points_to_dict 逻辑
data = {
    "label": self.label,
    "points": [...],
    "shape_type": "point",
    "label_offset": getattr(self, "label_offset", [0.0, 0.0]),  # 新增
}
```

加载时反向赋值即可。

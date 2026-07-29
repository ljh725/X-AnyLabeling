# X-AnyLabeling 姿态标签布局优化方案

本方案旨在通过“字号改小、内边距缩减、归一化的四象限侧栏列表”相结合，打造最合理、最清爽的姿态标签展示效果。

## 1. 修改 `pose_config.py`（调整默认参数与新增阈值）

修改 `PoseDisplayConfig` 的默认值，让整体视觉更紧凑，并增加一个缩放隐藏阈值。

在 `PoseDisplayConfig` 类中，修改以下字段的默认值：

```python
# Layout & colouring
layout_mode: str = "column"   # 默认改为 column

# Display parameters (screen-px semantics)
font_size: int = 9            # 从 11 缩小到 9
opacity: float = 0.85
leader_length: int = 15       # 从 40 缩小到 15
border_width: float = 1.0     # 从 1.5 缩小到 1.0
column_gap: int = 4           # 从 8 缩小到 4

# 新增：缩放阈值，低于此缩放比例时隐藏标签
label_zoom_threshold: float = 0.3
```

| 字段 | 原默认值 | 新默认值 | 说明 |
|------|----------|----------|------|
| `layout_mode` | `"anti"` | `"column"` | 默认改为列布局 |
| `font_size` | `11` | `9` | 字号缩小 |
| `leader_length` | `40` | `15` | 引线缩短 |
| `border_width` | `1.5` | `1.0` | 描边变细 |
| `column_gap` | `8` | `4` | 列间距缩小 |
| `label_zoom_threshold` | —（新增） | `0.3` | 缩放低于此值时隐藏标签 |

> 注意：记得在 `to_dict` 和 `from_dict` 方法中加入 `label_zoom_threshold` 的序列化处理。

## 2. 修改 `pose_layout.py`（替换为归一化四象限 Column 布局）

确保文件头有 `import math`，然后用以下代码替换你原来的 `layout_column` 函数。

```python
def layout_column(
    items: List[PoseLabelItem],
    mid: MidLine,
    bbox: Optional[QtCore.QRectF],
    column_gap: float,
) -> List[PoseLabelItem]:
    """Split labels into left / right / top / bottom columns using
    normalized spatial projection."""
    if not items:
        return items
    if bbox is None:
        bbox = _compute_bbox(items)
    if bbox is None:
        return items

    gap = column_gap
    max_w = max(it.rect.width() for it in items)

    left_items: List[PoseLabelItem] = []
    right_items: List[PoseLabelItem] = []
    top_items: List[PoseLabelItem] = []
    bottom_items: List[PoseLabelItem] = []

    center_x = bbox.x() + bbox.width() / 2.0
    center_y = bbox.y() + bbox.height() / 2.0
    half_w = max(bbox.width() / 2.0, 1.0)
    half_h = max(bbox.height() / 2.0, 1.0)

    for item in items:
        dx = item.anchor_x - center_x
        dy = item.anchor_y - center_y
        norm_dx = dx / half_w
        norm_dy = dy / half_h

        if abs(norm_dx) < 0.1 and abs(norm_dy) < 0.1:
            top_items.append(item)
            continue

        angle = math.atan2(norm_dy, norm_dx)

        if -math.pi / 4 <= angle <= math.pi / 4:
            right_items.append(item)
        elif math.pi / 4 < angle <= 3 * math.pi / 4:
            bottom_items.append(item)
        elif angle > 3 * math.pi / 4 or angle <= -3 * math.pi / 4:
            left_items.append(item)
        else:
            top_items.append(item)

    left_items.sort(key=lambda it: it.anchor_y)
    right_items.sort(key=lambda it: it.anchor_y)
    top_items.sort(key=lambda it: it.anchor_y)
    bottom_items.sort(key=lambda it: it.anchor_y)

    bbox_x = bbox.x()
    bbox_y = bbox.y()
    bbox_x2 = bbox.x() + bbox.width()
    bbox_y2 = bbox.y() + bbox.height()

    # 2. 左侧列
    lx = bbox_x - max_w - gap
    cy = bbox_y
    for item in left_items:
        ny = max(item.anchor_y - item.rect.height() / 2.0, cy)
        item.rect.moveTo(int(lx), int(ny))
        item.leader_start = QtCore.QPointF(item.anchor_x - 5, item.anchor_y)
        item.leader_end = QtCore.QPoint(
            item.rect.right(),
            int(item.rect.y() + item.rect.height() / 2.0),
        )
        cy = item.rect.bottom() + gap

    # 3. 右侧列
    rx2 = bbox_x2 + gap
    cy = bbox_y
    for item in right_items:
        ny = max(item.anchor_y - item.rect.height() / 2.0, cy)
        item.rect.moveTo(int(rx2), int(ny))
        item.leader_start = QtCore.QPointF(item.anchor_x + 5, item.anchor_y)
        item.leader_end = QtCore.QPoint(
            item.rect.left(),
            int(item.rect.y() + item.rect.height() / 2.0),
        )
        cy = item.rect.bottom() + gap

    # 4. 顶部列
    tcx = (bbox_x + bbox_x2) / 2.0
    cy = bbox_y
    for i, item in enumerate(top_items):
        col = -1 if i % 2 == 0 else 1
        nx = tcx + col * (max_w / 2.0 + gap / 2.0) - item.rect.width() / 2.0
        ny = cy - item.rect.height() - gap
        item.rect.moveTo(int(nx), int(ny))
        item.leader_start = QtCore.QPointF(item.anchor_x, item.anchor_y - 5)
        item.leader_end = QtCore.QPoint(
            int(item.rect.x() + item.rect.width() / 2.0),
            item.rect.bottom(),
        )
        cy = item.rect.y()

    # 5. 底部列
    bcx = (bbox_x + bbox_x2) / 2.0
    cy = bbox_y2
    for i, item in enumerate(bottom_items):
        col = -1 if i % 2 == 0 else 1
        nx = bcx + col * (max_w / 2.0 + gap / 2.0) - item.rect.width() / 2.0
        ny = cy + gap
        item.rect.moveTo(int(nx), int(ny))
        item.leader_start = QtCore.QPointF(item.anchor_x, item.anchor_y + 5)
        item.leader_end = QtCore.QPoint(
            int(item.rect.x() + item.rect.width() / 2.0),
            item.rect.top(),
        )
        cy = item.rect.bottom()

    return items
```

## 3. 修改 `pose_renderer.py`（缩减内边距与缩放隐藏）

在 `PoseRenderer` 的 `render` 方法开头，加入缩放判断：

```python
cfg = self.config
# 当缩放极小时，强制隐藏标签
if scale < cfg.label_zoom_threshold:
    show_labels = False
```

在 `_build_label_items` 和 `_draw_labels` 方法中修改内边距：

```python
pad_x = 4.0 / scale   # 从 6.0 改为 4.0
pad_y = 1.0 / scale   # 从 2.0 改为 1.0
```

## 4. 修改 `pose_settings_panel.py`（更新 UI 滑块范围）

在 `_build_sliders` 方法中找到 `slider_defs` 列表，修改 `font_size` 的范围：

```python
slider_defs = [
    (
        "font_size",
        self.tr("标签字号"),
        6,                # 最小值从 8 改为 6
        14,               # 最大值从 16 改为 14
        self._config.font_size,
        "",
    ),
    # ... 其他保持不变
]
```

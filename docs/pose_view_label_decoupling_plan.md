# Pose View 与原生标签系统解耦方案

## 背景

当前 `Pose View` 一旦开启（`pose_config.enabled = True`），会在 `Canvas.paintEvent` 中完全接管整张图的所有标签绘制，导致普通矩形、多边形、线条等非姿态 shape 的标签被隐藏。用户反馈这种"分割感"很强，希望 Pose View 只扩展 COCO 关键点的标签显示方式，其余 shape 继续走原生标签系统。

## 目标

1. Pose View 只负责 COCO 关键点的渲染（圆点、骨骼、person bbox、引线标签）。
2. 普通 shape 继续按原生规则显示标签，不受 Pose View 开关影响。
3. COCO 关键点的标签文本受 `label_display_mode` 控制（`label` / `id` / `both`）。
4. Pose View 的样式参数（字号、透明度、描边等）只作用于 pose 标签，不扩散到原生标签。

## 当前行为

```text
if self.show_labels and not self.pose_config.enabled:
    # 原生标签（所有 shape）

if self.pose_config.enabled:
    # PoseRenderer.render() 接管所有 pose 元素 + pose 标签
```

`PoseRenderer.render()` 中 `label_display_mode` 不可配置，关键点固定显示 `shape.label`。

## 改动方案

### 1. `anylabeling/views/labeling/widgets/canvas.py`

#### 1.1 解除原生标签与 Pose View 的互斥

位置：约第 2728 行

```python
# 改前
if self.show_labels and not self.pose_config.enabled:

# 改后
if self.show_labels:
```

#### 1.2 原生标签循环中跳过 COCO 关键点

位置：`Canvas.paintEvent` 中原生标签 shape 循环开头

```python
if shape.label in COCO_KEYPOINT_SET:
    continue
```

避免关键点同时被原生逻辑和 PoseRenderer 各画一次。

#### 1.3 PoseRenderer 调用传入 `label_display_mode`

位置：约第 2925 行

```python
count = self._pose_renderer.render(
    p,
    self.shapes,
    self.pixmap.size(),
    self.scale,
    show_labels=True,
    label_display_mode=self.label_display_mode,
    label_on_selection=True,
    hovered_group_id=None,
    zoom_reveals=False,
)
```

### 2. `anylabeling/views/labeling/widgets/pose_label/pose_renderer.py`

#### 2.1 `PoseRenderer.render()` 新增 `label_display_mode` 参数

```python
def render(
    self,
    painter: QtGui.QPainter,
    shapes: List[Any],
    pixmap_size: QtCore.QSize,
    scale: float,
    show_labels: bool = True,
    label_display_mode: str = "label",
    label_on_selection: bool = False,
    hovered_group_id: Optional[int] = None,
    zoom_reveals: bool = False,
) -> int:
```

#### 2.2 `_build_label_items()` 使用 `label_display_mode` 生成显示文本

在构造 `PoseLabelItem` 时，按模式计算 `display_text`：

```python
group_id = getattr(shape, "group_id", None)

if label_display_mode == "id":
    display_text = str(group_id) if group_id is not None else ""
elif label_display_mode == "both":
    display_text = f"{shape.label} #{group_id}" if group_id is not None else shape.label
else:  # "label"
    display_text = shape.label
```

并用 `display_text` 计算文字矩形：

```python
text_rect = fm.tightBoundingRect(display_text)
```

### 3. `anylabeling/views/labeling/widgets/pose_label/pose_layout.py`

无需改动。三种布局方式（`direct` / `anti` / `column`）继续生效。

## 行为变化

| 场景 | 改前 | 改后 |
|------|------|------|
| Pose View 开启，普通矩形/多边形 | 无标签 | 显示原生标签 |
| Pose View 开启，COCO 关键点 | 显示 pose 标签（仅名称） | 显示 pose 标签，受 `label_display_mode` 控制 |
| `label_display_mode == "id"` | 关键点仍显示名称 | 关键点显示 `group_id` |
| `label_display_mode == "both"` | 关键点仍显示名称 | 关键点显示 `名称 #group_id` |
| `show_labels` 关闭 | 所有标签隐藏 | 所有标签隐藏（不变） |
| Pose View 样式参数 | 影响所有标签 | 只影响 pose 标签 |

## 风险与边界

1. **非 COCO 的 `point` shape**：如果与 COCO 关键点坐标重合但 label 不同，原生标签和 pose 圆点可能叠加。这是预期行为，因为它不是 pose 关键点。
2. **Person 矩形框**：原生规则会在 bbox 左上角画 `person` 标签，PoseRenderer 会画 bbox 矩形，两者叠加可接受。
3. **`label_on_selection` 语义差异**：原生规则作用于单个 shape，PoseRenderer 当前作用于整个 group。本期保留差异，不做统一。

## 测试更新

| 文件 | 调整内容 |
|------|----------|
| `tests/test_canvas_interaction.py` | `test_should_draw_standard_label_hides_when_pose_view_on` 预期需改为"非 COCO shape 仍显示原生标签" |
| `tests/test_feature_interactions.py` | 若 `test_alt_h_noop_in_pose_view` 涉及标签断言，需同步调整 |

## 实施步骤

1. 修改 `pose_renderer.py`：新增 `label_display_mode` 参数并应用到 `_build_label_items()`。
2. 修改 `canvas.py`：解除互斥、跳过 COCO 关键点、传入 `label_display_mode`。
3. 更新相关单元测试。
4. 运行 `pytest` 验证行为。
5. 运行 `black` 与 `flake8` 格式化检查。

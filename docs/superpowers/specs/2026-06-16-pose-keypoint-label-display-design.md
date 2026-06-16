# Pose 关键点标签显示重构设计

> 源文件：`html-case/0616_code.html`  
> 目标框架：PyQt6（X-AnyLabeling 4.0.0-beta.4）  
> 创建时间：2026-06-16  
> 状态：架构已确认，待评审完整设计

---

## 1. 需求与决策摘要

### 1.1 最终视觉风格

采用 HTML 原型 `0616_code.html` 的实心彩色矩形标签风格：

- 每个关键点标签是一个填充色块（标签底色跟随关键点颜色）
- 文字内嵌在色块中，支持白/黑/自动/黄/自定义字体颜色
- 可选文字阴影、边框、透明度

**因此，昨日方案 `docs/keypoint_label_display_optimization.md`（描边文字、无背景）作废。**

### 1.2 功能范围：Tier 3 — 完整原型功能对齐

实现 HTML 原型的全部功能：

| 功能组 | 内容 |
|--------|------|
| 布局模式 | `direct`（方向引线）、`anti`（防遮挡）、`column`（侧栏列表） |
| 着色模式 | `bodypart`（按部位 5 色）、`person`（按目标） |
| 显示参数 | 标签字号、透明度、引线长度、描边宽度、列间距 |
| 显示选项 | 骨骼连线、中线参考、目标框、遮挡高亮、引线、文字阴影 |
| 字体颜色 | white / black / auto / yellow / custom |
| 颜色面板 | 部位颜色调整、目标颜色、颜色预设（default/pastel/neon/earth） |
| 遮挡统计 | 遮挡对数徽标 |

### 1.3 集成架构：纯模块 + Canvas 直集成

不建独立原型窗口，直接以可单元测试的纯模块落地，再接入现有 `Canvas`。

---

## 2. 整体架构与模块结构

```
anylabeling/views/labeling/widgets/pose_label/
├── __init__.py
├── pose_constants.py      # COCO 17 关键点、部位分组、骨骼边、颜色预设
├── pose_config.py         # PoseDisplayConfig dataclass（所有可调参数 + 默认值）
├── pose_layout.py         # 3 种布局算法：direct / anti / column（纯函数）
├── pose_renderer.py       # PoseRenderer：输入 QPainter + shapes + config → 绘制全部
├── pose_settings_panel.py # QFrame 面板：布局/着色模式、滑块、显示开关
└── pose_color_panel.py    # QFrame 面板：部位/目标颜色、预设、字体颜色
```

> **集成方式说明（§7.1 确认结果）**：`LabelingWidget` 继承自 `LabelDialog`（`QWidget`），
> 不是 `QMainWindow`，**不能使用 `QDockWidget` / `addDockWidget()`**。
> 现有 UI 是手写的 `QHBoxLayout`：左 toolbar + 中央 canvas + 右侧 `right_sidebar_layout`（`QVBoxLayout`）。
> 现有侧边面板（如 `display_mode_panel`、`insp_panel`）均为 `QFrame` +
> `setObjectName("sidebarPanel")` + `get_panel_style()` 样式。
> 本设计沿用同一模式，将 pose 面板以 `QFrame` 插入 `right_sidebar_layout`。

### 2.1 数据流

```
用户操作侧栏面板
       ↓ 更新
PoseDisplayConfig（内存单例，与 Canvas 共享）
       ↓ 触发
Canvas.update() → paintEvent
       ↓ 检测 pose_config.enabled
PoseRenderer.render(painter, self.shapes, config, pixmap_size, scale)
       ↓ 按 group_id 分组
对每个 person 组：
  1. 计算中线 mid + 包围盒 bbox
  2. 绘制 bbox / midline / skeleton（按开关）
  3. 构建 PoseLabelItem 列表
  4. 调用 pose_layout（根据 layout_mode 选 direct/anti/column）
  5. 绘制关键点圆点
  6. 绘制引线 + 实心彩色矩形标签 + 内嵌文字（+阴影）
       ↓ 返回
occlusion_count → 信号 → 更新遮挡统计徽标
```

### 2.2 设计原则

- `pose_constants.py` / `pose_layout.py` / `pose_config.py` **零 QWidget 依赖**，可独立单元测试。
- `pose_renderer.py` 只依赖 `QPainter` + `QtCore`，不依赖 `Canvas` 类。
- `canvas.py` 改动最小：加一个 `if pose_config.enabled` 分支调用 renderer，跳过 COCO 关键点 point 标签的原有渲染。
- 两个 `QFrame` 面板读写同一个 `PoseDisplayConfig` 实例，插入 `LabelingWidget` 的 `right_sidebar_layout`。

---

## 3. 数据层：`pose_constants.py`

定义 COCO 17 关键点语义、部位分组、骨骼边、颜色预设。项目当前没有统一部位分组，需要新建。

```python
COCO_KEYPOINT_ORDER: List[str] = [
    "nose", "l_eye", "r_eye", "l_ear", "r_ear",
    "l_sho", "r_sho", "l_elb", "r_elb", "l_wri",
    "r_wri", "l_hip", "r_hip", "l_knee", "r_knee",
    "l_ank", "r_ank",
]

COCO_KEYPOINT_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate(COCO_KEYPOINT_ORDER)
}

BODY_PARTS: Dict[str, List[str]] = {
    "head": ["nose", "l_eye", "r_eye", "l_ear", "r_ear"],           # 0-4
    "la":   ["l_sho", "l_elb", "l_wri"],                           # 5,7,9
    "ra":   ["r_sho", "r_elb", "r_wri"],                           # 6,8,10
    "ll":   ["l_hip", "l_knee", "l_ank"],                          # 11,13,15
    "rl":   ["r_hip", "r_knee", "r_ank"],                          # 12,14,16
}

LABEL_TO_BODY_PART: Dict[str, str] = {
    label: part
    for part, labels in BODY_PARTS.items()
    for label in labels
}

SKELETON_EDGES: List[Tuple[int, int]] = [
    (0, 1), (0, 2), (1, 3), (2, 4),   # head
    (5, 6), (5, 7), (7, 9),            # left arm + shoulders
    (6, 8), (8, 10),                   # right arm
    (5, 11), (6, 12), (11, 12),        # torso
    (11, 13), (13, 15),                # left leg
    (12, 14), (14, 16),                # right leg
]

DEFAULT_BODY_COLORS: Dict[str, str] = {
    "head": "#e74c3c",
    "la":   "#3498db",
    "ra":   "#9b59b6",
    "ll":   "#2ecc71",
    "rl":   "#f39c12",
}

DEFAULT_PERSON_COLORS: List[str] = ["#e74c3c", "#3498db", "#2ecc71"]

COLOR_PRESETS: Dict[str, Dict[str, str]] = {
    "default": {
        "head": "#e74c3c", "la": "#3498db", "ra": "#9b59b6",
        "ll": "#2ecc71", "rl": "#f39c12",
    },
    "pastel": {
        "head": "#f5a5a5", "la": "#a5c8f5", "ra": "#c8a5f5",
        "ll": "#a5f5c8", "rl": "#f5d5a5",
    },
    "neon": {
        "head": "#ff0055", "la": "#00ccff", "ra": "#cc00ff",
        "ll": "#00ff88", "rl": "#ffaa00",
    },
    "earth": {
        "head": "#c0755a", "la": "#5a8fc0", "ra": "#8f5ac0",
        "ll": "#5ac075", "rl": "#c09a5a",
    },
}
```

### 3.1 关于 KEYPOINT_ORDER 重复定义的说明

项目当前在 `keypoint_fill_mode.py`、`keypoint_tool_window.py`、`inspector/validation_engine.py`、`inspector/rule_config_widget.py`、`inspector/inspector_panel.py` 中重复定义了同样的 17 个标签。本模块将提供权威定义，后续可逐步用 `from pose_constants import COCO_KEYPOINT_ORDER` 替换。但本次实施**不强制重构这些文件**，只新增公共定义。

---

## 4. 配置层：`pose_config.py`

```python
@dataclass
class PoseDisplayConfig:
    """Pose 标签显示参数。"""

    # 主开关
    enabled: bool = False

    # 布局与着色
    layout_mode: str = "anti"           # direct / anti / column
    color_mode: str = "bodypart"        # bodypart / person

    # 显示参数
    font_size: int = 11
    opacity: float = 0.85
    leader_length: int = 40
    border_width: float = 1.5
    column_gap: int = 8

    # 显示开关
    show_skeleton: bool = True
    show_midline: bool = False
    show_bbox: bool = True
    occlusion_highlight: bool = True
    show_leader: bool = True
    font_shadow: bool = True

    # 字体颜色
    font_color_mode: str = "white"      # white / black / auto / yellow / custom
    custom_font_color: str = "#00ff88"

    # 颜色
    body_colors: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_BODY_COLORS)
    )
    person_colors: List[str] = field(
        default_factory=lambda: list(DEFAULT_PERSON_COLORS)
    )
    color_preset: str = "default"

    # 统计
    occlusion_count: int = 0
```

### 4.1 持久化映射

这些字段将对应写入 `anylabeling/configs/xanylabeling_config.yaml` 和 `anylabeling/views/labeling/settings/schema.py`。具体键名见 §8。

---

## 5. 布局引擎：`pose_layout.py`

### 5.1 数据结构

```python
@dataclass
class PoseLabelItem:
    """单个关键点标签候选。"""

    shape_ref: object              # Shape 实例
    label: str                     # 关键点标签文本
    keypoint_index: int            # 0-16
    group_id: Optional[int]
    anchor: QtCore.QPointF         # 关键点坐标
    rect: QtCore.QRect             # 标签矩形（图像坐标）
    direction: str = "up"          # up / left / right / left-up / ...
    leader_start: QtCore.QPointF = field(default_factory=QtCore.QPointF)
    leader_end: QtCore.QPoint = field(default_factory=QtCore.QPoint)
    occluded: bool = False
```

### 5.2 布局算法

| 模式 | 函数 | 行为 |
|------|------|------|
| `direct` | `layout_direct(items, mid, config)` | 沿关键点身体方向直接外放标签，引线长度 = `leader_length` |
| `anti` | `layout_anti(items, mid, config)` | `direct` 基础上，当标签重叠时沿方向继续外推；仍冲突则上下微移 |
| `column` | `layout_column(items, mid, bbox, config)` | 按身体左右/顶部分栏，垂直堆叠在 bbox 两侧 |

### 5.3 方向计算（基于 HTML `compDir`）

1. 计算身体中线 `mid`：优先由左肩（5）+ 右肩（6）中点得到；缺失时取鼻子（0）。
2. 计算关键点相对中线的水平偏移 `rx = keypoint.x - mid.mx`。
3. 根据 `rx` 和身体区域（头/上肢/下肢）确定方向：
   - `|rx| <= threshold`：垂直方向（`up` / `down`）
   - `rx < 0`：左侧，头为 `left-up`，下肢为 `left-down`，其余为 `left`
   - `rx > 0`：右侧，头为 `right-up`，下肢为 `right-down`，其余为 `right`

### 5.4 与现有 `keypoint_label_layout.py` 的关系

现有防遮挡算法保持不动，仅用于 `pose_config.enabled == False` 的旧路径。启用 pose view 后，统一由 `pose_layout.py` 接管布局。

---

## 6. 渲染器：`pose_renderer.py`

```python
class PoseRenderer:
    """将 pose 关键点组渲染到 QPainter 上。"""

    def __init__(self, config: PoseDisplayConfig):
        self.config = config

    def render(
        self,
        painter: QtGui.QPainter,
        shapes: List[Any],
        pixmap_size: QtCore.QSize,
        scale: float,
    ) -> int:
        """渲染所有 pose 标注，返回遮挡对数。"""
```

### 6.1 坐标系与缩放语义（§7.2 确认结果）

`Canvas.paintEvent` 在 `canvas.py:2176` 执行 `p.scale(self.scale, self.scale)`，
painter 后续所有绘制自动乘以 `scale`。现有标签渲染在 `canvas.py:2680` 用
`font_size / Shape.scale` 反向补偿，使屏幕字号视觉恒定。

**PoseRenderer 沿用同一规则，不做额外的 `painter.scale()`**（调用方 painter 已缩放）：

| 元素 | 坐标系 | 说明 |
|------|--------|------|
| 关键点坐标、bbox、骨骼端点、中线 | 图像坐标 | painter 自动缩放 |
| 引线起点/终点 | 图像坐标 | painter 自动缩放 |
| 标签字号 `font_size` | `/ scale` 补偿 | `QFont("...", config.font_size / scale)` |
| 标签 padding | `/ scale` 补偿 | `padding_x / scale, padding_y / scale` |
| 描边宽度 `border_width` | `/ scale` 补偿 | `QPen(..., config.border_width / scale)` |
| 引线长度 `leader_length` | `/ scale` 补偿 | 布局参数传 `config.leader_length / scale` |
| 关键点半径 | `/ scale` 补偿 | `drawEllipse` 半径 `5 / scale` |

这样在任意缩放级别下，标签字号、间距、引线长度的**屏幕像素恒定**，
只有几何位置（关键点、骨骼）随缩放变化。

### 6.2 渲染流程

```
# NOTE: 不调用 painter.scale() — Canvas.paintEvent 已在 line 2176 缩放过 painter
# 所有 / scale 补偿在绘制字号/线宽/padding 时逐项处理

person_groups = group_shapes_by_person(shapes)
occlusion_count = 0

for group_id, group in person_groups.items():
    person_rect = find_person_rectangle(group)
    keypoints = find_keypoint_points(group)
    mid = compute_midline(keypoints)
    person_color = get_person_color(group_id)

    if config.show_bbox and person_rect:
        draw_bbox(person_rect, color)
    if config.show_midline and mid:
        draw_midline(mid, keypoints)
    if config.show_skeleton:
        draw_skeleton(keypoints, color_mode)

    items = build_label_items(keypoints, mid, config)
    items = apply_layout(items, mid, bbox, config)
    occlusion_count += count_overlaps(items)
    mark_occluded(items)

    draw_keypoints(keypoints, color_mode)
    draw_labels(items)      # 引线 → 背景 → 边框 → 阴影 → 文字

return occlusion_count
```

### 6.3 绘制层级

从下到上：

1. 目标框 / 中线 / 骨骼
2. 关键点圆点
3. 引线（`show_leader`）
4. 标签背景填充色
5. 标签边框（`border_width > 0`）
6. 文字阴影（`font_shadow`）
7. 文字本体

### 6.4 颜色规则

| color_mode | 关键点颜色 | 标签背景颜色 |
|------------|-----------|-------------|
| `bodypart` | `DEFAULT_BODY_COLORS[body_part]` | 同上 |
| `person`   | `person_colors[group_id % len(person_colors)]` | 同上 |

遮挡高亮开启时，发生重叠的标签背景额外叠加半透明错误色（HTML 用 `#f38ba8` 30% 透明度）。

### 6.5 字体颜色

| font_color_mode | 实现 |
|-----------------|------|
| `white` | `#ffffff` |
| `black` | `#000000` |
| `auto`  | 基于背景亮度：亮度 ≥ 128 用黑，否则用白 |
| `yellow`| `#ffff00` |
| `custom`| `config.custom_font_color` |

---

## 7. Canvas 集成

### 7.1 `Canvas` 新增属性

```python
class Canvas(QWidget):
    # 新增信号
    pose_occlusion_count_changed = pyqtSignal(int)

    def __init__(...):
        # 新增：从 config 加载 PoseDisplayConfig
        self.pose_config = PoseDisplayConfig(...)
        self._pose_renderer = PoseRenderer(self.pose_config)
```

### 7.2 标签渲染覆盖规则（§7.3 确认结果）

现有标签渲染在 `canvas.py:2711` 的 `for shape in self.shapes:` 循环中处理
**所有** shape 类型（rectangle / polygon / circle / line / linestrip / point）。

**Pose View 启用时的精确覆盖规则**：

| shape 类型 | pose view ON | pose view OFF |
|-----------|-------------|---------------|
| `point` 且 `label ∈ COCO_KEYPOINT_ORDER` | **跳过原有渲染**，由 `PoseRenderer` 全权处理（骨骼、关键点圆点、标签、引线） | 原有渲染路径 |
| `point` 但 label 不在 COCO 列表（自定义点） | 原有渲染路径不变 | 原有渲染路径 |
| `rectangle`（含 person 框） | **跳过 person 框标签**（由 PoseRenderer 的 `show_bbox` 接管）；非 person 矩形标签正常渲染 | 原有渲染路径 |
| `polygon` / `circle` / `rotation` / `line` / `linestrip` | 原有渲染路径不变 | 原有渲染路径 |

**实现方式**：在 `canvas.py:2711` 循环内增加过滤条件：

```python
for shape in self.shapes:
    # ... 现有可见性检查 ...

    # Pose View 过滤：跳过 COCO 关键点 point 标签
    if (
        self.pose_config.enabled
        and shape.shape_type == "point"
        and shape.label in COCO_KEYPOINT_ORDER
    ):
        continue

    # Pose View 过滤：跳过 person 矩形标签（标签文字 "person" 的 rectangle）
    if (
        self.pose_config.enabled
        and shape.shape_type == "rectangle"
        and shape.label == "person"
        and shape.group_id is not None
    ):
        continue  # bbox 由 PoseRenderer 按 show_bbox 开关绘制

    # ... 原有标签位置计算 ...
```

然后在现有标签渲染循环**之后**（约 `canvas.py:2988` 附近），插入 PoseRenderer 调用：

```python
# 现有标签渲染完毕后，绘制 pose overlay
if self.pose_config.enabled and self._has_pose_shapes():
    count = self._pose_renderer.render(
        p, self.shapes, self.pixmap.size(), self.scale
    )
    if count != self.pose_config.occlusion_count:
        self.pose_config.occlusion_count = count
        self.pose_occlusion_count_changed.emit(count)
```

> **注意**：PoseRenderer 不做 `painter.save()/restore()` 或 `painter.scale()`，
> 因为调用方的 painter 已在 `canvas.py:2176` 处于缩放状态。Renderer 直接在
> 已缩放的 painter 上绘制图像坐标内容，字号/线宽逐项 `/ scale` 补偿。

### 7.3 启用条件

`_has_pose_shapes()` 的判定：

```python
def _has_pose_shapes(self):
    if not self.shapes:
        return False
    return any(
        s.shape_type == "point" and s.label in COCO_KEYPOINT_ORDER
        for s in self.shapes
    )
```

### 7.4 与现有菜单开关的关系

| 现有菜单 | pose view off | pose view on |
|----------|---------------|--------------|
| `label_on_selection` | 生效 | 忽略（pose view 下按 pose 规则显示） |
| `keypoint_label_spread` | 生效 | 忽略（由 pose_layout_mode 接管） |
| `keypoint_label_leader_line` | 生效 | 忽略（由 pose_show_leader 接管） |
| `label_display_mode` | 生效 | 忽略（pose 标签统一显示 label） |

### 7.5 交互复用

平移、缩放、选择、拖动关键点复用 `Canvas` 已有实现，无需改动。

---

## 8. 侧栏面板（QFrame，非 QDockWidget）

### 8.1 为什么不用 QDockWidget

| 条件 | 事实 |
|------|------|
| `LabelingWidget` 父类 | `LabelDialog` → `QWidget`（**不是** `QMainWindow`） |
| `LabelingWrapper` 父类 | `QWidget` |
| `MainWindow` 父类 | `QMainWindow`（但只是薄壳，不含标注逻辑） |
| 现有侧边面板模式 | `QFrame` + `setObjectName("sidebarPanel")` + `get_panel_style()` |

`QDockWidget` 只能添加到 `QMainWindow`。如果加到外层 `MainWindow`，所有信号/回调
需要穿透 `MainWindow` → `LabelingWrapper` → `LabelingWidget` 三层，严重破坏封装性。
因此**沿用现有 `QFrame` 面板模式**，将 pose 面板插入 `right_sidebar_layout`。

### 8.2 `PoseSettingsPanel`

分组内容：

- **布局模式**：`direct` / `anti` / `column` 单选
- **着色模式**：`bodypart` / `person` 单选
- **显示参数**：
  - 标签字号（8-16）
  - 标签透明度（0.30-1.00）
  - 引线长度（15-80）
  - 描边宽度（0-4）
  - 列间距（4-30，仅 column 模式生效）
- **显示选项**：骨骼连线、中线参考、目标框、遮挡高亮、引线、文字阴影复选框

### 8.3 `PoseColorPanel`

分组内容：

- **字体颜色**：white / black / auto / yellow / custom 单选；custom 时显示 `QColorDialog` 触发按钮
- **部位颜色调整**：head / la / ra / ll / rl 五个颜色选择器 + 预览块
- **目标颜色调整**：为每个已出现的 group_id 提供颜色选择器
- **颜色预设**：default / pastel / neon / earth 按钮

### 8.4 与 `LabelingWidget` 的集成

在 `label_widget.py` 的 `__init__` 中（`right_sidebar_layout` 构建区域，约 line 2667-2898），
参照 `display_mode_panel`（line 2687-2737）和 `insp_panel`（line 2890-2894）的模式：

```python
# 在 right_sidebar_layout 构建区域，display_mode_panel 之后插入：
self.pose_settings_panel = PoseSettingsPanel(
    config=self.pose_config, parent=self
)
self.pose_settings_panel.setObjectName("sidebarPanel")
self.pose_settings_panel.setStyleSheet(get_panel_style())
self.pose_settings_panel.setVisible(self.pose_config.enabled)
right_sidebar_layout.addWidget(self.pose_settings_panel)

self.pose_color_panel = PoseColorPanel(
    config=self.pose_config, parent=self
)
self.pose_color_panel.setObjectName("sidebarPanel")
self.pose_color_panel.setStyleSheet(get_panel_style())
self.pose_color_panel.setVisible(self.pose_config.enabled)
right_sidebar_layout.addWidget(self.pose_color_panel)
```

面板控件变化时：
1. 更新 `self.pose_config` 对应字段
2. 调用 `self.canvas.update()` 触发重绘
3. 可选：调用 `self.set_dirty()` 标记配置变更

Pose View 开关切换时：
- `pose_config.enabled = True` → `panel.setVisible(True)`
- `pose_config.enabled = False` → `panel.setVisible(False)`

---

## 9. 配置持久化

### 9.1 新增配置键（`xanylabeling_config.yaml`）

```yaml
pose_view:
  enabled: false
  layout_mode: "anti"
  color_mode: "bodypart"
  font_size: 11
  opacity: 0.85
  leader_length: 40
  border_width: 1.5
  column_gap: 8
  show_skeleton: true
  show_midline: false
  show_bbox: true
  occlusion_highlight: true
  show_leader: true
  font_shadow: true
  font_color_mode: "white"
  custom_font_color: "#00ff88"
  body_colors:
    head: "#e74c3c"
    la: "#3498db"
    ra: "#9b59b6"
    ll: "#2ecc71"
    rl: "#f39c12"
  person_colors:
    - "#e74c3c"
    - "#3498db"
    - "#2ecc71"
  color_preset: "default"
```

### 9.2 schema.py 注册

在 `anylabeling/views/labeling/settings/schema.py` 的 `ConfigSchema` 中为上述键添加类型/默认值定义。

---

## 10. 菜单与快捷键

- **View 菜单**新增：
  - `Pose View`：复选框，切换 `pose_config.enabled`
  - 启用时自动显示两个侧栏面板（`setVisible(True)`）；禁用时隐藏
- 可选快捷键：`Ctrl+Shift+P`（Toggle Pose View）

---

## 11. 测试策略

### 11.1 单元测试

```bash
pytest tests/views/labeling/widgets/pose_label/
```

测试覆盖：

- `pose_constants.py`：验证索引、部位分组、骨骼边一致性
- `pose_config.py`：序列化/反序列化
- `pose_layout.py`：
  - `direct` 在中心线两侧产生正确方向
  - `anti` 能消除 N 个标签的简单重叠
  - `column` 在 bbox 两侧产生合理列
- `pose_renderer.py`：
  - 遮挡计数正确
  - 标签颜色按部位/目标分配正确

### 11.2 手动验收清单

- [ ] point 标签为实心彩色矩形，文字内嵌
- [ ] bodypart 模式下身部位颜色正确（头红、左臂蓝、右臂紫、左腿绿、右腿橙）
- [ ] person 模式下同一 group_id 颜色一致
- [ ] anti 模式标签重叠明显减少
- [ ] column 模式标签按左右/顶部成列
- [ ] 引线可见，不被背景覆盖
- [ ] 缩放时标签字号视觉恒定
- [ ] 浅色关键点（黄/青/绿）字体可读（auto 模式切黑）
- [ ] 深色关键点（蓝/红/黑）字体可读（auto 模式切白）
- [ ] line/linestrip/rectangle/polygon 标签在 pose view 关闭时完全不变
- [ ] 颜色预设一键生效
- [ ] 遮挡统计徽标实时更新

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| `canvas.py` 继续膨胀 | 维护困难 | 全部 pose 逻辑封装到 `pose_renderer.py`，canvas 只留 10-20 行调用 |
| 布局算法 O(N²) 性能问题 | 密集人群场景卡顿 | 按 group_id 独立布局，O(person_size²)；缓存布局结果帧间复用 |
| 用户标签名不标准 | 部位着色失效 | 支持简写、全拼、自定义别名三种映射；无法映射时回退到 group 颜色 |
| 旧配置兼容 | schema 校验失败 | schema.py 全部给默认值 |
| 与现有 `label_on_selection` 等开关冲突 | 行为不一致 | pose view 启用时明确覆盖旧开关，UI 上禁用或提示 |

---

## 13. 实现顺序（草案）

1. **M1**：`pose_constants.py` + `pose_config.py` + 配置 schema
2. **M2**：`pose_layout.py`（3 种布局）+ 单元测试
3. **M3**：`pose_renderer.py`（不含面板）+ 单元测试
4. **M4**：`canvas.py` 接入 + 菜单开关
5. **M5**：`pose_settings_panel.py` + `pose_color_panel.py`
6. **M6**：持久化、i18n、手动验收

---

## 14. 已确认问题与遗留问题

### 14.1 已确认（本次评审解决）

| 问题 | 结论 |
|------|------|
| Dock 集成方式 | **不用 `QDockWidget`**。`LabelingWidget` 是 `QWidget` 不是 `QMainWindow`。改用 `QFrame` 面板插入 `right_sidebar_layout`，与 `display_mode_panel`、`insp_panel` 同模式。 |
| 字号与缩放语义 | Painter 已在 `canvas.py:2176` 缩放。几何元素用图像坐标（自动缩放），字号/padding/线宽逐项 `/ scale` 补偿（屏幕像素恒定）。Renderer **不做额外 `painter.scale()`**。 |
| 旧标签渲染覆盖规则 | Pose View ON 时：跳过 COCO keypoint point 标签 + person 矩形标签的原有渲染；非 pose 图形（polygon/line/circle/普通 rectangle）正常渲染。PoseRenderer 在原有标签循环之后调用。 |

### 14.2 遗留问题（实现时再定）

1. 骨骼连线是否在 pose view 关闭时仍可独立显示？还是完全绑定 pose view？
2. 颜色预设是否也保存为目标颜色（per-person）？还是只影响部位颜色？
3. 是否需要"导出/导入颜色方案"功能？（HTML 原型未涉及）
4. 面板默认折叠/展开状态：初始可见还是折叠收起？

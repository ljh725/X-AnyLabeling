# 05 · Pose View 标签解耦
#### Pose View Label Decoupling & Layout

> filter-driven 单字段解耦架构：用 `pose_focus_group_id` 一个字段驱动标签列表与选中焦点的解耦，4 种防遮挡布局算法，总览/选中两态显示。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

原版 X-AnyLabeling 开启 Pose View 后，`PoseRenderer.render()` 会**完全接管整张图**所有标签的渲染，导致两个严重问题：

**痛点 1：视觉分割感**
```
原版 Pose View 开启后：           期望效果：
┌────────────────────┐            ┌────────────────────┐
│   ┌─[骨架+关键点]  │            │ person ┌─[骨架]   │
│   │   (只有骨架)    │            │ ┌───┐  │  (共存)   │
│   │                 │            │ │car│  │          │
│   │  (矩形/多边形    │            │ └───┘  │          │
│   │   被隐藏!)       │            │        └──...     │
└────────────────────┘            └────────────────────┘
```
普通矩形/多边形/线条标签被隐藏，只能看到骨架，标注员无法同时核对其他标签。

**痛点 2：选中态污染**
选中某人（聚焦）会触发原生标签流程的 `selection_changed`，污染普通标签的选中状态，导致副作用。

---

## 方案：filter-driven 解耦架构

### 核心设计：单一字段驱动两态切换

用 `canvas.pose_focus_group_id` **一个字段**驱动总览/选中两态切换：

```python
# 概念示意（实际分散在 canvas.py 的多个方法中）
def _apply_group_focus(self, gid):
    """聚焦到某个 person 的 group_id"""
    self.pose_focus_group_id = gid
    self.update()  # 触发重绘

def show_all_instances(self):
    """退出聚焦，显示所有人（总览态）"""
    self.pose_focus_group_id = None
    self.update()
```

这把"标签列表"（原生 shape 列表）与"选中焦点"（pose 聚焦）解耦——**Pose View 修改聚焦态不触碰原生 selection 流程**。

### 按 shape 类型过滤（而非模式切换）

让 Pose View 与原生标签**共存**，而非二选一：

```python
def _should_draw_standard_label(self, shape):
    """只有 COCO 关键点标签才交给 PoseRenderer，其余走原生绘制"""
    if shape.label in COCO_KEYPOINT_SET:
        return False  # PoseRenderer 处理
    return True       # 原生绘制循环处理
```

原生绘制循环跳过 `label=="person"` 矩形（避免与 PoseRenderer 的分色 bbox 双绘），但 person 文字标签仍走原生。

---

## 技术亮点

### 1. 总览/选中两态显示

| 维度 | 总览态（focus=None） | 选中态（聚焦某人） |
|------|---------------------|-------------------|
| 颜色 | 强制 person 分色（临时换色 save/restore） | 面板配置的 color_mode |
| bbox | 显示（分色，快速识别人数） | 按 cfg.show_bbox |
| 骨架/中线 | 隐藏（简化视觉） | 显示（按配置） |
| 关键点标签 | 隐藏 | 显示（受 label_display_mode） |

总览态让标注员快速看到"图里有几个人、分布如何"；选中态聚焦单人细节（骨架+标签+引线）。降低密集人群标注的视觉负荷。

### 2. 4 种防遮挡布局算法

关键点标签互相遮挡、盖住骨架是姿态标注的顽疾。实现 4 种布局算法（纯函数，可独立单测）：

| 布局 | 算法 | 适用场景 |
|------|------|---------|
| **direct** | 沿身体方向外放，无碰撞处理 | 稀疏场景 |
| **anti** | direct + 优先级排序 + 沿方向外推消重叠（O(N²)） | 中等密度 |
| **column** | 归一化四象限分区，bbox 左右两侧垂直堆叠 | 高密度 |
| **category** | 按部位分组（head/arm/leg）绕 bbox 排布 | 按部位审查 |

彩色实心标签 + 引线连接，HTML 原型级渲染质量。

### 3. 纯模块优先原则

`pose_label/` 子包遵循"纯模块优先"——底层模块零 QWidget 依赖：

```
pose_label/
├── pose_constants.py    173行  COCO 17点/部位/骨骼/颜色预设（零 Qt）
├── pose_config.py       156行  PoseDisplayConfig dataclass + 序列化（零 Qt）
├── pose_layout.py       454行  3种布局算法纯函数（零 Qt）
├── pose_category_layout 342行  第4种category布局（自包含）
├── pose_renderer.py     475行  QPainter 渲染管线
├── pose_settings_panel  296行  设置面板
├── pose_color_panel.py  250行  颜色面板
├── pose_view_panel.py    68行  QDockWidget 容器
└── __init__.py           58行  包导出
```

`pose_constants`/`pose_config`/`pose_layout` 可在无 GUI 环境独立单测。

### 4. 事件来源区分（R3 修复）

filter-driven 架构下必须显式区分"用户操作"与"程序触发"的事件。一个典型案例：

**问题**：进入 Keypoint Fill 模式（按 K）时，画布会发程序性空选中 `selection_changed([])`，被 `_pose_focus_on_selection` 误判为"用户点空白退出聚焦"而清空聚焦。

**方案**：用 `keypoint_fill_mode.is_active` 守卫——Keypoint Fill 激活时整体跳过 pose 聚焦逻辑。

```python
# 概念示意
def _pose_focus_on_selection(self, selection):
    if self.keypoint_fill_mode.is_active:  # 程序性触发，跳过
        return
    # 用户操作，正常处理聚焦
    ...
```

这是 filter-driven 架构下"事件来源区分"必须显式处理的体现。

### 5. 配置全持久化

21 项 `pose_view.*` 配置键存入 `~/.xanylabelingrc`，跨会话稳定：布局模式、着色模式、字体色、部位色、目标色、预设、显示开关等。

---

## 代码定位

| 文件 | 行数 | 职责 |
|------|------|------|
| [`pose_label/pose_renderer.py`](../../anylabeling/views/labeling/widgets/pose_label/pose_renderer.py) | 475 | QPainter 渲染管线 |
| [`pose_label/pose_layout.py`](../../anylabeling/views/labeling/widgets/pose_label/pose_layout.py) | 454 | 3 种布局算法（direct/anti/column） |
| [`pose_label/pose_category_layout.py`](../../anylabeling/views/labeling/widgets/pose_label/pose_category_layout.py) | 342 | category 布局 |
| [`pose_label/pose_settings_panel.py`](../../anylabeling/views/labeling/widgets/pose_label/pose_settings_panel.py) | 296 | 设置面板 |
| [`pose_label/pose_color_panel.py`](../../anylabeling/views/labeling/widgets/pose_label/pose_color_panel.py) | 250 | 颜色面板 |
| [`pose_label/pose_constants.py`](../../anylabeling/views/labeling/widgets/pose_label/pose_constants.py) | 173 | COCO 17 点/骨骼/颜色（零 Qt） |
| [`pose_label/pose_config.py`](../../anylabeling/views/labeling/widgets/pose_label/pose_config.py) | 156 | PoseDisplayConfig（零 Qt） |
| [`pose_label/pose_view_panel.py`](../../anylabeling/views/labeling/widgets/pose_label/pose_view_panel.py) | 68 | QDockWidget 容器 |

集成点：
- [`canvas.py`](../../anylabeling/views/labeling/widgets/canvas.py) — paintEvent 接入 + `pose_focus_group_id`/`_apply_group_focus` 两态机制（~20 行改动）
- [`label_widget.py`](../../anylabeling/views/labeling/label_widget.py) — `toggle_pose_view`（~13 处引用）
- [`settings/schema.py:204-224`](../../anylabeling/views/labeling/settings/schema.py) — 21 个 `pose_view.*` 配置键

**合计：1,994 行**（`pose_label/` 目录，9 个文件）

---

## 测试覆盖

| 测试文件 | 用例数 |
|---------|--------|
| [`tests/test_pose_layout.py`](../../tests/test_pose_layout.py) | 14 |
| [`tests/test_pose_category_layout.py`](../../tests/test_pose_category_layout.py) | 13 |
| [`tests/test_pose_renderer.py`](../../tests/test_pose_renderer.py) | 7 |
| [`tests/test_pose_color_panel.py`](../../tests/test_pose_color_panel.py) | 2 |
| [`tests/test_keypoint_label_layout.py`](../../tests/test_keypoint_label_layout.py) | 14 |
| **合计** | **36+** |

flake8 clean，black 通过。回归测试见 [`docs/feature_interaction_test_matrix.md`](../feature_interaction_test_matrix.md) 8.8/8.9（解耦 + 两态换色恢复不变量）。

---

## 设计文档

- [`docs/pose_view_label_decoupling_plan.md`](../pose_view_label_decoupling_plan.md) — 解耦方案
- [`docs/pose_label_feature_summary.md`](../pose_label_feature_summary.md) — 功能总结
- [`docs/POSE_VIEW_LAYOUT_TABLE_MODEL.md`](../POSE_VIEW_LAYOUT_TABLE_MODEL.md) — 布局表格模型
- [`docs/keypoint_fill_call_chain.md`](../keypoint_fill_call_chain.md) — Keypoint Fill 调用链
- [`docs/feature_interaction_test_matrix.md`](../feature_interaction_test_matrix.md) — 交互测试矩阵

---

## 截图

> `[截图待补]` — 计划补充：Pose View 与原生标签共存、总览/选中两态切换、4 种布局对比、Keypoint Fill 工作流

# 04 · 矩形边编辑
#### Rectangle Edge Editing

> 独立选中并拖动矩形的任意一条边（左/右/上/下），保留其他三条边不变。几何计算层与 Canvas UI 层严格解耦，反翻转 clamp 保证矩形永不坍塌。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

标注矩形时（尤其目标检测/密集场景），经常需要精修某条边：

- 两个并排物体的分界线要对齐
- 一个框的边缘要精确贴合图像边界
- 把某条边对齐到另一个框的边

**原生编辑只能拖角点（顶点）或整体平移**——拖角点会**同时改变两条边**，破坏另一方向的对齐。无法独立移动单条边。

```
原生拖角点：                    边编辑：
  ┌─────┐                        ┌─────┐
  │     │                        │     │
  └──┐  │   拖右下角 →           └─────┘   拖右边 →
     │  │                          ↑        只改右边
     └──┘                         左/上/下不变
   宽和高都变了                 只有宽变了
```

---

## 功能演进（诚实呈现）

本功能经历了从「边对齐」到「边编辑」的简化演进，我如实记录这个过程：

| 阶段 | 提交 | 设计 |
|------|------|------|
| **A-B** | `088f3d7` | 几何辅助类 `RectEdgeRef` + 测试 |
| **C-E** | `0cef86b` | Canvas 状态机 + 鼠标/键盘事件 |
| **F** | `23532e1` | overlay 渲染 |
| **G** | `9ab6e75` | View 菜单 action + 绘制模式互斥 |
| **审计修复** | `78c8327` | 菜单/canvas 同步、active-edge 刷新、hover 清理 |
| **简化** | `79bd668` | **移除 snap/reference，简化为纯边编辑** |

**原设计**（边对齐）：先点一条参考边（reference edge），再拖另一条目标边，靠近参考边时**吸附（snap）**到其坐标。状态机含 `rect_edge_reference_edge` / `rect_edge_snap_active` / `rect_edge_invalid_edge`，overlay 有 5 种颜色（白/蓝/橙/绿/红）。

**最终版**（边编辑）：直接拖拽矩形某条边即可。移除了 `edges_are_compatible()` 和 `RECT_EDGE_SNAP_SCREEN_PX` 常量，去掉了 reference/snap/invalid 状态，overlay 只剩白色 hover/active 两态。

> **设计决策**：简化版聚焦最核心的「独立拖单边」诉求，降低复杂度。吸附对齐虽然更强大，但增加了状态机复杂度和学习成本，在当前场景下投入产出比不划算。这个权衡过程记录在 [docs/cls3-010_task_矩形边对齐功能实现任务文档.md](../cls3-010_task_矩形边对齐功能实现任务文档.md)。

---

## 架构设计

### 三层分离

```
┌─────────────────────────────────────────┐
│  label_widget.py  (菜单层)               │
│  toggle_rect_edge_align() / 互斥守卫      │
└──────────────────┬──────────────────────┘
                   │ set_rect_edge_align_enabled()
                   ▼
┌─────────────────────────────────────────┐
│  canvas.py  (交互层)                     │
│  状态机 + 事件处理 + overlay 渲染          │
└──────────────────┬──────────────────────┘
                   │ apply_edge_coord()
                   ▼
┌─────────────────────────────────────────┐
│  rect_edge_alignment.py  (几何层, 纯计算)  │
│  RectGeometry / RectEdgeRef              │
│  ← 无 Qt Widgets 依赖，可独立单测         │
└─────────────────────────────────────────┘
```

---

## 技术亮点

### 1. 几何层/UI 层严格解耦

`rect_edge_alignment.py` 是纯计算模块（无 Qt Widgets 依赖）。核心是两个 frozen dataclass：

- **`RectGeometry`**（`rect_edge_alignment.py:53`）— 规范化的轴对齐矩形，永远存 min/max，与输入点顺序无关
- **`RectEdgeRef`**（`rect_edge_alignment.py:100`）— 对某条边的**临时编辑句柄**，持有 `Shape` 的活动引用

**关键边界约束**：`RectEdgeRef` 只是临时句柄，**绝不序列化到 JSON、不写入 `Shape.other_data/flags/attributes`**——文档反复强调这一点。它持有 Shape 的活动引用以便 in-place 改几何，但生命周期只在拖拽期间。

### 2. 反翻转 clamp

`geometry_with_edge_coord` 保证 `min` 永远 `< max`，矩形不会因拖过头而坍塌/翻转：

```python
# anylabeling/views/labeling/rect_edge_alignment.py:320-370
def geometry_with_edge_coord(geometry, edge_name, coord, min_size=1.0):
    """Return a new geometry with one edge moved to ``coord``.

    The opposite edge is preserved and the moved edge is clamped so the
    rectangle can never flip (``min`` always stays below ``max``):

    ====================  =========================
    edge                  clamp
    ====================  =========================
    left                  coord <= x_max - min_size
    right                 coord >= x_min + min_size
    top                   coord <= y_max - min_size
    bottom                coord >= y_min + min_size
    ====================  =========================
    """
    x_min, y_min = geometry.x_min, geometry.y_min
    x_max, y_max = geometry.x_max, geometry.y_max

    if edge_name == RECT_EDGE_LEFT:
        x_min = min(coord, x_max - min_size)      # 不会超过右边
    elif edge_name == RECT_EDGE_RIGHT:
        x_max = max(coord, x_min + min_size)      # 不会低于左边
    elif edge_name == RECT_EDGE_TOP:
        y_min = min(coord, y_max - min_size)
    elif edge_name == RECT_EDGE_BOTTOM:
        y_max = max(coord, y_min + min_size)

    return RectGeometry(x_min, y_min, x_max, y_max)
```

### 3. Canvas 状态机

一组**纯瞬时、不持久化**的标志位（`canvas.py:__init__` 声明）：

```
rect_edge_align_enabled      # 总开关
rect_edge_hover_edge         # 当前悬停的边（RectEdgeRef）
rect_edge_active_edge        # 正在拖拽的边
rect_edge_dragging           # 是否处于拖拽
rect_edge_drag_start_points  # 拖拽起始点，供 Esc 恢复
```

交互链：

```
hover（mouseMove 算候选）
  → 按下选中（mousePress 设 active+dragging+存起始点）
  → 实时改坐标（mouseMove 调 _rect_edge_drag_update，每次从最新几何重建 active edge）
  → 松开提交（mouseRelease 比 start_points 判断是否真变了，变了才 store_shapes()）
  → Esc 取消恢复（_handle_rect_edge_escape）
```

**关键细节**：每次 `_rect_edge_drag_update` 都从最新几何**重建 active edge**（修复了审计 P1#2「active-edge 不刷新」），让 overlay 跟随实时位置。一次 release = 一个 undo 粒度。

### 4. 绘制模式双向互斥

**双向互斥**确保边编辑与绘制模式不会冲突：

- **正向**（`toggle_rect_edge_align`）：开启边编辑时，若处于 `drawing()` 态则强制 `set_edit_mode()`
- **反向**（`new_data` 守卫 `label_widget.py:4046`）：用户切到任何 create 模式时，若边编辑 action 已勾选，则 `blockSignals(True)` 关掉 action。注释明确：**只有真正进 create 模式才清，回 edit 模式不清**——这正是审计修复 P1#1「menu/canvas sync」解决的问题

### 5. 命中测试

`_rect_edge_hit_candidate`（`canvas.py:3911`）按 `(1, edge_distance, area, -stack_index)` 排序选最近/最小/最新创建的矩形，**顶点命中优先于边命中**（顶点在范围内则跳过该 shape 的边候选），复用了 `_shape_hit_candidates` 的排序语义。

---

## 代码定位

| 文件 | 行数 | 职责 |
|------|------|------|
| [`rect_edge_alignment.py`](../../anylabeling/views/labeling/rect_edge_alignment.py) | 407 | 几何辅助模块（纯计算，无 Qt Widgets） |
| [`canvas.py`](../../anylabeling/views/labeling/widgets/canvas.py) | ~250（rect_edge 相关） | 状态机 + 事件 + overlay 渲染 |
| [`label_widget.py`](../../anylabeling/views/labeling/label_widget.py) | ~30 | View 菜单 action + 互斥守卫 |

核心函数：
- `geometry_from_shape()` — Shape 规范化为 RectGeometry
- `nearest_edge()` — epsilon 内返回最近边
- `geometry_with_edge_coord()` — 移动单边 + 反翻转 clamp
- `apply_edge_coord()` — 就地重写 Shape 四点
- `iter_edges()` — 枚举四条边

---

## 测试覆盖

[`tests/test_rect_edge_alignment.py`](../../tests/test_rect_edge_alignment.py)（253 行，6 个测试类，**21 个用例**，headless Qt）：

| 测试类 | 用例数 | 覆盖 |
|--------|--------|------|
| `TestGeometryFromShape` | 6 | 2 点对角/4 点乱序规范化、非矩形返回 None |
| `TestPointsFromGeometry` | 1 | TL→TR→BR→BL 顺序 |
| `TestIterEdges` | 4 | 四边 axis/coord/opposite |
| `TestNearestEdge` | 2 | 命中/超出 epsilon |
| `TestGeometryWithEdgeCoord` | 4 | 改单边 + 四方向反翻转 clamp |
| `TestApplyEdgeCoord` | 4 | 重写四点、不动 label/group_id |

> 注：Canvas 交互层（状态机、overlay、互斥）目前无自动化测试，靠几何层单测 + 手动验证。

---

## 设计文档

- [`docs/cls3-010_task_矩形边对齐功能实现任务文档.md`](../cls3-010_task_矩形边对齐功能实现任务文档.md) — 完整任务/设计文档（含演进记录）

---

## 截图

> `[截图待补]` — 计划补充：边编辑 hover 高亮、拖拽中 overlay、Esc 取消恢复演示

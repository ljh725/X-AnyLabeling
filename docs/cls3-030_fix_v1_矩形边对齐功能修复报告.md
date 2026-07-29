# 矩形边对齐功能修复报告 v1

> 本文档对应审核结论 `docs/cls3-040_review_v1_矩形边对齐功能审核结论.md`，记录 3 个 Findings 的修复方案、
> 代码改动、验证结果。
>
> - 审核结论：`docs/cls3-040_review_v1_矩形边对齐功能审核结论.md`（Codex v1）
> - 原实现报告：`docs/cls3-020_impl_矩形边对齐功能实现报告.md`
> - 修复提交：`78c8327 fix(rect-edge-align): address Codex audit v1`
> - 实现前备份节点：`backup/before-rect-edge-align`

## 修复总览

| # | 级别 | 问题摘要 | 状态 |
|---|------|----------|------|
| 1 | P1 | 从绘制模式开启边对齐 → 菜单 action 与 Canvas 状态不一致 | ✅ 已修 |
| 2 | P1 | 拖动时 active edge 的 p1/p2/coord 不刷新 → 状态色画在旧位置 | ✅ 已修 |
| 3 | P2 | hover 命中边后未清理旧 h_hape/h_vertex → 旧高亮残留 | ✅ 已修 |

修改文件 2 个、净增 23 行 / 删 5 行；24 个单测全绿；全量回归零新增失败。

---

## Finding 1（P1）：菜单状态与 Canvas 状态不一致

### 根因

`label_widget.py:toggle_rect_edge_align(enabled=True)` 开启时若处于绘制模式会先调
`set_edit_mode()`，而 `set_edit_mode()` → `toggle_draw_mode(edit=True)` 的旧实现里，
**只要 action 被勾选就取消勾选并关 Canvas**（无 `edit` 条件）。调用链：

```
toggle_rect_edge_align(True)
  ├─ set_edit_mode()                          # 因 drawing() 为 True
  │   └─ toggle_draw_mode(edit=True)
  │       └─ action 已勾选 → 取消勾选 + Canvas 关闭   # ← 错误：把刚勾上的 action 又取消了
  └─ canvas.set_rect_edge_align_enabled(True) # Canvas 又打开
```

结果：Canvas 开启，但菜单 action 显示未勾选。

### 修复

`label_widget.py:toggle_draw_mode` 的互斥块加 `not edit` 条件，**只在真正进入创建模式
（`edit=False`）时清 action**，切回 edit mode 时不动 action：

```python
# anylabeling/views/labeling/label_widget.py (toggle_draw_mode)
if (
    not edit                                          # ← 新增条件
    and rect_edge_action is not None
    and rect_edge_action.isChecked()
):
    rect_edge_action.blockSignals(True)
    rect_edge_action.setChecked(False)
    rect_edge_action.blockSignals(False)
    self.canvas.set_rect_edge_align_enabled(False)
```

修复后调用链：`toggle_rect_edge_align(True)` → `set_edit_mode()` →
`toggle_draw_mode(edit=True)`，因 `not edit` 为 False，跳过清理块；回到
`toggle_rect_edge_align` 把 Canvas 打开。菜单 action 与 Canvas 状态一致。

### 边界

- 用户主动进入创建模式（`toggle_draw_mode(edit=False, ...)`）时，`not edit` 为 True，
  action 仍会被正确取消勾选并关 Canvas —— 互斥语义不变。
- `blockSignals` 防递归保留。

---

## Finding 2（P1）：拖动时 active edge 几何不刷新

### 根因

`RectEdgeRef` 是 frozen dataclass。拖动开始时 `rect_edge_active_edge` 指向初始 edge，
其 `p1/p2/coord` 是拖动前的坐标。`mouseMoveEvent` 拖动分支用 `apply_edge_coord` 改了
`active.shape.points`，但**没有更新 `rect_edge_active_edge`**。绘制时
`_draw_rect_edge_alignment_overlay` 仍用旧 edge 的 `p1/p2` 画橙/绿状态色 → 颜色落在
原始边位置，而不是当前预览边。

### 修复

在 `apply_edge_coord` 之后，根据 `active.shape` 的当前几何 + `active.edge_name`
重新派生 edge 并写回 `rect_edge_active_edge`：

```python
# anylabeling/views/labeling/widgets/canvas.py (mouseMoveEvent, drag branch)
rea.apply_edge_coord(active.shape, active.edge_name, coord)
# Refresh the active edge from the just-mutated geometry so the overlay
# (orange/green status colour) follows the live preview position instead
# of the original edge.
updated_geom = rea.geometry_from_shape(active.shape)
if updated_geom is not None:
    self.rect_edge_active_edge = rea.edge_from_geometry(
        active.shape, updated_geom, active.edge_name
    )
self.update()
```

`edge_name` 与 `shape` 在整个拖动过程中是稳定的（只有坐标变），所以重派生安全。
`apply_edge_coord` 内部已调 `_invalidate_cache()`，`geometry_from_shape` 直接读
`shape.points` 的 min/max，得到的就是当前预览几何。

### 验证

冒烟测试（offscreen）：构造矩形 left edge（coord=0），拖动到 coord=30 后重派生，
确认 `rect_edge_active_edge.coord == 30.0` 且 `p1.x() == 30.0`。**通过。**

---

## Finding 3（P2）：hover 命中边后旧高亮残留

### 根因

`mouseMoveEvent` 的 hover 分支命中边后直接 `return`，**没有清理既存的
`h_hape/h_vertex/h_edge/h_cuboid_face`**。若上一帧 hover 过顶点或其他 shape，
旧 highlight 会继续影响绘制（旧 shape 的 `highlight_vertex` 状态未清，
`selected_vertex()` 可能残留 True）。

### 修复

命中边后、`return` 之前调 `self.un_highlight()`，复用既有清理方法
（清 `h_hape/h_vertex/h_edge/h_cuboid_face` + 对旧 shape 调 `highlight_clear()`）：

```python
# anylabeling/views/labeling/widgets/canvas.py (mouseMoveEvent, hover branch)
if candidate is not None:
    # Edge hovered: clear any stale shape/vertex/edge/cuboid hover state
    # left over from a previous frame so the old highlight does not bleed
    # through, then suppress the default hover loop.
    self.un_highlight()
    self.show_shape.emit(-1, -1, pos)
    return
```

### 验证

冒烟测试（offscreen）：先植入 `h_hape=r, h_vertex=0` 并调 `r.highlight_vertex(...)`，
再走边 hover 路径并调 `un_highlight()`，确认 `h_hape is None` 且 `h_vertex is None`。
**通过。**

---

## 验证

### 自动测试

```powershell
conda activate x-anylabeling-cu12
python -m pytest tests/test_rect_edge_alignment.py
python -m py_compile anylabeling/views/labeling/widgets/canvas.py `
                  anylabeling/views/labeling/label_widget.py
python -m flake8 anylabeling/views/labeling/widgets/canvas.py
```

结果：

| 项 | 结果 |
|---|---|
| `pytest tests/test_rect_edge_alignment.py` | **24 passed** |
| `py_compile`（canvas.py + label_widget.py） | **COMPILE_OK** |
| `flake8 canvas.py` | **exit 0（干净）** |
| `flake8 label_widget.py` | **10 条均为既存**（与备份 tag 数量一致，修复前后无变化） |
| 全量 `pytest tests/` | **16 failed / 356 passed** —— 与修复前**完全相同**，零新增失败（16 条既存失败集中在 `test_settings/`、`test_ppocr/`、`test_filter_persistence.py`，与本功能无关） |

### 行为冒烟（offscreen Canvas）

- **P1#2**：拖动后 `rect_edge_active_edge.coord` 从 0.0 刷新到 30.0，`p1.x()` 跟随。
  → `VERIFY_OK`
- **P2#3**：边 hover 后 `un_highlight()` 清空 `h_hape`/`h_vertex`。
  → `VERIFY_OK`
- **P1#1**：纯条件分支改动（`and not edit`），代码审查确认 `set_edit_mode()` 调用链
  跳过清理块；GUI 实机勾选状态建议 Codex 复核。

### 仍需 Codex 实机复核

P1#1/P1#2 的视觉效果（菜单勾选一致性、橙/绿状态色跟随预览边）依赖真实 Qt 渲染，
offscreen 无法肉眼确认。建议在桌面环境按实现报告 §H.3 矩阵再跑一遍。

---

## 改动清单

| 文件 | 改动 |
|------|------|
| `anylabeling/views/labeling/label_widget.py` | `toggle_draw_mode` 互斥块加 `not edit` 条件（P1#1） |
| `anylabeling/views/labeling/widgets/canvas.py` | mouseMove 拖动分支：`apply_edge_coord` 后重派生 `rect_edge_active_edge`（P1#2） |
| `anylabeling/views/labeling/widgets/canvas.py` | mouseMove hover 分支：命中边后调 `un_highlight()`（P2#3） |

净增 23 行 / 删 5 行，单 commit：`78c8327`。

## 审核方提到的测试环境问题

审核结论提到「当前 shell 默认 `C:\Python314`，conda activate 失败，未能复跑 pytest」。
本环境用 conda env `x-anylabeling-cu12` 的 python 直接调用（路径
`C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe`），已成功复跑，
结果见上「自动测试」。建议审核方在配置好的 conda 环境再确认一次。

## 回退

```bash
# 仅回退本次修复（回到实现版本）：
git revert 78c8327

# 回退到实现前：
git reset --hard backup/before-rect-edge-align
```

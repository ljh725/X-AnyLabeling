# 稳定精修预览 — 阶段二（TargetPreview）实现方案

## 对齐结果
7 个疑问全部按你的选择：
- Q1 (A) 信号监听 + 排查漏网（已排查出 4 条，见 §1）
- Q2 拆分 clear：`clear_rect_edge_alignment` 只清 drag；切图路径额外 `_clear_all`
- Q3 安全区只在 `_enter_target_if_valid()` 触发，不挂 move
- Q4 复用 `stable_preview_shape`
- Q5 TargetPreview 不画边高亮
- Q6 只加字段，UI 保留总开关
- Q7 贴边用容差 `< 1.0`

## §1 Q1 排查结论（信号监听会漏 4 条路径）

| 方法 | 行号 | 行为 | 后果 |
|------|------|------|------|
| `delete_selected()` | 2334 | 删除后置空，**不 emit** | 删预览矩形后 Target 残留 |
| `delete_shape()` | 2340-2341 | 从 selected 移除，**不 emit** | 残留 |
| `restore_shape()` | 492 | undo 后置空，**不 emit** | 撤销后残留 |
| `end_move(copy=True)` | 1606-1607 | 替换引用，**不 emit** | 指向旧 shape |

**处理策略**：主体走信号监听（1 行 connect 覆盖 12 处 emit）。这 4 条漏网路径，**各补 1 行 `selection_changed.emit(self.selected_shapes)`**——语义上它们本就是选区变化，补 emit 是修正缺失的副作用，而非新增副作用（label_widget 端本就监听此信号刷新属性面板等，补 emit 让其行为更正确）。

---

## §2 文件改动清单

### 文件 1：`anylabeling/views/labeling/widgets/canvas.py`（核心）

#### 2.1 新增字段（`__init__`，`canvas.py:297` 阶段一字段块之后）

```python
# Phase 2: TargetPreview state.
self.stable_preview_target_enabled = True
self.stable_preview_drag_locked_enabled = True
self.stable_preview_mode = "none"  # "none" | "target" | "drag_locked"
self.stable_preview_target_rect = None  # QRectF image coords
self.stable_preview_target_padding_ratio = 0.4
self.stable_preview_safe_ratio = 0.7
```
> Q4：复用 `stable_preview_shape`，不新增 target_shape 字段。

#### 2.2 信号监听（`__init__` 末尾，字段全部定义之后）

```python
self.selection_changed.connect(
    self._stable_preview_on_selection_changed
)
```

#### 2.3 拆分 clear 方法（替换阶段一的 `_stable_preview_clear`）

阶段一只有一个 `_stable_preview_clear`。阶段二替换为 4 个语义明确的方法（紧邻 `clear_rect_edge_alignment`，`canvas.py:3953` 区）：

```python
def _stable_preview_clear_drag_locked(self):
    """只清 DragLocked 态：locked_rect + active_edge_name + mode。保留 target。"""
    self.stable_preview_locked_rect = None
    self.stable_preview_active_edge_name = None
    if self.stable_preview_mode == "drag_locked":
        self.stable_preview_mode = "none"

def _stable_preview_clear_target(self):
    """只清 Target 态：target_rect + mode。保留 drag。"""
    self.stable_preview_target_rect = None
    if self.stable_preview_mode == "target":
        self.stable_preview_mode = "none"

def _stable_preview_clear_all(self):
    """彻底清：shape + drag + target + mode。切图/重置用。"""
    self.stable_preview_shape = None
    self.stable_preview_locked_rect = None
    self.stable_preview_target_rect = None
    self.stable_preview_active_edge_name = None
    self.stable_preview_mode = "none"

def _stable_preview_enter_target_if_valid(self):
    """DragLocked 结束后按选区决定：回 Target 还是 Idle。
    安全区在这里判断（Q3：唯一触发点）。"""
    if (not self.stable_preview_enabled
            or not self.stable_preview_target_enabled):
        self._stable_preview_clear_all()
        return
    sel = self.selected_shapes
    if len(sel) == 1 and sel[0].shape_type == "rectangle":
        self.stable_preview_shape = sel[0]
        self._stable_preview_update_target_rect_by_safezone()
        self.stable_preview_mode = "target"
    else:
        self._stable_preview_clear_all()
```

> 保留 `_stable_preview_clear()` 作为 `_clear_all` 的别名（或直接删除并改所有调用点）。倾向**删除单数 clear，改为显式调用**——正是你强调的"不要用万能 clear"。

#### 2.4 新增 TargetPreview 计算方法（`canvas.py:3953` 区）

```python
def _stable_preview_compute_target_rect(self, shape):
    """§7.1 基础计算：bbox center 居中，max(基础裁剪, 外扩bbox)，clamp。"""
    # 复用 _clamp_rectf_to_image

def _stable_preview_update_target_rect_by_safezone(self):
    """§8 安全区：bbox 在 safe_rect 内则保留 target_rect，否则重算。含边缘放宽。"""
    # Q3：唯一触发点，不挂 move
```

边缘放宽（Q7 容差）：判断贴边用 `< 1.0` 而非 `== 0`。

#### 2.5 选区同步方法

```python
def _stable_preview_on_selection_changed(self, selected_shapes):
    """selection_changed 信号槽。§6.2 规则。"""
    # 注意：拖动中（mode==drag_locked）不响应，DragLocked 优先
    if self.stable_preview_mode == "drag_locked":
        return
    if (not self.stable_preview_enabled
            or not self.stable_preview_target_enabled):
        self._stable_preview_clear_all()
        return
    if len(selected_shapes) == 1 and selected_shapes[0].shape_type == "rectangle":
        self.stable_preview_shape = selected_shapes[0]
        self.stable_preview_target_rect = self._stable_preview_compute_target_rect(...)
        self.stable_preview_mode = "target"
    else:
        self._stable_preview_clear_all()
```

#### 2.6 修改 begin_drag_locked（`canvas.py:3920`）

阶段一 `_stable_preview_begin_drag_locked` 进入 drag 时只设 locked_rect。阶段二补：设 `stable_preview_mode = "drag_locked"`，**保留** target_rect（供松开后回 Target）。
- 注意受 `drag_locked_enabled` 开关控制（Q6）：关闭时不进入 drag_locked。

#### 2.7 修改 release / escape 衔接

阶段一 release 走 `clear_rect_edge_alignment`（含 `_stable_preview_clear`）。阶段二改为：
- `clear_rect_edge_alignment`（`canvas.py:3981`）把 `_stable_preview_clear()` 改为 `_stable_preview_clear_drag_locked()`（**只清 drag，保留 target**）。
- **release 路径**（`canvas.py:1559` 区，clear 之后）：在 `clear_rect_edge_alignment()` 调用之后，加 `self._stable_preview_enter_target_if_valid()`。
- **escape / cancel 路径**：`cancel_rect_edge_drag`（`canvas.py:3983`）末尾同样加 `_stable_preview_enter_target_if_valid()`。

#### 2.8 切图路径改为 _clear_all（Q2 核心）

| 方法 | 行号 | 改动 |
|---|---|---|
| `load_pixmap` | 4422（现 `_stable_preview_clear()`） | 改为 `_stable_preview_clear_all()` |
| `load_shapes` | 4456（`clear_rect_edge_alignment`） | clear_rect_edge_alignment 只清 drag 了，**额外加 `_stable_preview_clear_all()`**（确保切图清 Target） |
| `reset_state` | 4507（`clear_rect_edge_alignment`） | 同上，额外加 `_stable_preview_clear_all()` |
| `set_editing(False)` | 668 | 改为 `_stable_preview_clear_all()` |

#### 2.9 Q1 漏网路径补 emit（4 处）

| 方法 | 行号 | 补 emit |
|---|---|---|
| `delete_selected` | 2334 后 | `self.selection_changed.emit(self.selected_shapes)` |
| `delete_shape` | 2341 后 | `self.selection_changed.emit(self.selected_shapes)` |
| `restore_shape` | 492 后 | `self.selection_changed.emit(self.selected_shapes)` |
| `end_move` copy 分支 | 1607 后 | `self.selection_changed.emit(self.selected_shapes)` |

#### 2.10 浮层绘制按 mode 分支（`canvas.py:4144` `_draw_stable_preview_overlay`）

阶段一 source 固定取 `locked_rect`。阶段二改为：
```python
if self.stable_preview_mode == "drag_locked":
    src = self.stable_preview_locked_rect
elif self.stable_preview_mode == "target":
    src = self.stable_preview_target_rect
else:
    return
```
- Q5：target 模式下**跳过** "Active edge highlight" 段（4220-4236，只有 drag_locked 才画边高亮）。
- 其余（裁剪图/绿框/标签）两种模式都画。

paintEvent 守卫（`canvas.py:3151-3163`）：把条件从 `rect_edge_dragging` 放宽为 `stable_preview_mode != "none"`（target 时也要画）。

---

### 文件 2：`anylabeling/views/labeling/label_widget.py`（接线）

| 改动 | 位置 | 说明 |
|---|---|---|
| set_stable_preview_enabled | toggle handler（`canvas.py:7091`） | 无需改，canvas 侧总开关已处理 |
| drag_locked_enabled 受控 | 无需 UI | Q6 只加字段，默认 True；begin_drag_locked 内判断 |

> 阶段二 label_widget 几乎不动（Q6：不加子菜单 UI）。drag_locked_enabled / target_enabled 默认 True，在 canvas 内部判断。

---

## §3 状态机衔接图（验证 Q2 拆分正确）

```
单选矩形 → selection_changed → _on_selection_changed → mode=target, compute target_rect
   │
   press 边 → begin_drag_locked → mode=drag_locked（保留 target_rect）
   │
   move → 不动（drag_locked 锁定）
   │
   release → clear_rect_edge_alignment(只清drag) → _enter_target_if_valid
              → 安全区判断 → mode=target 或 _clear_all
   │
   escape → cancel_rect_edge_drag → _enter_target_if_valid（同上）
   │
切图(load_pixmap/load_shapes/reset_state) → _clear_all（彻底）
进入绘制模式(set_editing F) → _clear_all
delete/undo/copy → 补 emit → _on_selection_changed → 按选区收敛
```

## §4 验收对照（文档 §13）
- [ ] 单选矩形 → 出现 TargetPreview
- [ ] 多选/非矩形/取消选中 → 隐藏
- [ ] 小幅拖动后松开 → 安全区内底图不动
- [ ] 边缘目标（左上角/右下角）小幅移动 → 不反复跳动
- [ ] 拖动时 DragLocked 接管，松开回 Target
- [ ] Escape → 回 Target（若仍选中）或隐藏
- [ ] 删除/撤销/切图/进绘制模式 → 彻底清空无残留
- [ ] 阶段一 DragLocked 行为不回归

## §5 风险点
1. **release 后 enter_target 的时序**：`clear_rect_edge_alignment` 清了 `rect_edge_dragging`，需确认此时 `selected_shapes` 仍是该矩形（拖动不改选区），_enter_target 能正确回 Target。
2. **补 emit 的副作用**：delete/undo 补 emit 后，label_widget 端的 selection_changed 槽会多触发一次（刷新属性面板等），需确认无副作用——预计是正向修正。
3. **load_shapes 的 `_clear_all` 时机**：load_shapes 先 clear_rect_edge_alignment（只清drag）再 `_clear_all`（清全部），顺序OK。
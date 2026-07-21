# 09 · 精修控制模式

> **现行状态（2026-07-20）**：仅保留鼠标 `zoom`/`fixed` 降速、Ctrl 临时精修和精修锁定。本文中的 Tab 键盘选边、单边方向键微调和撤销合并已经退役，相关运行时代码与测试已删除。

#### Precision Refinement

> 矩形框精细调整的**主流程**：鼠标精修降速增益（`zoom`/`fixed` 两种模式）、Ctrl 临时精修、Tab 键盘选边、方向键 1px / Shift+方向键 5px 单边微调。通过一个独立的「虚拟游标」隔离精修 delta，不污染 hit-test / hover / transform 等基础交互。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

精修矩形框（贴合目标边界、对齐相邻框）时，鼠标手抖导致 **1-3 像素误差**是最大痛点。原生拖拽在 300%-400% 放大下：

```
放大到 400% → 鼠标动 1 像素，图像坐标动 0.25 像素（看似很精细）
但手指/手腕的微小抖动 → 屏幕上动 4-8 像素 → 图像上动 1-2 像素
→ 想精确停在目标边界，却总是过冲/欠冲
```

而键盘整体平移只能移动整个框，**无法单独移动一条边**——但贴合边界时常常只想动一条边。

---

## 方案：鼠标降速 + 键盘像素级 + Tab 选边

精修控制模式由**五个子能力**组成，覆盖从「粗对齐」到「1 像素定稿」的全流程：

| 子能力 | 作用 | 入口 |
|--------|------|------|
| 精修模式锁定（Ctrl+Alt+F） | 持续降速，不必一直按 Ctrl | View 菜单 |
| Ctrl 临时精修 | 不锁定时按住 Ctrl 临时降速 | 拖拽中按 Ctrl |
| 键盘整体微调 | 方向键 1px，Shift+方向键 5px | 选中后按方向键 |
| Tab 键盘选边 | 单选矩形后 Tab 循环 left/top/right/bottom | 选中矩形后按 Tab |
| 单边键盘微调 | 选中边后方向键移动该边 1px（Shift=5px） | 选边后按方向键 |

**推荐工作流**：放大 → 开精修锁/按 Ctrl → 鼠标拖到接近 → Tab 选边 → 方向键 1px 定稿。

---

## 技术亮点

### 1. 虚拟游标：delta 隔离，基础交互零污染

精修的核心是一个**独立的虚拟游标**，只缩放拖拽 delta，**绝不改写** `self.prev_point`：

```
真实 pos ──(delta = pos - raw_prev)──► 虚拟 prev += delta / factor ──► 虚拟 pos（喂给 bounded_move）
                                          │
                                          └─ self.prev_point 保持真实值（hit-test/hover/transform 仍用它）
```

```python
# canvas.py:3674-3694
def _effective_drag_pos(self, pos, ev):
    if not self._precision_active(ev):
        self._reset_virtual_cursor()
        return pos
    if self._virtual_prev_point is None:
        self._virtual_prev_point = QtCore.QPointF(self.prev_point)
        self._precision_raw_prev_point = QtCore.QPointF(self.prev_point)
    factor = self.precision_factor
    delta = pos - self._precision_raw_prev_point
    scaled = QtCore.QPointF(delta.x() / factor, delta.y() / factor)
    eff = self._virtual_prev_point + scaled
    self._virtual_prev_point = eff
    self._precision_raw_prev_point = QtCore.QPointF(pos)
    return eff
```

这是「D4 隔离规则」——`prev_point` 是 `move_by_keyboard`、press-reset、hit-test 等多处依赖的真实游标，精修只另起一套虚拟累加器。**好处**：精修不影响任何已有交互的正确性，测试 `test_7_17_*` 连续 10 次拖动后断言 `prev_point.x() == 0.0`（从未被污染）。

精修**不改**这些：`transform_pos()`、hit-test、hover 判断、epsilon、键盘微调、局部边缘吸附——全部继续用真实 `pos`。

### 2. zoom 模式：解决高放大下的拖拽僵硬

最初用 `fixed` 模式（固定倍率，如 4），但在 400% 放大下 `1/4` 倍率让拖拽**僵硬到难以移动**。`zoom` 模式让实际倍率随缩放自适应：

```python
# canvas.py:3626-3643
@property
def precision_factor(self):
    mode = getattr(self, "_precision_mode_cfg", "fixed")
    if mode == "zoom":
        scale_factor = max(1.0, float(self.scale))
        max_factor = max(1.0, float(self._precision_max_factor_cfg"))
        return min(scale_factor, max_factor)    # min(scale, max)
    return self._precision_factor_cfg            # fixed
```

默认 `zoom + max_factor 2.0` 的实际效果：

| 缩放比例 | scale | 实际精修倍率 | 拖拽相对速度 |
|---------|-------|------------|------------|
| 100% | 1.0 | 1.0（floor） | 正常 |
| 150% | 1.5 | 1.5 | 2/3 |
| 200% | 2.0 | 2.0 | 1/2 |
| 300% | 3.0 | **2.0（cap）** | 1/2 |
| 400% | 4.0 | **2.0（cap）** | 1/2 |

两个 clamp：`max(1.0, scale)` 保证低缩放不加速；`min(scale, max_factor)` 保证高缩放最多降到 1/2——**消除了早期 400%→1/4 的僵硬感**。

### 3. Tab 选边：独立单边操作

Tab 拦截（`event()` override，在 Qt 焦点遍历之前消费）循环选中矩形的四条边：

```python
# canvas.py:4942, 4959-4984
_KEYBOARD_EDGE_CYCLE = ("left", "top", "right", "bottom")

def _cycle_keyboard_edge(self):
    if len(self.selected_shapes) != 1 or 不是矩形:
        self._clear_keyboard_edge()         # 非单矩形 → 清空
        self.keyboard_edge_selected.emit("")
        return
    ...
    edge = _KEYBOARD_EDGE_CYCLE[(idx + 1) % 4]
    self.keyboard_edge_selected.emit(edge)   # 状态栏提示
```

选边后方向键**只移动那一条边**（而非整体），用 `rect_edge_alignment.apply_edge_coord` 带 `min_size=1.0` 反翻转 clamp：

```python
# canvas.py:4986-5026（_nudge_keyboard_edge 节选）
step = MOVE_SPEED if (modifiers & Shift) else 1.0   # 5px / 1px
new_coord = 当前边坐标 ± step
apply_edge_coord(shape, edge, new_coord, min_size=1.0)  # 反翻转 clamp
self.store_shapes(merge_window=0.5)   # 0.5s 内的连续按键合并成一次 undo
```

**`merge_window=0.5`**：连按 10 次方向键 = 1 次 undo（而非 10 次），精修体验丝滑。

### 4. Ctrl 临时精修：单事件级开关

```python
# canvas.py:3659-3667
def _precision_active(self, ev=None):
    if self.precision_mode_locked:
        return True                          # 锁定态
    if ev is not None:
        return bool(ev.modifiers() & ControlModifier)  # 按住 Ctrl
    return False
```

锁定态（Ctrl+Alt+F 切换）恒为 True；未锁定时**每个 mouseMove 事件**现查 Ctrl 修饰键——按住才降速，松开立即恢复，**零状态切换**，纯瞬时。

---

## 坐标模型

| 模式 | 公式 |
|------|------|
| 普通拖拽 | `image_delta = screen_delta / canvas.scale` |
| 精修拖拽 | `precision_image_delta = screen_delta / canvas.scale / precision_factor` |

精修只额外多除一个 `precision_factor`，几何含义清晰。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`canvas.py:3626-3643`](../../anylabeling/views/labeling/widgets/canvas.py) | `precision_factor` 属性（zoom/fixed 模式） |
| [`canvas.py:3674-3694`](../../anylabeling/views/labeling/widgets/canvas.py) | `_effective_drag_pos` 虚拟游标（delta 隔离） |
| [`canvas.py:3659-3667`](../../anylabeling/views/labeling/widgets/canvas.py) | `_precision_active` Ctrl/锁 判定 |
| [`canvas.py:4959-4984`](../../anylabeling/views/labeling/widgets/canvas.py) | `_cycle_keyboard_edge` Tab 选边 |
| [`canvas.py:4986-5026`](../../anylabeling/views/labeling/widgets/canvas.py) | `_nudge_keyboard_edge` 单边 1px/5px |
| [`canvas.py:5234-5265`](../../anylabeling/views/labeling/widgets/canvas.py) | `_editing_arrow_dispatch` 整体/单边分流 |
| [`canvas.py:5147-5157`](../../anylabeling/views/labeling/widgets/canvas.py) | `event()` override 拦截 Tab |
| [`label_widget.py:7220-7245`](../../anylabeling/views/labeling/label_widget.py) | 精修锁切换 handler |
| [`label_widget.py:7277-7293`](../../anylabeling/views/labeling/label_widget.py) | Tab 选边状态栏提示 |
| [`schema.py:800-847`](../../anylabeling/views/labeling/settings/schema.py) | 3 个精修设置字段 |
| [`xanylabeling_config.yaml:241-243`](../../anylabeling/configs/xanylabeling_config.yaml) | 默认 `zoom / 2.0 / 4` |

---

## 测试覆盖

[`tests/test_precision_mode.py`](../../tests/test_precision_mode.py)（14 个测试，headless Qt）：

| 分组 | 测试 | 验证点 |
|------|------|--------|
| **精修增益** | `test_7_9_*` | fixed factor=4：raw 8px → 2px |
| **zoom 模式** | `test_zoom_*`（3 个） | scale=1.5→1.5；scale=4.0→cap 2.0；scale=0.5→floor 1.0 |
| **关闭直通** | `test_7_9b_*` | 精修关 → pos 不变，虚拟游标 None |
| **无漂移** | `test_7_17_*` | 连续 10 次拖动，虚拟累加=10px，**`prev_point.x()==0`**（D4 铁证） |
| **Tab 选边** | `test_keyboard_edge_*`（3 个） | 循环 L→T→R→B；非单矩形不触发；align 关也能用 |
| **hover 清边** | `test_7_20_*` | `_clear_keyboard_edge` 幂等 |
| **undo 合并** | `test_7_21_*` | 0.5s 内合并、窗口外追加；默认不合并 |

---

## 设计方法论沉淀

- **虚拟游标隔离**是「在不破坏既有不变量的前提下注入新行为」的通用模式：新建一套并行的累加状态，让新行为（精修）和旧依赖（prev_point）各走各的路。相比直接改 `prev_point`，这种方式让回归风险降到零。
- **clamp 双向**（floor + cap）：`max(1.0, ...)` 防退化、`min(..., max)` 防过激——这是处理「用户可调参数」时保证边界合理的标准姿势。

---

## 截图

> `[截图待补]` — 计划补充：Tab 选边高亮 + 方向键 1px 单边移动 + 状态栏「已选择矩形右边」

# 鼠标事件处理顺序构建文档

> 适用范围：`anylabeling/views/labeling/widgets/canvas.py`
> 关联文件：`anylabeling/views/labeling/label_widget.py`（不重写任何鼠标事件，仅通过信号被动响应）
> 分支基准：`feature/selection-optimization`（含矩形边对齐功能 rect_edge_align）

---

## 0. 文档目的与阅读对象

本文档系统性梳理 X-AnyLabeling 画布（`Canvas`）中所有鼠标事件（按下、移动、释放、双击、滚轮）的**入口位置、分支优先级、状态机协同、信号派发与 undo 提交语义**，帮助：

- 新增交互功能时找到正确的「插入点」；
- 排查「点击没反应 / 被吞事件 / 误触发平移」类回归；
- 理解矩形边对齐等跨事件状态机如何贯穿 press → move → release。

**核心结论先行**：所有鼠标逻辑只在 `Canvas` 内部消化，`label_widget` 不接管任何 `mouse*Event`，仅订阅 Canvas 信号。每个事件处理器是一条**线性短路链**，靠 `if ... return` 表达优先级，关键插入点都有注释护栏。

---

## 1. 架构总览

### 1.1 事件收口点

| 事件方法 | 文件:行 | 复杂度标记 |
|----------|---------|-----------|
| `mouseMoveEvent` | `canvas.py:703` | `# noqa: C901`（圈复杂度超阈值） |
| `mousePressEvent` | `canvas.py:1291` | `# noqa: C901` |
| `mouseReleaseEvent` | `canvas.py:1560` | — |
| `mouseDoubleClickEvent` | `canvas.py:1653` | — |
| `wheelEvent` | `canvas.py:3672` | — |

### 1.2 坐标系转换

所有事件第一行（除 `is_loading` 早退外）：

```python
pos = self.transform_pos(ev.position())  # canvas.py:3472
```

`transform_pos` 把 Qt 屏幕坐标转换为**画布图像逻辑坐标**（扣除缩放/平移）。后续所有 `contains_point`、`bounded_move_*`、矩形边对齐的吸附阈值都基于此坐标系。

### 1.3 通用前置门控

```
if self.is_loading: return   # 加载图片期间吃掉所有事件，防止脏状态
```

任何新加的事件处理器都必须在最开头保留这道门控。

### 1.4 与 label_widget 的契约

Canvas → label_widget 的信号通道（仅列举与鼠标相关）：

| 信号 | 触发场景 |
|------|---------|
| `scroll_request` | 滚轮滚动、左键拖空白平移画布 |
| `zoom_request` | Ctrl + 滚轮 |
| `selection_changed` | 选区变化 |
| `shape_moved` | 形状几何变化后（触发 label_widget 持久化） |
| `drawing_polygon` | 进入/退出绘制态 |
| `show_shape` | 实时反馈矩形/立方体的宽高 |
| `mode_changed` | 绘制完成自动切回编辑态 |
| `edit_label_requested` | 双击编辑标签 |
| `split_position_changed` | Shift+滚轮调 compare 分屏 |

---

## 2. mousePressEvent（按下）— 交互的核心入口

**位置**：`canvas.py:1291` ｜ **入口签名**：`def mousePressEvent(self, ev)`

按下事件决定**本次交互的语义**（新建点 / 选区 / 进入拖拽 / 弹菜单），是整个标注交互的中枢。

### 2.1 完整优先级链

```
is_loading? ──► return
_pending_edge_point = None
pos = transform_pos(ev.position())
│
├─ 【P0 最高优先级】rect_edge_align_enabled && editing() && rect_edge_hover_edge is not None
│     │   (canvas.py:1306-1348)
│     ├─ reference_edge 为空
│     │     → 记录参考边: rect_edge_reference_edge = hover
│     │     → return
│     ├─ edges_are_compatible(reference, hover)
│     │     → 进入拖拽态:
│     │         rect_edge_active_edge      = hover
│     │         rect_edge_dragging         = True
│     │         rect_edge_drag_start_points = list(hover.shape.points)
│     │         rect_edge_drag_start_edge_coord = hover.coord
│     │         rect_edge_drag_start_mouse_coord = pos.x() 或 pos.y()
│     │     → return
│     └─ 不兼容（异轴 or 同一形状）
│           → rect_edge_invalid_edge = hover（短暂红色提示）
│           → return
│
├─ LeftButton 分支:
│   │
│   ├─ 【P1】drawing()  ──── 按 create_mode 分发  (canvas.py:1349-1498)
│   │     │
│   │     ├─ self.current 非空 → 给现有 shape 加点
│   │     │   ├─ polygon       : add_point(line[1]); 闭合则 finalise
│   │     │   ├─ circle/line   : current.points = line.points; finalise
│   │     │   ├─ rectangle     : 补 3 点成 4 点矩形; finalise
│   │     │   ├─ cuboid        : 1 点→前后面 8 点; finalise
│   │     │   ├─ rotation      : 4 点矩形; finalise
│   │     │   ├─ quadrilateral : add_point; 4 点闭合则 finalise
│   │     │   ├─ linestrip     : add_point; Ctrl 修饰键则 finalise
│   │     │   └─ [自动切回编辑态] rectangle/rotation/.../point 且非自动标注
│   │     │                   且 current 已空 → mode_changed.emit()
│   │     │
│   │     └─ self.current 为空 → 新建 Shape
│   │         ├─ 在 pixmap 内: current = Shape(create_mode); add_point(pos)
│   │         │   ├─ point    : 立即 finalise
│   │         │   ├─ circle   : shape_type='circle'
│   │         │   └─ 其余     : line.points=[pos,pos]; drawing_polygon.emit(True)
│   │         ├─ auto_decode + 自动标注 POINT 模式: on_auto_decode_timeout(); return
│   │         └─ 越界 linestrip/rectangle/rotation/... : 钳位到 pixmap 后新建
│   │
│   └─ 【P2】editing()  ──── 选区/顶点/边操作  (canvas.py:1499-1542)
│         ├─ selected_edge()                         → add_point_to_edge()
│         ├─ selected_vertex() + Shift + 可删点类型  → remove_selected_point()
│         ├─ selected_vertex() (无 Shift)            → 翻转 is_move_editing
│         │     · True  → override_cursor(CURSOR_MOVE)
│         │     · False → override_cursor(CURSOR_POINT)
│         ├─ _pending_initial_backup → store_shapes()（首次编辑前快照）
│         ├─ select_shape_point(pos, multiple_selection_mode=Ctrl)
│         └─ prev_point / prev_pan_point 记录, repaint()
│
└─ RightButton && editing():  (canvas.py:1543-1557)
      · 若无选中 or hover 不在选中集 → select_shape_point(Ctrl=多选)
      · prev_point = pos
```

### 2.2 关键顺序约束

1. **P0 必须在 P1/P2 之前返回**：矩形边对齐功能若放在 `drawing()/editing()` 之后，会被普通选区逻辑吞掉点击。这是 `78c8327` 提交修复的核心问题。
2. **P1 内部 `self.current` 非空判断**决定是「加点」还是「新建」——这是绘制态机的关键分叉。
3. **P2 的 `is_move_editing` 翻转**：单击顶点切换移动模式，光标随之变化，是「点击即拖」与「点击锁定再拖」两种交互的开关。

---

## 3. mouseMoveEvent（移动）— 分支最密集

**位置**：`canvas.py:703` ｜ **入口签名**：`def mouseMoveEvent(self, ev)`

移动事件承担**实时预览**职责：绘制预览线、移动选中元素、画布平移、矩形边拖拽预览。

### 3.1 完整优先级链

```
is_loading? / transform_pos 失败 ──► return

[预备] prev_hover_shape = self.h_hape
[预备] prev_move_point = pos
[预备] repaint()
[预备] auto_decode 定时器触发判定 (_should_trigger_auto_decode)
│
├─ 【M0】drawing()  ──── 绘制预览  (canvas.py:728-823)
│     ├─ 计算预览线 line.line_color / shape_type
│     ├─ current 为空 → override_cursor(CURSOR_DRAW); return
│     ├─ rectangle/cuboid → show_shape.emit(高, 宽, pos)
│     ├─ 越界裁剪:
│     │     · 非 rectangle/rotation/quadrilateral/cuboid → intersection_point
│     │     · snapping + polygon + close_enough(起点) → 吸附起点 + 高亮 0 号顶点
│     │     · rotation + close_enough(起点) → 吸附
│     │     · quadrilateral (≥3点) + close_enough → 吸附
│     ├─ Shift + line/linestrip → _snap_line_pos (水平/垂直/45°)
│     ├─ 按 create_mode 写入 self.line 预览
│     ├─ brush 模式 (_brush_drawing && polygon):
│     │     · snapping + close_enough → finalise(); return
│     │     · 距离 ≥ brush_point_distance → current.add_point(pos)
│     └─ return
│
├─ 【M1】RightButton & ev.buttons()  ──── 多边形复制移动  (canvas.py:826-836)
│     ├─ selected_shapes_copy 非空 + prev_point
│     │     → override_cursor(CURSOR_MOVE)
│     │     → bounded_move_shapes(selected_shapes_copy, pos)
│     │     → return
│     └─ selected_shapes 非空
│           → selected_shapes_copy = [s.copy() for s in selected_shapes]  # 建副本
│           → return
│
├─ 【M2】rect_edge_dragging (左键按住中)  ──── 最高优先级守卫  (canvas.py:842-848)
│     │   ※ 注释明确: 必须在下方 M3 的 pan 块之前消费, 否则 scroll_request 会吞掉
│     └─ _rect_edge_drag_update(pos); return
│
├─ 【M3】LeftButton & ev.buttons()  ──── 移动选中元素  (canvas.py:851-935)
│     ├─ ① selected_vertex()
│     │     → bounded_move_vertex(pos)
│     │     → moving_shape = True
│     │     → rectangle/cuboid → show_shape.emit(高, 宽, pos)
│     ├─ ② selected_cuboid_face() && h_hape.shape_type=='cuboid' && prev_point
│     │     → offset = pos - prev_point
│     │     → move_cuboid_face_by(h_hape, h_cuboid_face, offset)
│     │     → prev_point = pos; moving_shape = True; show_shape.emit
│     ├─ ③ selected_shapes && prev_point
│     │     → bounded_move_shapes(selected_shapes, pos)
│     │     → moving_shape = True
│     │     → rectangle/cuboid → show_shape.emit
│     └─ ④ 否则（点空白）
│           → scroll_request.emit(水平/垂直)  ← 左键拖动平移画布
│     · return
│
├─ 【M4】editing() && is_move_editing  ──── 顶点/面移动(无键按住)  (canvas.py:937-983)
│     ├─ override_cursor(CURSOR_MOVE)
│     ├─ selected_vertex() → bounded_move_vertex
│     ├─ selected_cuboid_face() + cuboid → move_cuboid_face_by
│     └─ 否则 → is_move_editing = False
│     · return
│
└─ 【M5】rect_edge_align_enabled (无拖拽)  ──── hover 候选计算  (canvas.py:994-1019)
      ├─ 候选变化 → rect_edge_hover_edge = candidate; update()
      ├─ candidate 非空:
      │     · un_highlight()  ← 清除残留 shape/vertex 高亮
      │     · show_shape.emit(-1, -1, pos)  ← 关闭尺寸提示
      │     · return  ← 抑制默认 hover 循环, 防止整体填充覆盖边高亮
      └─ candidate 为空 → 落入下方默认 hover 循环 (vertex/edge hover)
```

### 3.2 关键插入点说明

#### M2（矩形边拖拽守卫）

```python
# canvas.py:842-848
if (self.rect_edge_align_enabled
    and self.rect_edge_dragging
    and self.rect_edge_active_edge is not None):
    self._rect_edge_drag_update(pos)
    return
```

**为何必须前置**：M3 的 ④ 分支会 `scroll_request.emit()` 把画布拖走。一旦矩形边拖拽的 move 落入 ④，预览丢失且画布被误平移。注释（`canvas.py:985-993`）详细记录了这一历史教训。

#### M4 vs M3 的细微差别

- **M3** 在左键按住时触发，覆盖「拖动整体形状」。
- **M4** 在 `is_move_editing=True`（P2 单击顶点锁定）时触发，无需按住按键，用于「点击锁定后移动顶点」交互。

---

## 4. mouseReleaseEvent（释放）— 提交语义

**位置**：`canvas.py:1560` ｜ **入口签名**：`def mouseReleaseEvent(self, ev)`

释放事件承担**变更提交**职责：弹菜单、提交 undo、取消选区。

```
is_loading? ──► return
│
├─ RightButton:  (canvas.py:1565-1574)
│   ├─ menu = self.menus[len(selected_shapes_copy) > 0]
│   ├─ restore_cursor()
│   └─ menu.exec() 返回 False 且有副本
│         → selected_shapes_copy = []  ← 取消移动(删除副本)
│
├─ LeftButton:  (canvas.py:1575-1614)
│   │
│   ├─ 【R0】rect_edge_dragging → 提交对齐  (canvas.py:1581-1604)
│   │     ├─ 比对 drag_start_points 与当前 points:
│   │     │     · 长度不同 → changed=True
│   │     │     · 任一点坐标不同 → changed=True
│   │     ├─ changed 为 True:
│   │     │     · store_shapes()       ← 入 undo 栈
│   │     │     · shape_moved.emit()   ← 通知 label_widget 持久化
│   │     ├─ clear_rect_edge_alignment(keep_reference=True)
│   │     │     ← 保留参考边以便连续对齐下一目标
│   │     └─ return
│   │
│   └─ 【R1】editing() && h_shape_is_selected && not moving_shape
│         → selection_changed.emit(排除 h_hape)  ← 点击同对象取消选中
│
└─ store_moving_shape()  (canvas.py:1616)
      · 统一收尾: 若本次有移动且几何变化, store_shapes + shape_moved
      · moving_shape = False
```

### 4.1 R0 的提交语义（重要）

矩形边对齐功能刻意做「**变更检测**」：

```python
# canvas.py:1582-1603 (摘要)
changed = (len(current) != len(start_points)
           or 任一点坐标不同)
if changed:
    self.store_shapes()
    self.shape_moved.emit()
self.clear_rect_edge_alignment(keep_reference=True)
```

**为什么**：用户可能点击目标边后没拖动就松手。若无条件入 undo 栈，会污染历史。`keep_reference=True` 让参考边保留，用户可继续对齐下一个目标。

---

## 5. mouseDoubleClickEvent（双击）

**位置**：`canvas.py:1653` ｜ **入口签名**：`def mouseDoubleClickEvent(self, ev)`

```
is_loading? ──► return
│
├─ auto_decode_mode + is_auto_labeling + auto_decode_tracklet
│     → auto_decode_finish_requested.emit(); return  (canvas.py:1658-1665)
│
├─ editing() && double_click_edit_label  (canvas.py:1667-1677)
│     · pos = transform_pos(ev.position())
│     · 遍历 _shape_hit_candidates(pos)  ← 优先级排序(小面积优先)
│         · _undo_pending_edge_point()
│         · 若不在 selected_shapes → selection_changed.emit([shape])
│         · h_shape_is_selected = False
│         · edit_label_requested.emit()
│         · return
│
└─ double_click == 'close' && can_close_shape()  (canvas.py:1683-1688)
      ├─ linestrip : finalise()  (保留 press 加的最后一个点)
      └─ polygon/q... : 若 > 3 点 → pop_point() 后 finalise()
                          (pop 掉 press 在双击前误加的重复点)
```

### 5.1 双击与 press 的协同陷阱

注释（`canvas.py:1679-1682`）记录了一个经典坑：双击事件触发前，`mousePressEvent` 会先触发一次，给 polygon/quadrilateral 多加一个点。因此双击处理需要 `pop_point()` 修正。linestrip 例外——它把 press 加的点当作正式终点保留。

### 5.2 嵌套对象的优先级排序

`_shape_hit_candidates` 用 `(距离, 面积, -stack_index)` 排序，使**重叠/嵌套**场景优先选中内层（小面积）对象。这是从 beta.11 迁移的功能 C，取代了旧的 `reversed + 首次 contains 命中`。

---

## 6. wheelEvent（滚轮）

**位置**：`canvas.py:3672` ｜ **入口签名**：`def wheelEvent(self, ev: QWheelEvent)`

```
mods = ev.modifiers(); delta = ev.angleDelta()
│
├─ 【W0】editing + 滚轮编辑矩形 + 单选 rectangle + 无 Ctrl  (canvas.py:3677-3702)
│     · shape.contains_point(pos)
│         → _scale_rectangle(shape, wheel_up)        整体中心缩放
│     · 否则
│         → _adjust_rectangle_edge(shape, pos, wheel_up)  就近推拉边
│     · store_shapes + shape_moved + accept + return
│
├─ 【W1】Shift + compare_pixmap 非空  (canvas.py:3705-3717)
│     · split_position ±= 0.02 (钳位 [0,1])
│     · split_position_changed.emit()
│     · accept + return
│
├─ 【W2】Ctrl  (canvas.py:3719-3722)
│     · zoom_request.emit(delta.y(), pos)
│
└─ 【W3】默认  (canvas.py:3723-3730)
      · scroll_request.emit(水平) + scroll_request.emit(垂直)

accept()
```

### 6.1 W0 的几何操作

- **`_scale_rectangle(shape, scale_up)`** (`canvas.py:3733`)：以矩形中心为锚点按 `rect_scale_step` 缩放，逐点检查不超出 pixmap 边界。
- **`_adjust_rectangle_edge(shape, cursor_pos, move_outward)`** (`canvas.py:3776`)：找最接近光标的边，向外/内推一个步长。

---

## 7. 状态机字段总览

下表是**贯穿多个事件**的状态变量。修改任何一个都会改变事件流向，必须谨慎评估跨事件影响。

| 字段 | 类型 | 置位点 | 影响的事件分支 |
|------|------|--------|---------------|
| `is_loading` | bool | 加载图片 | 全部事件首道门控 |
| `mode` (`CREATE`/`EDIT`) | enum | `set_mode()` | press P1/P2、move M0/M3/M4 |
| `self.current` | Shape? | press 新建 | press P1「加点 vs 新建」、move M0 |
| `rect_edge_align_enabled` | bool | View 菜单动作 | press P0、move M2/M5、release R0 整条链 |
| `rect_edge_hover_edge` | RectEdgeRef? | move M5 计算 | press P0 是否触发 |
| `rect_edge_reference_edge` | RectEdgeRef? | press P0 第一次点击 | press P0 兼容性判定、move M2 吸附目标 |
| `rect_edge_active_edge` | RectEdgeRef? | press P0 第二次点击 | move M2、release R0 |
| `rect_edge_dragging` | bool | press P0 第二次点击 | move M2 守卫、release R0 提交 |
| `rect_edge_drag_start_points` | list[QPointF]? | press P0 | release R0 变更检测、Esc 恢复 |
| `rect_edge_drag_start_mouse_coord` | float? | press P0 | move M2 计算增量 |
| `rect_edge_drag_start_edge_coord` | float? | press P0 | move M2 计算增量 |
| `rect_edge_snap_active` / `snap_coord` | bool/float? | move M2 | overlay 颜色（绿=已吸附） |
| `rect_edge_invalid_edge` | RectEdgeRef? | press P0 不兼容 | overlay 短暂红色提示 |
| `selected_vertex()` | bool | hover 计算 | press P2、move M3① / M4 |
| `selected_cuboid_face()` | bool | hover 计算 | press P2、move M3② / M4 |
| `is_move_editing` | bool | press P2 顶点翻转 | move M4 |
| `_brush_drawing` | bool | 鼠标按住 polygon | move M0 自动加点 |
| `enable_wheel_rectangle_editing` | bool | 配置 | wheel W0 |
| `selected_shapes_copy` | list | move M1 建副本 | move M1、release 右键取消 |
| `moving_shape` | bool | move M3/M4 | release R1 取消选中判定 |
| `h_hape` / `h_shape_is_selected` | Shape?/bool | hover 计算 | press P2、release R1 |
| `prev_point` / `prev_pan_point` | QPointF? | press/move | move M3 增量计算 |

---

## 8. 矩形边对齐功能时序（跨事件协同）

这是当前分支 `feature/selection-optimization` 的核心功能，跨越 press → move → release（甚至 Esc）三个事件，是理解状态机协同的最佳案例。

### 8.1 完整时序

```
┌─────────────────────────────────────────────────────────────────┐
│  阶段 0: 模式关闭                                                 │
│  rect_edge_align_enabled = False                                 │
│  所有 rect_edge_* 字段 = None/False                              │
└─────────────────────────────────────────────────────────────────┘
                            │ 用户在 View 菜单启用
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 1: Hover 探测 (持续, move M5)                              │
│  rect_edge_align_enabled=True, editing()=True, 无左键按下        │
│                                                                  │
│  move 事件落入 M5:                                                │
│    candidate = _rect_edge_hit_candidate(pos)                     │
│    若候选变化 → rect_edge_hover_edge = candidate; update()       │
│    candidate 非空 → un_highlight() + show_shape(-1,-1) + return  │
│    ↑ 抑制默认 hover 循环, 防止整体填充覆盖边高亮                   │
└─────────────────────────────────────────────────────────────────┘
                            │ 左键按下
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 2a: 第一次点击 (press P0)                                   │
│  条件: hover_edge is not None                                    │
│                                                                  │
│  reference_edge 为空:                                            │
│    rect_edge_reference_edge = hover   ← 锁定参考边(蓝色)         │
│    return                                                        │
└─────────────────────────────────────────────────────────────────┘
                            │ 用户移到目标边, 再次左键按下
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 2b: 第二次点击 (press P0)                                   │
│  reference_edge 非空, hover 指向另一条边                          │
│                                                                  │
│  edges_are_compatible(reference, hover)?                         │
│    ├─ 是 (同轴, 不同形状):                                        │
│    │     rect_edge_active_edge           = hover                 │
│    │     rect_edge_dragging              = True                  │
│    │     rect_edge_drag_start_points     = list(hover.shape.points)│
│    │     rect_edge_drag_start_edge_coord = hover.coord           │
│    │     rect_edge_drag_start_mouse_coord = pos.x() 或 .y()      │
│    │     return                                                  │
│    └─ 否 (异轴 or 同形状):                                       │
│          rect_edge_invalid_edge = hover  ← 红色短暂提示          │
│          return                                                  │
└─────────────────────────────────────────────────────────────────┘
                            │ 左键按住拖动
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 3: 实时拖拽预览 (move M2, 最高优先级守卫)                   │
│  rect_edge_dragging=True                                         │
│                                                                  │
│  _rect_edge_drag_update(pos):                                    │
│    coord = start_edge_coord + (current_mouse - start_mouse)      │
│    ↑ 用增量而非绝对值, 防止首帧跳变                              │
│                                                                  │
│    吸附判定:                                                     │
│      snap_threshold_image = RECT_EDGE_SNAP_SCREEN_PX / scale     │
│      if |coord - reference.coord| ≤ threshold:                   │
│          coord = reference.coord   ← 吸附到参考边                │
│          snap_active = True        ← overlay 变绿                │
│                                                                  │
│    rea.apply_edge_coord(active.shape, edge_name, coord)          │
│      ↑ 原地修改 shape.points (预览)                              │
│    刷新 active_edge (使 overlay 跟随预览位置)                     │
│    update()                                                      │
└─────────────────────────────────────────────────────────────────┘
                            │ 左键释放
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 4: 提交 (release R0)                                       │
│  rect_edge_dragging=True                                         │
│                                                                  │
│  变更检测:                                                       │
│    changed = (len(current) ≠ len(start_points)                   │
│              or 任一点坐标不同)                                  │
│  if changed:                                                     │
│      store_shapes()       ← 入 undo 栈                           │
│      shape_moved.emit()   ← 通知 label_widget 持久化             │
│  clear_rect_edge_alignment(keep_reference=True)                  │
│    ↑ 清拖拽/吸附/无效态, 保留 reference_edge                     │
│  return                                                          │
└─────────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
   继续对齐下一目标              按 Esc / 切模式
   (回到阶段 2b)                 → clear_rect_edge_alignment()
                                (清 reference_edge)
```

### 8.2 Esc 取消语义

`_handle_rect_edge_escape` (`canvas.py:3976`)：

```
rect_edge_dragging 为 True?
  → cancel_rect_edge_drag()  ← 用 drag_start_points 恢复 shape
  → keep_reference=True      ← 仍保留参考边
  → return True
rect_edge_reference_edge 非空?
  → clear_rect_edge_alignment()  ← 清参考边
  → return True
否则 return False  ← 交给默认 Esc 行为
```

### 8.3 不变量与边界

- **一次释放 = 一次 undo 粒度**：release R0 通过变更检测保证无操作不入栈。
- **参考边跨次保留**：用户可连续对齐多个目标到同一条参考边，无需每次重选。
- **Esc 永不切模式**：Esc 只取消拖拽或清参考边，不关功能本身（View 菜单动作才切）。
- **吸附阈值随缩放反比**：`RECT_EDGE_SNAP_SCREEN_PX / scale` —— 屏幕像素固定，图像坐标系下随放大而收紧。

---

## 9. Undo / 持久化语义

### 9.1 `store_shapes()` — 入栈

**位置**：`canvas.py:345`

```python
def store_shapes(self):
    if getattr(self, "_pending_initial_backup", False) and self.shapes:
        # 首次编辑前快照（如打开文件后第一次操作）
        ...
    shapes_backup = [s.copy() for s in self.shapes]
    if len(self.shapes_backups) > self.num_backups:
        self.shapes_backups = self.shapes_backups[-self.num_backups - 1:]
    self.shapes_backups.append(shapes_backup)
```

**调用点**：`finalise()`（绘制完成）、release R0（矩形边对齐提交）、`store_moving_shape()`（移动提交）、wheel W0（滚轮编辑矩形）。

### 9.2 `store_moving_shape()` — 移动收尾

**位置**：`canvas.py:360`

```
若 moving_shape=True:
  对 h_hape + selected_shapes 逐个检查:
    若 points 变化 → store_shapes() + shape_moved.emit(); break
  moving_shape = False
```

**设计意图**：移动过程中不频繁入栈，仅在 release 时一次性提交。

### 9.3 调用约束

- `store_shapes()` 是「重操作」（深拷贝所有 shape），**禁止在 move 事件中调用**。
- release / wheel / finalise 是合法调用点。
- `_pending_initial_backup` 用于「打开文件首次操作」的额外快照，配合 `_pending_edge_point` 等待标记。

---

## 10. 候选选择与命中检测

### 10.1 `_shape_hit_candidates(pos)` — 通用优先级排序

贯穿 `select_shape_point`、双击编辑、矩形边对齐候选计算。排序键：

```
(命中类型优先级, 距离, 面积, -stack_index)
```

- **命中类型**：顶点 > 边 > 内部
- **距离**：越近越优
- **面积**：越小越优（嵌套场景优先内层）
- **stack_index**：越新创建越优（`-` 使新的排前）

### 10.2 `_rect_edge_hit_candidate(point)` — 矩形边专用

**位置**：`canvas.py:3995`

约束：
- 仅在 `rect_edge_align_enabled && editing()` 时运行；
- **顶点命中优先于边命中**：若某形状有顶点在 epsilon 内，跳过该形状的边候选；
- 排序键同 `_shape_hit_candidates`。

---

## 11. 常见回归与陷阱清单

| 现象 | 根因 | 涉及位置 |
|------|------|---------|
| 矩形边对齐点击无反应 | P0 放在了 P1/P2 之后被吞 | press 链顺序 |
| 矩形边拖拽时画布跟着平移 | M2 守卫缺失，move 落入 M3④ 的 scroll_request | move M2 |
| hover 矩形边时整体被填充覆盖 | M5 未 `un_highlight()` + return | move M5 |
| 双击 polygon 多一个点 | press 在双击前先触发加了一点 | doubleClick 需 pop_point |
| 无操作点击也进 undo | release R0 缺变更检测 | release R0 |
| Esc 关掉了功能而非取消拖拽 | `_handle_rect_edge_escape` 未优先处理 dragging | Esc 处理 |
| 菜单/Canvas 状态不同步 | View 菜单 action 与 `rect_edge_align_enabled` 未双向绑定 | `78c8327` 修复 |
| 顶点拖拽时尺寸提示不刷新 | move M3① 未对 rectangle/cuboid emit show_shape | move M3 |

---

## 12. 新增鼠标交互的接入指南

若要新增一个鼠标交互功能，按以下清单接入：

### 12.1 决策插入点

1. **是否需要跨事件状态？**
   - 是 → 定义一组前缀化字段（如 `xxx_hover` / `xxx_dragging` / `xxx_start_*`），参考矩形边对齐。
   - 否 → 单事件内完成。

2. **优先级？**
   - 必须早于 `drawing()/editing()` 主分流 → 插在 press P0 区。
   - 必须早于左键 pan → 插在 move M2 区（守卫形式）。
   - 否则按语义插入对应子链。

3. **提交时机？**
   - release 时提交 → 用变更检测 + `store_shapes()` + `shape_moved.emit()`。
   - 禁止在 move 中 `store_shapes()`。

### 12.2 必做检查项

- [ ] 保留 `if self.is_loading: return` 首道门控。
- [ ] 用 `pos = self.transform_pos(ev.position())` 转坐标。
- [ ] 功能开关字段（`xxx_enabled`）门控所有新增分支。
- [ ] release 提交前做变更检测，避免污染 undo。
- [ ] 添加 Esc 取消路径（`keyPressEvent` 中）。
- [ ] 注释说明「为何必须在此 return」（给后人留护栏）。
- [ ] 关闭功能时调用 `clear_xxx()` 清所有状态字段。

### 12.3 测试建议

- 优先用 pytest 模拟事件序列（参考 `tests/` 下矩形边对齐用例）。
- 关键场景：功能开/关、加载中、与 drawing/editing 模式冲突、Esc 中断、连续操作（keep_reference 语义）。

---

## 13. 文件位置索引

| 内容 | 行号 |
|------|------|
| `mouseMoveEvent` | 703 |
| `mousePressEvent` | 1291 |
| `mouseReleaseEvent` | 1560 |
| `mouseDoubleClickEvent` | 1653 |
| `wheelEvent` | 3672 |
| `drawing()` / `editing()` | 620 / 624 |
| `store_shapes()` / `store_moving_shape()` | 345 / 360 |
| `transform_pos()` | 3472 |
| `bounded_move_vertex()` / `bounded_move_shapes()` | 2214 / 2265 |
| `select_shape_point()` | 1700 |
| `_rect_edge_drag_update()` | 3879 |
| `clear_rect_edge_alignment()` | 3933 |
| `cancel_rect_edge_drag()` | 3954 |
| `_handle_rect_edge_escape()` | 3976 |
| `_rect_edge_hit_candidate()` | 3995 |
| `_scale_rectangle()` / `_adjust_rectangle_edge()` | 3733 / 3776 |

---

## 14. 附录：信号流总图

```
┌─────────────────── 用户鼠标操作 ───────────────────┐
│                                                    │
│  Move / Press / Release / DoubleClick / Wheel      │
│                                                    │
└──────────────────────┬─────────────────────────────┘
                       │ Qt 派发
                       ▼
              ┌────────────────────┐
              │   Canvas (canvas.py)│
              │                    │
              │  is_loading 门控    │
              │  transform_pos     │
              │  线性短路优先级链   │
              │                    │
              └──────┬─────────────┘
                     │ 信号派发
                     ▼
   ┌─────────────────────────────────────────┐
   │ scroll_request  zoom_request            │
   │ selection_changed  shape_moved          │
   │ drawing_polygon  show_shape             │
   │ mode_changed  edit_label_requested      │
   │ split_position_changed                  │
   │ auto_decode_finish_requested            │
   └────────────────────┬────────────────────┘
                        │
                        ▼
            ┌────────────────────────┐
            │  label_widget.py       │
            │  (不重写任何鼠标事件)   │
            │  仅订阅信号做持久化/   │
            │  UI 同步/状态栏更新    │
            └────────────────────────┘
```

---

**文档版本**：v1.0
**基准 commit**：`78c8327`
**维护建议**：每次新增鼠标交互功能时，更新第 7 节状态机字段表与第 11 节陷阱清单。

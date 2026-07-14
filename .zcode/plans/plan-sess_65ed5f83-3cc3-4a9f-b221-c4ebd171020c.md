# 实现计划 — manual-person-annotation-refinement

基于已批准的 `proposal.md` / `design.md` / `tasks.md`（含 N1/N2/N3 三项决策）。
所有 `file:line` 引用基于当前 `feature/selection-optimization` 分支。

## 一、架构总览

### 新增文件（2 个）
| 文件 | 类型 | 职责 |
|------|------|------|
| `anylabeling/views/labeling/widgets/digit_bind_draw_manager.py` | plain object（对称 `DigitRenameManager`） | bind_draw 规则、pending context、双校验、操作提示生成 |
| `anylabeling/views/labeling/edge_snap.py` | **纯 Python**（不依赖 PyQt6，可单测） | 灰度+梯度缓存、法线方向评分、median 聚合、双判据阈值 |

### 修改文件（4 个）
| 文件 | 改动 |
|------|------|
| `anylabeling/configs/xanylabeling_config.yaml` | +4 配置 key（Decision 13） |
| `anylabeling/views/labeling/settings/schema.py` | allow-list 登记 4 key |
| `anylabeling/views/labeling/label_widget.py` | `create_digit_mode` 分流、`new_shape` 消费 pending context、`load_file` 清理、状态栏提示、修饰键判定 |
| `anylabeling/views/labeling/widgets/canvas.py` | 精修虚拟光标、键盘选边状态机、undo 合并、`store_shapes` 时间戳、hover 退出键盘选边、edge snap 触发、新状态 slots |

### 新增测试（4 个文件，对应 task 7.1-7.23）
`tests/test_auto_person_instance.py`、`tests/test_digit_bind_draw_manager.py`、`tests/test_precision_mode.py`、`tests/test_edge_snap.py`

---

## 二、关键技术决策（spec 未明示，实现必定的 6 项）

| # | 决策 | 理由 / 锚点 |
|---|------|-------------|
| D1 | **`DigitBindDrawManager` 为 plain object**，状态提示用 `self._label_widget.status(msg, delay)`（`label_widget.py:3351`），i18n 用 `self._label_widget.tr(...)` | 对称 `DigitRenameManager`（`digit_rename_manager.py:41` 无基类）。修正 design.md 的"context=DigitShortcutHints"——代码库标注子系统全用 `self.tr()`，无 `QCoreApplication.translate`，实现上 context 归到 label_widget 类名，功能等价 |
| D2 | **来源回填时序**：在 `new_shape` 的 `label_widget.py:6619`（`set_last_label` 调用）**之前**执行 `source.group_id = gid` | `set_last_label` 内部 `canvas.py:4896` 调 `store_shapes()` 是新建的 undo 推送点；回填在其前才能合并到同一快照（Q5/task 3.13） |
| D3 | **pending context 消费点**：`label_widget.py:6572`（`last_label=` 之后）与 `6573`（`last_gid=` 之前）之间 | Decision 3 优先级要求 pending context 早于 `auto_use_last_gid` 的 `last_gid` 计算 |
| D4 | **虚拟光标隔离**：新 slot `self._virtual_prev_point`（`canvas.py:154` 附近），**绝不写入 `self.prev_point`** | `move_by_keyboard`（`canvas.py:4772`）复用 `prev_point`；污染会破坏键盘微调。精修模式走独立 `_precision_move(pos)` 路径，不调 `bounded_move_shapes` |
| D5 | **undo 合并**：`store_shapes`（`canvas.py:389`）加 `self._last_snapshot_ts`，append 前检查 `now - ts < 0.5` 则 `shapes_backups[-1] = backup`（替换）而非 append | timestamp-based，无 QTimer，无延迟落盘（N2）。合并只在键盘微调路径触发（加 `merge=True` 参数），不影响其他 13 个调用点 |
| D6 | **精修修饰键 = `Ctrl`（按住临时）**，另加可选 toggle 锁定（快捷键暂用未占用的 `Ctrl+Alt+R`，避开了 `Ctrl+Alt+P`=stable_preview） | Alt 被 snapping 占用（`canvas.py:4829`），Shift 留给 5px，Ctrl+Shift+E 已是 rect_edge toggle |

---

## 三、分阶段实现（6 阶段）

阶段间依赖：**阶段 0 是所有前置**；1/2/3/4 相对独立；5 依赖全部。

### 阶段 0：配置与 schema（task 1.1-1.5）

**改动**：
- `xanylabeling_config.yaml`：新增 `auto_person_instance: false`、`digit_shortcut_mode: rename`、`canvas_precision_factor: 4`、`canvas_edge_snap_range: 4`
- `settings/schema.py`：allow-list 登记（参照 `auto_use_last_label` 在 `schema.py:179`）

**验证 V1**：确认扁平顶层 key（`canvas_precision_factor`）与现有 `canvas:` 嵌套块（`xanylabeling_config.yaml:100`）共存时 `config.py` 不报 schema 错——用 `py_compile` + 一个加载配置的 smoke 测试。

---

### 阶段 1：功能 1 — auto_person_instance（task 2.1-2.7）

**改动 `label_widget.py:new_shape`**（`6527-6646`）：
- 在 `6578`（`if self.digit_to_label is not None:` 分支内）和 `6583`（`auto_use_last_label` 分支）之前插入功能 1 检查：
  ```
  if (config["auto_person_instance"]
      and text == "person"
      and target_shape_type == "rectangle"
      and bind_pending is None
      and group_id is None):
      group_id = self.canvas.gen_new_group_id()
      self.status(self.tr("已创建 person #%d") % group_id, 2000)
  ```
- 优先级：`bind_pending`（阶段 2 接入）> 功能 1 > `auto_use_last_gid`（现有 `last_gid`）。功能 1 命中时短路 `last_gid`。
- task 2.7：在 `finish_auto_labeling_object`（`8620`）显式不加功能 1 逻辑，配 test 7.16。

**测试**：`test_auto_person_instance.py` — test 7.1（自动生成）、7.2（不与 auto_use_last_label 互斥）、7.3（优先于 auto_use_last_gid）、7.16（不作用于 auto-labeling）。

---

### 阶段 2：功能 2 + 操作提示（task 1.6/1.7、3.1-3.14、4.1-4.8）

**新文件 `digit_bind_draw_manager.py`**（镜像 `digit_rename_manager.py:41-209`）：
```
class DigitBindDrawManager:
    def __init__(self, label_widget)
    def is_active(self) -> bool          # config["digit_shortcut_mode"] == "bind_draw"
    def handle_digit(self, digit) -> bool  # 主入口，返回是否消费
    def _resolve_target(self, digit)      # 读 digit_shortcuts 映射 → label+shape_type
    def _validate_source(self)            # 单选 + person/head/face
    def _resolve_gid(self, source)        # 继承或拟分配（记录 need_backfill）
    def _check_duplicate(self, gid, label, shape_type)  # 双校验入口
    def consume_pending(self) -> (label, gid, source, backfill) | None  # new_shape 调用
    def clear_pending(self)               # 清理点调用
    def _hint(self, ...)                  # 生成提示，走 label_widget.status
```
- pending context 字段（task 1.6）：`source_ref`、`target_label`、`target_shape_type`、`gid`、`need_backfill`。

**改 `label_widget.py:create_digit_mode`**（`3866-3886`）：
```
def create_digit_mode(self, digit_num):
    if self._config["digit_shortcut_mode"] == "bind_draw":
        self.digit_bind_draw_manager.handle_digit(digit_num)
        return
    if self.digit_rename_manager.is_rename_mode_active():
        ...（现有 rename 路径不变）
```

**改 `label_widget.py:new_shape`**（D3 锚点 `6572-6573` 之间）：
```
pending = self.digit_bind_draw_manager.consume_pending()
if pending is not None:
    # 再次校验（task 3.11）
    if self.digit_bind_draw_manager._check_duplicate(pending.gid, pending.target_label, pending.target_shape_type):
        self.digit_bind_draw_manager.clear_pending()
        self.canvas.undo_last_line()  # 取消刚画的空 shape
        return
    text, group_id = pending.target_label, pending.gid
    if pending.need_backfill and pending.source_ref in self.canvas.shapes:
        pending.source_ref.group_id = pending.gid  # D2：在 set_last_label(6619) 前
    self.digit_bind_draw_manager.clear_pending()
# ...（现有 last_gid 计算在 6573）
```

**清理点（task 1.7/3.14）**：`load_file`（`7230`）、` Esc`、`toggle_draw_mode` 切换、`undo_shape_edit` 调 `clear_pending()`。

**提示 + 去抖（task 4.x）**：`_hint` 内对"选中变化"用 `QTimer.singleShot(200, ...)` 去抖（task 4.7）；仅在 `bind_draw` 模式响应选中变化（task 4.3）。

**测试**：`test_digit_bind_draw_manager.py` — test 7.4-7.8、7.14（undo 原子性）、7.15（Esc 后来源不变）、7.18（pending 期间禁用冲突操作）。

---

### 阶段 3：功能 3 — 精修控制模式（task 5.1-5.16）

**新状态 slots**（`canvas.py:154` 与 `274-282` 附近）：
```
self._virtual_prev_point = None      # D4 隔离
self.precision_mode_locked = False   # toggle 锁定
self.rect_edge_keyboard_edge = None  # 键盘选边（None=整体移动）
self.rect_edge_keyboard_shape = None
self._last_snapshot_ts = 0.0         # D5 undo 合并
```
扩展 `clear_rect_edge_alignment`（`canvas.py:4412`）清键盘选边。

**精修拖动（D4，task 5.1-5.6）**：
- `mouseMoveEvent`（`canvas.py:761` 之后、拖动分支 `889/905/914` 之前）加：
  ```
  if self._precision_active():  # Ctrl 按住 或 locked
      if self._virtual_prev_point is None:
          self._virtual_prev_point = self.prev_point
      eff_pos = self._virtual_prev_point + (pos - self._virtual_prev_point) / self.precision_factor
      self._virtual_prev_point = eff_pos
  else:
      eff_pos = pos
  ```
  仅把 `eff_pos` 传入三个拖动分支的 `bounded_move_*` / `_rect_edge_drag_update` 调用；hit-test 仍用 `pos`。
- `mousePressEvent` 的 `prev_point` 重置点（`1579/1597/2447`）同步重置 `_virtual_prev_point = None`。
- `_precision_active()` = `precision_mode_locked or (ev.modifiers() & CtrlModifier)`。
- 状态栏提示倍率（task 5.6）：进入/退出时 `label_widget.status(...)`。

**键盘选边状态机（task 5.9-5.12，N1）**：
- `_dispatch_default_key_press`（`canvas.py:4831` editing 分支顶部）加 `Key_Tab` 处理：选中单 rectangle 时进入，循环 `left→top→right→bottom→left`。
- **N1**：`mouseMoveEvent` 的 `canvas.py:1070`（`rect_edge_hover_edge` 更新后）加：hover 到任意边时 `self.rect_edge_keyboard_edge = None` 并重绘。
- 退出条件：Esc、切选、切图、绘制模式、点空白、**hover 到任意边**。

**键盘微调（task 5.7/5.8/5.13-5.16）**：
- 改 `canvas.py:44` `MOVE_SPEED = 5.0` 语义：方向键默认 1px，Shift 时 5px。在 `4832-4839` 分支读 `ev.modifiers() & ShiftModifier` 选步长。
- 键盘选边存在时：方向键走 `apply_edge_coord(shape, edge, coord ± step)`（task 5.13/5.14），否则走 `move_by_keyboard`（task 5.7/5.8）。
- 单边微调设 `self.moving_shape = True` 以触发 `keyReleaseEvent`（`canvas.py:4875`）的 undo 提交。

**undo 合并（D5，task 5.15）**：
- `store_shapes` 加可选参数 `merge_window=0.0`；键盘微调路径传 `merge_window=0.5`。append 前检查 `time.monotonic() - self._last_snapshot_ts < merge_window` 则替换 `shapes_backups[-1]`。

**测试**：`test_precision_mode.py` — test 7.9（降速 1/4）、7.10（1px/5px）、7.17（连续拖动无漂移）、7.20（hover 退出键盘选边）、7.21（undo 合并）。

---

### 阶段 4：功能 4 — 局部边缘吸附（task 6.1-6.14）

**新文件 `edge_snap.py`（纯 Python）**：
```
class EdgeSnapCache:
    def __init__(self): self._key = None; self._gray = None; self._grad = None
    def ensure(self, gray_array, cache_key)  # 懒构建，cacheKey 变化失效
    def gradient_x(self) -> np.ndarray
    def gradient_y(self) -> np.ndarray

def score_edge(cache, edge_axis, edge_coord, p1, p2, search_range) -> List[(coord, score)]
    # 法线方向梯度，沿边中段采样，median 聚合（task 6.5/6.6）

def best_snap_candidate(cache, edge_name, geom, search_range, k, abs_floor) -> Optional[float]
    # 双判据（N3）：score >= k*local_max and score >= abs_floor
```
- 阈值硬编码（task 6.8 保留 hook）：`k=0.6`、`abs_floor=10.0`（梯度强度），实现时调参。
- 灰度源：`canvas.pixmap.toImage()` → np（`canvas.py` 顶部 `import cv2, numpy as np`）。

**改 `canvas.py`**：
- 新 slot `self._edge_snap_cache = EdgeSnapCache()`；`load_pixmap`（`4931`）失效缓存。
- 触发（task 6.11）：新增 `snap_active_edge()` 方法，由按键调用（绑定未占用快捷键，候选 `Ctrl+Shift+S`，避开 `Ctrl+Shift+E`）。
- validate-before-apply（task 6.10，Q11）：
  ```
  geom = rea.geometry_from_shape(shape)
  cand = best_snap_candidate(...)  # None 即失败
  if cand is None: 失败提示; return
  test_geom = rea.geometry_with_edge_coord(geom, edge, cand, min_size)  # pure
  if <test_geom 对应 coord != cand>:  # 触发 clamp
      失败提示; return
  rea.apply_edge_coord(shape, edge, cand, min_size)  # 不会 raise
  store_shapes(); shape_moved.emit()  # task 6.14 undo
  ```
- 成功/失败提示（task 6.12/6.13）走 `label_widget.status(...)`。

**测试**：`test_edge_snap.py` — test 7.11（强边缘命中）、7.12（低响应不移动）、7.13（翻转/最小尺寸）、7.19（clamp 时保持原位）、7.22（仅自适应满足不吸附）、7.23（仅绝对下限满足不吸附）。

---

### 阶段 5：集成互斥 + 验证 + 文档（task 7 余、8.x、Decision 12）

**Decision 12 互斥**：
- `edge_snap` 触发前检查 `digit_bind_draw_manager` pending 为空；非空则提示拒绝。
- `handle_digit` 前检查 `rect_edge_keyboard_edge is None`；非空则提示退出键盘选边后再绑定绘制。

**文档/i18n（task 8.7）**：所有新文案用 `label_widget.tr(...)`；更新 `.ts` 并跑 `scripts/compile_languages.py`（AGENTS.md 指明）。

**验证清单**：
- V1（阶段 0）：扁平 key 与 config.py 兼容。
- V2（阶段 2）：pending context 消费在 `last_gid` 之前。
- V3（阶段 4）：阈值双判据用中等对比度合成图验证。
- 8.1-8.6 手工验证：rename 旧行为、bind_draw 流程、100/200/400% zoom 手感、stable_preview + rect_edge 不回归。

---

## 四、执行顺序与依赖

```
阶段 0（配置/schema）
   ├─→ 阶段 1（功能 1）        独立
   ├─→ 阶段 2（功能 2+提示）   依赖 0
   ├─→ 阶段 3（功能 3 精修）   独立
   └─→ 阶段 4（功能 4 吸附）   独立
          └─→ 阶段 5（互斥+集成+文档）依赖 1-4
```
推荐顺序：0 → 1 → 2 → 3 → 4 → 5。每阶段完成后跑对应测试 + `black -l 79` + `flake8`。

## 五、风险与缓解
- **Q7 漂移**：D4 隔离 `_virtual_prev_point`，测试 7.17 守护。
- **Q5 原子性**：D2 回填在 `set_last_label` 前，测试 7.14 守护。
- **Q11 clamp**：阶段 4 validate-before-apply，测试 7.19 守护。
- **键盘 y 轴取反**：`canvas.py:4832` 现状 Up=-5，阶段 3 改 1px 时保持取反语义。
- **不回归**：阶段 5 的 8.3/8.6 手工验证 rename/rect_edge/stable_preview 旧行为。

## 六、不引入新依赖
`cv2`、`numpy` 已在仓库（`label_widget.py:12`、`utils/qt.py:138`）。`edge_snap.py` 复用。

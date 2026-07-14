# 08 · 数字快捷绑定绘制
#### Digit Bind Draw

> 选中一个 `person/head/face` 矩形作为来源，按数字快捷键新建同一人物实例下的其他框，自动**继承或补齐** `group_id`。一个独立的 `DigitBindDrawManager` 承载全部状态机逻辑，与 `LabelWidget` 通过 4 处窄接口协作。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

人物标注中「给已有 person 补 head/face」是高频操作。原生流程：

```
画 person 框（group_id = 7）
  → 记住这个 7
  → 画 head 框 → 弹对话框 → 输入 "head" → 手动在 group_id 填 7
  → 画 face 框 → 弹对话框 → 输入 "face" → 手动在 group_id 填 7
  → 一旦填错/忘填，person-head-face 三类就不关联了，下游质检全乱
```

痛点是**人工把 group_id 从来源框"抄"到新框**——既慢又错。

---

## 方案：来源驱动 + 数字快捷触发

把「重命名」模式的数字键（选中对象按数字键改 label）扩展出第二个互斥模式 **`bind_draw`**：

```
选中一个 person/head/face 来源框
  → 按某个数字键（该键已绑定 head + rectangle）
  → 自动进入 head 矩形绘制
  → 画完后新框自动继承来源的 group_id
```

| 模式 | 行为 |
|------|------|
| `rename`（默认） | 选中对象后按数字键 → 改 label |
| `bind_draw` | 选中来源对象后按数字键 → 绑定绘制（继承/回填 gid） |

`group_id` 解析有两种情形：

```
来源已有 gid → 继承            (need_backfill = False)
来源没有 gid → 现生成一个新 gid，画完时同时回填来源和新框  (need_backfill = True)
```

---

## 技术亮点

### 1. 独立管理器 + 窄接口

全部状态机逻辑收敛进 `DigitBindDrawManager`（414 行，纯 Python，镜像 `DigitRenameManager`）。它与 `LabelWidget` 只通过 **4 处窄接口**协作：

| 调用点 | 接口 | 时机 |
|--------|------|------|
| `create_digit_mode` | `handle_digit(digit_num)` | 数字键按下 |
| `new_shape` | `consume_pending()` | 绘制完成提交 |
| `undo`/`load_file`/模式切换 | `clear_pending()` | 取消/切图/切模式 |
| `trigger_edge_snap` | 读 `pending is not None` | 拒绝守卫 |

`LabelWidget` 不持有任何 bind_draw 状态细节——状态全在管理器里，主控件只负责生命周期钩子。

### 2. 懒回填：来源 group_id 绝不在按下时写

关键设计决策（D2）：**来源对象的 `group_id` 在按数字键时绝不立即写入**。即使需要回填，也只标记 `need_backfill=True`，真正的写操作推迟到 `consume_pending` 由调用方执行。

为什么？**撤销原子性**。如果在按下时就写来源 gid，绘制过程中用户按 Esc 取消，来源框已经被改了——而新框没创建，留下一个孤立的、无法对应到一次「创建新 shape」操作的修改，undo 栈对不上。

懒回填保证「来源回填 + 新框创建」落在**同一个 `store_shapes` 快照**里，一次 undo 一起回退：

```python
# label_widget.py:6567-6582
def _consume_digit_bind(self, last_gid):
    pending = self.digit_bind_draw_manager.consume_pending()
    if pending is None:
        return None
    p_label, p_gid, p_source, p_backfill = pending
    if p_backfill and p_source in self.canvas.shapes:
        p_source.group_id = p_gid    # 回填来源（紧贴新框创建之前）
    self.digit_bind_draw_manager.clear_pending()
    return p_label, p_gid
```

`clear_pending()` 的 docstring 明确：「来源 shape 的 group_id 从未写过（懒回填），所以无需 revert」。

### 3. 两阶段防重复（TOCTOU 守卫）

同 `group_id` 下不允许出现两个相同 label（防止同组两个 person）。重复检测在**两个时机**各做一次：

```
按下数字键时（Stage 1）   ──  _group_has_label(gid, target_label) → 拒绝进绘制
        │
        ▼ 进入绘制（期间数据可能变化）
提交时（Stage 2，TOCTOU） ──  consume_pending 再查一次 → 拒绝提交
```

```python
# digit_bind_draw_manager.py:168-205（consume_pending）
def consume_pending(self):
    if self._pending is None:
        return None
    ctx = self._pending
    # TOCTOU：绘制期间可能出现重复
    if self._group_has_label(ctx.gid, ctx.target_label):
        self._hint_duplicate(ctx.gid, ctx.target_label)
        self._pending = None
        return None
    ...
```

Stage 1 挡住「按下时已重复」，Stage 2 挡住「绘制过程中第三方把同组同 label 加进来了」——经典的 TOCTOU（Time-Of-Check-To-Time-Of-Use）防御。

### 4. 与功能 1 的边界：单点决策表

「未选中对象 + person 数字键」应当走 [Auto Person Instance（07）](07-auto-person-instance.md) 而非 bind_draw。这个边界在 `handle_digit` 入口处用一个**早于来源校验**的判断短路：

```python
# digit_bind_draw_manager.py:125-131
if self._can_start_unbound_person_instance(target_label, target_shape_type):
    self._enter_unbound_person_draw(digit_num, target_label, target_shape_type)
    return True   # 短路，不进来源校验
# 下面才是正常的 bind_draw 来源校验
```

完整边界：

| 状态 | 按数字键行为 |
|------|-------------|
| 未选中 + person/rectangle + 功能1开启 | 功能1：未绑定 person 绘制，完成后生成新 gid |
| 选中 person/head/face 来源 | 功能2：绑定绘制，继承/回填 gid |
| 未选中 + head/face | 拒绝，提示先选来源 |
| bind_draw pending 中再按数字键 | 拒绝（`_hint_pending_active`，防栈叠） |

### 5. 四处取消守卫，来源零副作用

`clear_pending()` 从四个钩子调用，每个都附注释说明为何安全：

| 钩子 | 位置 | 原因 |
|------|------|------|
| `undo_shape_edit` | `label_widget.py:3519` | 来源从未写过 gid，无需 revert |
| `load_file` | `label_widget.py:7424` | 切图后来源引用失效 |
| 提交后 | `label_widget.py:6581` | 正常清理 |
| 模式切换 | `runtime_applier.py:472` | 换模式即作废 pending |

---

## 代码定位

| 位置 | 行数 | 说明 |
|------|------|------|
| [`digit_bind_draw_manager.py`](../../anylabeling/views/labeling/widgets/digit_bind_draw_manager.py) | 414 | `DigitBindDrawManager` 全部状态机 |
| [`digit_bind_draw_manager.py:280-293`](../../anylabeling/views/labeling/widgets/digit_bind_draw_manager.py) | — | `_resolve_gid` 继承/回填逻辑 |
| [`digit_bind_draw_manager.py:168-205`](../../anylabeling/views/labeling/widgets/digit_bind_draw_manager.py) | — | `consume_pending` TOCTOU 守卫 |
| [`digit_bind_draw_manager.py:306-333`](../../anylabeling/views/labeling/widgets/digit_bind_draw_manager.py) | — | 与功能1边界（`_can_start_unbound_person_instance`） |
| [`label_widget.py:3899-3905`](../../anylabeling/views/labeling/label_widget.py) | — | `create_digit_mode` 委托入口 |
| [`label_widget.py:6567-6582`](../../anylabeling/views/labeling/label_widget.py) | — | `_consume_digit_bind` 提交 + 回填 |
| [`label_widget.py:7253`](../../anylabeling/views/labeling/label_widget.py) | — | edge_snap 拒绝守卫 |
| [`schema.py:417-431`](../../anylabeling/views/labeling/settings/schema.py) | — | `digit_shortcut_mode` enum（rename/bind_draw） |
| [`digit_shortcut_page_manager.py`](../../anylabeling/views/labeling/widgets/digit_shortcut_page_manager.py) | 312 | 数字键分页（0-9 → 多页索引解析） |

---

## 测试覆盖

[`tests/test_digit_bind_draw_manager.py`](../../tests/test_digit_bind_draw_manager.py)（19 个测试，纯单测，host 用 `SimpleNamespace` mock，无 Qt）：

| 分组 | 测试 | 验证点 |
|------|------|--------|
| **gid 继承** | `test_7_4_*` | 来源 gid=7 → pending.gid==7，need_backfill==False |
| **gid 回填** | `test_7_5_*` | 来源无 gid → 生成 1，need_backfill==True；consume 返回 `("person",1,source,True)` |
| **生命周期** | `test_7_5_consume_then_clear_*` | consume 不清 pending，需显式 clear |
| **防重复** | `test_7_6_*` | Stage 1 拒绝（同组已有 target label） |
| **TOCTOU** | `test_7_6b_*` | Stage 2 拒绝（绘制期间出现重复） |
| **来源校验** | `test_7_7*` | 多选/无选/坏 label/坏 shape_type 全拒绝 |
| **功能1边界** | `test_no_source_person_*` | 未选 + person + 功能1开 → 未绑定绘制 |
| **功能1边界** | `test_no_source_head_*` | 未选 + head → 仍要求来源（例外仅 person） |
| **目标校验** | `test_invalid_target_*` | 非 bind label / 非 rectangle / 未映射全拒绝 |
| **懒回填** | `test_7_15_*` | clear_pending 后来源 gid 仍为 None（零副作用） |
| **undo 原子** | `test_7_14_*` | consume 返回 backfill 元组，由调用方紧贴新框写入 |
| **模式互斥** | `test_7_18_*` | pending 中再按数字键被拒 |

---

## 设计方法论沉淀

- **懒回填 / 推迟写入** 是「保证 undo 原子性」的通用手法：把副作用推迟到能和主操作共用一个快照的时机。这和数据库事务的「所有写在同一事务」同构。
- **两阶段校验** 是 TOCTOU 防御的标准模式：入口挡一次、用之前再挡一次，代价是两次查重，换来的是「绘制过程中数据变化也不会产生非法状态」。

---

## 截图

> `[截图待补]` — 计划补充：选中 person → 按 head 数字键 → 绘制 → 三框同 gid 的演示

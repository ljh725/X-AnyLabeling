# Filter State + Engine 架构模板

## 目标

该模板用于沉淀复杂 UI 状态功能的固定实现方式，尤其适用于存在 Qt signal、跨图片状态保持、UI 刷新、可见性同步、筛选/恢复调用链的功能。

核心目标：

1. 避免 UI 控件成为权威状态。
2. 避免程序同步 UI 时被 Qt signal 误判为用户操作。
3. 避免状态、UI、canvas 可见性在刷新/切图/恢复时分叉。
4. 避免单个大类同时承担状态保存、匹配计算、UI 同步、刷新编排。
5. 将边界行为固化到测试和文档中，降低后续扩展风险。

---

## 适用场景

当功能满足以下任意多项时，应优先采用该模式：

1. 状态需要跨图片、跨页面或跨刷新周期保持。
2. 状态由多个 UI 控件共同影响。
3. 存在 `currentIndexChanged`、`itemChanged`、`selectionChanged` 等 Qt signal。
4. 程序会主动同步 UI 控件状态。
5. 状态会影响对象可见性、导航、保存、批量处理或 inspector。
6. 需要区分“用户主动操作”和“程序内部刷新”。
7. 后续可能继续扩展筛选条件或显示模式。

简单布尔开关不必强行套用该模式。例如 `show_scores`、`show_labels`、`show_attributes` 这类只同步到 Canvas 的开关，可以继续使用简单的 `set_canvas_params()`。

---

## 分层模型

| 层级 | 职责 | 不应该做 |
|------|------|----------|
| State | 保存权威状态、规范化输入、判断是否 active | 访问 Qt UI、访问 canvas、触发刷新 |
| Engine | 根据状态计算结果，并应用到目标对象 | 读取 combobox、保存 pending restore、处理菜单事件 |
| UI Adapter | 将用户操作转换为 state setter 调用 | 直接散落写状态字段、做复杂匹配计算 |
| Orchestrator | 编排切图、恢复、索引重建、统一 apply | 持有隐式业务状态、依赖 signal 副作用 |
| Tests | 固化边界行为和回归场景 | 只测试 happy path |
| Docs | 记录调用链、约束、禁忌和验证清单 | 写死易过期行号、复制旧实现细节 |

推荐结构：

```text
FeatureState       保存权威状态
FeatureEngine      计算和应用
LabelingWidget     UI 适配和流程编排
Tests              固化边界行为
Docs               记录调用链和设计约束
```

筛选保持功能中的对应关系：

```text
FilterState        保存 label/gid/shape_type 筛选状态
ShapeFilterEngine  计算命中项并同步 visibility
LabelingWidget     菜单、combobox、切图恢复、apply 编排
tests              覆盖状态同步、signal block、pending restore
docs               记录架构、调用链、边界和维护禁忌
```

---

## State 设计规范

State 是功能的唯一权威状态。

示例：

```python
class FilterState:
    DEFAULT_GID = "-1"
    DEFAULT_TYPE = ""

    def __init__(self, labels=None, gid=None, shape_type=None):
        self.labels = set(labels) if labels else set()
        self.gid = self._normalize_gid(gid)
        self.shape_type = shape_type or self.DEFAULT_TYPE

    def set_labels(self, labels):
        self.labels = set(labels) if labels else set()

    def set_gid(self, gid):
        self.gid = self._normalize_gid(gid)

    def set_shape_type(self, shape_type):
        self.shape_type = shape_type or self.DEFAULT_TYPE

    def has_active_filter(self):
        return bool(self.labels) or self.gid != "-1" or self.shape_type != ""
```

规则：

1. 所有外部写入必须走 setter。
2. setter 必须负责输入规范化。
3. 不直接写 `state.xxx = value`，除非在类内部。
4. 不从 UI 控件读取值作为长期状态。
5. `copy()` 必须返回独立快照，避免引用共享。
6. `reset()` 必须恢复完整默认状态。

推荐：

```python
self._filter_state.set_gid(raw_gid)
```

避免：

```python
self._filter_state.gid = raw_gid
```

---

## Engine 设计规范

Engine 负责计算和应用，不负责 UI 控件。

示例职责：

1. 根据 state 和 index 计算命中对象。
2. 将可见性结果同步到 list item、shape、canvas。
3. 返回是否发生变化，交给调用方决定是否刷新 canvas 或 navigator。

Engine 可以接收必要依赖，但应避免直接依赖完整 `LabelingWidget`。

推荐：

```python
self._filter_engine = ShapeFilterEngine(
    label_list=self.label_list,
    canvas=self.canvas,
    get_label_info=lambda: self.label_info,
    update_select_toggle_tooltip=self._update_select_toggle_button_tooltip,
)
```

规则：

1. 不读取 combobox 当前文本。
2. 不保存 pending restore。
3. 不负责菜单 action。
4. 不决定何时切图或恢复。
5. 不直接弹 UI 提示。

---

## UI Adapter 设计规范

UI Adapter 负责把用户操作翻译为状态变更。

统一顺序：

```text
用户操作
  -> state setter
  -> 同步 UI 表示
  -> 明确调用 apply
```

程序内部同步 UI 时：

```text
程序刷新 UI
  -> state setter
  -> QSignalBlocker 阻断 UI signal
  -> 更新控件显示
  -> 由调用方决定是否统一 apply
```

关键规则：

1. `block_signal=True` 只表示“不触发 Qt 回调”，不表示“不更新 state”。
2. 用户回调可以立即 apply。
3. 程序批量刷新应先 block signal，再统一 apply。
4. UI 控件显示值不能反向覆盖复杂状态，尤其是多选状态。

推荐：

```python
def set_gid_filter_value(self, gid, block_signal=False):
    self._filter_state.set_gid(gid)
    index = self.gid_filter_combobox.gid_box.findText(str(gid))
    if index < 0:
        index = self.gid_filter_combobox.gid_box.findText("-1")
    if index >= 0:
        blocker = None
        if block_signal:
            blocker = QtCore.QSignalBlocker(self.gid_filter_combobox.gid_box)
        self.gid_filter_combobox.gid_box.setCurrentIndex(index)
        del blocker
```

避免：

```python
def set_gid_filter_value(self, gid, block_signal=False):
    self.gid_filter_combobox.gid_box.setCurrentText(str(gid))
    # 依赖 currentIndexChanged 回调再更新 state
```

---

## Apply 入口规范

复杂功能应收敛到一个明确 apply 入口。

筛选功能示例：

```python
def _apply_combined_shape_filters(self):
    has_active_filter = self._filter_state.has_active_filter()

    if not has_active_filter:
        changed = self._filter_engine.apply_label_visibility()
        if changed:
            self.canvas.update()
            self.update_navigator_shapes_if_needed()
        self.status("")
        return

    matched_items = self._filter_engine.compute_matches(
        self._filter_state, self._filter_index
    )
    visible_count, changed = self._filter_engine.sync_label_list_visibility(
        lambda item: item in matched_items
    )
```

规则：

1. apply 只读 State，不从 UI 控件读权威值。
2. apply 负责 active/inactive 分支。
3. apply 不应修改筛选 state。
4. apply 返回或内部处理 changed，避免无意义刷新。
5. canvas/navigator 刷新必须由 changed 决定。

---

## Restore / Refresh 规范

跨图片保持统一流程：

```text
load_file()
  -> _pending_filter_restore = _copy_filter_state()
  -> reset_state()
  -> load_shapes()
  -> _refresh_shape_filters()
      -> restore pending via State.set_*()
      -> rebuild index
      -> update UI boxes with block_signal=True
      -> _apply_combined_shape_filters()
```

规则：

1. pending restore 保存 State 快照，不保存 UI 控件值。
2. 恢复 pending 时必须走 State setter。
3. 重建 index 后再 apply。
4. 更新 UI 控件时必须 block signal。
5. 恢复流程最后统一 apply，不依赖 combobox 回调。

推荐：

```python
restored = self._pending_filter_restore
self._pending_filter_restore = None
self._filter_state.set_labels(restored.labels)
self._filter_state.set_gid(restored.gid)
self._filter_state.set_shape_type(restored.shape_type)
```

避免：

```python
self._filter_state.labels = restored.labels
self._filter_state.gid = restored.gid
self._filter_state.shape_type = restored.shape_type
```

---

## Signal 处理规范

Qt signal 的核心风险是“程序同步 UI”被误当成“用户操作”。

常见错误链：

```text
程序设置 combobox 当前项
  -> currentIndexChanged 触发
  -> callback 改 state
  -> callback apply
  -> apply 改 item checkState
  -> itemChanged 触发
  -> shape.visible 被覆盖
```

处理原则：

1. 程序同步 UI 时默认使用 `QSignalBlocker`。
2. 用户回调中才执行“用户选择语义”。
3. 不要让 combobox 当前文本覆盖多选 state。
4. item visibility 批量同步时，应阻断 item model signal。
5. signal blocker 的生命周期必须覆盖整个 UI 更新操作。

---

## 测试模板

复杂 UI 状态功能至少覆盖以下回归场景：

1. `block_signal=True` 时 State 仍更新。
2. 程序同步 combobox 不触发用户回调。
3. pending restore 走 setter 并规范化状态。
4. 无 active filter 时执行正确恢复逻辑。
5. 多选状态不会被单选 UI 覆盖。
6. active filter 存在时只显示命中项。
7. 清空 filter 后恢复可见性。
8. 切图后状态保持/清空符合开关设置。

测试文件建议：

```text
tests/test_<feature>_persistence.py
tests/test_<feature>_state.py
tests/test_<feature>_engine.py
```

筛选功能当前模板：

```text
tests/test_filter_persistence.py
```

---

## 文档模板

每个复杂 UI 状态功能建议包含以下文档章节：

```text
1. 功能目标
2. 适用场景和非目标
3. 权威状态
4. UI 入口
5. Engine / 执行层
6. 切图 / 刷新 / 恢复调用链
7. signal block 规则
8. 已知边界场景
9. 回归测试
10. 人工验证清单
11. 维护禁忌
```

文档建议写稳定概念和调用链，不建议写大量精确行号。行号容易随重构过期。

---

## 维护禁忌

避免以下写法：

```python
# 不推荐：UI 控件变成权威状态
current_gid = self.gid_filter_combobox.gid_box.currentText()
self._filter_state.gid = current_gid
self._apply_combined_shape_filters()
```

推荐：

```python
# 推荐：State 是权威状态
self._filter_state.set_gid(current_gid)
self._apply_combined_shape_filters()
```

避免：

```python
# 不推荐：程序同步 UI 时触发用户回调
combo.setCurrentIndex(index)
```

推荐：

```python
# 推荐：程序同步 UI 时阻断 signal
blocker = QtCore.QSignalBlocker(combo)
combo.setCurrentIndex(index)
del blocker
```

避免：

```python
# 不推荐：Engine 读取 UI
label = self.label_filter_combobox.text_box.currentText()
```

推荐：

```python
# 推荐：Engine 使用 State
matched = self._filter_engine.compute_matches(
    self._filter_state, self._filter_index
)
```

---

## 扩展检查清单

新增或扩展复杂 UI 状态功能前，检查以下问题：

1. 权威状态在哪里？
2. UI 控件是否只是展示/输入，而不是状态源？
3. 程序刷新 UI 是否 block signal？
4. 是否有统一 apply 入口？
5. apply 是否只读 State？
6. 切图/刷新/恢复是否走同一流程？
7. pending restore 是否保存 State 快照？
8. 恢复是否走 setter？
9. Engine 是否脱离 UI 控件？
10. 是否补了 block signal、pending restore、多选状态、清空状态的测试？
11. 是否写了维护禁忌和人工验证清单？

---

## 当前落地点

该模板已在筛选保持功能中使用：

```text
anylabeling/views/labeling/filter_state.py
anylabeling/views/labeling/filter_engine.py
anylabeling/views/labeling/label_widget.py
tests/test_filter_persistence.py
docs/fix_rect_label_visibility_after_creation.md
```

后续类似功能可以优先参考该结构，例如：

1. 属性筛选。
2. 文件筛选。
3. inspector 问题筛选。
4. focus / solo 可见性模式。
5. 批量编辑状态保持。
6. label manager / gid manager 联动逻辑。

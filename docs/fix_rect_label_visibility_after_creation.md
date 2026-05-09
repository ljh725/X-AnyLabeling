# Fix: 矩形标注后对象可见性被筛选刷新影响

## 日期

2026-05-09

---

## 一、问题描述

按 `R` 快捷键创建矩形后，标注刚加入对象列表时应保持可见。但在筛选状态刷新链路中，如果筛选状态、对象列表复选框、`shape.visible` 和 `canvas.visible` 的同步顺序不一致，新对象可能出现以下问题：

1. 对象面板复选框状态和 `shape.visible` 不一致。
2. 清空筛选后，之前被筛掉的对象没有恢复显示。
3. 跨图片保持筛选时，旧筛选状态恢复后覆盖当前图片对象可见性。
4. 多标签筛选状态被单选下拉框回调误清空。

---

## 二、最新筛选架构

当前筛选逻辑已经从 `LabelingWidget` 的旧字典状态中拆分为两个核心模块：

| 模块 | 文件 | 职责 |
|------|------|------|
| `FilterState` | `anylabeling/views/labeling/filter_state.py` | 统一保存并规范化 label/gid/shape_type 筛选状态 |
| `ShapeFilterEngine` | `anylabeling/views/labeling/filter_engine.py` | 计算筛选命中项，并同步对象列表、shape 和 canvas 可见性 |

`LabelingWidget` 仍负责 UI 入口、切图流程、筛选菜单刷新和状态恢复，但不再直接承担筛选匹配计算。

### 2.1 权威状态

筛选权威状态为：

```python
self._filter_state = FilterState()
```

字段语义：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `labels` | `set()` | 多标签筛选集合 |
| `gid` | `"-1"` | 组 ID 筛选，`"-1"` 表示全部 |
| `shape_type` | `""` | 形状类型筛选，空字符串表示全部 |

所有外部写入都应通过：

```python
set_labels()
set_gid()
set_shape_type()
```

避免直接写字段导致 `None`、空字符串或非字符串 gid 绕过规范化。

### 2.2 执行引擎

筛选应用由 `ShapeFilterEngine` 执行：

```python
self._filter_engine = ShapeFilterEngine(
    label_list=self.label_list,
    canvas=self.canvas,
    get_label_info=lambda: self.label_info,
    update_select_toggle_tooltip=self._update_select_toggle_button_tooltip,
)
```

关键方法：

| 方法 | 说明 |
|------|------|
| `compute_matches(filter_state, filter_index)` | 根据当前筛选状态和索引计算命中对象 |
| `sync_label_list_visibility(get_visible)` | 同步对象复选框、`shape.visible`、`canvas.visible` |
| `apply_label_visibility()` | 无 active filter 时，按 `label_info[label]["visible"]` 恢复对象可见性 |

---

## 三、矩形创建后的调用链

```text
用户按 R 并完成矩形
  |
  v
Canvas.finalise()
  - 创建 Shape，默认 visible=True
  - 加入 canvas.shapes
  - emit new_shape()
  |
  v
LabelingWidget.new_shape()
  - 确定 label / group_id / flags / description
  - add_label(shape)
  |
  v
LabelingWidget.add_label()
  - 创建 LabelListWidgetItem
  - 加入对象列表
  - 根据 refresh_filters 决定是否调用 _refresh_shape_filters()
  |
  v
LabelingWidget._refresh_shape_filters()
  - 消费 _pending_filter_restore
  - 重建 _filter_index
  - 刷新 label/gid/shape_type 下拉项
  - 调用 _apply_combined_shape_filters()
```

该链路的关键点是：新对象加入后，筛选刷新必须以 `FilterState` 为权威状态，而不是以 combobox 当前文本或旧 UI 残留为准。

---

## 四、跨图片筛选保持流程

### 4.1 开启 Enable Global Filter

默认开启：

```python
self._global_filter_keep_enabled = True
```

切图时：

```text
load_file()
  |
  |-- _pending_filter_restore = _copy_filter_state()
  |-- reset_state()
  |-- 加载图片和标注
  |-- load_shapes()
        |
        v
      _refresh_shape_filters()
        |-- FilterState.set_labels(restored.labels)
        |-- FilterState.set_gid(restored.gid)
        |-- FilterState.set_shape_type(restored.shape_type)
        |-- _apply_combined_shape_filters()
```

恢复时必须走 `FilterState` 的 setter，确保 `gid=None`、`gid=""` 等输入都会规范化为 `"-1"`。

### 4.2 关闭 Enable Global Filter

关闭时：

```text
toggle_global_filter_keep(False)
  |-- _filter_state.reset()
  |-- set_label_filter_value("", block_signal=True)
  |-- set_gid_filter_value("-1", block_signal=True)
  |-- set_shape_type_filter_value("", block_signal=True)
  |-- _apply_combined_shape_filters()
```

`set_gid_filter_value()` 和 `set_shape_type_filter_value()` 现在采用 state-first 模式，即使 `block_signal=True` 也会同步 `_filter_state`，不再依赖 Qt 回调副作用。

---

## 五、根因和修复点

### 5.1 清空筛选后没有恢复可见性

旧逻辑在无 active filter 时直接返回，导致之前被筛掉的对象仍保持隐藏。

最新修复：

```python
if not has_active_filter:
    changed = self._filter_engine.apply_label_visibility()
    if changed:
        self.canvas.update()
        if self.navigator_dialog.isVisible():
            self.update_navigator_shapes()
    self.status("")
    return
```

含义：

- 无 label/gid/shape_type 筛选时，不再执行匹配筛选。
- 但会恢复对象可见性到 label 级别的可见性设置。
- 避免清空筛选后对象仍隐藏。

### 5.2 多标签筛选被 combobox 回调清空

多标签筛选由菜单支持，但 label combobox 仍是单选控件。更新 combobox 摘要时，如果触发 `currentIndexChanged`，会进入 `text_selection_changed()` 并把多标签集合覆盖为单标签或空集合。

最新修复：

```python
blocker = QtCore.QSignalBlocker(self.label_filter_combobox.text_box)
self.label_filter_combobox.text_box.setCurrentIndex(idx)
del blocker
```

应用位置：

- `_set_selected_labels()`
- `_update_combo_box_label_summary()`

### 5.3 gid/type setter 只改 UI 不改状态

旧逻辑依赖 `currentIndexChanged` 回调更新状态。`block_signal=True` 时，UI 会变化但 `_filter_state` 不会变化。

最新修复：

```python
def set_gid_filter_value(self, gid, _checked=False, block_signal=False):
    self._filter_state.set_gid(gid)
    ...

def set_shape_type_filter_value(
    self, shape_type, _checked=False, block_signal=False
):
    self._filter_state.set_shape_type(shape_type)
    ...
```

### 5.4 pending restore 直接写字段

旧逻辑直接写：

```python
self._filter_state.labels = ...
self._filter_state.gid = ...
self._filter_state.shape_type = ...
```

最新修复：

```python
self._filter_state.set_labels(restored.labels)
self._filter_state.set_gid(restored.gid)
self._filter_state.set_shape_type(restored.shape_type)
```

---

## 六、当前行为规则

| 场景 | 行为 |
|------|------|
| 无 active filter | 按 label 可见性恢复所有对象显示状态 |
| 有 label/gid/type 筛选 | 只显示命中对象，同时尊重 label 可见性 |
| 多标签筛选 | 以 `FilterState.labels` 为权威状态，combobox 只作为摘要显示 |
| 切图且保持筛选开启 | 保存并恢复 `FilterState` 快照 |
| 切图且保持筛选关闭 | 不保存筛选，状态保持默认无筛选 |
| 手动切换全部可见性 | active filter 存在时禁用，避免和筛选状态冲突 |

---

## 七、回归测试

新增测试文件：

```text
tests/test_filter_persistence.py
```

覆盖点：

1. `set_gid_filter_value()` / `set_shape_type_filter_value()` 在 `block_signal=True` 时仍同步状态。
2. pending restore 会走 `FilterState` setter 并规范化默认值。
3. 无 active filter 时会调用 `apply_label_visibility()` 恢复可见性。
4. 多标签摘要更新不会触发 combobox 回调并清空状态。

当前本地环境缺少 `PyQt6`，测试会被跳过。安装 PyQt6 后运行：

```bash
pytest tests/test_filter_persistence.py
```

---

## 八、人工验证清单

1. 打开图片，按 `R` 创建矩形，确认对象复选框勾选且矩形可见。
2. 启用 label 筛选后创建不匹配 label 的对象，确认筛选行为正确。
3. 清空筛选，确认之前隐藏的对象按 label 可见性恢复。
4. 同时选择多个 label，确认切图后多标签筛选不丢失。
5. 启用 Enable Global Filter 后切图，确认 label/gid/type 筛选保持。
6. 关闭 Enable Global Filter 后切图，确认筛选状态清空。
7. 切换 label 可见性，再清空筛选，确认仍尊重 label 级可见性。

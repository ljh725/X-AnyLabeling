# Pose View 标签隐藏与自动聚合模式修改说明

> 日期：2026-06-16  
> 目标：形成可直接执行的实现说明，用于修改 Pose View 原生标签隐藏与自动聚合模式。

## 1. 修改目标

本次修改包含两个独立目标：

1. **Pose View 开启后隐藏全部 Canvas 原生标签**
   - 不直接复用 `label_on_selection` 开关。
   - 复用 `label_on_selection` 的“标签进入绘制列表前统一 gate”机制。
   - Pose View 开启时，Canvas 原生 label pass 不绘制任何 shape 标签。
   - PoseRenderer 的骨架、关键点、bbox、pose 标签 overlay 保持独立渲染。

2. **简化并修正自动聚合模式**
   - 开启/关闭方式更清晰。
   - 聚合目标保持稳定。
   - 不可见目标不能被鼠标、列表或程序化选择入口选中。

## 2. 涉及文件

| 文件 | 修改内容 |
|------|----------|
| `anylabeling/views/labeling/widgets/canvas.py` | 原生标签绘制 gate、PoseRenderer 调用位置、shape 可交互判断 |
| `anylabeling/views/labeling/label_widget.py` | 自动聚合状态、列表选择过滤、关闭/ESC 行为 |
| `docs/pose_label_feature_summary.md` | 如需要，补充行为总结 |

## 3. Pose View 标签隐藏方案

### 3.1 当前问题

当前 `canvas.py` 中原生标签绘制逻辑大致是：

```text
if self.show_labels:
    for shape in self.shapes:
        可见性检查
        Pose View 特例：跳过 COCO keypoint point 和 person rectangle
        计算 label_text
        计算 label rect
        label_on_selection gate
        labels.append(...)

    绘制 labels
    PoseRenderer.render(...)
```

问题：

- Pose View 开启时只跳过部分 pose 相关标签。
- polygon、line、普通 rectangle 等原生标签仍可能显示。
- PoseRenderer 调用被包在 `if self.show_labels:` 内，关闭全局标签时可能误伤 Pose View overlay。

### 3.2 目标行为

```text
Pose View OFF:
    show_labels / label_on_selection 行为保持原样

Pose View ON:
    Canvas 原生标签全部隐藏
    PoseRenderer overlay 独立绘制
```

### 3.3 推荐实现

在 `Canvas` 中增加原生标签统一判断，不直接使用 `label_on_selection` 状态实现隐藏，而是使用同一类 gate 结构。

建议新增私有方法：

```python
def _should_draw_standard_label(self, shape):
    """Return whether the standard Canvas label should be drawn."""
    if not self.show_labels:
        return False
    if self.pose_config.enabled:
        return False
    if not self.is_shape_interactive(shape):
        return False
    return True
```

然后在原生标签循环中，将现有 Pose View 特例：

```python
if self.pose_config.enabled:
    if shape.shape_type == "point" and shape.label in COCO_KEYPOINT_SET:
        continue
    if (
        shape.shape_type == "rectangle"
        and shape.label == "person"
        and shape.group_id is not None
    ):
        continue
```

替换为：

```python
if not self._should_draw_standard_label(shape):
    continue
```

### 3.4 PoseRenderer 调用位置

PoseRenderer 不应依赖 `self.show_labels`。应从原生标签绘制块中移出，放在原生 labels pass 之后。

目标结构：

```text
if self.show_labels and not self.pose_config.enabled:
    绘制 Canvas 原生标签

if self.pose_config.enabled and self._has_pose_shapes():
    PoseRenderer.render(...)
```

注意：

- `label_on_selection` 仍可传给 PoseRenderer，用于控制 Pose 标签的稀疏显示。
- `show_labels=False` 是否隐藏 PoseRenderer 标签，需要单独产品确认；本说明默认不影响 Pose View overlay。

## 4. 自动聚合模式方案

### 4.1 当前问题

当前自动聚合模式通过 `auto_focus_instance` 布尔值控制：

```text
Alt+H 开启
选中 shape 后隐藏其他 group
ESC 临时显示全部，但 auto_focus_instance 仍保持 True
再次选择又重新聚合
```

主要问题：

- 开启/关闭语义不够直观。
- ESC 后是“临时退出聚合”，但模式仍开启，用户容易误解。
- 只用 `hidden_by_filter` 控制绘制隐藏，选择命中入口仍可能选中不可见目标。

### 4.2 目标状态机

改为更明确的状态模型：

```text
OFF
  ↓ 开启自动聚合
ARMED
  ↓ 选择可见且有 group_id 的目标
FOCUSED(group_id)
  ↓ 选择另一个可见 group
FOCUSED(new_group_id)
  ↓ ESC 或关闭自动聚合
OFF
```

状态字段建议：

```python
self.auto_focus_instance = False
self.auto_focus_group_id = None
```

语义：

- `auto_focus_instance == False`：自动聚合关闭。
- `auto_focus_instance == True and auto_focus_group_id is None`：已开启，等待选择目标。
- `auto_focus_instance == True and auto_focus_group_id is not None`：已聚焦某个 group。

### 4.3 开启/关闭行为

`toggle_auto_focus_instance()` 推荐修改为：

```text
关闭 -> 开启:
    auto_focus_instance = True
    auto_focus_group_id = None
    不立即隐藏任何目标
    状态提示：自动聚合已开启，选择目标后聚焦

开启 -> 关闭:
    auto_focus_instance = False
    auto_focus_group_id = None
    show_all_instances()
    状态提示：自动聚合已关闭
```

### 4.4 目标保持

`_auto_focus_on_selection(selected_shapes)` 只在选中可见、可交互、有 `group_id` 的 shape 时更新目标。

目标逻辑：

```text
if auto_focus_instance is False:
    return
if selected_shapes 为空:
    return
current_shape = 第一个可交互且 group_id 非空的 shape
if current_shape 不存在:
    return
auto_focus_group_id = current_shape.group_id
对 canvas.shapes:
    shape.hidden_by_filter = shape.group_id != auto_focus_group_id
canvas.update()
```

这样：

- 点击当前聚合目标内部关键点，不会丢失目标。
- 选择另一个可见 group，会切换聚合目标。
- 没有有效选择时，不自动清空当前目标。

### 4.5 ESC 行为

建议 ESC 在自动聚合开启时直接关闭聚合，而不是临时退出。

目标行为：

```text
if auto_focus_instance:
    auto_focus_instance = False
    auto_focus_group_id = None
    show_all_instances()
    event.accept()
```

状态提示：

```text
已关闭自动聚合
```

如仍希望保留“临时显示全部但模式仍开启”，需要给它单独命名，例如“暂停聚合”，否则用户会继续遇到状态不直观的问题。

## 5. 不可见目标不能被选中

### 5.1 统一可交互判断

在 `Canvas` 中新增公共判断：

```python
def is_shape_interactive(self, shape):
    """Return whether a shape can be hovered, selected, or edited."""
    return (
        self.is_visible(shape)
        and getattr(shape, "visible", True)
        and not getattr(shape, "hidden_by_filter", False)
    )
```

### 5.2 替换选择入口判断

以下位置应使用 `is_shape_interactive(shape)`：

| 入口 | 当前风险 | 修改方式 |
|------|----------|----------|
| hover 命中 | 隐藏对象仍可能被 hover | `for shape in reversed([...])` 改为过滤 `is_shape_interactive` |
| `select_shape_point()` | 隐藏对象仍可能被点击选中 | `if not self.is_shape_interactive(shape): continue` |
| 双击编辑 label | 隐藏对象仍可能进入编辑 | 替换 `is_visible` 判断 |
| label list 选择 | 左侧列表可绕过画布选择 | `label_selection_changed()` 中过滤不可交互 shape |
| `select_shapes()` | 程序化入口可绕过 | 发射选择前过滤不可交互 shape |

### 5.3 label list 选择过滤

`label_widget.py::label_selection_changed()` 当前会直接收集列表选中项：

```python
for item in self.label_list.selected_items():
    selected_shapes.append(item.shape())
```

应改为：

```python
for item in self.label_list.selected_items():
    shape = item.shape()
    if self.canvas.is_shape_interactive(shape):
        selected_shapes.append(shape)
```

如果过滤后为空，应调用：

```python
self.canvas.deselect_shape()
```

## 6. 推荐执行步骤

1. 在 `canvas.py` 增加 `is_shape_interactive(shape)`。
2. 在 hover、点击选择、双击编辑、`select_shapes()` 中统一使用该方法。
3. 在 `label_widget.py::label_selection_changed()` 过滤不可交互 shape。
4. 在 `canvas.py` 增加 `_should_draw_standard_label(shape)`。
5. 将原生标签绘制条件改为 `self.show_labels and not self.pose_config.enabled`。
6. 将 PoseRenderer 调用移出 `if self.show_labels:` 块。
7. 在 `label_widget.py` 增加 `auto_focus_group_id` 状态。
8. 修改 `toggle_auto_focus_instance()`：开启只进入 ARMED，关闭恢复全部可见。
9. 修改 `_auto_focus_on_selection()`：只根据可交互且有 `group_id` 的目标更新聚合目标。
10. 修改 ESC 行为：自动聚合开启时直接关闭并恢复全部目标。
11. 手动验证 Pose View 与普通标签模式。

## 7. 验收清单

### 7.1 Pose View 标签隐藏

- [ ] Pose View 关闭时，普通标签显示逻辑与修改前一致。
- [ ] Pose View 开启时，Canvas 原生标签全部隐藏。
- [ ] Pose View 开启时，polygon / line / rectangle / point 的原生标签均不显示。
- [ ] Pose View 开启时，PoseRenderer overlay 仍正常显示。
- [ ] `label_on_selection` 原有开关状态不被修改。
- [ ] `show_labels=False` 不导致程序崩溃；PoseRenderer 行为符合产品预期。

### 7.2 自动聚合

- [ ] 开启自动聚合后，不立即隐藏任何目标。
- [ ] 选中有 `group_id` 的可见目标后，只显示同 group 目标。
- [ ] 再选中另一个可见 group 后，聚合目标切换。
- [ ] ESC 后自动聚合关闭，全部目标恢复显示。
- [ ] 再次切换自动聚合关闭时，全部目标恢复显示。
- [ ] 没有 `group_id` 的 shape 不触发聚合。

### 7.3 不可见目标选择

- [ ] 被 `hidden_by_filter=True` 隐藏的目标不能 hover。
- [ ] 被 `hidden_by_filter=True` 隐藏的目标不能鼠标选中。
- [ ] 左侧对象列表不能选中当前不可交互目标。
- [ ] `shape.visible=False` 的目标不能被选中。
- [ ] `canvas.visible[shape]=False` 的目标不能被选中。
- [ ] 当前已选中目标被隐藏后，选择状态应被清理或不再可操作。

## 8. 风险与边界

| 风险 | 说明 | 处理 |
|------|------|------|
| PoseRenderer 是否受 `show_labels` 控制 | 本说明默认 Pose View overlay 独立于原生标签 | 如产品要求，可新增 `pose_config.show_pose_labels` |
| label list 过滤后 UI 选择状态回弹 | 用户点击不可见项后可能需要清除列表选择 | 使用 `_no_selection_slot` 防止递归 |
| 已选中目标被自动隐藏 | 可能残留 selected 状态 | 自动聚合隐藏前过滤/清理不在目标 group 的 selected 状态 |
| `hidden_by_filter` 与其他筛选系统重叠 | 当前已有 shape filter 使用可见状态 | 保持 `hidden_by_filter` 只表示临时聚合隐藏 |

## 9. 推荐最终行为定义

```text
普通模式:
    show_labels 控制是否显示原生标签
    label_on_selection 控制原生标签稀疏显示

Pose View:
    原生标签层全部关闭
    PoseRenderer 独立负责 pose overlay

自动聚合:
    开启后等待选择
    选择可见 group 后聚焦
    目标保持到切换、ESC 或关闭
    不可见对象不可 hover、不可选择、不可编辑
```


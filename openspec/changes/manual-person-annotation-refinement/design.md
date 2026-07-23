## Context

当前代码中，画布缩放与鼠标控制的关系已经明确：

- `Canvas.paintEvent()` 使用 `p.scale(self.scale, self.scale)` 绘制图像。
- `Canvas.transform_pos()` 使用 `point / self.scale - self.offset_to_center()` 将鼠标位置转为图像坐标。
- `LabelWidget.paint_canvas()` 将 `canvas.scale` 设置为 `0.01 * zoom_widget.value()`。

因此鼠标拖动的图像坐标控制模型为：

```text
image_delta = screen_delta / canvas.scale
control_gain = 1 / canvas.scale
```

当 zoom 较小时，同样的屏幕鼠标位移会映射成更大的图像坐标位移，导致几像素级修边不稳定；当 zoom 足够大时，同样鼠标位移映射成更小图像位移，用户会感觉更稳。

现有相关能力：

- `LabelWidget.create_digit_mode()` 读取数字快捷键映射，设置 `digit_to_label` 并进入绘制模式。
- `DigitRenameManager` 在编辑模式且有选中对象时拦截数字键，用于重命名选中对象。
- `Canvas.gen_new_group_id()` 扫描当前画布 shapes，返回 `max(group_id) + 1`。
- `Canvas.group_selected_shapes()` / `ungroup_selected_shapes()` 提供通用 `group_id` 组合能力。
- `rect_edge_alignment.py` 提供矩形边命中、单边拖动和反翻转约束。
- Stable preview 是观察型预览，不改变鼠标事件仲裁，也不是图像边缘吸附。

## Goals / Non-Goals

**Goals:**

- 新建 `person rectangle` 时自动创建新人物实例 `group_id`。
- 将数字快捷键扩展为互斥的“重命名模式”和“绑定绘制模式”。
- 绑定绘制模式下从选中来源对象继承或创建 `group_id`。
- 对重复目标 label 做创建前拒绝，避免同一人物实例内重复 `person` / `head` / `face`。
- 提供数字快捷操作提示，让标注员明确当前模式、来源、目标和拒绝原因。
- 提供精修控制模式，降低鼠标拖动控制增益，默认 `precision_factor = 4`。
- 提供键盘像素级整体/单边微调。
- 提供按键触发的局部边缘吸附，默认搜索范围 `±4` image pixels。

**Non-Goals:**

- 不引入自动检测模型。
- v0 不改变 auto-labeling 结果落地流程；`finish_auto_labeling_object` 不触发“新建 person 自动创建人物实例”。
- 不改变 JSON 数据结构。
- 不自动重排或重命名历史 `group_id`。
- 不在 v0 中支持多选来源的绑定绘制。
- 不做实时边缘吸附。
- 不让 Data Inspector 自动写回正式 JSON。

## Decisions

### Decision 1: 功能一使用独立开关

新增配置开关，建议展示名为“新建 person 自动创建人物实例”。该开关只在手动新建 `person rectangle` 且没有绑定绘制上下文提供 `group_id` 时生效；v0 不作用于 auto-labeling 结果落地入口。

**Rationale**: 该功能改变现有 `group_id` 输入习惯，应由标注员显式启用。

### Decision 2: 功能一不与“自动使用上一个标签”互斥

当“自动使用上一个标签”和“新建 person 自动创建人物实例”同时开启时，如果上一个标签为 `person`，连续绘制应创建 `person #1`、`person #2`、`person #3`。

**Rationale**: label 沿用和 `group_id` 自动新建是不同字段的决策。连续标注 `person` 时，自动沿用 label 但每个 `person` 创建新实例是高效工作流。

### Decision 3: 功能一优先于“自动使用上一个 group_id”

优先级为：

```text
绑定绘制模式继承 group_id
  > 新建 person 自动创建人物实例
  > 自动使用上一个 group_id
  > 手动输入 group_id
```

当 `auto_use_last_gid` 与功能一同时开启时，需要提示功能一优先，新建 `person` 不沿用上一组 ID。

**Rationale**: `person` 是人物实例锚点，默认沿用上一组 ID 容易导致连续新 `person` 被错误绑定为同一人。

### Decision 4: 数字快捷功能拆为互斥模式

数字快捷功能下提供两个互斥分支。互斥模式是持久配置，建议 key 为 `digit_shortcut_mode`，取值为 `rename` 或 `bind_draw`；pending bind context 是运行时瞬时对象，只存在于按数字键后到绘制完成/取消之间。

```text
数字快捷重命名模式
  选中对象 + 数字键 -> 修改选中对象 label

数字快捷绑定绘制模式
  选中来源 + 数字键 -> 新建目标 shape，并绑定 group_id
```

**Rationale**: 选中对象不能同时隐式表示“编辑目标”和“新建对象的绑定来源”。显式互斥模式降低误操作。

实现结构采用新增 `DigitBindDrawManager`，与现有 `DigitRenameManager` 对称。`LabelWidget.create_digit_mode()` 根据 `digit_shortcut_mode` 分流：

```text
if digit_shortcut_mode == "bind_draw":
    DigitBindDrawManager.handle_digit(digit)
elif DigitRenameManager.is_rename_mode_active():
    DigitRenameManager.trigger_rename(digit)
else:
    normal digit drawing
```

`DigitBindDrawManager` 负责绑定绘制规则、pending context、重复校验和数字快捷操作提示；`DigitRenameManager` 继续只负责编辑态重命名，避免把两套职责塞进同一个 manager。

### Decision 5: 绑定绘制 v0 只支持单选 person/head/face 来源

绑定绘制模式下，来源对象 v0 仅支持单个 `person` / `head` / `face`。多选或来源 label 不支持时提示并拒绝。

**Rationale**: 多选来源可能含多个 `group_id`，会让继承目标不明确。v0 保持简单可预测。

### Decision 6: 来源无 group_id 时允许继续，但延迟提交

若来源对象无 `group_id`，按数字键后只记录“拟分配 `new_group_id = max(group_id) + 1`”到 pending context，不立刻修改来源对象。来源回填与新 shape 创建在绘制完成时作为一次事务提交；Esc 取消绘制、切图、切模式或清理 pending context 时，来源对象保持原状。

**Rationale**: 标注员可以先画 `head` / `face` 再补 `person`，协议不应强制谁先画。

### Decision 7: 同组同 label 已存在时提示并拒绝

绑定绘制 v0 只接受目标为 `rectangle + person/head/face`。创建前检查当前 `group_id` 下是否已有目标 label；若已存在，提示并拒绝进入绘制。绘制完成消费 pending context 时必须再校验一次，避免期间数据变化导致重复。

**Rationale**: 同一人物实例内 `person` / `head` / `face` 应各自唯一，重复框通常表示误操作，应优先保护数据一致性。

### Decision 8: 数字快捷操作提示是功能二的一部分

提示必须覆盖：

- 模式切换
- 选中对象变化
- 数字键触发
- 拒绝执行

提示内容应包括模式、选中数量、来源 label、来源 shape_type、来源 `group_id`、数字键、目标 label、目标 shape_type、动作结果或拒绝原因。

提示仅在 `bind_draw` 模式下积极响应选中变化，`rename` 模式保持现有安静行为。选中变化提示应轻量去抖，建议 200ms 合并；翻译 context 建议为 `DigitShortcutHints`。

**Rationale**: 该设计假设标注员可以学习模式，但不能承受隐式冲突。持续反馈能降低学习成本，同时去抖避免状态栏刷屏。

### Decision 9: 功能三定义为精修控制模式

功能三不只做键盘 1px 微调，而是提供鼠标控制增益管理：

```text
precision_image_delta = screen_delta / canvas.scale / precision_factor
```

默认 `precision_factor = 4`。普通拖动保持现有行为，精修拖动通过修饰键临时启用，并可提供锁定开关供连续精修使用。

精修模式只缩放拖动 delta，不改变 `transform_pos()`、hit-test、epsilon 或 hover 判断。连续拖动必须使用虚拟光标策略，避免 `prev_point` 漂移：

```text
raw_delta = raw_pos - virtual_prev_pos
precision_delta = raw_delta / precision_factor
virtual_prev_pos = virtual_prev_pos + precision_delta
```

**Rationale**: 用户的手抖矛盾来自视觉清晰度和坐标控制增益。降低控制增益可以在不继续 zoom in 的情况下获得接近高 zoom 的精修手感。

### Decision 10: 功能四只做按键触发的当前边吸附

局部边缘吸附 v0 仅对当前选中矩形边生效，默认搜索范围为当前边附近 `±4` image pixels。吸附通过按键触发，不随鼠标实时触发。

边缘评分缓存当前文件的灰度图与法线方向梯度图，切图时失效。评分采用边法线方向梯度，沿边中段聚合，避免角点噪声。聚合方式使用 median，降低角点、局部纹理突刺和孤立强响应对候选边坐标的影响。

可靠性阈值 v0 采用**自适应阈值 + 绝对下限双判据**，两者同时满足才接受候选；`k` 和 `abs_floor` 硬编码，保留配置 hook：

```text
accept iff
  best_score >= k * local_max_response   # 自适应：相对于本图/本边局部最强响应
  and best_score >= abs_floor            # 绝对下限：避免暗图弱响应被相对放大
```

自适应阈值为主，保证不同对比度图像表现一致；绝对下限兜底，防止纹理稀疏图把弱响应当强边误吸。`local_max_response` 取当前边搜索窗口内的最大梯度响应。

吸附前必须 validate：候选若超出搜索范围、响应不足、会导致矩形翻转/低于最小尺寸，或调用 `apply_edge_coord` 时会触发 clamp，则视为失败并保持原位。

**Rationale**: 实时吸附会改变鼠标手感并与精修控制模式互相干扰。按键触发更可控，可通过撤销恢复。先 validate 再 apply 能避免 clamp 到用户没有选择的位置。

### Decision 11: 键盘微调使用精修默认语义

方向键默认移动 1 image pixel，`Shift + 方向键` 移动 5 image pixels。矩形单边键盘微调需要独立“键盘选边”状态：

```text
进入条件：选中单个 rectangle 后按 Tab
循环顺序：left -> top -> right -> bottom -> left
视觉指示：高亮当前键盘选边，复用矩形边编辑 active edge 样式
退出条件：Esc、切换选中对象、切换图片、进入绘制模式、点击空白取消选择、鼠标 hover 到任意矩形边
```

键盘单边微调只在键盘选边状态存在时生效；否则方向键保持整体移动。

**键盘选边与鼠标 hover 边的共存**：当存在键盘选边状态时，鼠标一旦 hover 到任意矩形边即退出键盘选边状态，把“active edge”控制权交还给鼠标，避免两套选中边同时高亮或单边微调目标歧义（hover 即接管）。

连续键盘微调的 undo 合并采用 **timestamp-based 替换式合并**，不引入定时器：每次 `store_shapes()` 前检查上一个快照时间戳，若 `now - last_snapshot_ts < 500ms` 则替换最后一个快照而非 append；否则正常 append。合并窗口内只保留一次快照，避免快速连按冲掉历史，也无延迟落盘风险。

**Rationale**: 功能三的目标是精修，默认 1px 更符合任务语义；Shift 仍保留粗调效率。键盘事件是离散输入，需要合并 undo，避免快速连按冲掉历史快照。

### Decision 12: 模式与选择语义互斥

绑定绘制 pending 期间禁用边吸附和单边微调；矩形边拖动/键盘选边精修期间不触发绑定绘制。`precision_factor` 只影响鼠标拖动降速，键盘微调和边缘吸附是独立能力，始终可用。

**Rationale**: 绑定绘制使用“选中 shape”作为来源，边缘吸附/单边微调使用“选中边”作为目标。两套选择语义同时生效会造成误操作。

### Decision 13: 配置 key 与 schema

新增配置建议使用扁平 key，避免引入点路径 schema 复杂度：

```text
auto_person_instance: false
digit_shortcut_mode: rename
canvas_precision_factor: 4
canvas_edge_snap_range: 4
```

这些 key 必须登记到设置 schema allow-list，并写入默认配置。

### Decision 14: 直接矩形边拖动按事务边界收口

直接矩形边拖动必须与普通矩形顶点编辑保持相同的图像边界语义：
left/top 不得小于图像原点，right/bottom 不得超过图像尺寸，同时继续遵守
最小宽高和反翻转约束。

一次鼠标手势是一个编辑事务：左键释放提交一次 undo；Esc、窗口失焦、
窗口停用或鼠标抓取丢失时回滚到按下前的 points。活动拖动只在左键仍按下
时消费 mouse move，避免中断后无按键移动继续修改几何。

鼠标移动热路径不做无条件同步 `repaint()`。矩形边命中将全局顶点优先和
边候选计算合并到一次 shape 遍历，并直接维护最佳候选，不构造完整排序列表。

**Rationale**: 直接边拖动不能绕过已有矩形边界约束；事务化结束可以保证
实时预览变更最终必然提交或回滚；减少同步重绘和重复全量扫描可降低大量
标注对象下的交互延迟。

### Decision 15: 边交互、稳定预览和对象选择使用单一状态所有者

矩形边鼠标交互抽取为独立状态控制器，显式表达
`idle -> hover -> pending -> dragging -> idle`。pending 三元组、active edge、
拖动起始 points 和键盘选边由控制器统一维护，Canvas 只负责 Qt 事件、坐标
转换、几何应用、undo 和绘制。

稳定预览使用独立状态对象和枚举模式 `none/target/drag_locked`，不再通过
Canvas 上多组无约束字段表达。预览仍然是观察型功能，不参与鼠标命中仲裁。

对象选择的唯一所有者是 Canvas：Canvas 在发出 `selection_changed` 前更新
`selected_shapes` 和每个 `Shape.selected`。LabelingWidget 只观察信号并同步
列表、属性面板和 actions，不再反向写回 Canvas。

边编辑视觉通过 `Shape.paint(..., force_unselected=True)` 的渲染参数表达，
移除 Shape 数据对象上的瞬时 `edge_editing` 字段。

**Rationale**: 单一所有者消除依赖同步 signal 回写的隐式环路；显式状态转换
防止 pending/dragging 字段组合不完整；渲染参数避免 Canvas 瞬时 UI 状态泄漏
进 Shape 数据模型。

### Decision 16: 绑定落标采用三态校验和单点提交

绑定绘制完成后，最终校验必须明确区分“没有 pending”“pending 可提交”和
“pending 已拒绝”。拒绝状态不得降级成普通数字绘制，也不得继承上一个
`group_id`；本次临时目标框直接丢弃。

来源对象回填延迟到目标标签合法性、来源仍存在、来源标签/形状类型、来源
`group_id` 稳定性和同组同标签唯一性全部通过之后，再与目标 shape 落标一起
写入同一 undo 快照。Esc、Backspace 清空最后一点、切图、撤销、切换模式以及
矩形裁剪失败都同时清理 pending 和 `digit_to_label`。

`group_id` 的共同合法性定义为“非 bool 的非负整数”。人物实例成员标签、
矩形类型和该合法性判断放在共享纯 Python 模块中。质检允许同一组同时存在
一个 head 和一个 face，只报告同组同标签重复；person 仍是关键点工具的姿态
锚点，不把任意 rectangle 自动视为人物实例。

**Rationale**: 三态结果避免失败与无 pending 共用 `None` 而继续错误落框；
单点提交避免来源已改、目标未落的半成品；共享不变量减少创建、绑定和质检
规则各自漂移。

## Proposed Behavior

### 新建 person 自动创建人物实例

```text
if auto_person_instance_enabled
and target_label == "person"
and target_shape_type == "rectangle"
and no pending bind context:
    group_id = canvas.gen_new_group_id()
```

完成后提示：

```text
已创建 person #4
```

### 数字快捷绑定绘制

```text
source = single selected shape
target = digit shortcut mapping

if source invalid:
    reject with hint

if source.group_id is None:
    gid = gen_new_group_id()
    record pending source_backfill_gid = gid
else:
    gid = source.group_id

if target is not rectangle + person/head/face:
    reject with hint
elif existing shape in gid has target.label:
    reject with hint
else:
    enter draw mode with pending label, shape_type, group_id
```

绘制完成消费 pending context 时再次校验目标合法性和同组同 label 唯一性。若来源需要回填，来源回填和新 shape 创建必须在同一次 undo 快照中提交。

### 精修控制模式

普通拖动不变：

```text
image_delta = screen_delta / canvas.scale
```

精修拖动：

```text
precision_delta = raw_delta / 4
virtual_prev_pos += precision_delta
```

键盘微调建议：

```text
方向键 -> 当前选中 shape 或边移动 1 image pixel
Shift + 方向键 -> 移动 5 image pixels
```

### 局部边缘吸附

```text
selected edge = left/right/top/bottom
search range = current coord +/- 4 image pixels
score each candidate coord by median local normal-gradient response on the edge middle segment
local_max = max score in search window
if best_score >= k * local_max and best_score >= abs_floor
   and move keeps min size:
    validate candidate does not require clamp
    move edge to best coord
else:
    keep current coord
```

## Risks / Trade-offs

- **[Risk] 数字键模式切换后用户忘记当前模式** -> Mitigation: 模式切换、选择变化、数字键触发均显示“数字快捷操作提示”。
- **[Risk] 自动回填来源 group_id 可能修改用户未预期对象** -> Mitigation: 仅单选来源；来源无 ID 时按键提示将创建并回填。
- **[Risk] 取消绑定绘制后来源对象被提前回填** -> Mitigation: pending context 延迟提交；取消绘制不修改来源。
- **[Risk] `auto_use_last_gid` 与功能一同时开启造成理解冲突** -> Mitigation: 功能一优先并提示。
- **[Risk] 精修降速连续拖动出现 `prev_point` 漂移** -> Mitigation: 只缩放 delta 并使用虚拟光标累计。
- **[Risk] 边缘吸附在低对比图像上误吸附** -> Mitigation: 自适应 + 绝对下限双判据、最大偏移、最小尺寸约束；失败时不移动。
- **[Risk] 键盘选边与鼠标 hover 边同时高亮造成歧义** -> Mitigation: 鼠标 hover 到任意矩形边即退出键盘选边状态。
- **[Risk] 连续键盘微调冲掉 undo 历史** -> Mitigation: timestamp-based 替换式合并（500ms 窗口），无定时器、无延迟落盘。

## Migration Plan

无需数据迁移。新增配置默认应保守：

- 新建 person 自动创建人物实例：默认关闭或在首次启用时提示。
- 数字快捷绑定绘制模式：默认关闭，保留现有数字重命名行为。
- 精修控制模式：默认关闭，保留普通拖动行为。
- 局部边缘吸附：仅用户触发时执行。
- 键盘方向键默认步进从 5px 调整为 1px，`Shift + 方向键` 保留 5px 粗调；这是有意的精修行为变化，需在用户提示/文档中说明。

# 手动人物标注精修功能总结

> **历史文档提示（2026-07-20）**：功能 3 仅保留鼠标精修降速；其中的键盘选边已经删除。功能 4“局部边缘吸附”已经整体退役。本文其余内容用于记录原始设计与产品验证过程，不代表现行行为。

## 目标

本组功能服务于手动标注 `person` / `head` / `face` 三类矩形框时的两个核心问题：

1. 人物实例关系：减少 `group_id` 手动输入和事后修正。
2. 矩形框精修：降低鼠标手抖导致的 1-3 像素误差。

四个功能分为两个方向：

| 方向 | 功能 | 主要问题 |
| --- | --- | --- |
| 人物实例绑定 | 功能 1：Auto Create Person Instance | 新建 person 时自动生成人物实例 ID |
| 人物实例绑定 | 功能 2：Digit Bind Draw | 基于已选对象继承/补齐同组 ID |
| 矩形框精修 | 功能 3：Precision Refinement | 鼠标、键盘、选边的精细控制 |
| 矩形框精修 | 功能 4：Local Edge Snap | 基于局部像素边缘的可选吸附命令 |

## 功能 1：Auto Create Person Instance

### 中文名称

新建 person 自动创建人物实例

### 定位

当标注员新建 `person` 矩形框时，系统自动生成新的 `group_id`，避免手动输入 person 实例 ID。

### 入口

设置项：

```text
Settings -> General -> Behavior -> Manual Annotation
Auto Create Person Instance
```

### 触发条件

同时满足：

- 功能开关开启。
- 新建对象 `label == "person"`。
- 新建对象 `shape_type == "rectangle"`。
- 当前不是功能 2 的绑定绘制 pending 上下文。
- 走手动标注创建路径，不作用于 auto-labeling 结果落地。

### 规则

- `person` 框的 `group_id` 默认自动生成，不需要手动输入。
- 新建 `person` 时优先使用新生成的 `group_id`，不沿用 `auto_use_last_gid`。
- 可以与 `auto_use_last_label` 同时开启；连续绘制 `person` 时，每个 `person` 都生成新的 `group_id`。
- 新建成功后状态栏提示 `已创建 person #n`。

### 使用方式

```text
开启 Auto Create Person Instance
不选中任何来源对象
按数字快捷键进入 person/rectangle 绘制，或手动选择 person 矩形绘制
完成框后自动生成新的 group_id
```

## 功能 2：Digit Bind Draw

### 中文名称

数字快捷绑定绘制

### 定位

使用已选中的 `person` / `head` / `face` 作为来源对象，通过数字快捷键新建同一人物实例下的其他框，并继承或补齐 `group_id`。

### 入口

设置项：

```text
Settings -> General -> Behavior -> Manual Annotation
Digit Shortcut Mode = bind_draw
```

### 与数字快捷重命名的关系

数字快捷键有两个互斥模式：

| 模式 | 行为 |
| --- | --- |
| `rename` | 选中对象后按数字键，修改现有对象 label |
| `bind_draw` | 选中来源对象后按数字键，进入绑定绘制 |

### 触发条件

同时满足：

- `Digit Shortcut Mode == bind_draw`。
- 数字快捷键已配置目标 `label + shape_type`。
- v0 只接受目标为 `rectangle + person/head/face`。
- 来源对象为单选 `person/head/face` 矩形框。

### 规则

- 来源对象已有 `group_id`：新建对象继承该 `group_id`。
- 来源对象没有 `group_id`：先生成拟分配 ID，绘制完成后同时回填来源对象和新对象。
- 取消绘制、切图、退出 pending 时，不回填来源对象。
- 同一 `group_id` 下已存在目标 label 时拒绝创建，避免同组重复 `person/head/face`。
- 进入绘制前和绘制完成提交前都检查重复，避免过程中数据变化导致重复。

### 功能 1 与功能 2 的边界

| 状态 | 按数字键行为 |
| --- | --- |
| 未选中对象，目标是 `person/rectangle`，功能 1 开启 | 进入新建 person 实例绘制，完成后生成新 `group_id` |
| 选中 `person/head/face` 来源对象 | 进入功能 2 绑定绘制，继承或回填来源 `group_id` |
| 未选中对象，目标是 `head/face` | 拒绝，提示先选中来源对象 |

## 功能 3：Precision Refinement

### 中文名称

精修控制模式

### 定位

功能 3 是当前矩形框精细调整的核心功能。它解决的是鼠标控制增益、键盘像素移动和单边调整问题。

### 子能力

| 子能力 | 作用 |
| --- | --- |
| 精修模式锁定 | 降低鼠标拖拽增益，减少越过目标边界 |
| Ctrl 临时精修 | 不锁定状态下，按住 Ctrl 临时降速拖拽 |
| 键盘整体微调 | 方向键 1px，Shift + 方向键 5px |
| Tab 键盘选边 | 单选矩形后，Tab 循环选择 left/top/right/bottom |
| 单边键盘微调 | 选中边后，方向键移动当前边 1px，Shift 为 5px |

### 坐标模型

普通拖拽：

```text
image_delta = screen_delta / canvas.scale
```

精修拖拽：

```text
precision_image_delta = screen_delta / canvas.scale / precision_factor
```

精修只缩放拖拽 delta，不改变：

- `transform_pos()`
- hit-test
- hover 判断
- epsilon
- 键盘微调
- 局部边缘吸附

### 精修增益模式

当前支持两种模式：

| 模式 | 实际倍率 |
| --- | --- |
| `fixed` | `canvas_precision_factor` |
| `zoom` | `min(canvas.scale, canvas_precision_max_factor)` |

默认配置：

```yaml
canvas_precision_mode: zoom
canvas_precision_max_factor: 2.0
canvas_precision_factor: 4
```

默认实际效果：

| 缩放比例 | 实际精修倍率 |
| --- | --- |
| 100% | 1.0 |
| 150% | 1.5 |
| 200% | 2.0 |
| 300% | 2.0 |
| 400% | 2.0 |

这样避免早期 `400% -> 1/4` 带来的拖拽僵硬感。默认高缩放下最多降速到 1/2。

### 使用方式

```text
选中矩形框
开启 精修模式锁定，或按住 Ctrl 临时精修
鼠标拖动整体、顶点或矩形边
必要时按 Tab 选边
用方向键做 1px 单边调整，Shift + 方向键做 5px 调整
```

### 设计结论

功能 3 是矩形框精修的主流程。应优先通过合适的精修增益、键盘 1px/5px 微调和 Tab 选边，完成大多数 1-3 像素调整。

## 功能 4：Local Edge Snap

### 中文名称

局部边缘吸附

### 当前定位

局部边缘吸附是一次性命令，不是开关模式。它对当前 Tab 选中的矩形边，在附近图像像素范围内搜索较强边缘，并尝试把当前边移动过去。

当前实现分析的是图像像素梯度，不是模型识别，也不是语义理解。

```text
框边附近像素 -> 灰度/梯度 -> 候选边缘强度 -> 通过阈值则吸附
```

### 使用方式

```text
选中一个矩形框
按 Tab 选择 left/top/right/bottom 某条边
按 Ctrl+Alt+E，或菜单中点击 局部边缘吸附
```

### 当前规则

- 只对当前键盘选中的矩形边生效。
- 默认在当前边附近 `±4` image pixels 搜索。
- 成功时提示边名、旧坐标、新坐标和移动像素数。
- 失败时提示未找到可靠边缘，并保持原位。
- 支持撤销。

### 开发方向问题备注

功能 4 当前存在方向偏差，需要暂缓强化。

原先设计中，局部边缘吸附被理解为功能 3 后的自动补齐步骤：

```text
人工精修到附近 -> 算法根据图像边缘补齐 1-3 像素
```

但讨论后发现，当前标注任务中“图像强边缘”不一定等于“标注规则上的正确边界”：

- 人物边界可能模糊。
- 衣服纹理可能强于人体轮廓。
- 头发、遮挡、光照会干扰梯度。
- `person` 框可能需要遵守数据规范上的留白，不一定贴紧图像边缘。
- `head/face/person` 的框间关系可能比图像梯度更重要。

因此，功能 4 不应作为当前精修主流程继续强化。当前结论是：

```text
功能 3 是主流程。
功能 4 暂作为实验性、可选的一次性命令保留。
后续不继续扩大功能 4，除非重新定义其目标。
```

如果后续要继续发展，应先重新立项，明确它到底是：

1. 图像边缘吸附。
2. 框间几何对齐。
3. person/head/face 实例内规则约束。
4. 人工确认式候选建议。

这四个方向不能混为一个功能。

## 推荐工作流

### 新建人物实例

```text
Auto Create Person Instance = on
Digit Shortcut Mode = bind_draw
未选中对象
按 person/rectangle 数字快捷键
绘制 person 框
系统自动生成新 group_id
```

### 给已有人物补 head/face

```text
Digit Shortcut Mode = bind_draw
选中已有 person/head/face 框
按 head 或 face 的数字快捷键
绘制新框
新框继承来源 group_id
```

### 精细调整框

```text
缩放到 300%-400%
Precision Drag Mode = zoom
Precision Drag Max Factor = 2.0
开启精修模式锁定，或按住 Ctrl 临时精修
拖动框边接近目标
Tab 选边
方向键 1px 微调，Shift + 方向键 5px 微调
```

### 局部边缘吸附

```text
仅在需要实验性辅助时使用
选中矩形 -> Tab 选边 -> Ctrl+Alt+E
若吸附结果不符合标注规则，应撤销并使用功能 3 手动微调
```

## 当前优先级

| 优先级 | 内容 |
| --- | --- |
| P0 | 功能 1/2 的 `group_id` 自动生成、继承、回填、拒绝重复 |
| P0 | 功能 3 的精修增益、Tab 选边、键盘 1px/5px 微调 |
| P1 | 功能 3 的状态栏提示和可发现性 |
| P2 | 功能 4 保留为实验命令，暂不扩展 |

## 验收重点

- 功能 1：新建 `person` 后自动获得新的 `group_id`。
- 功能 2：选中来源对象后，数字快捷绘制的新框继承或回填同一 `group_id`。
- 功能 3：400% 缩放下，`zoom + max_factor 2.0` 不再出现明显拖拽僵硬。
- 功能 3：Tab 后状态栏提示当前选中边，方向键可以进行 1px 单边调整。
- 功能 4：仅验证命令可执行、可失败、可撤销；不作为主流程验收指标。

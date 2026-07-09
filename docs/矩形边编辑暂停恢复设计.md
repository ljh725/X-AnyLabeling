# 矩形边编辑暂停与恢复设计

## 1. 背景

当前矩形边编辑是编辑模式下的工具。用户进入任意创建/标注模式时，
`toggle_draw_mode(False, create_mode=...)` 会关闭矩形边编辑，避免鼠标
事件在“画新标注”和“拖旧矩形边”之间发生冲突。

这个行为是安全的，但会带来一个体验问题：

```text
用户开启矩形边编辑
  -> 按 R 或数字快捷键进入标注模式
  -> 矩形边编辑被关闭
  -> 回到编辑模式后，用户需要手动再打开
```

本设计的目标是：进入标注模式时只临时暂停矩形边编辑，回到编辑模式后
自动恢复用户之前表达过的开启意图。

## 2. 核心假设

快捷键/菜单开关可以代表用户意图层。

用户按下矩形边编辑快捷键，或在菜单中勾选“矩形边编辑”，不只表示
“现在打开一下”，而是表示：

```text
只要我处在编辑模式，就希望矩形边编辑保持可用。
```

因此，进入创建/标注模式时关闭矩形边编辑不应被理解为用户关闭了该功能，
而应被理解为系统为了避免交互冲突做出的临时暂停。

## 3. 三层模型

功能状态分为三层：

```text
用户意图层
  用户是否希望矩形边编辑在编辑模式下可用

实际运行层
  当前 Canvas 是否真的启用了矩形边编辑

状态调度层
  根据当前是编辑模式还是标注模式，决定实际运行层开关
```

建议状态字段：

```text
rect_edge_user_wants_on: bool
canvas.rect_edge_align_enabled: bool
```

其中：

- `rect_edge_user_wants_on` 表示用户意图。
- `canvas.rect_edge_align_enabled` 表示当前画布实际是否启用矩形边编辑。
- 菜单 action / 快捷键是用户改变意图的入口。

## 4. 状态规则

### 4.1 用户手动开启

```text
用户按快捷键或勾选菜单
  -> rect_edge_user_wants_on = true
  -> 如果当前是编辑模式：
       canvas.rect_edge_align_enabled = true
  -> 如果当前是标注/创建模式：
       canvas.rect_edge_align_enabled = false
       等回到编辑模式再恢复
```

### 4.2 用户手动关闭

```text
用户按快捷键或取消菜单
  -> rect_edge_user_wants_on = false
  -> canvas.rect_edge_align_enabled = false
  -> 清理 hover edge / active edge / dragging 等临时状态
```

用户主动关闭后，系统不应在回到编辑模式时自动打开。

### 4.3 进入标注/创建模式

```text
进入 create mode
  -> 如果 rect_edge_user_wants_on == true：
       canvas.rect_edge_align_enabled = false
       清理矩形边编辑临时状态
  -> rect_edge_user_wants_on 保持 true
```

这一步是“暂停”，不是“关闭用户意图”。

### 4.4 回到编辑模式

```text
回到 edit mode
  -> 如果 rect_edge_user_wants_on == true：
       canvas.rect_edge_align_enabled = true
  -> 如果 rect_edge_user_wants_on == false：
       canvas.rect_edge_align_enabled = false
```

恢复时只恢复功能开关，不恢复之前 hover 或 active 的具体边。

## 5. 与现有模式入口的关系

以下入口都会进入创建/标注模式，因此都应触发暂停逻辑：

- 字母快捷键，例如 `R` 创建矩形。
- 数字快捷键创建指定 shape/label。
- 右键菜单中的创建矩形/多边形等动作。
- 左侧工具栏和顶部菜单的创建动作。
- 自动标注面板的 `+Rect`、加点、减点等交互。
- 关键点填充模式进入 point 创建。
- brush polygon 等其他创建类模式。

设计重点不是逐个入口单独处理，而是集中在 `toggle_draw_mode(False, ...)`
这一类创建模式切换处处理暂停，在 `set_edit_mode()` 或等价回到编辑模式的
路径中处理恢复。

## 6. UI 表达策略

有两种 UI 表达方案。

### 6.1 最小实现方案

```text
action.checked 跟随实际运行状态
rect_edge_user_wants_on 单独保存用户意图
```

进入创建模式时：

```text
action.checked = false
canvas.rect_edge_align_enabled = false
rect_edge_user_wants_on = true
```

回到编辑模式时：

```text
action.checked = true
canvas.rect_edge_align_enabled = true
```

优点是贴近当前实现，用户不会看到“菜单勾着但当前不可用”的状态。

### 6.2 精细 UI 方案

```text
action.checked 表示用户意图
canvas.rect_edge_align_enabled 表示实际可用状态
```

进入创建模式时 action 仍保持勾选，但需要额外通过 tooltip、禁用态或状态栏
说明“标注模式下矩形边编辑暂停”。该方案表达更准确，但改动较大。

建议第一阶段采用最小实现方案。

## 7. 恢复保护条件

自动恢复前应确认：

- 当前已经回到编辑模式。
- 不处于正在绘制的中间态。
- 没有未完成的当前 shape。
- 自动标注模式已经结束或不再占用创建交互。
- 关键点填充模式没有继续占用 point 创建。

如果保护条件不满足，应继续保持暂停，等待下一次安全的编辑模式入口再恢复。

## 8. 建议职责分工

### LabelingWidget

负责用户意图和模式调度：

- 记录 `rect_edge_user_wants_on`。
- 在用户快捷键/菜单操作时更新用户意图。
- 在进入创建模式时暂停实际运行状态。
- 在回到编辑模式时按用户意图恢复。
- 同步菜单 action 的 checked 状态。

### Canvas

负责实际交互能力：

- `set_rect_edge_align_enabled(enabled)` 只处理实际开关。
- 关闭时清理 hover、active、dragging 等临时状态。
- 不负责判断用户长期意图。

## 9. 预期不变量

```text
用户主动打开过
  -> 回到编辑模式后恢复矩形边编辑

用户主动关闭过
  -> 回到编辑模式后不自动打开

进入创建模式
  -> 矩形边编辑实际不可用

回到编辑模式
  -> 是否可用取决于用户意图

恢复功能
  -> 不恢复旧 hover/active 边
```

## 10. 一句话结论

矩形边编辑的快捷键/菜单开关应被建模为用户意图层：

```text
快捷键/菜单负责表达用户想不想用；
Canvas 负责当前能不能用；
LabelingWidget 负责在标注模式和编辑模式之间暂停/恢复。
```

这样进入标注模式时不会抹掉用户意图，回到编辑模式后也不会变成系统
自作主张打开功能，而是在恢复用户之前明确表达过的选择。

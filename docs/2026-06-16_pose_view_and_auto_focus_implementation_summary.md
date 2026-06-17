# Pose View 标签隐藏与自动聚合模式实现总结

> 日期：2026-06-16
> 计划文档：docs/0616_pose_view_label_hide_and_auto_aggregation_change_plan.md
> 实施计划：docs/superpowers/plans/2026-06-16-pose-view-label-hide-and-auto-aggregation.md

## 1. 实现目标

完成两个核心修改：

1. **Pose View 开启后隐藏全部标签（原生 Canvas 标签 + Pose 关键点标签）**
2. **自动聚合模式状态机化，并确保不可见目标不可交互**

> 修订（2026-06-16 二次）：初版误解需求——只隐藏了原生 Canvas 标签，而 Pose
> 关键点标签（PoseRenderer 绘制的 nose/left_eye 等文字）仍常驻显示。最终确
> 定的交互为：**Pose View 下原生标签全隐藏；关键点标签默认隐藏，鼠标悬停或
> 选中某个 person（含其关键点或目标框）时，仅显示该对象同组的全部关键点标
> 签**；点击空白区域取消选中即回到纯净视图（只剩骨架/圆点/bbox）。

## 2. 修改文件

| 文件 | 修改内容 |
|------|----------|
| `anylabeling/views/labeling/widgets/canvas.py` | 新增 `is_shape_interactive()`、`_should_draw_standard_label()`；统一交互入口；重构标签绘制与 PoseRenderer 调用位置 |
| `anylabeling/views/labeling/label_widget.py` | 新增 `auto_focus_group_id`；重构自动聚合状态机；左侧标签列表过滤与同步 |
| `anylabeling/views/labeling/widgets/pose_label/pose_renderer.py` | 新增 `show_labels` 参数，控制 Pose 关键点标签显示 |
| `tests/test_canvas_interaction.py` | 新增 8 个单元测试 |

## 3. Pose View 标签隐藏行为

### 3.1 开关方式

在主界面勾选 **View → Pose View** 即可。

### 3.2 最终行为

```text
Pose View OFF:
    show_labels / label_on_selection 行为与修改前一致

Pose View ON:
    Canvas 原生标签（label / group_id / description）全部隐藏
    Pose 关键点标签：默认隐藏
        - 鼠标悬停某个 person  → 显示该组关键点标签
        - 点击选中某个 person（关键点或目标框）→ 显示该组关键点标签
        - 换到另一个 person → 切换到那组
        - 点击空白区域 → 取消选中 → 回到纯净视图（无关键点标签）
    缩放触发已关闭（放大不再自动显示全部标签）
    始终渲染：骨架、关键点圆点、bbox
```

### 3.3 关键代码变更

- 新增 `Canvas.is_shape_interactive(shape)`：判断 shape 是否可交互
- 新增 `Canvas._should_draw_standard_label(shape)`：Pose View 开启时直接返回 `False`（隐藏原生标签）
- 原生标签绘制条件改为 `if self.show_labels and not self.pose_config.enabled`
- 移除原 Pose View 特例跳过逻辑，统一使用 `_should_draw_standard_label()`
- `PoseRenderer.render()` 移出原生标签 block；**调用处固定
  `show_labels=True`、`label_on_selection=True`、`zoom_reveals=False`**
  （`canvas.py` Pose View overlay 内）：
    - `show_labels=True`：启用关键点标签（不再是强制 False）
    - `label_on_selection=True`：Pose View 内置"按组按需显示"——只有
      悬停/选中的组才显示标签
    - `zoom_reveals=False`：关闭缩放触发，避免放大时冒出全部标签
- `PoseRenderer` 的 `any_selected` 判断补充 person 目标框的 `.selected`，
  使"点 person 框"也能点亮该组（原先只识别关键点选中）

## 4. 自动聚合模式行为

### 4.1 状态机

```text
OFF
  ↓ 开启自动聚合（Alt+H）
ARMED（auto_focus_instance=True, auto_focus_group_id=None）
  ↓ 选择可见且有 group_id 的目标
FOCUSED(group_id)
  ↓ 选择另一个可见 group
FOCUSED(new_group_id)
  ↓ ESC 或再次 Alt+H 关闭
OFF
```

### 4.2 关键行为

| 操作 | 行为 |
|------|------|
| Alt+H 开启 | 不立即隐藏任何目标，状态提示“自动聚合已开启，选择目标后聚焦” |
| 选择可见有 group_id 的目标 | 只显示同 group 目标，其他隐藏 |
| 选择另一个可见 group | 聚合目标切换 |
| ESC | 直接关闭自动聚合，全部目标恢复显示 |
| Alt+H 关闭 | 直接关闭自动聚合，全部目标恢复显示 |
| 没有 group_id 的 shape | 不触发聚合 |

### 4.3 不可见目标保护

通过 `is_shape_interactive()` 统一控制：

- 被 `hidden_by_filter=True` 隐藏的目标：不能 hover、不能鼠标选中、不能双击编辑
- `shape.visible=False` 的目标：不能交互
- `canvas.visible[shape]=False` 的目标：不能交互
- 左侧标签列表：不可交互项点击后不会被选中，对应行会隐藏
- 程序化入口 `select_shapes()`：会自动过滤掉不可交互 shape

### 4.4 关键代码变更

- 新增 `LabelingWidget.auto_focus_group_id`
- `toggle_auto_focus_instance()`：开启进入 ARMED，关闭恢复全部可见
- `_auto_focus_on_selection()`：只根据可交互且有 `group_id` 的目标更新聚合目标，并清理被隐藏目标的 `selected` 状态
- `_escape_auto_focus_if_active()`：ESC 直接关闭聚合
- `_sync_label_list_hidden_by_filter()`：聚合时同步隐藏左侧列表行并取消选中

## 5. 测试与验证

| 项目 | 结果 |
|------|------|
| `pytest tests/test_canvas_interaction.py -v` | 8 passed |
| `black -l 79 <4 files>` | 无改动 |
| `flake8 <4 files>` | 仅既有 F841/C901/F541 问题，无新增错误 |
| 完整 pytest | 因环境缺少 `supervision` 无法运行，与本次改动无关 |

## 6. 已知边界

- Pose View 下关键点标签采用"按组按需显示"（`show_labels=True` +
  `label_on_selection=True` + `zoom_reveals=False` 传入
  `PoseRenderer.render()`）。无任何额外开关：悬停/选中即显示该组，点空白
  回到纯净。若日后需要"完全无标签"的常开纯净模式，可新增
  `pose_config.show_pose_labels` 开关。
- 自动聚合使用的 `hidden_by_filter` 仅表示临时聚合隐藏，不影响其他筛选系统。

## 7. 如何验证

### Pose View 标签按组显示

1. 打开一张含 pose 标注的图片（多人/多组）。
2. 关闭 Pose View，确认普通标签（label / group_id / description）正常显示。
3. 勾选 Pose View，确认：
   - 原生标签全部消失
   - **无悬停/无选中时，Pose 关键点标签也全部消失（纯净视图）**
   - 骨架、关键点圆点、bbox 仍显示
4. 鼠标悬停某个 person → 该组关键点标签出现；移到另一个 person → 切换。
5. 点击某个 person（关键点或目标框）→ 该组关键点标签常驻显示。
6. 点击画面空白区域 → 选中清空 → 关键点标签全部消失，回到纯净视图。

### 自动聚合

1. 选中一个带 `group_id` 的 shape。
2. 按 `Alt+H` 开启自动聚合。
3. 确认开启后没有立即隐藏其他目标。
4. 点击该 shape 或同 group 的 shape，确认只显示该 group。
5. 点击另一个可见 group 的 shape，确认聚合目标切换。
6. 按 `ESC`，确认自动聚合关闭、全部目标恢复显示。

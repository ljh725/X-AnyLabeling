# 六项 P2 修复结果复核 · 2026-11-17

后续：本报告保留修复前复核结论。F1–F4 已于同日修复并通过专项与密集复核全目录验证，见 [实施与验证结果](FIX_IMPLEMENTATION.md)；画布既有失败、原生退出及未覆盖项也在该记录中单列。

结论：**原八项复现全部通过，但六项问题中只有 R2、R5 已在本轮范围内闭环；R1、R3、R4、R6 仍有遗漏或修复引入的回归。**补充六项独立行为检查全部失败，不能据原八项通过就判定六项全部修复。

本次只复核和保存证据，未修改业务代码、测试实现或 OpenSpec 勾选状态。

## 对象与验证口径

- 工作分支仍为 `codex/4.2.1/dense-review-redesign-plan`，起点 HEAD 为 `90f3e876`；修复代码仍在未提交工作区。本轮结论针对该工作区，不代表仅检出 HEAD 即可复现相同结果。
- 原问题定义及修复前日志见 [首次报告](REVIEW.md)。本轮逐项检查 `display.py`、`workspace.py`、`label_widget.py` 及新增持久测试 `test_workspace_review_fixes.py`，并验证相关调用链。
- 沿用 conda `x-anylabeling-cu12`、Qt offscreen、`get_config()` 的真实窗口配置会话及 `tests/conftest.py` 的 `.tmp/` 写保护和 INI QSettings；未放宽隔离。Qt DLL 仍需在沙箱外加载。
- 原复现原样运行，补充实验仅写入 `.tmp/dense-review-recheck-20261117/test_followup.py`；两个脚本均加载现有隔离 fixture。进程启用 `-vv -o faulthandler_timeout=30` 和外层硬超时。
- 既有 `.gitignore`、开发文档、业务代码、测试和翻译资源全部保留，本轮只提交报告与台账。

## 六项结果

| 原问题 | 原复现结果 | 修复复核结论 |
| --- | --- | --- |
| R1 隐藏 dock 留下覆盖层和编辑暂停 | 通过 | 真正 hide 已释放；浮动时也被当成退出，原图对照丢失，见 F4 |
| R2 查漏刷新重置观察范围 | 通过 | 本轮范围内通过；`refresh_all()` 改为同步区域显示，不再无条件导航 |
| R3 重开丢失任务预设 | 通过 | 预设恢复，但会恢复旧任务快照的对象，覆盖最新当前目标，见 F3 |
| R4 小数缩放和适应窗口模式丢失 | 两参数均通过 | scale/FIT_WINDOW 表面值恢复；控件、画布尺寸及 FIT_WIDTH 仍未恢复，见 F1 |
| R5 查漏修改普通文字开关 | 通过 | 本轮范围内通过；已移除预设对 `canvas.show_texts` 的直接赋值 |
| R6 关联点未区分任务、查漏未收起点 | 两项均通过 | 类别与框/点任务的角色已区分，但查漏点轮廓仍绘制且可命中，见 F2 |

## 尚未闭环的发现

### F1 · P2 · 视口恢复缺少控件、画布几何和完整缩放模式

位置：`anylabeling/views/labeling/label_widget.py:4567`，重点为 4584–4589 的分支。

恢复手动视图时只赋值 `canvas.scale`，没有同步缩放控件、`canvas.adjustSize()`、导航器、图像视图记忆及相应滚动范围。通过正常入口设置 126.4%，切到查漏再返回：实际 scale 已为 1.264，但缩放控件仍显示 25，画布宽仍为查漏时的 160 像素，而原先宽为 809 像素。这会使显示值、可滚动几何和画布实际变换不一致。

另外，仅特殊处理 FIT_WINDOW，FIT_WIDTH 被归入手动分支。真实调用 `set_fit_width()` 后往返，模式由 FIT_WIDTH（1）变成 MANUAL（2）。

建议统一复用完整视口恢复路径；同文件 `_dense_review_restore_view()` 已展示了精确缩放、控件、画布尺寸和视图记忆同步所需步骤。保留三种缩放模式，不只验证 scale 和 FIT_WINDOW。

证据：`test_task_snapshot_restores_zoom_control_and_canvas_size`、`test_task_snapshot_restores_fit_width_mode` 均失败。

### F2 · P2 · 查漏隐藏点只清零符号和类名，轮廓及命中仍在

位置：`anylabeling/services/dense_review/display.py:407`；绘制链为 `shape.py:710` 的 `_outline_path()` 和 `shape.py:771` 的 `_paint_with_display_style()`。

点类型只将 points/text/text_plate 设为零，仍保留非零 outline。`_outline_path()` 对点会构建点标记路径，`Shape.paint()` 仍画这个轮廓；`drawable` 和 `hittable` 也因非零 outline 保持 True。

真实窗口进入查漏后，将同一 kp1 和解析出的 paint style 绘制到空白 QImage，像素发生变化；在 kp1 坐标调用真实画布 `_shape_hit_candidates()`，kp1 仍在候选列表。原来的 `style.points == 0` / `style.text == 0` 断言不足以证明它已从画布收起。

建议按点类型协调全部可绘制组件和交互资格，确保隐藏点不会残留轮廓、属性或组连线，也不能成为隐藏的编辑目标；保留矩形查漏轮廓。

证据：`test_coverage_point_has_no_rendered_pixels`、`test_coverage_point_is_not_hittable` 均失败。对应原 R6、DP-02、SN-05。

### F3 · P2 · 重开面板重放旧快照，回退当前审核对象

位置：`anylabeling/views/labeling/dense_review/workspace.py:3378`，以及 `_restore_task_target()` 中 2906–2909 的 `session.set_current()`。

重开调用 `_restore_task_view(restore_viewport=False, focus=False)`，虽然没有移动画布，仍会恢复上次任务切换时缓存的 shape。复现为：类别任务的 rect1 → 查漏 → 类别 → 正常导航 rect2 → 关闭再打开；当前对象由 rect2 回退为 rect1。此时界面/审核范围可能切到旧对象，而画布仍停留在用户最新视口。

建议重开只恢复任务策略并以当前会话目标为准；若需要重放快照，应在关闭前准确捕获最新目标，避免使用上次切换的过期值。此问题由修复 R3 新增的重开恢复路径引入。

证据：`test_reopen_keeps_latest_current_object` 失败，实际 rect1，预期 rect2。对应 WL-02、WL-07。

### F4 · P2 · 浮动触发退出清理，把下拉原图对照切回聚焦

位置：`anylabeling/views/labeling/dense_review/workspace.py:3380` 的 `hideEvent()` 以及重开的 `_apply_task_display()` 路径。

新增 hide 处理没有区分真正隐藏和浮动/停靠的临时 hide/show。通过下拉框选择 original，然后正常调用 `setFloating(True)`，原图对照被清理；show 时按任务预设重新选择 focus，最终 `_dense_review_display_mode == "focus"`。这改变了用户当前显示策略和编辑暂停状态。

此处复现是下拉选择的持续原图对照，不是按住看原图；按住模式失焦结束的既有规则不能解释本次变化。建议对浮动/停靠保留显示策略与当前目标，真正关闭/隐藏仍及时清理，分别验证两类生命周期。

证据：`test_float_keeps_original_display_mode` 失败，实际 focus，预期 original。对应原 R1、WL-02、DP-13。

## 测试证据及覆盖限制

| 验证 | 结果 | 日志 |
| --- | --- | --- |
| 原八项复现原样复跑 | **8 passed**，28.43s，退出码 0 | [原复现](recheck-original-probes.txt) |
| 补充六项真实窗口行为检查 | **6 failed**，23.23s，退出码 1；归并为 F1–F4 | [失败证据](recheck-followup.txt) |
| 与上轮相同的画布十文件 | **286 passed，6 subtests passed**，15.96s，退出码 0 | [画布日志](recheck-canvas.txt) |
| 密集复核全目录（含新增持久修复测试） | **276 passed，698 subtests passed**，449.19s，退出码 0 | [全目录日志](recheck-dense-review.txt) |
| OpenSpec strict | valid，退出码 0 | 本次命令输出 |
| 三个修复业务文件及新增持久测试的 diff 空白检查 | 通过 | 本次命令输出 |

新增持久测试 `test_workspace_review_fixes.py:105` 有 `assert ... or True`，该断言恒真，不能证明“明确区域导航确实移动画布”。该用例仍检查了 session 的 current_region，但视口效果需补充有效断言；本轮没有修改该测试。

没有重跑全仓、完整画布、标注、设置和 Inspector 套件；工具栏布局、Windows 点云、真实屏幕、双屏/DPI、性能及减负验收均未执行。未重新跑 black/flake8。现有测试通过不能替代上述像素、命中、生命周期和完整视口的失败证据。

本轮只新增复核文档与证据的本地提交，修复代码仍未提交；未推送、未开 PR、未合入 `codex/4.2.1-baseline-organization`。

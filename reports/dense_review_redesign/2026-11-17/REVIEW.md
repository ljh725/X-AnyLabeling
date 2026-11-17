# 密集复核工作区实现复核 · 2026-11-17

复核对象为 `redesign-dense-review-workspace`，结论为**实施中，发现 6 项待修问题，不能按整体完成交付**。本次只复核并留存证据，未修改业务代码或勾选实施任务。

## 修订与范围

- 分支：`codex/4.2.1/dense-review-redesign-plan`，复核时 HEAD 为 `134462ac35761a13aa2fa60f06fd7ca4e45d67c7`。
- 包含开工时已存在的未提交修改：工作区 dock 与三任务视图、主窗口接入、显示/原图对照/分组编辑、对应测试及四语言资源；新增未跟踪文件 `tests/test_dense_review/test_workspace_dock_tasks.py` 同样纳入验证。
- `.gitignore` 和 `docs/development/` 的既有工作保留，未纳入本次提交。
- 合入目标沿用 `codex/4.2.1-baseline-organization`；此次仅本地保存报告，未推送、开 PR 或合入。
- 对照五份规格、设计、验收矩阵与任务清单。清单实际为 **25/91 已勾选、66 项未勾选**；第 9 组已有未提交实现，但仍未勾选，不能把新增控件和通过已有测试等同于任务完成。

下列源码行号对应复核时的工作区，后续修复可能改变行号。

## 发现

### R1 · P2 · 隐藏 dock 没有清理覆盖层，原图模式下会继续禁止编辑

位置：`anylabeling/views/labeling/dense_review/workspace.py:3314`（`closeEvent` / `_end_review_view`）；`label_widget.py:4988` 的 `dense_review_active()`。

清理只接在 `closeEvent()`，没有处理 dock 的 hide/visibility 生命周期。正常打开后进入原图对照，再调用 dock 的 `hide()` 时，host 已认为工作区不活跃，但 canvas 仍安装覆盖层，`annotation_editing_paused()` 仍为 True。普通画布因隐藏面板留下的状态而无法修改标注。

建议区分真正隐藏与浮动/重新停靠的临时事件，为不可见状态提供幂等清理；恢复时重新安装当前任务策略。任务 9.6、DP-17、WL-12 需覆盖这一入口，而不只验证 `close()`。

复现：`test_hide_dock_removes_review_overlay`，失败值 `annotation_editing_paused() == True`。

### R2 · P2 · 查漏页的普通刷新会覆盖用户刚调整的观察范围

位置：`anylabeling/views/labeling/dense_review/workspace.py:1752`。

`refresh_all()` 在查漏任务中无条件调用 `_show_current_region()`，后者执行区域适配缩放和重新定位。用户放大检查局部后，刷新、编辑后的状态更新等都会把视图拉回整区。实测 75% 缩放、pan `(17, 23)` 刷新后变为 25%、pan `(35, 7.3333...)`。

建议把区域导航与列表/状态刷新分开，只有区域身份变化或用户明确定位时移动画布。对应任务 9.2、10.3、SN-06。

复现：`test_background_refresh_keeps_coverage_viewport`。

### R3 · P2 · 关闭再打开保留任务名称，却丢失该任务的显示预设

位置：`anylabeling/views/labeling/dense_review/workspace.py:3299`，及 `label_widget.py:5478`。

关闭时清空 `_dense_review_role_styles`，重开却因 `_view_ready` 为 True 只恢复 display mode，跳过 `_apply_task_display()`。因此仍显示“空间查漏”，实际已经恢复普通类别核对的角色强度。非当前矩形 outline 从关闭前 0.45 变成 0.65，points 从 0 变成 0.55，文字和底板也恢复默认值。

建议将重开与浮动/停靠期间的 show 事件分开，重开必须恢复任务策略，并保留当前有效目标和视口。对应任务 9.2、9.6、WL-07。

复现：`test_reopen_reapplies_coverage_preset`。

### R4 · P2 · 任务视口快照丢失小数缩放和适应窗口模式

位置：`anylabeling/views/labeling/label_widget.py:4547`、`:4564`。

快照保存整数 `zoom_widget.value()`，没有保存实际 `canvas.scale` 和 `zoom_mode`；恢复调用 `set_zoom()` 又强制变成手动模式。通过应用正常入口设置 126.4%，切到查漏再回来后变成 126%；原先适应窗口的视图往返后变成手动缩放，后续调整窗口也不再按原模式适配。

同文件原图对照的 `_dense_review_snapshot_view()` / `_dense_review_restore_view()` 已保存实际缩放和模式，可统一视口快照契约，避免两套实现语义漂移。对应任务 9.2、WL-07。

复现：`test_task_round_trip_keeps_fractional_zoom_and_mode[False]`、`[True]`，分别得到 `(1.26, MANUAL)` / `(1.264, MANUAL)` 与 `(0.1, MANUAL)` / `(0.1, FIT_WINDOW)` 的差异。

### R5 · P2 · 查漏预设直接覆盖普通画布的文字开关

位置：`anylabeling/views/labeling/label_widget.py:4613`。

`dense_review_apply_task_preset("coverage")` 直接设置 `canvas.show_texts = True`，离开查漏或关闭面板时均不恢复。原先关闭的普通文字显示因此被打开，动作勾选和实际画布状态也可能不一致。它与普通类别标签开关 `show_labels` 是不同的设置，已有“不回写普通标签开关”测试未覆盖这一项。

建议把复核文字覆盖限制在显示解析/绘制策略内，保留用户当前普通设置，而不是无条件写 canvas 开关。对应任务 6.1、12.1、DP-18、WL-12。

复现：`test_coverage_does_not_change_ordinary_text_switch`，关闭后 `canvas.show_texts == True`，预期 False。

### R6 · P2 · 关联点提升不区分任务，查漏时仍显示当前人物的点和点名

位置：`anylabeling/views/labeling/label_widget.py:4944`、`:4595`。

显示 context 总是把当前矩形的关联点加入 `associated_ids`，不区分类别、框与关键点、查漏任务。查漏只把 batch/other 的 points 设为零，current 样式却继承 batch 默认 `points=0.55`、`text=0.75`。结果关联点仍被赋予 current 角色并绘制，与查漏默认收起点和点名的预设不一致；类别核对与框/关键点观察对关联点的提升也没有形成区别。

建议显式将任务策略送入角色解析，关联点仅在相应人物观察任务提升；查漏的点与点文字按形状类型关闭，避免影响矩形轮廓。对应任务 9.2、10.3、D1/D2、SN-05。

复现：`test_coverage_hides_associated_keypoint_symbols` 得到 points 0.55；`test_category_does_not_promote_associated_points` 得到 role `current`。

## 验证

环境为 conda `x-anylabeling-cu12`，Python 3.12.12、Windows、Qt offscreen。全部真实窗口用例使用 `get_config()` 建立隔离配置会话，沿用现有 `.tmp/` 写保护、INI QSettings，不接触真实用户配置。

首次受限运行因 `QtCore` DLL 加载被拒绝而退出 4，这是环境限制。重新运行时保留配置隔离，并用外层 `subprocess.run(timeout=...)` 设置硬超时，pytest 同时启用 `-vv -o faulthandler_timeout=30`。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| `pytest tests/test_dense_review` | 264 passed，698 subtests passed，394.46s，退出码 0 | [完整日志](dense-review.txt) |
| 受影响画布十个文件 | 286 passed，6 subtests passed，14.78s，退出码 0 | [完整日志](canvas.txt) |
| 新增真实窗口复核探针 | **8 failed**，26.40s，退出码 1；对应上述 6 项缺陷 | [完整失败日志](probes-final.txt) |
| `openspec validate redesign-dense-review-workspace --strict` | valid，退出码 0 | 本次命令输出 |
| 三个相关业务文件 `git diff --check` | 通过 | 本次命令输出 |

画布验证文件为 `test_fill_opacity`、`test_shape_selection`、`test_groups`、`test_label_visibility_mode`、`test_rotation_handle`、`test_selection_priority`、`test_drag_refresh`、`test_shift_point_fit_interaction`、`test_rectangle_edge_migration`、`test_navigation`。

一次性复核脚本位于本机 `.tmp/dense-review-audit-20261117/test_audit.py`，复用 `tests/test_dense_review/test_workspace_dock_tasks.py` 的真实窗口 fixture，加载 `tests.conftest` 保留配置写保护。初版七项探针后，将缩放探针改为正常应用入口并参数化，最终以本报告的八项结果为准。

历史报告提及的两项 Shift 拟合失败在此次工作区测试中均通过；本次没有为它们作新修复，不能把当前工作区验证结果归到仅 HEAD 的代码上。现有全目录回归通过与新增探针失败同时成立：它们覆盖的行为不同。

## 任务与交付边界

25 个已勾选项不能代表 91 项整体完成。第 9 组的 dock、三任务入口有代码和已有测试，但上述任务恢复与显示问题仍待修；未勾选的标签避让、重叠候选、卡片聚合/异步预算、小地图、设置和 Inspector 等保持原状态。

未运行完整 `tests/test_canvas`、`tests/test_labeling`、`tests/test_settings`、`tests/test_inspection` 或全仓测试；工具栏布局和 Windows 不适用的点云套件未运行。真实屏幕 M1–M8、双屏/DPI、性能及两位用户减负验收未执行。本次未重新跑 black/flake8，业务代码未修改。

本批本地提交只含复核报告、日志和现有 CUSTOM-121/仓库操作台账的复核登记；开工时已有业务改动保持原样。没有新实现提交、远端推送或目标分支合入。

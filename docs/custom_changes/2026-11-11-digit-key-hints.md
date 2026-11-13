# CUSTOM-118：数字键提示条修复与映射解析统一

- 状态：已实现待验证（自动化通过，真实屏幕人工验收未做）
- 功能分类：原功能修改（数字键提示条为 4.2.1 新增本地能力）
- 创建日期、最后更新日期：2026-11-11（Asia/Shanghai）
- 原始版本与基线提交：X-AnyLabeling 4.2.1，基线 `f87fdfa8`
- 实现提交 / PR：无（工作区改动，未提交）
- 工作区已有修改、前置依赖：工作区另有一批未提交的矩形预览/单点拟合改动
  （`rect_edge_click.py`、`rectangle_preview.py`、`point_fit.py`、
  `rectangle_crosshair.py`、`canvas.py` 等）以及数字键提示条的首版实现
  （`widgets/digit_shortcut_bar.py`、`show_digit_shortcuts` 配置、设置页排除项）。
  本记录只涵盖提示条复核修复，未触碰上述绘制/拟合逻辑。

## 问题与目标

复核数字键提示条首版时发现六个问题：

1. 图片生命周期：打开有效图片后再打开不存在或损坏的文件，提示卡仍可点击并
   切换绘制模式。预期：图片重置或加载失败后卡片禁用且清除高亮，成功加载后恢复；
   普通绘制与四极值草稿进行期间卡片禁用，完成或取消后恢复。
2. 显示设置同步：`show_digit_shortcuts` 未纳入 `SettingsController` 的运行时
   监听，同一配置会话中其他入口提交新值后菜单勾选与提示条不同步。
3. 映射解析：提示卡与物理数字键各自解析映射，规则可能漂移；只有 `mode` 的旧配置
   与字符串数字键的兼容性无统一保证。
4. 打包翻译：嵌入资源里的 `zh_CN.qm` 未包含「数字键提示」「未绑定」，打包后失效。
5. 刷新：相同映射/交互状态/高亮状态重复传入时仍整表刷新。
6. 文档：中英文用户手册未覆盖提示条行为。

## 修改位置与方法

| 文件 / 函数 | 原行为 | 改后行为 | 迁移注意事项 |
| --- | --- | --- | --- |
| `widgets/digit_shortcut_bar.py`：`resolve_digit_mapping()`（新增） | 解析逻辑分散在 `DigitShortcutBar.set_mappings` 与 `LabelingWidget.create_digit_mode` | 单一解析入口：整数键与字符串数字键都接受；`mode` 不在 `Shape.get_supported_shape()` 视为未绑定；缺 `label` 或只有空白时用默认 `object` | 提示卡与物理数字键必须继续共用此函数，不要再各自判空 |
| `DigitShortcutBar.set_mappings()` | 每次整表重建标签/提示/可访问名称并重置高亮 | 先归一化为 `{digit: (label, mode)}`，与现有映射完全相同则直接返回；映射变化时仅当当前高亮数字不再绑定时清除 | 归一化结果用元组，保证可比较；标签实际变化仍刷新文字、tooltip、accessibleName |
| `DigitShortcutBar.set_interactions_enabled()` / `set_active_digit()` | 每次都遍历九个按钮 | 状态未变化时跳过 `_refresh_buttons()` | 状态仍写入字段，重复值不触发重绘 |
| `DigitShortcutBar.set_active_digit()` | `digit in self._mappings`（初始化时为 `{}`） | `self._mappings` 初值改为 `None` 并用 `or {}` 兜底 | 避免构造期 `set_mappings({})` 之前出现 None 判断异常 |
| `LabelingWidget.create_digit_mode()` | 自行 `data.get("mode")`、`data.get("label", "object")` | 调用 `resolve_digit_mapping()`，返回 `None` 即按未绑定处理 | 数字键 0 仍走同一路径，仍可配置与使用，只是不显示在提示条 |
| `LabelingWidget.reset_state()` | 只重置画布/图片状态 | 额外禁用提示卡并清除高亮，覆盖图片关闭、切换以及加载失败前的重置 | 成功加载由 `toggle_actions(True)` 恢复；不要改成在失败分支单独处理 |
| `settings/controller.py`：`SettingsController.__init__` 的 `_runtime_keys` | 含 `digit_shortcuts`，不含 `show_digit_shortcuts` | 增加 `show_digit_shortcuts`，复用既有 `SettingsRuntimeApplier.apply_change` 同步菜单勾选与提示条可见性 | 该键已在 `schema.EXCLUDED_KEYS` 中，不进设置页，仅作运行时同步 |
| `anylabeling/resources/translations/*`、`resources.py` | 嵌入 `zh_CN.qm` 缺少两条新翻译 | 通过 `scripts/compile_languages.py` 重新生成 | 改 `.ts`/`.qrc` 后必须重跑脚本，不要手改 `resources.py` |
| `pyproject.toml`：`markers` | 只有 `slow` | 新增 `shared_config`，用于「窗口与配置会话共享同一 config 对象」的用例 | 仅供测试标记使用 |
| `docs/zh_cn/user_guide.md`、`docs/en/user_guide.md` | 无提示条说明 | 补充显示方式、卡片行为、旧配置兼容、数字键 0 与绘制期间禁用 | — |

新增/调整测试：

- `tests/test_widgets/test_digit_shortcut_bar.py`：旧映射兼容、相同输入跳过刷新与
  标签变化仍刷新、嵌入 `zh_CN.qm` 翻译（`DigitShortcutBar/Unbound`、
  `LabelingWidget/Digit Key Hints`）。
- `tests/test_labeling/test_digit_rectangle_save.py`：图片生命周期（缺失/损坏文件）、
  普通绘制与四极值草稿期间禁用、配置会话提交后菜单与提示条同步、只有 `mode` 的
  旧映射对卡片与物理键都生效且数字键 0 不在提示条中。

## 兼容与数据影响

- 配置文件：未新增字段（`show_digit_shortcuts` 首版已存在，默认 `false`）。
  旧配置 `digit_shortcuts: {1: {mode: rectangle}}` 继续可用，卡片与按键都使用
  默认标签 `object`；只有 `mode` 的条目在管理器里保持原样，未被编辑的数字不会被写回。
- 整数键与字符串数字键仍由 `config._normalize_digit_shortcuts` 归一化，运行时两处
  （提示卡、物理键）都兼容两种写法。
- 提示条仍只显示 1–9 共九张等宽单行卡片，焦点策略不变（`NoFocus`），数字键 0
  不出现在提示条中。
- 保存失败回滚、默认隐藏、重启恢复均由既有 `update_user_preference` 与
  配置会话保证，本次未改变该路径。

## 验证

环境：conda `x-anylabeling-cu12`（Python 3.12 + PyQt6），
`C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe`，
`QT_QPA_PLATFORM=offscreen`（`tests/conftest.py` 强制），
`--basetemp` 使用仓库内 `.tmp/bt-*` 独立目录。

计划：先跑提示条/数字键专项，再跑受影响目录 `tests/test_settings`、
`tests/test_config`、`tests/test_widgets`、`tests/test_canvas`、`tests/test_labeling`。

实际（全部为自动化结果，未经真实屏幕人工验收）：

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_widgets/test_digit_shortcut_bar.py tests/test_labeling/test_digit_rectangle_save.py tests/test_settings/test_digit_shortcut_flow.py tests/test_labeling/test_digit_label_actions.py` | 87 passed |
| `pytest tests/test_settings` | 90 passed, 1 skipped, 9 subtests passed |
| `pytest tests/test_config` | 62 passed |
| `pytest tests/test_widgets --ignore=tests/test_widgets/test_toolbar_layout.py` | 52 passed；2 failed：`test_canvas_adjustment.py::test_brightness_contrast_updates_are_throttled`、`test_defaults_and_tooltips_describe_adjustment_targets`（基线 `f87fdfa8` 同样失败，非本次回归） |
| `pytest tests/test_canvas`（逐文件执行，整目录会挂起） | 24 个文件通过（728 用例中除下列项外全部通过）；2 failed：`test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`、`test_rectangle_size.py::test_action_switch_updates_canvas_and_config`（基线同样失败）；3 个文件挂起：`test_navigation.py`、`test_rectangle_edge_migration.py`、`test_rectangle_preview_overlap.py` |
| `pytest tests/test_labeling`（逐文件执行） | 28 个文件通过；4 个文件失败：`test_label_widget_attributes.py`（2）、`test_label_widget_metrics.py`（1）、`test_upload_shape_attributes.py`（3）、`test_video_classifier_workers.py`（2），共 8 项，全部在基线同样失败；6 个文件挂起：`test_candidate_review_regressions.py`、`test_check_status.py`、`test_correction_metrics_gate.py`、`test_drag_commit.py`、`test_image_switch.py`、`test_show_shape_status.py` |
| `black --check` / `flake8` | `widgets/digit_shortcut_bar.py` 已格式化且无告警；`settings/controller.py` 仅保留基线已有的 `C901`（37）复杂度告警；`label_widget.py` 的 black 差异位于本次未触碰的既有区域（工作区并行改动），未处理 |

挂起原因（`-o faulthandler_timeout=45` 抓栈）：这些用例的 `window` fixture 直接
`MainWindow(...)` 构造且未先建立配置会话目标，构造期 `actions` 初始化经
`set_canvas_params` → `update_user_preference` → `persist_user_preferences` 保存失败后
`error_message` 弹出模态框阻塞事件循环。已在基线提交 `f87fdfa8` 的独立
`git worktree` 中复现同一栈帧（`label_widget.py` 的 `error_message` /
`persist_user_preferences`），确认非本次改动引入；本次未修改该保存/提示路径。

未运行：`tests/test_widgets/test_toolbar_layout.py`（CI 排除）、`tests/test_pointcloud`
（需 Linux + xcb + xvfb，Windows 上会失败）、其余与提示条无关的目录
（`tests/test_canvas` 与 `tests/test_labeling` 之外的部分）。

已知限制：提示条在真实屏幕下的深浅主题、缩放屏与既有视觉检查未由本次自动化覆盖。

## 迁移与回退

- 迁移顺序：`resolve_digit_mapping()` 与 `DigitShortcutBar` 的缓存逻辑是基础，必须先迁移；
  再迁移 `create_digit_mode` 调用点与 `reset_state` 禁用逻辑；最后迁移控制器监听键。
- 上游变化时的适配点：若上游改了数字键解析或 `Shape.get_supported_shape()`，
  统一在 `resolve_digit_mapping()` 内适配，不要在两处分别改。
- 需保留的原行为：默认隐藏、重启恢复、保存失败回滚、数字键 0 可配置可用、
  九张等宽单行卡片与 `NoFocus` 焦点策略、绘制期间不丢草稿。
- 回退：删除 `resolve_digit_mapping()` 并把 `set_mappings`／`create_digit_mode` 恢复为各自
  解析；移除 `reset_state()` 中的禁用两行；从 `_runtime_keys` 去掉
  `show_digit_shortcuts`；重新生成翻译资源；撤掉两份手册段落与新增测试
  （`shared_config` 标记可一并撤销）。

## 后续修订

| 日期 | 原因 | 实际改动 / 提交 | 验证结果 |
| --- | --- | --- | --- |
| 2026-11-11 | 首次实施复核修复 | 见上表，工作区未提交 | 专项 87 项通过；受影响目录见上表，失败与挂起均已在基线复现 |

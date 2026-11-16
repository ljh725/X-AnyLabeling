# 密集复核重设计：实施进度与验证记录

本文件记录 `redesign-dense-review-workspace` 的实施批次、验证命令、退出码与未覆盖项。
规格依据见 `openspec/changes/redesign-dense-review-workspace/`，验收矩阵见其 `acceptance.md`。

- 工作分支：`codex/4.2.1/dense-review-redesign-plan`
- 集成目标：`codex/4.2.1-baseline-organization`
- 实施起点（备份标签）：`pre-dense-review-redesign` = `37c4679b`（指向提交 `052239f2`）
- 环境：conda `x-anylabeling-cu12`，Python 3.12.12，PyQt6 6.10.2 / Qt 6.10.0，Windows
- 测试入口：`tests/conftest.py` 强制 `QT_QPA_PLATFORM=offscreen`，配置与 `QSettings` 重定向到 `.tmp/`

## 验证口径

`tests/test_dense_review` 全目录在本机约需 140–170 秒，因此按 AGENTS.md
「Qt 集成测试防挂起」约定，使用外层硬超时包装器并在 pytest 侧开启
`faulthandler_timeout`，便于在挂起时保留用例名与堆栈：

```bash
python .tmp/hard_timeout.py <秒> -q -o faulthandler_timeout=60 <目标> \
    -p no:randomly --basetemp=.tmp/pt-<名称>
```

单项关闭随机顺序（`-p no:randomly`）以便横向比对同一批次的通过数。

## 基线既有失败（不属于本变更）

开工前实测，`pre-dense-review-redesign` 起点即存在以下失败，之后各批次保持不变：

| 用例 | 现象 |
| --- | --- |
| `tests/test_dense_review/test_workspace_evidence.py::test_closed_workspace_keeps_shift_fit_target_and_undo[False]` | 单点拟合后 `bounding_rect()` 未变化 |
| 同上 `[True]` | 同上 |

分类：既有缺陷，未在本次修复，也未因本次改动新增失败。

## 批次 1 · `bf75b13f` 列表启用与滚动（任务组 1–2）

改动：空状态禁用的批次/卡片/区域列表在会话恢复时按实际内容重新启用；
区域动作随区域计划就位。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_workspace_lists.py` | 4 passed，新增 |
| `tests/test_dense_review` 全目录 | 144 passed，2 项基线失败 |
| 覆盖场景 | WL-05 空状态到有效会话、WL-06 会话切换、OC-16 滚轮/滚动条与后台刷新不回滚 |
| 未覆盖 | 真实鼠标滚轮物理事件（使用合成 `QWheelEvent`，仍属离屏） |

修复前对照：同一批测试在旧实现上 3 failed，确认断言有效。

## 批次 2 · `3b09eefd` 显示解析纯数据层（任务组 3 前半）

改动：新增 `services/dense_review/display.py`，按当前/本批/其他角色输出
填充、描边、点、手柄、文字、属性、连线、遮罩强度，默认填充为零；
同一结果同时给出可绘制与可命中；排除原因可读。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_display_policy.py` | 14 passed，新增 |
| 覆盖场景 | DP-01 三角色分级、DP-02 零强度退出命中、DP-11/DP-12 优先级、DP-15 附属叠加、DP-17/DP-18 普通模式 |
| 未覆盖 | 真实屏幕亮度调参（规格列为试用默认值） |

## 批次 3 · `96e93981` 画布集成与审核范围分离（任务组 3–4）

改动：`Canvas` 安装复核显示表，绘制门与命中门同源；`Shape.paint` 接受
`display_style` 按组件强度绘制；mask、组连线、标签底板/文字、属性与度数
文字统一服从角色；`ObjectReviewState` 记录 `group_id`，`session.associated_ids()`
只关联「同图 + 同组 + 唯一主矩形」的点，group 0 有效，多框歧义不猜测。

关键语义修正：`unsupported` 不再抑制绘制与命中。关键点与其他形状保持
可观察、可命中、可按既有命令编辑，仅以 `reviewable=False` 表达其不在正式
确认范围（`SUPPORTED_SHAPE_TYPES` 仍为 `("rectangle",)`）。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_canvas_display_overlay.py` | 9 passed，新增 |
| `tests/test_dense_review/test_workspace_mixed_shapes.py` | 6 passed，新增，真实 `MainWindow` |
| `tests/test_dense_review/test_session.py` | 32 passed（含 group_id 往返） |
| `tests/test_dense_review` 全目录 | 173 passed，2 项基线失败 |
| 覆盖场景 | OC-01/OC-02/OC-03 group 关联与歧义、OC-10/OC-12/OC-15 点可观察与待支持、PC-03/PC-04 矩形确认不波及点、DP-01/DP-02/DP-03/DP-07/DP-08/DP-15 绘制与命中 |

## 批次 4 · `4af3c92f` 显示结果贯穿绘制/命中/退出（任务组 5 及 DP-17）

改动（含两处实施中发现的真实缺陷）：

1. 手动隐藏与类别/group 过滤/反选变更后立即重建显示表。此前会话中表格
   不失效，隐藏对象仍被绘制并响应命中。
2. 退出复核时按当前用户设置重算画布可见性，不再用进入时快照覆盖复核期间
   新增的隐藏/过滤（DP-17、WL-12 明确禁止）。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_display_consistency.py` | 9 passed，新增，真实 `MainWindow` |
| `tests/test_dense_review` 全目录 | 182 passed，2 项基线失败 |
| 覆盖场景 | DP-11 隐藏原因与命中、PC-06 临时显示不改确认资格、DP-11/DP-14 切目标与切图结束例外、DP-12/DP-13 原图对照退出命中、DP-17/WL-12 关闭恢复最新设置、DP-07 当前矩形边优先、DP-10 拖动目标固定、DP-08 绘制顺序不改保存顺序 |

## 批次 5 · `26fed309` 复核标签策略与原图对照（任务组 6）

改动：复核期间标签文字由角色强度决定，临时覆盖普通 `show_labels=False`
与 `show_labels_only_selected=True`，类别名始终可读且不写回普通设置；
标签循环在复核模式下即使普通开关全关也进入。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_display_text_and_original.py` | 7 passed，新增，真实 `MainWindow` |
| `tests/test_dense_review` 全目录 | 189 passed，2 项基线失败 |
| 覆盖场景 | DP-05 普通开关两态下的标签可读与设置不被改写、DP-13 对照暂停标注命中、DP-14 切图/关闭结束对照、DP-17 退出恢复、DP-18 普通模式 |

## 批次 6 · `c569a29f` 可调卡片图像高度与大图块（任务组 8.1–8.5 部分）

改动：移除固定 176 单元高与 108 图像高；图像区默认 320（160–640 可调），
文字带单独预留；面板增宽只改列数并保持高度；图块目标像素按显示尺寸与
DPR 计算并进入缓存键；新增高度滑块与四语言文案并重跑资源编译。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_card_geometry.py` | 9 passed，新增 |
| `tests/test_dense_review/test_translations.py` | 8 passed，614 subtests |
| `tests/test_dense_review` 全目录 | 198 passed，2 项基线失败 |
| 覆盖场景 | OC-07 默认值与可调范围、OC-08 上下文独立、OC-09 列数与 DPR、OC-17/OC-18 尺寸进入缓存键 |

过程中修正的自身问题：新增文案未入翻译导致 `test_translations` 12 项失败；
`.ts` 插入时留下重复 `<message>` 与缺失开标签，`lrelease` 直接报错。
均已修复并重新编译，最终 `test_translations` 全通过。

## 任务 1 附带修复 · `db2b10d2` 导航用例配置会话挂起

现象：`tests/test_canvas/test_navigation.py` 顺序执行必挂，单跑通过。

根因（faulthandler 实测）：两条用例裸建 `MainWindow` 时未建立配置会话，
窗口初始化保存偏好失败触发模态 `QMessageBox.critical`，offscreen 下永久阻塞。

修复：改用 `get_config()` 加载 `.tmp` 下测试专用配置，建立可写会话，保留
真实保存路径与写保护。

| 项目 | 结果 |
| --- | --- |
| 两条用例单跑 | 各 1 passed（5.99s / 5.52s） |
| `tests/test_canvas/test_navigation.py` 整文件 | 83 passed，9.93s，退出码 0 |

### 同类挂起仍存在于其他两个文件（未修，超出本次授权范围）

`tests/test_canvas/test_rectangle_edge_migration.py` 与
`tests/test_canvas/test_rectangle_preview_overlap.py` 整文件执行仍复现同一
模态弹窗阻塞（堆栈同样落在 `label_widget.error_message`）。两者的目标是
`MainWindow` / `LabelingWidget` 直建用例，需要同样的配置会话改造。
本批次只按要求修复 `test_navigation.py`，上述两文件按未覆盖登记。

## 复核轮次 · 2026-11-16（针对 `6b0f1168` 的六项问题）

复核脚本 `.tmp/test_redesign_review_audit.py` 复跑六项，修复前 **6 failed**，
修复后 **6 passed**；断言已并入持久测试文件，临时脚本未入库。

| 问题 | 根因 | 修复 | 提交 | 测试节点 |
| --- | --- | --- | --- | --- |
| P1 关闭后复核样式重新生效 | 覆盖层按「会话存在」安装，会话关闭后仍存活 | 改为按工作区可见状态激活 | `47c7018d` | `test_display_consistency.py::test_closed_workspace_keeps_regular_canvas_after_visibility_edit` |
| P1 原图对照仍显示/命中分组 | `_group_at_point`/`_paint_groups` 只看 `shape.visible` | 新增 `_group_visible_shapes()` 服从显示解析；旋转手柄同源接入 | `7d9a27b3` | `test_original_comparison_blocks_group_paint_and_hit`、`test_original_comparison_disables_rotation_handles` |
| P2 临时显示只停在解析表 | 绘制/命中被旧可见性提前过滤 | `is_visible()` 在复核模式下以有效结果为准；命中去掉旧过滤 | `47c7018d` | `test_temporary_show_reaches_paint_and_hit`、`test_original_comparison_wins_over_temporary_show` |
| P2 默认聚焦吞掉本批与关联点 | 沿用旧背景隐藏开关 | 聚焦模式不再隐藏背景，由角色决定 | `47c7018d` | `test_focus_mode_paints_batch_members_and_associated_points` |
| P2 当前对象未置顶 | 轮廓按 `canvas.shapes` 原顺序绘制 | 新增按角色排序的绘制序列，数据顺序不变 | `7d9a27b3` | `test_current_object_paints_last_without_reordering_data` |
| P2 仅改 `group_id` 关联不更新 | `_sync_one()` 未把组号列为变更条件 | 提升为独立变更条件 | `bfd7e001` | `test_group_association_sync.py` |

任务 6.4 的按住查看补齐：`test_hold_original_restores_previous_mode_on_release`、
`test_hold_original_ends_on_blur_and_image_switch`、`test_hold_original_requires_an_active_workspace`。

### 本轮验证

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review` 全目录 | **209 passed, 2 failed**, 614 subtests, 255.89s, 退出码 1 |
| 失败项 | `test_workspace_evidence.py::test_closed_workspace_keeps_shift_fit_target_and_undo[False]` / `[True]`，与上轮 198/2 完全同一批，非本次引入 |
| `test_display_consistency.py` | 17 passed |
| `test_display_text_and_original.py` | 10 passed |
| `test_group_association_sync.py` | 1 passed（新增文件） |
| `test_workspace.py` | 22 passed |
| 受影响画布测试 | `test_fill_opacity` 12、`test_shape_selection` 11、`test_groups` 16、`test_label_visibility_mode` 6、`test_rotation_handle` 2、`test_selection_priority` 6、`test_drag_refresh` 11，全部通过 |
| OpenSpec | `openspec validate --strict` valid |
| 格式与静态检查 | `black` 通过；`flake8` 无新增问题（仅仓库既有 C901/F841/F541） |
| `git diff --check` | 通过 |

过程中修正的自身问题：`_grouped_shapes()` 一度整体过滤隐藏成员，导致
`test_groups.py::test_hidden_group_members_are_counted_but_not_hit_tested`
失败；改为只在几何/命中处过滤后恢复通过。

### 本轮未修与跟踪

- 任务 5.3 的重叠候选选择界面仍按原任务跟踪，未在本轮实现。
- `test_rectangle_edge_migration.py`、`test_rectangle_preview_overlap.py`
  整文件仍复现基线既有模态弹窗挂起（本次未触碰，未作为回归依据）。
- 任务 8.2 的宽度受限提示与主画布入口、8.4 的比较窗口当前版本仍未实现，
  `tasks.md` 中两项已恢复为未勾选并标注「部分完成」。

## 第二轮复核 · 2026-11-16（针对 `2df16c07`）

复核脚本 `.tmp/test_redesign_followup_audit.py` 复跑五项：修复前 **5 failed**，
修复后 **5 passed**。上轮脚本 `.tmp/test_redesign_review_audit.py` 六项仍
**6 passed**（无回退）。两份脚本的断言已并入持久测试文件，临时脚本未入库。

| 问题 | 根因 | 修复 | 提交 | 测试节点 |
| --- | --- | --- | --- | --- |
| 分组编辑改动隐藏成员 | `_select_group()` 取整组，隐藏与锁定成员一并入选 | 新增 `_group_editable_shapes()`，复核下选择/拖动/微调共用有效成员；无覆盖层时保持原规则 | `82668b12` | `test_redesign_followup_audit.py::test_group_hit_cannot_select_or_move_a_hidden_member`、`test_display_consistency.py::test_group_gesture_skips_hidden_and_locked_members` |
| 原图模式仍可移动 | 几何入口未检查对照状态 | 新增 `annotation_editing_paused()`，`bounded_move_shapes`/`move_by_keyboard`/`rotate_by_keyboard` 统一拒绝 | `82668b12` | `test_original_mode_does_not_nudge_invisible_selection`、`test_display_consistency.py::test_original_mode_pauses_geometry_edits` |
| 按住看原图无入口、标签绕过显示结果 | hold API 仅测试调用；绘制循环直接读 `shape.visible` | 工具栏新增按钮（pressed/released 绑定）；新增 `_overlay_visible()` 接管标签/底板/引线/属性/遮罩 | `05b1a26b`、`82668b12` | `test_display_text_and_original.py::test_hold_original_button_press_and_release`、`test_hold_original_button_ends_on_blur_close_and_image_switch`、`test_original_mode_renders_without_annotation_labels` |
| 当前矩形内部命中抢占关键点 | 当前角色全部命中整体提前 | 优先权仅限命中类型 0/1（顶点、边）；内部命中不覆盖可见点 | `82668b12` | `test_click_point_inside_current_rect_targets_point`、`test_display_consistency.py::test_point_inside_current_rectangle_is_selectable` |
| 手动隐藏被误判为全局关闭 | 以「是否还有可见对象」推断全局开关 | 改读真实开关状态；`manual-hidden` 可临时显示，真实 `global-off` 仍优先 | `05b1a26b` | `test_all_manual_hides_are_distinct_from_global_toggle`、`test_single_manual_hide_is_not_a_global_shutdown`、`test_hiding_every_object_by_hand_is_not_a_global_shutdown`、`test_real_global_switch_beats_temporary_show`、`test_original_mode_outranks_temporary_show_reason` |

### 本轮验证

| 项目 | 结果 |
| --- | --- |
| 本轮复现脚本 | 修复前 5 failed → 修复后 5 passed |
| 上轮复现脚本 | 6 passed（无回退） |
| `tests/test_dense_review` 全目录 | **229 passed, 2 failed**, 622 subtests, 299.71s, 退出码 1（含两份临时审计脚本）；断言迁入持久文件并删除临时脚本后复跑为 **219 passed, 2 failed**, 281.85s, 退出码 1 |
| 失败项 | `test_workspace_evidence.py::test_closed_workspace_keeps_shift_fit_target_and_undo[False]` / `[True]`，与 `2df16c07` 基线完全同一批 |
| `test_display_consistency.py` | 23 passed |
| `test_display_text_and_original.py` | 12 passed |
| `test_translations.py` | 8 passed，622 subtests |
| 受影响画布测试 | `test_fill_opacity` 12、`test_shape_selection` 11、`test_groups` 16、`test_label_visibility_mode` 6、`test_rotation_handle` 2、`test_selection_priority` 6、`test_drag_refresh` 11、`test_shift_point_fit_interaction` 44，共 108 passed |
| OpenSpec | `openspec validate --strict` valid |
| 格式与静态检查 | `black` 通过；`flake8` 无新增问题（仅既有 C901/F841/F541） |
| `git diff --check` | 通过（仅 CRLF 转换警告） |

过程中修正的自身问题：

1. `_group_editable_shapes()` 一度在普通模式也过滤锁定成员，令
   `test_groups.py::test_locked_group_does_not_move_partially` 失败；改为
   仅在复核覆盖层存在时收窄集合后恢复。
2. 两处新增界面文案未入翻译，导致 `test_translations` 8 项子失败；补齐
   中英日韩并重编译后通过。
3. 一条既有断言（框内命中归矩形）与本轮修复目标冲突，按新语义更新为
   「框内可见关键点优先，点压框边时框边优先」。

### 本轮未修与跟踪

- 任务 5.3 重叠候选选择界面、8.2 宽度受限提示、8.4 比较窗口仍未实现。
- 停靠面板、三任务视图、原图小地图、Inspector 交接继续由原任务跟踪。
- `test_rectangle_edge_migration.py`、`test_rectangle_preview_overlap.py`
  整文件仍复现基线既有模态弹窗挂起，未触碰。

## 最终验收（本次交付范围）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 密集复核目录 | `pytest tests/test_dense_review` | 198 passed，2 failed（基线既有），614 subtests |
| 导航文件 | `pytest tests/test_canvas/test_navigation.py` | 83 passed，9.94s，退出码 0 |
| 受影响的画布文件 | `test_fill_opacity` / `test_shape_selection` / `test_groups` / `test_label_visibility_mode` | 12 / 11 / 16 / 6 passed |
| OpenSpec | `openspec validate redesign-dense-review-workspace --strict` | valid |
| 翻译 | `scripts/compile_languages.py` | 四语言 2459 条，无错误 |

单列说明：

- `tests/test_widgets/test_toolbar_layout.py`：**未运行**（CI 排除项，本次未涉及工具栏布局）。
- `tests/test_pointcloud/`：**未运行**（Windows 不具备 xcb + xvfb），本功能不涉及点云。
- `tests/test_canvas/test_rectangle_edge_migration.py` 与
  `tests/test_canvas/test_rectangle_preview_overlap.py`：整文件执行仍复现基线
  既有模态弹窗挂起，**未作为本次回归依据**；其目标用例单跑可过。
- 人工验收 M1–M8、性能门槛 P1–P4：**未执行**，均为真实屏幕项。
- 本次勾选 26 项任务，均对应具体提交与测试；其余 65 项未勾选，保持未完成。

## 未覆盖与后续

- `tests/test_widgets/test_toolbar_layout.py`：未运行（CI 排除项）。
- `tests/test_pointcloud/`：Windows 上不适用（需 xcb + xvfb），未运行。
- 任务组 6 已完成（`26fed309`）；任务组 8 的尺寸/DPR/缓存键部分已完成
  （`c569a29f`），其余部分（裁切并集、框外点入口、失败重试、比较窗口）
  尚未实施。
- 尚未实施：矩形卡聚合 UI（组 7）、停靠工作区（组 9）、原图小地图与
  空间查漏（组 10）、设置与交接（组 11–12）。
- 人工验收 M1–M8 与性能门槛 P1–P4 未执行，均为真实屏幕项，不能由离屏
  截图替代。

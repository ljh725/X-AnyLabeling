# 密集标注复核工作流实施验证

日期：2026-11-02（Asia/Shanghai）
分支：`codex/refactor-data-inspector-workflow`
基线：`9a37c5474c390e93243e33a88e8232a19c833280`
本地基线标签：`backup/add-dense-annotation-review-workflow-20261102`（已核验 SHA，尚未推送远端）
状态：代码实施完成首版；自动化验证通过；人工试用、性能门槛、翻译导出和训练导出往返未完成。

## 环境

- 解释器：`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`
- Python 3.12.12；PyQt6 6.10.2；Qt 6.10.0
- GUI 测试：`QT_QPA_PLATFORM=offscreen`（Windows）
- 静态检查：flake8 `--max-line-length=79 --max-complexity=18`；Black line length 79

## 实际模块

| 模块 | 内容 |
| --- | --- |
| `anylabeling/services/dense_review/models.py` | 版本化进度契约、配置、对象/批次/查漏状态、完成状态 |
| `signatures.py` | 矩形规范化、类别/几何签名、内容哈希 |
| `ledger.py` | 全对象账本、空间顺序、稳定批次、显式重建 |
| `coverage.py` | 整图重叠网格、区域基线、旧/新位置失效 |
| `config.py` | 本地复核配置读写与冲突校验 |
| `session.py` | 确认/失效/疑难/暂跳/覆盖/完成/撤销/持久化协调 |
| `storage.py` | 顶层命名空间、图像指纹、外部文件状态 |
| `anylabeling/views/labeling/dense_review/workspace.py` | 非模态工作区、批次面板、卡片、查漏页、动作与快捷键 |
| `config_dialog.py` | 批次、类别/框规则、网格配置编辑器 |
| `thumbnails.py` | 可见项优先的后台裁剪、有界 LRU、代际丢弃 |
| `label_widget.py` | 菜单入口、会话生命周期、保存/恢复、排除项、聚焦、全图、撤销接入 |
| `canvas.py` | 临时查漏区域虚线覆盖，不改标注 |

数据写入标注 JSON 顶层可选 `xanylabeling_dense_review`；不写入 shape，不改变旧 `checked`/`review_status` 语义。

## 自动化证据（本轮实际运行）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 新增密集复核服务/GUI | `python -m pytest tests/test_dense_review -q` | **70 passed** |
| Inspector 回归 | `python -m pytest tests/test_inspection -q` | **80 passed** |
| 定向 labeling | `digit_label_actions`、`editing_command_scope`、`batch_edit_fields`、`check_status`、`image_switch`、`label_file_load/save`、`shape_filter`、`label_locks` | **72 passed, 15 subtests** |
| labeling 全量 | `python -m pytest tests/test_labeling -q` | **192 passed, 8 failed**, 45 subtests |
| canvas | `python -m pytest tests/test_canvas -q` | **578 passed, 1 failed**, 83 subtests |
| widgets | `python -m pytest tests/test_widgets -q` | **29 passed, 3 failed**, 2 subtests |
| settings 单文件 | `test_schema`（7）、`test_controller`（13）、`test_dialog_layout`+`test_runtime_applier`+`test_shape_colors`（21 passed, 1 skipped, 9 subtests） | 全部通过 |
| utils/config | `python -m pytest tests/test_utils tests/test_config -q` | **85 passed, 8 skipped**, 28 subtests |
| OpenSpec | `openspec validate add-dense-annotation-review-workflow --strict` | 通过 |
| 静态检查 | flake8（新服务/GUI/测试）；Black；`compileall`；`git diff --check` | 通过 |

### 基线既有失败（非本变更新增）

以下失败与 Inspector 实施记录中的基线失败一致：

- `tests/test_canvas/test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`（179 != 139）。
- `tests/test_widgets/test_canvas_adjustment.py::...test_brightness_contrast_updates_are_throttled`（0 != 1）。
- `tests/test_widgets/test_toolbar_layout.py` 两项：26 < 28、39 != 42。
- labeling 全量 8 项：`SimpleNamespace` 缺 `copy`/`_metadata_generation`、Windows 标题/路径断言、`NamedTemporaryFile` 在 Windows 上的权限失败。

### 评审 F1–F4 修复（2026-11-02）

- F1：缩略图缓存按边界、上下文、目标尺寸和源图版本键控；边界变化使旧缓存/失败状态失效，同 ID 旧请求结果被丢弃。探针 `test_changed_bounds_request_fresh_card`、`test_cache_is_keyed_by_bounds_and_source_version`、`test_stale_same_id_result_is_ignored`。
- F2：审核撤销改为按剩余动作顺序判断，连续审核操作可依次撤销。
- F3：全图返回只恢复显示策略，不再重新聚焦缩放；用户倍率、滚动和中心保留。探针 `test_full_image_roundtrip_restores_user_zoom`。
- F4：统一动作历史按真实顺序记录审核与内容变更；框移走再移回后仍先撤销最新画布编辑，连续审核撤销继续可用。探针 `test_manual_edit_back_to_same_content_keeps_canvas_undo_first`、`test_main_window_undo_reverts_latest_move_after_manual_roundtrip`，既有连续审核/交错序列探针继续通过。
- 详细根因与修复见 [评审响应](../../../reports/dense_review_workflow_20261102/REVIEW-RESPONSE-20261102.md)。

### 第二轮 R2-1 / R2-2 修复（2026-11-02）

- 每条审核/内容事务直接持有操作前的完整 `ReviewState`，撤销按事务取回确认、查漏、批次及游标；不再按内容哈希唯一缓存审核状态。
- 事务及其快照共用最近100条历史上限，一起保留或淘汰，移除独立50条审核快照栈；达到上限后不会暴露缺失快照的审核撤销。
- 强化状态模型及主窗口的两次移框撤销断言；增加50/51/99/100/101/151次审核变更、130条审核/编辑混合历史及画布内容未变的撤销回归。
- 修改前原两项探针为 **2 failed in 2.80s**；修改后 `tests/test_dense_review` 与三轮独立探针合跑 **85 passed in 44.80s**。三个修改的 Python 文件通过 Black（79列）及 flake8。
- 证据及完整命令见 [第二轮修复记录](../../../reports/dense_review_workflow_20261102/ROUND2-UNDO-FIX-20261102.md)，JUnit 见 [round2-fix-regression.xml](../../../reports/dense_review_audit_20261102/round2-fix-regression.xml)。任务3.6因 redo 未实现继续保持未完成；本轮不包含人工或性能验收。

### 未纳入通过结论

- `tests/test_settings` 整个目录一次运行时，在 `test_dialog_layout` 之后出现原生访问冲突退出（exit 3221226505）。各文件单独运行通过；该组合运行的崩溃未确认属于本变更新增，不能记为通过。
- 未重新运行全部历史版本或全部历史人工验收。

## 规格 Scenario 映射

| 规格 | 自动化覆盖 |
| --- | --- |
| 工作区可选/退出恢复 | `test_closing_workspace_restores_canvas_and_writes_nothing`、`test_display_modes_and_full_image_restore` |
| 混淆批次互斥/规则 | `test_config_dialog_round_trip_and_validation`、模型 `test_conflicting_config_cannot_start` |
| 全部对象入账/非矩形 | `test_all_objects_enter_stable_batches`、`test_non_rectangle_image_reports_partial_review_only` |
| 改类不跳位/框确认保留 | `test_relabel_keeps_batch_position_and_geometry_confirmation`、GUI 批次测试 |
| 新增/复制/删除/撤销 | `test_new_pending_delete_and_undo_restores_identity`、`test_new_copy_enters_pending_without_inheriting` |
| 卡片上下文/边缘/失败 | `test_crop_thumbnail_clamps_to_image_edges`、`test_crop_thumbnail_rejects_outside_bounds`；GUI 失败状态 |
| 单目标编辑/全图恢复 | `test_display_modes_and_full_image_restore` |
| 批次一次确认/范围/排除 | `test_candidate_scope_excludes_unresolved...`、`test_dimension_only_confirmation_and_completion`、GUI 批次测试 |
| 锁定对象可确认 | `test_locked_object_can_be_confirmed` |
| 疑难/暂跳/快捷标记 | `test_difficult_skipped_and_new_pending_block_completion`、`test_quick_difficult_shortcut_marks_without_dialog` |
| 确认撤销 | `test_undo_progress_and_content_edit`、`test_batch_confirmation_is_one_undo_without_touching_labels` |
| 保存重开/等价点序/微小改动 | `test_payload_round_trip...`、`test_equivalent_rectangle_order...`、`test_small_coordinate_change_invalidates_after_reload` |
| 图像更换/规则变更失效 | `test_image_change_clears_confirmations_and_coverage`、`test_rule_change_on_reload_invalidates` |
| 未知版本/损坏配置 | `test_unknown_version_is_rejected`、`test_config_round_trip_and_atomic_save`、GUI unknown-version 测试 |
| 外部冲突/输出目录隔离 | `test_external_change_is_detected_before_save`、`test_output_directory_keeps_independent_progress` |
| 空间查漏计划/显式完成 | `test_plan_covers_whole_image_and_has_overlap`、`test_complete_region_records_baseline`、GUI 查漏测试 |
| 区域旧/新失效/未知基线 | `test_move_invalidates_old_and_new_regions_only`、`test_delete_without_old_bounds_withdraws_everything` |
| 完成条件/空图/混合形状 | `test_dimension_only_confirmation_and_completion`、`test_empty_image_still_requires_spatial_review`、`test_non_rectangle_image_reports_partial_review_only` |
| 保存失败/未保存 | `test_save_failure_keeps_memory_progress`；GUI 显示“复核进度待保存” |

## 未验证

- 真实屏幕上的卡片布局、缩略图观感、并排比较、快捷键和无障碍可用性。
- 30 对象/6 类真实密集图、小目标、遮挡规则差异、框截断手臂等授权样本的人工验收。
- 冷/暖缓存首帧 p95、GUI 心跳 p95、拖框 p95 相对基线、缓存峰值；未做性能实测，不能引用设计目标为已达成。
- 两位实际使用者、顺序交叉对照组和独立质量复核；减负效果未验证。
- `.ts/.qm` 翻译生成与四种语言显示；新增文案未完成翻译周期。
- 训练导出/旧程序标签往返；仅确认新命名空间不写入 shape，未运行导出与旧程序实测。
- 卡片迟到/快速切图/关闭窗口等延迟注入自动化；已实现代际检查，但没有专门注入测试。
- 现有画布没有重做栈，批次确认的 redo 未实现。
- 完整虚拟列表和小窗口专用收起控件；当前实现为懒加载缩略图 + 可调整布局。

## 回退

1. 删除 `anylabeling/services/dense_review/`、`anylabeling/views/labeling/dense_review/`、`tests/test_dense_review/`。
2. 还原 `label_widget.py`、`widgets/canvas.py`、`settings/schema.py`、`configs/xanylabeling_config.yaml`、`tests/test_settings/test_schema.py` 中本功能相关改动；还原 `services/inspection/handoff.py` 的可用性声明与对应测试。
3. 标注 JSON 中的 `xanylabeling_dense_review` 保留原内容；旧程序不应把它解释为旧审核通过。需要彻底清理时另行备份并显式删除该命名空间。

# 密集复核：逐 Scenario 验收映射（2026-11-05）

本表覆盖三份规格全部 Scenario；建立映射不表示人工项已经通过。每条预期取对应规格 WHEN/THEN，自动化环境为 Windows / Python 3.12.12 / PyQt6 6.10.2 / Qt 6.10.0 / offscreen；人工环境和记录步骤见 [manual-acceptance.md](manual-acceptance.md)。

当前执行命令、JUnit、日志和原始性能结果统一见 [implementation-20261105.md](implementation-20261105.md)。参数化 node ID 在表中列基名，可通过 pytest 直接执行全部参数；原始 JUnit 保留每个参数的实际结果。逻辑/图像裁切测试不替代用户观察，标有 M1–M5 的行仍需相应人工验收。

## batch-review-progress

规格：[spec.md](specs/batch-review-progress/spec.md)。

| Scenario | 自动化 node ID / 证据 | 当前结果与人工部分 |
| --- | --- | --- |
| 一个框连续修改多次 | `tests/test_dense_review/test_session.py::test_geometry_move_invalidates_both_and_intersecting_coverage`<br>`tests/test_dense_review/test_workspace.py::test_relabel_move_and_undo_invalidate_progress` | 自动化：通过；人工待验：M4 |
| 未修改对象被浏览 | `tests/test_dense_review/test_workspace.py::test_closing_workspace_restores_canvas_and_writes_nothing` | 自动化：通过；人工待验：M4 |
| 全部预标注正确 | `tests/test_dense_review/test_session.py::test_repeated_batch_confirmation_is_idempotent`<br>`tests/test_dense_review/test_workspace.py::test_open_confirm_and_save_round_trip` | 自动化：通过；人工待验：M2 |
| 本轮只审类别 | `tests/test_dense_review/test_session.py::test_dimension_only_confirmation_and_completion` | 自动化：通过 |
| 大部分卡片在屏外 | `tests/test_dense_review/test_workspace_evidence.py::test_card_view_virtualizes_and_bounds_resources`<br>`tests/test_dense_review/test_session.py::test_candidate_scope_excludes_unresolved_and_conflicts_are_rejected` | 自动化：通过；人工待验：M1 |
| 数据失败与未生成屏外缩略图区分 | `tests/test_dense_review/test_workspace_evidence.py::test_compare_cold_cache_requests_updates_and_failures`<br>`tests/test_dense_review/test_session.py::test_candidate_scope_excludes_unresolved_and_conflicts_are_rejected` | 自动化：通过 |
| 同批含多种排除 | `tests/test_dense_review/test_session.py::test_candidate_scope_excludes_unresolved_and_conflicts_are_rejected` | 自动化：通过 |
| 聚焦隐藏其他框 | `tests/test_dense_review/test_workspace.py::test_hidden_and_filtered_objects_are_excluded_but_focus_is_not` | 自动化：通过 |
| 确认过程中新增对象 | `tests/test_dense_review/test_session.py::test_candidate_scope_excludes_unresolved_and_conflicts_are_rejected` | 自动化：通过 |
| 重复完成与锁定对象 | `tests/test_dense_review/test_session.py::test_repeated_batch_confirmation_is_idempotent`<br>`tests/test_dense_review/test_session.py::test_locked_object_can_be_confirmed` | 自动化：通过 |
| 疑难对象后续被批次完成遇到 | `tests/test_dense_review/test_session.py::test_difficult_skipped_and_new_pending_block_completion` | 自动化：通过 |
| 逐框模式发现无法判断的动作 | `tests/test_dense_review/test_workspace_evidence.py::test_cross_batch_completion_keeps_views_in_sync` | 自动化：通过 |
| 已审框被移到另一个人 | `tests/test_dense_review/test_session.py::test_geometry_move_invalidates_both_and_intersecting_coverage` | 自动化：通过 |
| 类别改变影响遮挡规范 | `tests/test_dense_review/test_session.py::test_relabel_keeps_batch_position_and_geometry_confirmation`<br>`tests/test_dense_review/test_signatures.py::test_unknown_box_rule_includes_label_in_geometry_signature` | 自动化：通过 |
| 显示与规则变化区别 | `tests/test_dense_review/test_signatures.py::test_content_hash_ignores_visibility_and_lock_but_tracks_content`<br>`tests/test_dense_review/test_session.py::test_config_rule_change_invalidates_and_batch_change_does_not` | 自动化：通过 |
| 复制已确认对象 | `tests/test_dense_review/test_workspace.py::test_new_copy_enters_pending_without_inheriting` | 自动化：通过 |
| 重开遇到重复身份 | `tests/test_dense_review/test_session.py::test_incompatible_version_and_identity_repair_do_not_inherit` | 自动化：通过 |
| 确认后立即撤销 | `tests/test_dense_review/test_workspace.py::test_batch_confirmation_is_one_undo_without_touching_labels` | 自动化：通过 |
| 编辑撤销重做 | `tests/test_dense_review/test_workspace.py::test_canvas_edit_redo_restores_bounds_and_review_state` | 自动化：通过 |
| 批次确认后保存失败 | `tests/test_dense_review/test_workspace.py::test_save_failure_keeps_memory_progress` | 自动化：通过 |
| 自动保存沿用策略且不逐帧写盘 | `tests/test_dense_review/test_workspace_evidence.py::test_autosave_writes_at_edit_and_confirmation_boundaries` | 自动化：通过 |
| 只读查看与取消切图 | `tests/test_dense_review/test_workspace.py::test_closing_workspace_restores_canvas_and_writes_nothing`<br>`tests/test_dense_review/test_workspace_evidence.py::test_workspace_closed_keeps_editing_navigation_and_save` | 自动化：通过 |
| 相同文件名更换图片内容 | `tests/test_dense_review/test_persistence.py::test_image_change_clears_confirmations_and_coverage` | 自动化：通过 |
| 同图切换输出目录 | `tests/test_dense_review/test_workspace.py::test_output_directory_keeps_independent_progress` | 自动化：通过 |
| 未改内容保存重开 | `tests/test_dense_review/test_persistence.py::test_equivalent_rectangle_order_keeps_confirmation`<br>`tests/test_dense_review/test_persistence.py::test_small_coordinate_change_invalidates_after_reload` | 自动化：通过 |
| 旧文件已有图片通过状态 | `tests/test_dense_review/test_export_roundtrip.py::test_legacy_fields_and_shape_extensions_survive_round_trip`<br>`tests/test_dense_review/test_export_roundtrip.py::test_old_program_rewrite_without_namespace_does_not_restore` | 自动化：通过 |
| 不兼容的进度版本 | `tests/test_dense_review/test_workspace.py::test_unknown_progress_is_preserved_until_explicit_rebuild` | 自动化：通过 |
| 外部编辑后尝试保存 | `tests/test_dense_review/test_workspace_evidence.py::test_external_conflict_from_save_entry` | 自动化：通过 |
| 保存冲突取消与重载 | `tests/test_dense_review/test_workspace_evidence.py::test_external_conflict_from_save_entry` | 自动化：通过 |

## dense-review-workspace

规格：[spec.md](specs/dense-review-workspace/spec.md)。

| Scenario | 自动化 node ID / 证据 | 当前结果与人工部分 |
| --- | --- | --- |
| 进入后自由编辑 | `tests/test_dense_review/test_workspace.py::test_relabel_move_and_undo_invalidate_progress`<br>`tests/test_dense_review/test_workspace_evidence.py::test_workspace_closed_keeps_editing_navigation_and_save` | 自动化：通过；人工待验：M4 |
| 小窗口与退出 | `tests/test_dense_review/test_workspace_evidence.py::test_small_window_can_collapse_each_auxiliary_panel`<br>`tests/test_dense_review/test_workspace.py::test_closing_workspace_restores_canvas_and_writes_nothing` | 自动化：通过；人工待验：M1 |
| 类别重复出现在两个批次 | `tests/test_dense_review/test_config_dialog.py::test_config_dialog_round_trip_and_validation` | 自动化：通过 |
| 当前批次发现第三类 | `tests/test_dense_review/test_workspace.py::test_configured_batches_keep_membership_after_relabel` | 自动化：通过 |
| 未配置遮挡框规则 | `tests/test_dense_review/test_signatures.py::test_unknown_box_rule_includes_label_in_geometry_signature`<br>`tests/test_dense_review/test_session.py::test_relabel_keeps_batch_position_and_geometry_confirmation` | 自动化：通过；人工待验：M4 |
| 错误预标注落到另一类别 | `tests/test_dense_review/test_session.py::test_all_objects_enter_stable_batches` | 自动化：通过 |
| 存在非矩形对象 | `tests/test_dense_review/test_session.py::test_non_rectangle_image_reports_partial_review_only` | 自动化：通过 |
| 改类后继续调框 | `tests/test_dense_review/test_workspace.py::test_configured_batches_keep_membership_after_relabel`<br>`tests/test_dense_review/test_workspace.py::test_relabel_move_and_undo_invalidate_progress` | 自动化：通过 |
| 调框跨越空间顺序 | `tests/test_dense_review/test_session.py::test_relabel_keeps_batch_position_and_geometry_confirmation` | 自动化：通过；人工待验：M4 |
| 完成后跨批次的目标与范围一致 | `tests/test_dense_review/test_workspace_evidence.py::test_cross_batch_completion_keeps_views_in_sync` | 自动化：通过 |
| 直接切换冷缓存与暖缓存批次 | `tests/test_dense_review/test_workspace_evidence.py::test_direct_batch_click_schedules_visible_thumbnails` | 自动化：通过；人工待验：M1 |
| 已完成批次之后补框 | `tests/test_dense_review/test_session.py::test_new_pending_delete_and_undo_restores_identity` | 自动化：通过 |
| 删除与撤销 | `tests/test_dense_review/test_session.py::test_new_pending_delete_and_undo_restores_identity` | 自动化：通过 |
| 预框截掉举起的手臂 | `tests/test_dense_review/test_thumbnails.py::test_crop_thumbnail_clamps_to_image_edges`<br>`tests/test_dense_review/test_samples.py::test_manifest_matches_review_ledger` | 自动化：通过；人工待验：M4 |
| 类别难以通过颜色区分 | `tests/test_dense_review/test_workspace_evidence.py::test_card_view_virtualizes_and_bounds_resources` | 自动化：通过；人工待验：M1、M4 |
| 两个学生动作需要对照 | `tests/test_dense_review/test_workspace_evidence.py::test_compare_cold_cache_requests_updates_and_failures` | 自动化：通过；人工待验：M4 |
| 冷缓存比较与迟到图块 | `tests/test_dense_review/test_workspace_evidence.py::test_compare_cold_cache_requests_updates_and_failures` | 自动化：通过 |
| 图块加载失败 | `tests/test_dense_review/test_workspace_evidence.py::test_compare_cold_cache_requests_updates_and_failures` | 自动化：通过 |
| 密集重叠中单点拟合 | `tests/test_dense_review/test_workspace.py::test_hidden_and_filtered_objects_are_excluded_but_focus_is_not`<br>`tests/test_dense_review/test_workspace_evidence.py::test_closed_workspace_keeps_shift_fit_target_and_undo` | 自动化：通过；人工待验：M4 |
| 临时查看所有框 | `tests/test_dense_review/test_workspace.py::test_display_modes_and_full_image_restore` | 自动化：通过 |
| 细长人体与小目标连续切换 | `tests/test_dense_review/test_samples.py::test_manifest_matches_review_ledger` | 自动化：通过；人工待验：M4 |
| 全图定位后返回 | `tests/test_dense_review/test_workspace.py::test_full_image_roundtrip_restores_user_zoom` | 自动化：通过 |
| 新快捷键与既有键冲突 | `tests/test_dense_review/test_workspace.py::test_dense_shortcuts_are_window_scoped` | 自动化：通过；人工待验：M1 |
| 旧图块延迟返回 | `tests/test_dense_review/test_delay_injection.py::test_fast_image_switch_drops_late_card_result`<br>`tests/test_dense_review/test_delay_injection.py::test_fast_output_directory_switch_drops_late_result`<br>`tests/test_dense_review/test_thumbnail_lifecycle.py::test_real_executor_bounds_backlog_and_recovers_after_switch` | 自动化：通过 |
| 大批次卡片与连续切图的资源边界 | `tests/test_dense_review/test_workspace_evidence.py::test_card_view_virtualizes_and_bounds_resources`<br>`tests/test_dense_review/test_thumbnail_lifecycle.py::test_real_executor_bounds_backlog_and_recovers_after_switch`<br>`tests/test_dense_review/test_performance_smoke.py::test_benchmark_harness_smoke`<br>真实切图资源 trace（见实施记录） | 自动化：通过；只对实测范围报告资源峰值，不外推无限运行 |
| 密集场景性能验收 | `tests/test_dense_review/test_performance_smoke.py::test_benchmark_harness_smoke`<br>30/300 对象，各 3 轮原始性能报告（见实施记录） | 自动化：通过；真实屏幕适用性待 M5 |

## spatial-omission-review

规格：[spec.md](specs/spatial-omission-review/spec.md)。

| Scenario | 自动化 node ID / 证据 | 当前结果与人工部分 |
| --- | --- | --- |
| 图片局部没有任何框 | `tests/test_dense_review/test_coverage_plan.py::test_plan_covers_whole_image_and_has_overlap` | 自动化：通过 |
| 改变窗口或重建区域 | `tests/test_dense_review/test_coverage_plan.py::test_different_grid_settings_produce_different_plan_identity`<br>`tests/test_dense_review/test_coverage_grid.py::test_cell_rects_follow_region_geometry` | 自动化：通过 |
| 自由平移穿过多块区域 | `tests/test_dense_review/test_workspace.py::test_spatial_review_requires_explicit_region_completion` | 自动化：通过 |
| 完成一块并继续 | `tests/test_dense_review/test_coverage_plan.py::test_complete_region_records_baseline`<br>`tests/test_dense_review/test_workspace.py::test_spatial_review_requires_explicit_region_completion` | 自动化：通过 |
| 保存关闭后恢复查漏位置 | `tests/test_dense_review/test_workspace_evidence.py::test_spatial_region_state_restores_after_save_and_reopen` | 自动化：通过 |
| 完成区域前补一个框 | `tests/test_dense_review/test_session.py::test_new_pending_delete_and_undo_restores_identity`<br>`tests/test_dense_review/test_session.py::test_difficult_skipped_and_new_pending_block_completion` | 自动化：通过 |
| 从查漏返回对象编辑 | `tests/test_dense_review/test_workspace_evidence.py::test_spatial_region_state_restores_after_save_and_reopen` | 自动化：通过；人工待验：M4 |
| 已审框跨区域移动 | `tests/test_dense_review/test_coverage_plan.py::test_move_invalidates_old_and_new_regions_only` | 自动化：通过 |
| 只改类别且覆盖要求不变 | `tests/test_dense_review/test_session.py::test_pure_relabel_does_not_withdraw_coverage` | 自动化：通过 |
| 应标范围规则不明确地改变 | `tests/test_dense_review/test_session.py::test_config_rule_change_invalidates_and_batch_change_does_not` | 自动化：通过 |
| 外部删除或移动已审对象 | `tests/test_dense_review/test_persistence.py::test_external_move_invalidates_old_and_new_regions_on_reload`<br>`tests/test_dense_review/test_persistence.py::test_external_delete_invalidates_only_old_regions` | 自动化：通过 |
| 三十个框全部完成但没有查漏 | `tests/test_dense_review/test_session.py::test_dimension_only_confirmation_and_completion` | 自动化：通过 |
| 空标注图片 | `tests/test_dense_review/test_session.py::test_empty_image_still_requires_spatial_review` | 自动化：通过 |
| 完成之后出现新增待审 | `tests/test_dense_review/test_session.py::test_difficult_skipped_and_new_pending_block_completion` | 自动化：通过 |
| 矩形与非矩形混合图片 | `tests/test_dense_review/test_session.py::test_non_rectangle_image_reports_partial_review_only` | 自动化：通过 |
| 本流程完成而旧验收未通过 | `tests/test_dense_review/test_workspace.py::test_open_confirm_and_save_round_trip`<br>`tests/test_dense_review/test_export_roundtrip.py::test_legacy_fields_and_shape_extensions_survive_round_trip` | 自动化：通过 |
| 试用结果只显示速度增加 | 人工协议 | 未执行人工试用；人工待验：M2、M3 |
| 记录有限样本收益 | 人工协议 | 未执行人工试用；人工待验：M2、M3 |
| 对照顺序与空图统计 | 人工协议 | 未执行人工试用；人工待验：M2、M3 |

覆盖计数：74 条 Scenario；所有表中 node ID 已用当前测试 AST 核对存在。

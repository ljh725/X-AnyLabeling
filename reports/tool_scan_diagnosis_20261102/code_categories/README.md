# 4.2.1 当前代码分类快照

日期：2026-11-02。基线：`6d250499d2dd81f78723b9217c7a9abf0443ca25`。HEAD：`9a37c5474c390e93243e33a88e8232a19c833280`。

本目录已实际导出原文件修改补丁与新增模块副本；运行目录和导入路径保持原位。包含当前工作区已有未提交 Inspector 代码，不能据此认定其已完成验收。

文件分类与功能分类不同：新增后台模块也可能服务于原功能改造，旧 canvas.py 也会承载新增能力。功能归属见 docs/custom_changes/CATALOG-20261030.md 和 CUSTOM-109 记录。

代码副本用于检查和迁移参考；补丁依据指定上游基线生成，不应直接套用到当前已修改工作区。二进制 .qm 和 resources.py 仅登记哈希，迁移时按项目资源流程重新生成。

## 源代码修改：上游已有文件的差异补丁（10 个文件）

| 文件 | 相对上游 | 当前状态 |
| --- | --- | --- |
| `anylabeling/configs/xanylabeling_config.yaml` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/label_file.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/label_widget.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/settings/runtime_applier.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/settings/schema.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/shape.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/utils/async_exif.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/utils/file_search.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/canvas.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/label_dialog.py` | M | Git 已跟踪，可能另有未提交修改 |

## 扩展代码：相对上游新增的运行模块（33 个文件）

| 文件 | 相对上游 | 当前状态 |
| --- | --- | --- |
| `anylabeling/services/inspection/__init__.py` | A | 未跟踪 |
| `anylabeling/services/inspection/candidates.py` | A | 未跟踪 |
| `anylabeling/services/inspection/duplicate.py` | A | 未跟踪 |
| `anylabeling/services/inspection/handoff.py` | A | 未跟踪 |
| `anylabeling/services/inspection/importers.py` | A | 未跟踪 |
| `anylabeling/services/inspection/manifest.py` | A | 未跟踪 |
| `anylabeling/services/inspection/models.py` | A | 未跟踪 |
| `anylabeling/services/inspection/profiles.py` | A | 未跟踪 |
| `anylabeling/services/inspection/rules.py` | A | 未跟踪 |
| `anylabeling/services/inspection/runner.py` | A | 未跟踪 |
| `anylabeling/services/inspection/storage.py` | A | 未跟踪 |
| `anylabeling/services/inspection/verification.py` | A | 未跟踪 |
| `anylabeling/views/labeling/editing_commands.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/inspector/__init__.py` | A | 未跟踪 |
| `anylabeling/views/labeling/inspector/controller.py` | A | 未跟踪 |
| `anylabeling/views/labeling/inspector/dialog.py` | A | 未跟踪 |
| `anylabeling/views/labeling/rect_edge_click.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/rectangle_size/__init__.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/rectangle_size/config_codec.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/rectangle_size/evaluator.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/rectangle_size/layout.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/rectangle_size/models.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/shape_filter.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/shape_identity.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/shared_view_state.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/utils/staged_annotation_loading.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/point_fit.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/rectangle_creation.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/rectangle_crosshair.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/rectangle_edge.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/rectangle_extreme.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/rectangle_size_overlay.py` | A | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/views/labeling/widgets/rectangle_size_rule_dialog.py` | A | Git 已跟踪，可能另有未提交修改 |

## 测试及工程配套（40 个文件）

| 文件 | 相对上游 | 当前状态 |
| --- | --- | --- |
| `scripts/compile_languages.py` | M | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_drag_refresh.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_label_visibility_mode.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_navigation.py` | M | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_rectangle_creation_crosshair.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_rectangle_edge_migration.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_rectangle_extreme_creation.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_rectangle_size.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_selection_priority.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_shape_identity.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_shift_point_fit_geometry.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_canvas/test_shift_point_fit_interaction.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_inspection/test_candidates.py` | A | 未跟踪 |
| `tests/test_inspection/test_duplicate_core.py` | A | 未跟踪 |
| `tests/test_inspection/test_handoff.py` | A | 未跟踪 |
| `tests/test_inspection/test_importers.py` | A | 未跟踪 |
| `tests/test_inspection/test_inspector_dialog.py` | A | 未跟踪 |
| `tests/test_inspection/test_manifest.py` | A | 未跟踪 |
| `tests/test_inspection/test_models.py` | A | 未跟踪 |
| `tests/test_inspection/test_profiles.py` | A | 未跟踪 |
| `tests/test_inspection/test_rules.py` | A | 未跟踪 |
| `tests/test_inspection/test_runner.py` | A | 未跟踪 |
| `tests/test_inspection/test_storage.py` | A | 未跟踪 |
| `tests/test_inspection/test_verification.py` | A | 未跟踪 |
| `tests/test_labeling/test_batch_edit_fields.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_candidate_review_regressions.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_digit_label_actions.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_drag_commit.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_edit_mode_shortcut.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_editing_command_scope.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_label_locks.py` | M | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_label_widget_attributes.py` | M | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_label_widget_groups.py` | M | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_shape_filter.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_labeling/test_show_shape_status.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_settings/test_runtime_applier.py` | M | Git 已跟踪，可能另有未提交修改 |
| `tests/test_settings/test_schema.py` | M | Git 已跟踪，可能另有未提交修改 |
| `tests/test_staged_annotation_metadata.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_staged_output_window.py` | A | Git 已跟踪，可能另有未提交修改 |
| `tests/test_ui_density_extremes_repair.py` | A | Git 已跟踪，可能另有未提交修改 |

## 翻译及生成资源（9 个文件）

| 文件 | 相对上游 | 当前状态 |
| --- | --- | --- |
| `anylabeling/resources/resources.py` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/resources/translations/en_US.qm` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/resources/translations/en_US.ts` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/resources/translations/ja_JP.qm` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/resources/translations/ja_JP.ts` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/resources/translations/ko_KR.qm` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/resources/translations/ko_KR.ts` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/resources/translations/zh_CN.qm` | M | Git 已跟踪，可能另有未提交修改 |
| `anylabeling/resources/translations/zh_CN.ts` | M | Git 已跟踪，可能另有未提交修改 |

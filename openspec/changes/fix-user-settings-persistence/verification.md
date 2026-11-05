# 验证记录：fix-user-settings-persistence

## 环境与基线

- 日期：2026-11-04
- 系统：Windows（DSH workspace-write 沙箱）
- Python：3.12.12（`x-anylabeling-cu12` conda 环境），PyQt6 offscreen
- 代码基线：`67c98a80 chore(baseline): organize UI development state and recovery evidence`
- 既有工作区差异：`dense_review`、`canvas` 等未提交改动先于本变更存在；本变更只在其上叠加配置持久化相关文件。

## 变更落点

| 文件 | 作用 |
| --- | --- |
| `anylabeling/user_config.py`（新增） | 配置上下文、字段补丁、三方比较、`QLockFile` 跨进程锁、原子替换、`.bak` 备份、损坏文件拒绝与恢复 |
| `anylabeling/config.py` | 启动目标解析、模板只读、会话安装、`save_config` 兼容适配（diff→补丁） |
| `anylabeling/views/labeling/settings/controller.py` | 字段草稿基线、只提交修改字段、冲突检测、失败保留草稿 |
| `anylabeling/views/labeling/settings/dialog.py` | 冲突/锁忙/损坏提示、备份恢复入口、失败关闭前重试/放弃 |
| `anylabeling/views/labeling/label_widget.py` | 主题、语言、数字映射、共享视图、矩形规则、显示开关、退出流程迁移；移除退出整份回写 |
| `anylabeling/services/auto_labeling/model_manager.py` | 自定义模型与远程服务设置改为字段提交 |
| `tests/conftest.py` | 每个测试独立配置目标 + 隔离 `QSettings` INI，结束恢复全局状态 |
| `tests/test_config/*`, `tests/test_settings/test_controller_persistence.py` | 新增回归 |
| `scripts/benchmark_dense_review.py`, `scripts/capture_dense_review_screenshots.py` | 显式配置目标与退出清理 |

## 行为—测试—结果

| 行为 | 测试 | 结果 |
| --- | --- | --- |
| 保存数字映射后保存通用设置，映射不被清空 | `tests/test_settings/test_controller_persistence.py::test_general_save_keeps_digit_mapping_saved_earlier` | 通过 |
| 只提交本会话修改字段，其余入口新值保留 | `test_save_submits_only_fields_modified_in_this_draft` | 通过 |
| 外部修改同字段 → 冲突、草稿保留、磁盘不覆盖 | `test_conflicting_external_change_is_reported_and_draft_kept` | 通过 |
| 写入失败保留草稿，故障解除后可重试 | `test_failed_write_keeps_draft_and_retry_succeeds` | 通过 |
| 无修改不写文件 | `test_no_modified_fields_does_not_touch_the_file` | 通过 |
| 外部更新刷新未修改字段、保留草稿字段 | `test_refresh_keeps_draft_values_and_updates_untouched_fields` | 通过 |
| 两进程不同字段合并 | `tests/test_config/test_user_config_store.py::test_two_processes_merge_different_fields` | 通过 |
| 两进程同字段冲突，先写者保留 | `test_two_processes_conflict_on_same_field` | 通过 |
| 等值提交幂等、不重写文件 | `test_equal_value_submission_is_idempotent` | 通过 |
| 锁忙可重试且不写文件 | `test_lock_busy_is_retryable_and_writes_nothing` | 通过 |
| 原子替换失败保留原文件、清理临时文件 | `test_failed_replace_keeps_the_previous_file` | 通过 |
| 不可序列化值被拒绝且不损坏原文件 | `test_unserializable_value_is_rejected_without_damage` | 通过 |
| 损坏文件拒绝覆盖 | `test_corrupt_document_is_never_overwritten` | 通过 |
| 备份恢复保留损坏内容 | `test_restore_backup_keeps_damaged_content` | 通过 |
| 首次创建写模板、无备份 | `test_creation_writes_template_and_reports_created` | 通过 |
| `.anylabelingrc` 迁移不覆盖新文件、旧文件保留 | `test_legacy_file_is_migrated_without_deleting_it` | 通过 |
| 旧键 `epsilon` 改写为 `canvas.epsilon` | `test_legacy_key_is_replaced_by_nested_target` | 通过 |
| 数字键以整数写入 | `test_digit_entries_use_integer_keys` | 通过 |
| 默认 / `--work-dir` / 文件型 `--config` 目标矩阵 | `tests/test_config/test_config_targets.py`（7 项） | 通过 |
| 内联 YAML / CLI 覆盖不落盘 | `test_inline_config_overrides_are_not_persisted`、`test_command_line_overrides_are_not_persisted` | 通过 |
| 真实窗口保存数字映射 + 设置，退出后新进程重开仍保留 | `.tmp/app_smoke.py`（offscreen MainWindow + 独立进程读取） | 通过 |
| 未修改快捷键不被退出还原 | 同上，`shortcuts.open` 保持模板值 | 通过 |
| 两个设置窗口交错保存：数字/快捷键先存、另一窗口草稿后存 | `tests/test_settings/test_two_window_persistence.py::test_digits_and_shortcut_saved_in_second_window_survive_first` | 通过 |
| 一个窗口取消不撤销另一窗口的已保存修改 | `test_cancel_in_one_window_keeps_the_other_windows_changes` | 通过 |
| 两个窗口同字段冲突：先写者保留、后写者草稿保留 | `test_conflict_between_two_windows_keeps_first_value` | 通过 |
| 重开后两个窗口的修改全部可见 | `test_restart_after_two_windows_sees_every_saved_field` | 通过 |
| 备份文件生成 | 同上，`.xanylabelingrc.bak` 存在 | 通过 |

## 真实环境确认（用户）

- 2026-11-04 用户重启应用后实测确认：此前“快捷键设置被还原”和“数字快捷键被清空”两个问题均已修复。

## 执行命令与结果

```text
python .tmp/run_tests.py tests/test_settings tests/test_config -q --basetemp=.tmp/pt26
77 passed, 1 skipped, 9 subtests passed

python .tmp/run_tests.py tests/test_config/test_user_config_store.py -q --basetemp=.tmp/pt21
17 passed

python .tmp/app_smoke.py one   # 真实 MainWindow：数字映射 + epsilon + model_hub
phase1 ok
python .tmp/app_smoke.py two   # 新进程重开校验
phase2 ok

openspec validate fix-user-settings-persistence --strict
Change 'fix-user-settings-persistence' is valid
```

## 既有失败与沙箱限制

- 本沙箱对 `pytest tmp_path` / `mkdtemp` 生成的目录追加了拒绝列目录的 ACL，凡使用 `tmp_path` 的用例在 setup 阶段即报 `PermissionError`，与本变更无关。
- 为区分回归与既有失败，将 `HEAD` 导出到 `.tmp/baseline-src` 并运行同一套 `tests/test_pointcloud/test_integration.py`：基线与本工作区均为 5 个失败（1 个 `tmp_path` + 4 个 `SimpleNamespace` 缺少 `async_exif_scanner`），失败集合一致。
- `tests/test_labeling`、`tests/test_canvas/test_rectangle_edge_migration.py` 等 GUI 重用例在该沙箱下长时间无输出（offstream 事件循环 + 目录 ACL），未作为门禁；对应改动仅涉及 `persist_user_preferences` 与退出流程。
- `tests/test_models/test_model_download.py` 全部用例依赖 `tmp_path`，仅做静态与补丁目标核对（`save_custom_models` 替换 `save_config`）。
- 真实“用户终端启动方式”未执行：以 `MainWindow` + offscreen 平台等价验证，重启使用独立进程。

## 兼容与回退

- YAML 结构不变；未知扩展键在合并时保留；`ui` 与旧顶层键在写入时清理。
- 数字映射仍为整数键；`shortcuts` 归一化规则未改。
- 回退只撤销本变更源码差异，保留用户 YAML 与 `.bak`；旧程序缺少并发锁，回退前需关闭多余实例，且不得用旧备份覆盖新配置。
- 模板不再被读取动作写入；首次默认配置创建改由受锁初始化事务完成。

## 2026-11-05 实施与验证

### 变更落点（本轮）

| 文件 | 作用 |
| --- | --- |
| `anylabeling/user_config.py` | `ConfigPatch` 草稿基线；锁内 B/C/P 比较；保存后同步未编辑字段；提交前文件字节复核（`ConfigExternalChange`）；`conflict_keys` 统一；`_atomic_write_bytes` 全流程统一为 `ConfigWriteError`；`restore_backup` 重建有效配置；`reload()`、`install_session()`、`initialize_target()` |
| `anylabeling/config.py` | 先初始化/迁移再构建 effective；记录内联与 CLI 临时覆盖路径；`validate_merged_config` 合并后快捷键校验；`save_config` 只接受显式字段/基线；元组路径保留数字整数段 |
| `anylabeling/views/labeling/settings/controller.py` | 提交携带草稿基线；持久化与 runtime 应用分离；`apply_failed`/`retry_apply()`；`reload_session()`、`rebase_draft()`；冲突统一为 `ConfigConflict` |
| `anylabeling/views/labeling/settings/dialog.py` | `conflict_keys` 渲染；重载真正重读磁盘；备份恢复保留草稿；“已保存未应用”提示与关闭前重试 |
| `anylabeling/views/labeling/widgets/label_dialog.py` | 数字管理器：打开时固定基线、确认→落盘→成功关闭、失败保留输入 |
| `anylabeling/views/labeling/label_widget.py` | 数字映射字段事务与基线；退出前重试应用；偏好写入携带基线 |
| `anylabeling/services/auto_labeling/model_manager.py` | 模型/远端设置保存失败传播到返回值与提示 |
| `anylabeling/views/labeling/widgets/auto_labeling/auto_labeling.py` | 远端服务器设置保存失败提示“仅当前会话生效” |
| `anylabeling/resources/translations/*.ts|*.qm` | 保存/冲突/备份恢复/运行失败/数字与模型失败的四语种文案 |
| `tests/conftest.py` | 配置目标、工作目录、环境变量、会话、`QSettings` 全部隔离并在结束后（含 None）还原；越界写入守卫 |
| `tests/test_config/test_transaction_hardening.py` | 新增 17 项故障注入、基线保护、恢复与合并校验回归 |
| `tests/test_config/test_isolation.py` | 新增 4 项隔离与哨兵回归 |
| `tests/test_config/_user_config_worker.py` | 支持多步骤、草稿基线与步骤间同步 |
| `tests/test_settings/test_digit_shortcut_flow.py` | 新增 6 项数字管理器事务回归 |
| `scripts/dev_isolation.py` | 开发脚本的独立配置会话、QSettings 绑定与完整还原 |

### 本轮实施—测试—结果

| 行为 | 测试 | 结果 |
| --- | --- | --- |
| 首次启动即可用旧 `.anylabelingrc` 的快捷键/数字映射，二次启动一致 | `test_config/test_config_targets.py::test_first_start_uses_a_migrated_legacy_file` | 通过 |
| 目标已存在时迁移不覆盖 | `test_existing_target_is_not_overwritten_by_legacy_migration` | 通过 |
| 内联/CLI 临时覆盖在无关保存后仍临时、不落盘 | `test_transient_overrides_survive_an_unrelated_save`、`test_inline_config_overrides_are_not_persisted`、`test_command_line_overrides_are_not_persisted` | 通过 |
| 无关保存把外部新值同步进有效配置 | `test_transaction_hardening.py::test_unrelated_save_syncs_external_change_into_effective` | 通过 |
| 旧草稿字段在无关保存后提交必须冲突 | `test_old_draft_field_conflicts_after_an_unrelated_save` | 通过 |
| 双进程：A 存无关字段、B 改 X、A 再写旧 X 被拒绝 | `test_user_config_store.py::test_stale_process_cannot_replace_a_field_written_elsewhere` | 通过（退出码 0/3，磁盘保留 B 值） |
| 独立进程经启动入口读取已提交值 | `test_fresh_process_reads_the_committed_document` | 通过 |
| 提交前外部改写文件被拒绝且不写入 | `test_external_change_between_read_and_replace_is_refused` | 通过 |
| 备份写入失败保留原文件与有效配置 | `test_backup_failure_keeps_the_target_untouched` | 通过 |
| 目标替换失败保留原件与有效备份、无临时文件残留 | `test_target_replace_failure_keeps_original_and_backup` | 通过 |
| 创建临时文件失败统一为存储错误且可重试 | `test_temporary_file_creation_failure_is_a_storage_error` | 通过 |
| 损坏文件被修复后可再次保存 | `test_repaired_document_can_be_saved_again` | 通过 |
| 合并后快捷键冲突拒绝提交、白名单例外放行 | `test_merged_shortcut_conflict_is_refused`、`test_whitelisted_duplicate_shortcut_is_allowed` | 通过 |
| 备份恢复重建有效配置（缺失字段消失、旧键归一化、保留副本不覆盖） | `test_restore_rebuilds_effective_instead_of_overlaying`、`test_restore_normalizes_legacy_backup_keys`、`test_restore_keeps_a_second_copy_of_the_damaged_file` | 通过 |
| 整份快照被拒绝；显式字段/基线可用；数字键整数 | `test_save_config_refuses_an_unsafe_whole_snapshot`、`test_save_config_accepts_explicit_fields_and_baselines`、`test_digit_paths_keep_integer_segments` | 通过 |
| runtime 应用失败仍报告已保存、可重试应用 | `test_controller_persistence.py::test_runtime_apply_failure_keeps_the_saved_document`、`test_retry_apply_reports_a_persistent_failure`、`test_dialog_reports_a_runtime_apply_failure_as_saved` | 通过 |
| 冲突后重新载入读到磁盘并可再次保存 | `test_two_window_persistence.py::test_conflict_reload_reads_the_file_again` | 通过 |
| 旧窗口不能用陈旧值覆盖外部写入 | `test_old_draft_cannot_replace_a_field_written_externally` | 通过 |
| 保存后仍可编辑未修改字段（基线已同步） | `test_untouched_field_can_be_edited_after_a_save` | 通过 |
| 数字管理器失败保留输入、成功才关闭、使用打开时基线、同数字冲突 | `test_digit_shortcut_flow.py`（6 项） | 通过 |
| 测试隔离、写入守卫与宿主配置哨兵 | `test_config/test_isolation.py`（4 项） | 通过 |
| 开发脚本隔离助手：真会话、写入落独立目录、状态还原、宿主不变 | `.tmp/check_isolation.py` | `isolation check ok` |
| 四语种文案可加载 | `QTranslator` 加载 `.qm` 断言译文 | 通过（zh_CN/ja_JP/ko_KR/en_US） |
| 真实窗口保存数字+设置，退出后新进程重读 | `.tmp/app_smoke.py one` / `two` | `phase1 ok` / `phase2 ok` |

### 执行命令与结果（本轮）

```text
python .tmp/run_tests.py tests/test_config -q --basetemp=.tmp/pt-u1
54 passed, 4 errors
# 4 个 error 均为沙箱对 tmp_path 的 ACL 拒绝（test_wheel_navigation_config）。

python .tmp/run_tests.py tests/test_settings -q --basetemp=.tmp/pt-u2
72 passed, 1 skipped, 3 failed, 9 subtests passed
# 3 个失败为 test_schema 字段计数（147/146、29/28、57/56），来自其它未提交变更，
# 与本变更无关，改动前基线同样失败。

python .tmp/run_tests.py tests/test_models tests/test_auto_labeling -q --basetemp=.tmp/pt-m3
179 passed, 32 errors, 5 failed
# 5 failed 与 32 error 全部为 tmp_path/AppData 沙箱权限拒绝，与配置持久化无关。

python .tmp/app_smoke.py one   # 真实 MainWindow offscreen
phase1 ok
python .tmp/app_smoke.py two   # 新进程重读
phase2 ok

python .tmp/check_isolation.py
isolation check ok

lrelease anylabeling/resources/translations/*.ts   # 需写入 translations 目录的一次性提权
2527/2527、2527/2527、2143（29 unfinished）、2143（29 unfinished）

openspec validate fix-user-settings-persistence --strict
Change 'fix-user-settings-persistence' is valid
```

### 本轮未执行

- 真实用户终端启动方式的保存—退出—重启验收（7.2）：需在实际终端交互确认快捷键绑定、数字绘制与模型配置，offscreen MainWindow 不能替代。
- `tests/test_labeling`、`tests/test_canvas` 等 GUI 重用例在本沙箱长时间无输出，未作为门禁。
- 与 `restore-v430-canvas-controls` 的导航、亮度/对比度按钮联合手测（7.3 的交错部分）。
- 独立提交（7.4）：工作区存在先于本变更的未提交差异，且沙箱禁止写 `.git`。

## 前轮未完成事项（下文后续修复结果优先）

- 与 `restore-v430-canvas-controls` 的联合回归（该变更的交错联测尚未执行）。
- 真实终端启动方式的完整验收（7.2）。
- 独立提交：工作区存在先于本变更的未提交差异（`dense_review` 等），且沙箱禁止写 `.git`，需在干净环境拆分提交。

## 后续修复 R1—R6（2026-11-05）

### 实施范围与保全

本轮已获授权按任务清单实施源码与测试，补齐 review-20261105.md 的6类问题。修改前保存相关源码/文档副本到 `.tmp/settings-followup-baseline-20261105/`；保留工作区此前的密集复核、Inspector、画布等成果。最新任务状态为25/27：真实终端交互7.2、独立提交7.4仍未完成，未归档。

### 行为—实施—证据

| 问题 | 实施结果 | 实际验证 |
| --- | --- | --- |
| R1 默认值/启动覆盖被误用为磁盘基线 | `ConfigSession.editing_baseline()` 表达原磁盘值和缺失；controller分开记录显示/持久基线，主窗口即时偏好及数字入口使用持久基线；显式保存退休对应临时覆盖 | 稀疏 `{}` 可保存epsilon；CLI epsilon明确修改成功且其他临时labels不落盘；真正并发修改仍拒绝。`test_persistence_review_regressions.py` |
| R2 无关保存后未修改字段基线仍旧 | 未修改字段收到已提交变化时刷新基线；成功保存后同步整个新草稿及基线，已修改字段保留原始基线 | 同进程与外部文件更新字体20→本窗保存epsilon→再改字体22均成功 |
| R3 pending apply被无关保存/重开清空 | 按字段累计失败，仅在实际应用成功时删除；重开不清除，重载支持重试；无修改保存仍保留错误状态提示 | runtime持续失败→无关保存→重开→重载仍保留pending，解除故障后重试清除；重载未变化文件也撤回未保存预览 |
| R4 重载留下删除项 | 保存/重载按模板、完整规范化磁盘与剩余临时覆盖重建有效配置；原位协调嵌套字典，保留引用并同步删除 | 删除单个数字、整个映射、整个文件均回到正确有效状态；重载不会凭空新建被删除文件 |
| R5 最新字段未应用到真实动作 | 配置会话在释放文件锁后发出effective_changed；controller识别所有运行字段变化并通知runtime，保存、其他入口提交、重载/恢复均覆盖；新增数字绘制映射与保持按钮同步 | 使用真实QAction验证保存/重载/其他入口提交3条路径；真实MainWindow重开后快捷键、数字模式/类别、模型列表及保持控件均有效 |
| R6 fixture还原重复组织目录 | 显式INI工厂已足够隔离，移除全局setPath/defaultFormat修改；保存/初始化/备份/恢复共用写入守卫 | 新增4项真实fixture生命周期测试：正常/异常、原值None/非None、嵌套使用，逐项对比INI路径及全局状态 |
| 主窗口联测4.5/7.3 | 打开设置草稿，经主窗口真正打开数字弹窗、保存数字，再交错操作菜单/面板保持、导航和模型列表 | `test_real_entries_interleave_restart_and_keep_drawing_bindings`：实际MainWindow关闭重开，QAction保留，数字键创建“车辆”矩形且标注JSON正确；亮度/对比度切图保留、导航模式及模型配置列表保留 |
| 数字失败重试 | 真实主窗口数字弹窗落盘失败时保持窗口/文本；解除故障后同一弹窗重试成功 | `test_main_window_digit_failure_preserves_input_for_retry` |

新建 `tests/test_settings/test_persistence_review_regressions.py`（13项）及 `test_persistence_window_integration.py`（2项），扩展 `test_config/test_isolation.py`（4项生命周期回归）。修改前先执行最初12项行为回归，实际结果11 failed、1 passed，固化缺口；新增预览回滚场景后共13项。

本轮还更新既有schema测试的计数：导航模式字段使总数为147、非快捷键57、Canvas29；保留其他字段/排除/默认值断言，未删除失败用例或跳过新场景。`anylabeling/config.py` 仅清理既有EOF多余空行。

### 执行命令与结果

环境：Windows、Python 3.12.12（`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`）、`QT_QPA_PLATFORM=offscreen`、`PYTHONDONTWRITEBYTECODE=1`。普通沙箱仍阻止Qt DLL加载；本轮测试经受控提权执行，所有配置/INI/样本使用项目 `.tmp/`，未改真实用户配置。

```text
python -B .tmp/run_tests.py tests/test_settings/test_persistence_review_regressions.py -q -p no:cacheprovider --basetemp=.tmp/settings-followup-before
# 修改实现前：11 failed, 1 passed

python -B .tmp/run_tests.py tests/test_settings/test_persistence_review_regressions.py tests/test_config/test_transaction_hardening.py tests/test_settings/test_controller_persistence.py tests/test_settings/test_two_window_persistence.py -q -p no:cacheprovider --basetemp=.tmp/settings-followup-core
46 passed in 17.64s

python -B .tmp/run_tests.py tests/test_config/test_isolation.py tests/test_settings/test_schema.py -q -p no:cacheprovider --basetemp=.tmp/settings-followup-fixtures
15 passed in 2.60s

python -B .tmp/run_tests.py tests/test_settings/test_persistence_window_integration.py -vv --tb=short -p no:cacheprovider --basetemp=.tmp/settings-followup-windows
2 passed in 14.14s

python -B .tmp/run_tests.py tests/test_config tests/test_settings tests/test_labeling/test_canvas_display_retention.py tests/test_labeling/test_toolbar_display_actions.py tests/test_labeling/test_review_status_panel.py tests/test_models tests/test_auto_labeling -q --tb=short -p no:cacheprovider --basetemp=.tmp/settings-followup-final --junitxml=.tmp/settings-followup-final.xml
401 passed, 2 failed, 1 skipped, 15 subtests passed in 177.94s

python -B .tmp/run_tests.py tests/test_labeling/test_canvas_display_retention.py -vv --tb=short -o faulthandler_timeout=30 -p no:cacheprovider --basetemp=.tmp/settings-followup-navigation-diagnosis
26 passed in 76.89s
```

最后一条是扩大回归长时间无新输出时启动的独立诊断：实际全部通过，没有线程阻塞或新失败，未把较慢初始化误记为功能挂起。扩大回归已正常结束。

两项失败均为 `test_auto_labeling/test_remote_server.py` 的 `test_prediction_forwards_selected_classes` 与 `test_selecting_all_classes_sends_empty_filter_override`：测试保持Windows NamedTemporaryFile打开时，远端模型再次open该文件被拒绝，调用栈不经过本次设置持久化代码。用仅导入标准库的探针独立确认：

```python
import tempfile
with tempfile.NamedTemporaryFile(suffix=".jpg") as sample:
    with open(sample.name, "rb") as stream:
        stream.read()
# PermissionError（不导入任何项目代码也出现）
```

未修改远端模型或临时文件测试来掩盖该平台限制。唯一跳过为环境没有可用字体导致的 `test_font_family_applies_and_restores_without_restart`，不冒称字体应用已验证。完整JUnit结果保留在 `.tmp/settings-followup-final.xml`。

### 静态检查与差异检查

- Black检查8个本轮设置模块/fixture/测试文件通过；主窗口仅格式化本次数字管理器及即时偏好函数范围。
- Flake8 `--select=E9,F821,F822,F823`（语法/未定义变量）通过。
- 全量Flake8还报告大函数C901、旧字符串F541及长行等提示，未将其声称为全部通过，未对无关UI结构做大幅重排或增加忽略注释。
- `git diff --check` 通过（仅现有CRLF/LF转换提示）；OpenSpec strict结果按本轮执行记录更新。

### 兼容、回退与剩余事项

YAML存储结构及数字整数键不变，不新增运行依赖；变化通知使用现有PyQt6，先释放文件锁再运行UI回调。无关临时覆盖继续仅当前会话生效。回退只撤销本轮增量，保留用户YAML、备份和其他功能工作区成果，禁止用旧备份自动恢复丢失映射。

7.2仍需用户真实终端原启动方式的可见交互验收；本轮真实MainWindow为offscreen自动测试，不将其冒称为真实桌面手测。7.3已完成与画布恢复控件的自动联测；屏幕布局、主题和系统缩放手感未因此获得额外结论。

7.4的验证文档、strict和增量交付材料已完成，但尚未独立提交。当前基线包含先于本轮的未提交功能及未跟踪文件，不能整份stage并冒充独立修复。`evidence/followup-20261105.patch` 与对应交付说明保留本轮工作区增量；它基于本轮实施前工作区，而非宣称可直接应用于HEAD。没有归档或修改用户历史配置。


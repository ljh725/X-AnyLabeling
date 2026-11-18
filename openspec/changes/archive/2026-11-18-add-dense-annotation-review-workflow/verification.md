# 密集标注复核工作流实施验证

> 当前状态以 [2026-11-05 实施与验证](implementation-20261105.md) 和 [tasks.md](tasks.md) 为准：代码补齐及自动化验证已推进，61/66 项勾选；人工和大范围合跑未决项仍未完成。下文为 2026-11-02 至 11-04 历史证据，原日期的“未实现/仅修改文档”等陈述不代表当前状态。

日期：2026-11-02 起，2026-11-03 补齐；2026-11-04 文档复核（Asia/Shanghai）
分支：`codex/refactor-data-inspector-workflow`（当前工作树 `codex/4.2.1-baseline-organization`）
基线：`9a37c5474c390e93243e33a88e8232a19c833280`
本地基线标签：`backup/add-dense-annotation-review-workflow-20261102`（已核验 SHA，尚未推送远端）
状态：首版已有实现与历史证据，整体验收未完成。2026-11-04 仅只读检查代码/测试/报告并修订 OpenSpec，未修改代码、未重跑产品或性能测试；当前缺口见 [review-20261104.md](review-20261104.md)。下文历史通过结果按其原日期、代码和范围解释。

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

## 历史自动化证据（2026-11-02/03；本次文档复核未重跑）

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
- 证据及完整命令见 [第二轮修复记录](../../../reports/dense_review_workflow_20261102/ROUND2-UNDO-FIX-20261102.md)，JUnit 见 [round2-fix-regression.xml](../../../reports/dense_review_audit_20261102/round2-fix-regression.xml)。截至 2026-11-02 任务3.6因 redo 未实现保持未完成；2026-11-03 补齐情况见下一节。该历史轮次不包含人工或性能验收。

### 2026-11-03 补齐（重做、翻译、样本、延迟注入、导出往返）

- **重做（3.6）**：画布新增 `shapes_redo` 快照栈，会话新增进度/内容重做流与共享 LIFO 顺序；`Ctrl+Z` / `Ctrl+Shift+Z`（设置可改键）。新编辑清空重做；画布快照保留 10 条、审核事务 100 条。`restore_shape` 现在自行恢复撤销栈不变式，撤销/重做后的列表刷新改用 `load_shapes(record_history=False)`。新增 5 项会话级与 3 项 GUI 回归（`test_redo_progress_restores_confirmation_and_cursor`、`test_redo_after_canvas_restores_review_state`、`test_new_progress_action_clears_redo`、`test_noop_confirm_keeps_redo_stream`、`test_mixed_undo_then_redo_restores_every_transaction`、`test_batch_confirmation_redo_restores_progress`、`test_canvas_edit_redo_restores_bounds_and_review_state`、`test_new_edit_clears_redo`）；`tests/test_labeling/test_batch_edit_fields.py` 的单步撤销断言同步到新契约。
- **翻译（7.8）**：四语言 `.ts` 各 +9 条新文案（`LabelingWidget` 的 `Redo`/tooltip、`SettingsDialog` 的 `Redo` 与 6 条密集复核快捷键标签），并补齐 22 条此前仍是英文占位的 zh_CN 密集复核文案；`schema.py` 的 `_settings_translation_markers()` 注册了 7 条 SettingsDialog 字面量（原提取机制遗漏），`lrelease` 重编 `.qm`（en_US 296559 / zh_CN 221211 / ja_JP 205323 / ko_KR 205549 字节）。新增 `app.py::load_translator()`，源码环境优先磁盘 `.qm`、打包环境回退 `:/languages/...` 资源。新增 `tests/test_dense_review/test_translations.py`：**6 passed, 10 subtests**，覆盖四语言新文案、工作区代表文案与 zh_CN 无 unfinished。ja/ko 其余 413 条历史 backlog 未翻译（工作区在 ja/ko 下仍显示英文），见“未验证”。
- **自制样本（1.3）**：新增 `scripts/generate_dense_review_samples.py`（确定性、`--check` 逐字节校验）与 `samples/dense_review/` 7 个场景（30 对象 6 类、12 全对、小目标遮挡、截断手臂、第三批错分、空图、混合形状）+ `manifest.json`/中文 `README.md`；新增 `tests/test_dense_review/test_samples.py` **8 passed**（计数/类别/ID、真实 `LabelFile` 零修复加载、真实 `DenseReviewSession` 批次成员与 `supported=False`）。
- **延迟注入（9.3）**：新增 `tests/test_dense_review/test_delay_injection.py` 6 项：快速切图、快速切输出目录、旧边界迟到结果、迟到失败、背景扫描回填、关窗/取消切换；用假 executor/假 worker 确定性投递，未发现代际或状态污染缺陷。
- **训练导出与旧程序往返（9.5）**：新增 `tests/test_dense_review/test_export_roundtrip.py` 5 项：进度命名空间只在顶层、旧 `checked`/`review_status` 与扩展字段保真、真实 `LabelConverter.custom_to_yolo` 导出仅 2 行数值字段、旧程序删除命名空间或修改标签后不恢复过期确认且覆盖部分失效。
- **性能（10.1–10.3）**：新增 `scripts/benchmark_dense_review.py`（真实 MainWindow + 工作区，30/300 对象、冷/暖缓存、心跳、拖框、缓存有界性）与 `test_performance_smoke.py`。首次实测 30 对象拖框+后台卡片 +36.0%/+23.0%；定位为 GUI 线程 PNG 解码、每 tick 32 条卡片的图标/标签刷新及 worker 争用，随后改为 worker 解码、每 tick 8 条、指针按下期间暂停卡片后台与 worker 争用、合并标签刷新，并补充 `is_pointer_down` 与两个缩略图回归测试。复测（300 样本）：暖切换 16.5/31.7 ms、心跳 2.5/3.2 ms 通过；拖框回退 300 对象 +8.7%/+8.2% 通过，30 对象 +18.9%/+24.8% 未通过（绝对亚帧）。缓存有界性通过（峰值 30/64 与 64/64，无线性增长）。10.2 不写成已实现。
- 汇总：`tests/test_dense_review` **123 passed in 53.06s**；`tests/test_canvas` **578 passed / 1 项基线失败**（`test_shape_label_keeps_fixed_screen_size_while_zooming`）；`tests/test_labeling` **192 passed / 10 failed**（8 项基线 + 2 项沙箱临时目录权限）；`tests/test_settings` 各文件通过，字段计数守卫更新为 146/90（新增 `shortcuts.redo` 与既有的 `shortcuts.open_correction_metrics`）；flake8/Black 通过。

### 未纳入通过结论

- `tests/test_settings` 整个目录一次运行时，在 `test_dialog_layout` 之后出现原生访问冲突退出（exit 3221226505）。各文件单独运行通过；该组合运行的崩溃未确认属于本变更新增，不能记为通过。
- 未重新运行全部历史版本或全部历史人工验收。

## 历史主题级覆盖索引（不等于逐 Scenario 验收表）

以下为原始主题索引，含缩略测试名和泛称；不能据此完成 9.1。逐 Scenario 的完整 node ID、人工步骤及实际结果仍待补齐，本轮新增场景也须纳入。

| 规格主题 | 历史自动化指代 |
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
- 性能门槛（10.2）未全部达标：按旧脚本口径，图内暖对象/批次切换与心跳数字在 30/300 对象均低于阈值；正确目标首帧可编辑终点尚未证明，切换验收未完成。拖框回退在 300 对象通过（+8.7% / +8.2%），**30 对象未通过**（+18.9% / +24.8%，绝对 p95 5.5–5.8 ms、p50 +0.08 ms）。修复与复测数据见 `perf_reports/dense_review/performance-20261103/SUMMARY.md` 的「修复后复测」；30 对象小基线下需真实屏幕与更高样本复核。
- 两位实际使用者、顺序交叉对照组和独立质量复核；减负效果未验证。
- `anylabeling/resources/resources.py` 仍嵌入 2026-11-02 的旧 `.qm`；本环境无兼容 `pyrcc6`，未重生成。源码运行改为优先读取磁盘 `.qm`，打包产物需在具备兼容 rcc 的机器重生成资源并回归后再发布。
- ja_JP / ko_KR 仍有 413 条历史未翻译消息（含工作区卡片/配置对话框主体文案），运行时回退英文；本次只补齐本变更新增文案与 22 条 zh_CN 占位。
- 四语言真实屏幕布局、字体度量和无障碍检查；offscreen 截图见 `images/dense_review/`，不能替代真实屏幕验收。
- 完整虚拟列表和小窗口辅助区域收起仍未完成。当前为懒生成缩略图与布局调整；二者属于设计 D1/D5 和任务 4.1/5.3/5.5 的承诺，不能排除出验收门槛。

## 2026-11-04 复核更正与剩余证据

本节为当前判定；前文保留历史结果，不代表本轮重新执行。问题详情、静态路径及验收条件见 [review-20261104.md](review-20261104.md)。

| 领域 | 已有证据可支持的范围 | 不能据此得出的结论 / 剩余工作 |
| --- | --- | --- |
| 批次导航 | 存在会话导航及单批次确认测试 | 跨批次列表/卡片/画布/确认范围一致；4.4 重开 |
| 卡片与比较 | 可见缩略图懒生成、provider LRU、已缓存比较图 | 直接切批必然加载、冷比较图迟到更新、完整虚拟化及小窗口收起；4.1/5.3/5.5 重开 |
| 翻译 | 中文及部分新文案/快捷键测试、磁盘 qm | 日/韩主体和打包资源、真实屏幕及无障碍全部可用；7.8 重开 |
| 查漏恢复 | 状态含区域游标，存在纯状态保存恢复 | GUI 关闭重开后的区域位置、疑难/暂跳均正确；8.3 重开 |
| 保存与冲突 | 保存失败内存保留、冲突函数检测 | 自动保存写入边界和真实冲突选择路径；新增 3.8/3.9 |
| 异步与集成 | 假 worker 注入及历史分文件测试 | 真实线程退出安全、关闭后全部主要操作、当前合跑无崩溃；9.3/9.6 重开，新增 9.7 |
| 导航性能 | offscreen navigate 加一次 pump 的旧耗时 | 正确目标首帧完成且可编辑，或真实切图性能；10.1 重开，10.2 仍未通过 |
| 资源有界 | 同图对象遍历时 provider 图像条目/字节及模拟代际清空 | 正常多图/目录生命周期全部资源和进程内存稳定；10.3 重开 |
| 减负与交付 | 自制样本、说明文档、历史 strict | 两位使用者真实效果与独立质量通过、所有承诺完成；10.4/10.5 保持未完成，11.3 重开 |

特别更正：10.3 原注释“切换 90/300 次”实际为同图对象切换；脚本的 image_switch_reset 是模拟 generation 清空，不是真实图片加载。provider 的 QImage 字节峰值不等于卡片图标、在途队列或进程总内存。历史数据保留，不改写成未做过的实验。

本轮检查：`openspec validate add-dense-annotation-review-workflow --strict` 通过；本变更目录 `git diff --check` 通过（清理任务 1.3 原有行尾空格后复验）。修改范围为本目录的 proposal、design、tasks、verification、三份增量规格及新增复核记录。功能、GUI、性能、翻译和人工验收均未在本轮执行，不因文档修改而关闭问题。

## 回退

1. 删除 `anylabeling/services/dense_review/`、`anylabeling/views/labeling/dense_review/`、`tests/test_dense_review/`。
2. 还原 `label_widget.py`、`widgets/canvas.py`、`settings/schema.py`、`configs/xanylabeling_config.yaml`、`tests/test_settings/test_schema.py` 中本功能相关改动；还原 `services/inspection/handoff.py` 的可用性声明与对应测试。
3. 标注 JSON 中的 `xanylabeling_dense_review` 保留原内容；旧程序不应把它解释为旧审核通过。需要彻底清理时另行备份并显式删除该命名空间。

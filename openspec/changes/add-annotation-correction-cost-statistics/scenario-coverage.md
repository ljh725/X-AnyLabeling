> **更正（2026-11-10，Lead）**：本报告作者当时未使用项目 conda 环境
> （`C:/Users/20441/.conda/envs/x-anylabeling-cu12`，其中已安装 PyQt6），因此文中
> "仓库测试无法运行 / 无 PyQt6"的表述不成立。该环境可运行定向用例，结果见
> [verification.md](verification.md) 与 [implementation-batch1-20261110.md](implementation-batch1-20261110.md)。
> 报告其余分析与结论未受影响。

# 修正成本统计：场景覆盖表（tasks.md 1.4）

- 变更：`openspec/changes/add-annotation-correction-cost-statistics`
- 任务：tasks.md **1.4 建立测试/验证目录和场景覆盖表，将四份 specs 的需求与后续任务、验证证据对应；记录既有定向测试基线**
- 覆盖对象：四份 spec 的**全部** Requirement 与 Scenario（见下表统计）
- 结论：**33 Requirement / 69 Scenario，共 102 条**；现有自动化覆盖 **0 条 Scenario 直接覆盖**、
  **1 条 Scenario 间接覆盖**（REP-1.1），其余 **68 条 TODO**；**0 条 Requirement 有直接自动化覆盖**。

---

## 0. 总量统计

| spec 目录 | Requirement | Scenario | 已有直接覆盖 | 间接/部分 | TODO |
| --- | --- | --- | --- | --- | --- |
| `annotation-correction-baseline` | 8 | 16 | 0 | 0 | 16 |
| `annotation-correction-events` | 8 | 17 | 0 | 0 | 17 |
| `annotation-correction-reporting` | 8 | 17 | 0 | **1**（REP-1.1） | 16 |
| `annotation-work-timing` | 9 | 19 | 0 | 0 | 19 |
| **合计** | **33** | **69** | **0** | **1** | **68** |

> 计数方式：`grep -c '^### Requirement:'` 与 `grep -c '^#### Scenario:'`，四份 spec 合计 102 行
> （24 / 25 / 25 / 28），与本文条目数一致。

编号规则：`BASE`=`annotation-correction-baseline`、`EVT`=`annotation-correction-events`、
`REP`=`annotation-correction-reporting`、`TIM`=`annotation-work-timing`；
`BASE-1` 为 Requirement 序号，`BASE-1.1` 为其第 1 个 Scenario。

覆盖状态图例：**✅ 已有**（现有测试直接断言）、**🟡 间接**（现有测试/代码只证明相邻行为）、
**⬜ TODO**（无任何验证，需新增）。

---

## 1. 证据目录规划（未来验证资产）

任务 1.4 要求"建立本变更的测试/验证目录"。建议（与现有 `tests/test_<模块>/` 结构一致）：

```
tests/test_correction_metrics/            # 纯服务（无 Qt）
  test_samples.py                          # 1.3 固定样本与 manifest（见 samples-design.md）
  test_core_identity.py                    # 身份/同名/缺失 ID/轮次
  test_core_differences.py                 # B/F/G/C 净差异、规范化、转换
  test_core_transactions.py                # 事务/触达/去重/幂等/撤销
  test_core_taxonomy.py                    # 类别版本、一对一映射、合并拆分、N/A
  test_scope.py                            # 支持范围与完整性（混合形状/缺口）
  test_provenance.py                       # 预测来源、允许列表、迟到/失败
  test_store.py                            # SQLite/队列/故障/检查点/导出快照
  test_recovery.py                         # 恢复、外部修改、版本间隙
  test_reporting.py                        # 面板/汇总/分组/完成去重
  test_export.py                           # CSV 契约、中文、注入、取消
  test_timing.py                           # 计时状态机（假时钟）
tests/test_labeling/                      # GUI 定向（Qt）
  test_correction_panel.py                 # 面板、空闲提示、完成/继续/复核
  test_correction_flows.py                 # 各矩形入口、锁定、自动保存、切图
openspec/changes/add-annotation-correction-cost-statistics/verification.md
reports/correction_metrics_<date>/         # 性能（9.4）与试用（9.5）证据
```

证据类型标注：**T**=自动化测试、**M**=手工验收（写入 `verification.md` 并附截图/记录）、
**P**=性能/试用证据文件（`reports/`）、**S**=固定样本（`samples/correction_metrics/`，见任务 1.3 设计）。

---

## 2. `annotation-correction-baseline`（8 R / 16 S）

| ID | Requirement / Scenario | tasks.md | 未来验证证据 | 现有覆盖 |
| --- | --- | --- | --- | --- |
| BASE-1 | 图片和轮次身份可追溯 | 2.1, 2.2, 3.1 | T `test_core_identity.py`；S 样本 9 | ⬜ |
| BASE-1.1 | 重排对象不产生修正 | 2.2, 2.3 | T `test_core_differences.py::test_reorder_is_noop`；S 样本 2 `identity_reorder` | ⬜ |
| BASE-1.2 | 同名图片属于不同数据集 | 2.2, 3.1 | T `test_core_identity.py::test_same_name_different_roots`（用 `dataset_identity()` 两组根目录） | ⬜ |
| BASE-2 | 已有标注起点明确声明来源 | 2.1, 4.2, 5.1 | T `test_provenance.py`；S 样本 7 | ⬜ |
| BASE-2.1 | 对历史标注开始统计 | 2.1, 4.1 | T `test_provenance.py::test_unknown_existing_origin`；S 样本 7 `freeze`（`ai_count is None` + `unknown-origin`） | ⬜ |
| BASE-2.2 | 后续编辑不修改起点 | 3.4, 5.1 | T `test_store.py::test_baseline_immutable_after_edit`；S 样本 7 `delete_one_relabel_two`（断言 `state["baseline"]` 未变） | ⬜ |
| BASE-3 | 替换预测与增量预测保留对象来源边界 | 2.1, 4.2, 4.3 | T `test_provenance.py`；S 样本 8/10；**依赖 GAP-2** | ⬜ |
| BASE-3.1 | AI 追加到人工框 | 4.2, 4.3 | T `test_provenance.py::test_additive_keeps_manual_objects`；S 样本 8（`ai_count==3`，非 8） | ⬜ |
| BASE-3.2 | 替换保留受保护对象 | 4.2 | T `test_provenance.py::test_replacement_keeps_protected`；S 样本 10 | ⬜ |
| BASE-4 | 单张与批量预测建立同等可追溯记录 | 4.1, 4.3, 2.6 | T `test_provenance.py::test_allowlist_blocks_secrets`（`safe_provenance` 丢弃 `api_key`/`https://…`）；S 样本 8 的非法 provenance 字段 | ⬜ |
| BASE-4.1 | 批量预测部分失败 | 4.3, 3.4 | T `test_store.py::test_batch_partial_failure_checkpoints` | ⬜ |
| BASE-4.2 | 迟到结果未应用 | 4.2 | T `test_provenance.py::test_late_result_not_attributed` | ⬜ |
| BASE-5 | 重新预测创建新运行和修正轮次 | 4.2, 3.5 | T `test_store.py::test_second_run_new_round` | ⬜ |
| BASE-5.1 | 修正后重新预测 | 4.2 | T 同上（旧轮次成本仍可查询，新净结果从新起点算） | ⬜ |
| BASE-6 | 统计独立保存且不改变标注文件契约 | 3.1, 3.3, 8.5, 10.4 | T `test_store.py`、`test_export.py`；既有训练导出回归 | ⬜ |
| BASE-6.1 | 统计存储不可写 | 3.3 | T `test_store.py::test_readonly_store_degrades`（标注仍保存成功 + 缺口标记） | ⬜ |
| BASE-6.2 | 导出训练数据 | 8.5, 10.4 | T `test_export.py::test_label_json_has_no_events`（对照现有 `tests/test_auto_training/` 训练格式） | ⬜ |
| BASE-7 | 保存检查点与标注成功版本一致 | 3.4, 5.1, 5.2 | T `test_store.py`、`test_correction_flows.py` | ⬜ |
| BASE-7.1 | 保存失败后重试 | 3.4 | T `test_store.py::test_failed_save_draft_then_success`（成本不重复累加） | ⬜ |
| BASE-7.2 | 丢弃草稿 | 5.2 | T `test_correction_flows.py::test_discard_restores_saved` | ⬜ |
| BASE-8 | 恢复时验证检查点和统计范围 | 3.5, 2.6, 2.2 | T `test_recovery.py`；S 样本 9 | ⬜ |
| BASE-8.1 | 标注已保存但统计检查点缺失 | 3.5 | T `test_recovery.py::test_version_gap_reported`；S 样本 9（身份冲突→计数全 None） | ⬜ |
| BASE-8.2 | 图片或标注被外部修改 | 3.5 | T `test_recovery.py::test_external_change_marks_incomparable` | ⬜ |
| BASE-8.3 | 混合形状或形状转换 | 2.6 | T `test_scope.py::test_non_rect_partial_scope`；S 样本 6（`unsupported_count=4`、`convert_one_rect`→`scope_changes=1`） | ⬜ |

---

## 3. `annotation-correction-events`（8 R / 17 S）

| ID | Requirement / Scenario | tasks.md | 未来验证证据 | 现有覆盖 |
| --- | --- | --- | --- | --- |
| EVT-1 | 只在有效操作完成时记录事务 | 2.4, 4.4, 4.5, 8.2 | T `test_core_transactions.py`；S 样本 2/4/5 | ⬜ |
| EVT-1.1 | 一次拖框有多次移动事件 | 4.5 | T `test_core_transactions.py::test_drag_samples_one_transaction`；S 样本 4 `repeat_syncs=37` 同一 `transaction_id` → 1 事务 | ⬜ |
| EVT-1.2 | 取消或没有实际变化 | 2.4, 4.5 | T 同上 `::test_identical_submit_no_tx`；S 样本 2 `no_change_submit`、样本 5 `lock_toggle_only` | ⬜ |
| EVT-2 | 批量事务与对象计数分开 | 2.4, 4.4 | T `test_core_transactions.py`；S 样本 3/5 | ⬜ |
| EVT-2.1 | 一次改动多个对象 | 4.4, 4.6 | T `::test_batch_relabel_one_tx_ten_touches`；S 样本 3 `batch_relabel_10`（1/10/10）、样本 5 `batch_relabel_all_10`（1/6/6，锁定不计） | ⬜ |
| EVT-2.2 | 重复修改同一对象 | 2.4 | T `::test_repeat_edit_dedupes_object`；S 样本 2 主变体 p-014（2 事务、去重 1） | ⬜ |
| EVT-3 | 矩形净结果按稳定身份集合计算 | 2.3 | T `test_core_differences.py`；S 样本 2/4/6 | ⬜ |
| EVT-3.1 | 原框同时改类和改框 | 2.3, 2.5 | T `::test_both_class_and_geometry`（进 C 和 G，`modified_original` +1）；S 样本 2（G=5,C=4,modified=10） | ⬜ |
| EVT-3.2 | 新增框再修改或删除 | 2.3, 2.4 | T `::test_new_then_edit_and_new_then_delete`；S 样本 2（n-101/n-102 只进 added） | ⬜ |
| EVT-4 | 撤销保留过程成本并更新净结果 | 4.7, 2.4 | T `test_core_transactions.py`、`test_correction_flows.py` | ⬜ |
| EVT-4.1 | 调框后完全撤销 | 4.7, 5.4 | T `::test_undo_restores_geometry_cost_kept`（净改框回 0，事务与时间保留） | ⬜ |
| EVT-4.2 | 撤销复核确认 | 4.7 | T `::test_review_undo_no_net_change`（`review-undo` 不计事务） | ⬜ |
| EVT-5 | 来源不同的编辑不能混作人工修正 | 4.1–4.7 | T `test_provenance.py`；S 样本 8；**依赖 GAP-1** | ⬜ |
| EVT-5.1 | 接受候选与手工绘制 | 4.2 | T `::test_candidate_accept_source`（`source` 可区分、均可能新增） | ⬜ |
| EVT-5.2 | AI 批量导入 | 4.3 | T `::test_prediction_import_not_manual_create`；S 样本 8 `second_ai_import`（added 3、1 事务、`ai_count` 仍 3） | ⬜ |
| EVT-6 | 全局类别改名保留语义和历史边界 | 2.5, 4.6, 5.4 | T `test_core_taxonomy.py` | ⬜ |
| EVT-6.1 | 明确的一对一改名 | 4.6 | T `::test_alias_rename_no_class_change`（体系版本+映射，净改类 0） | ⬜ |
| EVT-6.2 | 改名前已有个别改类 | 2.5 | T `::test_individual_change_survives_rename`（B→A2 语义改类保留） | ⬜ |
| EVT-6.3 | 类别合并或拆分 | 2.5, 7.4 | T `::test_merge_split_class_incomparable`（`class_comparable=False` → C/unchanged/modified/比例为 None，禁止 100% 原样） | ⬜ |
| EVT-7 | 类别归属和比例分母明确 | 2.5, 7.4, 8.3 | T `test_core_taxonomy.py`、`test_reporting.py` | ⬜ |
| EVT-7.1 | 改类并改框 | 2.5 | T `::test_geometry_attributed_to_initial_class`；S 样本 2 的 `classes` 分组断言 | ⬜ |
| EVT-7.2 | 空起点新增标注 | 2.5 | T `::test_zero_denominator_is_na`；S 样本 1 `add_three`（added=3，比例全 N/A） | ⬜ |
| EVT-8 | 修正数量不自动成为模型质量结论 | 5.6, 7.4, 8.1 | T `test_reporting.py`；S 样本 7 | ⬜ |
| EVT-8.1 | 用户删除一个框 | 5.6 | T `::test_delete_is_fact_not_false_positive`；S 样本 7（删除 1，无"误检"字段变化） | ⬜ |
| EVT-8.2 | 原样保存未复核预测 | 5.6 | T `::test_unchanged_does_not_imply_correct`（`quality=="not-assessed"`）；S 样本 2 `freeze` | ⬜ |

---

## 4. `annotation-correction-reporting`（8 R / 17 S）

| ID | Requirement / Scenario | tasks.md | 未来验证证据 | 现有覆盖 |
| --- | --- | --- | --- | --- |
| REP-1 | 统计默认关闭且无需逐框填报 | 7.1 | T `test_correction_panel.py`、现有 gate 测试；M 启用范围截图 | 🟡 部分 |
| REP-1.1 | 未启用统计正常编辑 | 7.1, 9.2 | 现有 `tests/test_labeling/test_correction_metrics_gate.py::test_actual_workflow_menu_disables_unfinished_statistics`（入口禁用、画布/复核/Inspector 仍可用）+ `tests/test_canvas/test_rectangle_preview_overlap.py` 以 `correction_metrics=None` 构造 host 仍可编辑保存 + 全画布回归 | 🟡 间接（只证明"未启用"，未证明"开关关闭下无事件/无计时/无存储"） |
| REP-1.2 | 对选定范围启用 | 7.1 | T `test_correction_panel.py::test_enable_selected_range`（显示生效范围与计时状态） | ⬜ |
| REP-2 | 当前图片面板区分不同统计口径 | 7.2, 5.6 | T `test_correction_panel.py`；S 样本 2/6/7 | ⬜ |
| REP-2.1 | 草稿不同于已保存版本 | 5.1, 7.2 | T `::test_draft_vs_saved_columns`；S 样本 2 `draft_not_saved`（draft 有值 / saved 全 None + `unsaved-result`） | ⬜ |
| REP-2.2 | 统计发生缺口 | 2.6, 7.2 | T `::test_gap_banner`；S 样本 6（`partial-scope`）、样本 7（`unknown-origin`） | ⬜ |
| REP-3 | 本轮处理完成绑定成功保存版本 | 5.3, 5.4, 5.5 | T `test_correction_flows.py`；S 样本 7 `complete_then_browse` | ⬜ |
| REP-3.1 | 保存成功但未声明完成 | 5.3 | T `::test_save_does_not_complete` | ⬜ |
| REP-3.2 | 完成后再次修改 | 5.4 | T `::test_edit_invalidates_complete`（含非矩形与全局改名） | ⬜ |
| REP-3.3 | 批量完成存在保存失败 | 5.3 | T `::test_batch_complete_lists_failures` | ⬜ |
| REP-4 | 完成数量去重且轮次阶段另列 | 5.3, 7.3 | T `test_reporting.py` | ⬜ |
| REP-4.1 | 同图重复完成和复核 | 5.3, 5.5 | T `::test_completed_images_dedup`（当前完成图数=1，复核另列） | ⬜ |
| REP-4.2 | 重跑预测形成新版本 | 5.3, 4.2 | T `::test_rerun_counts_once`（旧完成记录保留但不叠加） | ⬜ |
| REP-5 | 汇总使用明确可比范围 | 7.3, 7.4 | T `test_reporting.py`；S 样本 3/6 | ⬜ |
| REP-5.1 | 汇总混合完整和不完整轮次 | 7.3 | T `::test_complete_subset_only`（排除数量与原因单列）；S 样本 6 | ⬜ |
| REP-5.2 | 比较不同模型预测 | 7.3, 7.4 | T `::test_group_by_model_discloses_scope`；S 样本 8/10（`ai_count` 与起点披露） | ⬜ |
| REP-6 | CSV 保留统计语义和中文兼容性 | 8.1, 8.3 | T `test_export.py` | ⬜ |
| REP-6.1 | 中文及特殊文本导出 | 8.3 | T `::test_csv_chinese_quote_newline_injection`（`safe_cell`：`= + - @` 转义、BOM、引号） | ⬜ |
| REP-6.2 | 缺失来源和零分母导出 | 8.1, 8.3 | T `::test_unknown_source_and_na_columns`；S 样本 1/7（N/A 不写 0，含完整性/分母列） | ⬜ |
| REP-7 | 导出使用固定快照并可安全取消 | 8.2, 8.4 | T `test_export.py` | ⬜ |
| REP-7.1 | 导出期间继续编辑 | 8.2 | T `::test_snapshot_frozen_during_edit` | ⬜ |
| REP-7.2 | 取消覆盖已有报表 | 8.4 | T `::test_cancel_keeps_original`（`ExportCancelled` + 原子发布） | ⬜ |
| REP-8 | 统计负担有界且降级透明 | 3.2, 3.3, 9.4 | T `test_store.py`；P `reports/correction_metrics_*/perf.md` | ⬜ |
| REP-8.1 | 持续拖框 | 4.5, 9.4 | P 9.4 基准（S 样本 3 做 300 框拖拽；主线程 p95 ≤ 5 ms） | ⬜ |
| REP-8.2 | 后台积压超出可处理能力 | 3.2, 3.3 | T `::test_queue_saturation_degrades`（不无限增长、不静默丢失、编辑不受阻） | ⬜ |

---

## 5. `annotation-work-timing`（9 R / 19 S）

| ID | Requirement / Scenario | tasks.md | 未来验证证据 | 现有覆盖 |
| --- | --- | --- | --- | --- |
| TIM-1 | 启用后的时间状态可见 | 6.1, 6.2, 7.1 | T `test_timing.py`（`WorkClock`）、`test_correction_panel.py` | ⬜ |
| TIM-1.1 | 启用前图片已打开 | 6.2, 5.5 | T `::test_enable_does_not_backfill`（不补计打开时长） | ⬜ |
| TIM-1.2 | 图片加载尚未就绪 | 6.2 | T `::test_not_ready_state`（未就绪不计前台） | ⬜ |
| TIM-2 | 前台审图不依赖输入频率 | 6.1, 6.2 | T `test_timing.py`（假时钟推进无输入） | ⬜ |
| TIM-2.1 | 静止审图 | 6.1 | T `::test_idle_review_still_counts` | ⬜ |
| TIM-2.2 | 在标签弹窗中判断类别 | 6.2 | T `test_correction_panel.py::test_dialog_counts_as_foreground` | ⬜ |
| TIM-3 | 暂停和系统中断停止处理计时 | 6.3 | T `test_timing.py` | ⬜ |
| TIM-3.1 | 暂停后返回应用 | 6.3 | T `::test_explicit_pause_survives_background` | ⬜ |
| TIM-3.2 | 休眠或锁屏 | 6.3 | T `::test_sleep_gap_not_counted`（恢复后新片段） | ⬜ |
| TIM-4 | 长时间无输入只产生待确认空闲提示 | 6.4 | T `test_timing.py`、`test_correction_panel.py` | ⬜ |
| TIM-4.1 | 提示后确认一直在审图 | 6.4 | T `::test_confirm_review_keeps_time` | ⬜ |
| TIM-4.2 | 尚未确认或确认离开 | 6.4 | T `::test_unconfirmed_and_excluded`（原始与调整值分列，不可重复扣除） | ⬜ |
| TIM-5 | 图片和阶段时间不重复归属 | 6.2, 5.5 | T `test_timing.py`、`test_correction_flows.py` | ⬜ |
| TIM-5.1 | 切图后返回 | 6.2 | T `::test_switch_back_resumes_without_double` | ⬜ |
| TIM-5.2 | 取消切图 | 5.2, 6.2 | T `::test_cancel_navigation_no_target_time` | ⬜ |
| TIM-6 | 推理等待与前台处理不叠加 | 6.5 | T `test_timing.py` | ⬜ |
| TIM-6.1 | 后台预测时继续修正 | 6.5 | T `::test_parallel_inference_not_summed`（20s+20s ≠ 40s） | ⬜ |
| TIM-6.2 | 预测阻塞编辑 | 6.5 | T `::test_blocked_wait_separate`（阻塞不计前台人工） | ⬜ |
| TIM-7 | 保存和丢弃不清除已花费时间 | 6.6, 5.2 | T `test_timing.py`、`test_correction_flows.py` | ⬜ |
| TIM-7.1 | 丢弃修改 | 5.2 | T `::test_discard_keeps_time` | ⬜ |
| TIM-7.2 | 自动保存多次 | 5.1, 6.6 | T `::test_repeated_autosave_no_double_count` | ⬜ |
| TIM-8 | 明确完成停止计时且继续处理有显式边界 | 5.5, 6.1 | T `test_correction_flows.py`；S 样本 7 `complete_then_browse` | ⬜ |
| TIM-8.1 | 完成后留在画面浏览 | 5.5 | T `::test_browse_after_complete_no_time` | ⬜ |
| TIM-8.2 | 完成后继续修正 | 5.5 | T `::test_continue_restarts_without_backfill` | ⬜ |
| TIM-8.3 | 完成后开始复核 | 5.5 | T `::test_review_phase_separate` | ⬜ |
| TIM-9 | 异常恢复不虚构中断时间 | 6.6, 3.5 | T `test_timing.py`、`test_recovery.py` | ⬜ |
| TIM-9.1 | 崩溃后重开 | 6.6, 3.5 | T `::test_crash_gap_marked`（停机不计、尾段缺口非估算） | ⬜ |
| TIM-9.2 | 系统时间回拨 | 6.3, 6.6 | T `::test_clock_rollback_no_negative`（单调时钟、无负时长） | ⬜ |

---

## 6. 既有定向测试基线（任务 1.4 要求记录）

### 6.1 与本变更直接相关的现有测试

| 文件 | 用例数 | 内容 | 与本变更的关系 |
| --- | --- | --- | --- |
| `tests/test_labeling/test_correction_metrics_gate.py` | 2 | `test_direct_entry_reports_pending_instead_of_missing_import`、`test_actual_workflow_menu_disables_unfinished_statistics`：统计入口"开发中"提示、工作流菜单项禁用且画布/复核/Inspector 项仍启用 | **唯一直接相关**。属**回归锚点**：功能落地后这两个断言必然变化（入口将从禁用改为可用），须由任务 7.1 同步改写，**不能当作功能验收证据** |
| `tests/test_settings/test_schema.py` | 7 | `test_field_count` 断言 151 字段，其中含 `shortcuts.open_correction_metrics` | **回归锚点**：任务 7.1 新增设置项会改变字段数，必须同步更新该断言 |
| `tests/test_canvas/test_rectangle_preview_overlap.py` | 多个 | `dirty_host` 以 `correction_metrics=None` 构造 | **兼容锚点**：证明统计关闭时画布编辑/脏标记/保存路径不受影响（REP-1.1 间接证据） |

### 6.2 与名字相近但实际无关的现有测试（避免误判覆盖）

| 文件 | 用例数 | 实际内容 | 结论 |
| --- | --- | --- | --- |
| `tests/test_labeling/test_label_widget_metrics.py` | 12 | 全部是**标签控件/字体度量**：`_measure_text_width`、标签列表文本、锁定图标（`test_locked_item_uses_svg_icon`）、复核状态圆圈、窗口标题 checked、右键锁定、画布锁定时复选框 | **不覆盖**修正成本统计任何 Scenario。"metrics" 指文字/控件度量，非 correction metrics。其中 3 个锁定相关用例可作为样本 5 的 GUI 回归锚点 |
| `tests/test_dense_review/test_samples.py` | 6 | 密集复核合成样本 manifest 校验 | **方法学先例**（任务 1.3 生成器设计即沿用其约定），不覆盖本 spec |

### 6.3 基线运行记录

| 项 | 值 |
| --- | --- |
| 执行环境 | Bash 可用，但 **PyQt6 未安装**（`import anylabeling` 因 `PyQt6` 失败）→ **本会话无法执行任何 pytest / GUI 测试** |
| 已做的替代校验 | 用 `importlib` 直接加载 `anylabeling/services/correction_metrics/core.py`（仅标准库），实测 `snapshot()/differences()`：样本 2 主变体 `30/30/2/2/5/4/10/20`、样本 4 等价重写 `G=0` 与 1px 拖边 `G=1`、样本 6 转换 `scope_changes=1`、样本 1 零分母 `None`、样本 5 锁定快照相等、样本 9 `shape-identity-conflict` —— 全部与设计一致 |
| 仓库测试状态 | `python -m pytest tests/test_labeling/test_correction_metrics_gate.py -q` → `ImportError while loading conftest`：`tests/conftest.py:29 from PyQt6 import QtCore, QtWidgets` → `ModuleNotFoundError: No module named 'PyQt6'`。已探测 5 个解释器（3.14 / 3.13 / 3.11 / 3.9-32 / Miniconda 3.8）**均无 PyQt6**，故本环境无法运行仓库任何 pytest 用例（包括既有 gate 基线） |
| 文档自检 | 12 项自动检查全绿：标注字段集与顺序 == `Shape.KEYS`(12)、4 点矩形与 ID 正则、manifest schema 与 `ai_count=3`、15 张变体表 `F / modified / unchanged` 自洽、BASE/EVT/REP/TIM 场景编号完整、33 R / 69 S = 102 行无重复遗漏、样本→场景引用全部可解析、8 类样本 key 与 10 个 scene 段落齐备 |
| 建议基线命令 | `python -m pytest tests/test_labeling/test_correction_metrics_gate.py tests/test_settings/test_schema.py tests/test_canvas/test_rectangle_preview_overlap.py -q`（单条、定向、非全量） |
| 已知既有失败 | 未获取（无运行环境）；文档 `docs/custom_changes/2026-11-03-correction-cost-statistics.md:7` 记载"门控的两个回归用例已通过" |
| 记录位置 | 任务 10.2 的 `verification.md` 须登记：命令、环境、通过/失败/跳过/未运行四类计数，并**区分既有失败与新增失败** |

> 任务 1.4 的"区分既有失败与新增失败"落地方式：新增测试目录首跑时以 `git stash` 与否两态对比不现实，
> 建议改为**白名单基线法**——先在未改动工作区记录上述 4 个文件的通过用例名清单（基线 JSON），
> 之后每轮只比对"基线内新增失败"与"基线外新用例失败"两类，写入 `verification.md`。

---

## 7. 缺口清单（68 条 TODO 的归类）

| 缺口类别 | 条目 | 主责任务 | 前置条件 |
| --- | --- | --- | --- |
| 纯逻辑：身份/净差异/事务 | BASE-1.1/1.2/2.2/8.1/8.3、EVT-1.1/1.2/2.1/2.2/3.1/3.2/4.1/4.2/7.1/7.2 | 2.2–2.6 | — |
| 纯逻辑：来源与预测 | BASE-3.1/3.2/4.1/4.2/5.1、EVT-5.1/5.2、BASE-2.1 | 4.1–4.3 | **GAP-2（逐对象来源）**、**GAP-1（source 维度计数）** |
| 纯逻辑：类别体系 | EVT-6.1/6.2/6.3 | 2.5, 4.6 | 类别版本与映射 |
| 存储/恢复/故障 | BASE-6.1/7.1/7.2、REP-8.2、EVT-4.1（持久化侧） | 3.1–3.5, 5.1–5.2 | — |
| 汇总/面板/导出 | REP-1.2/2.1/2.2/3.1/3.2/3.3/4.1/4.2/5.1/5.2/6.1/6.2/7.1/7.2、EVT-8.1/8.2 | 7.1–7.5, 8.1–8.5, 5.3–5.6 | 面板/报表/导出实现 |
| 计时 | TIM-1.1 … TIM-9.2（19 条） | 6.1–6.6, 5.5 | `WorkClock` 假时钟测试 |
| 性能/人工 | REP-8.1、任务 9.4/9.5 | 9.4, 9.5 | 固定硬件、两位使用者 |
| 回归（已有锚点需改写） | REP-1.1 | 7.1, 9.2 | 功能落地后改写 gate 测试 |

### 7.1 需要先修数据模型才能通过的断言（阻塞项）

1. **GAP-2 逐对象来源缺失**：`core.initialise_state()` 只存轮次 `origin` + `predicted_ids`，
   无 `object_origins` → BASE-3.1/3.2 的"保留对象各自来源"无法断言（样本 8/10 只能断言 `ai_count`）。
2. **GAP-1 事务无 source 维度**：`report_row()` 只有 `operation_counts`（按 kind），
   无按 `source` 的计数 → EVT-5.1/5.2、EVT-8.1 的"人工 vs AI 可区分"需读事件表或补字段。
3. **GAP-3/5 缺失态字段未统一置 N/A**：`saved is None` 时 `final_count` 仍等于 `baseline_count`，
   `unsupported_count/scope_changes` 未置空 → REP-2.1 的"不将草稿显示为已交付"存在显示风险。
4. **GAP-4 details 编辑语义未定义**：改 `description` 会产 1 事务但净差异 `unchanged` → 样本 5 `description_only` 待 spec 澄清。

（详见 `.local/stage/team/samples-design.md` §7。）

---

## 8. 覆盖 → 任务 反查（tasks.md 各任务应产出哪些证据）

| tasks.md | 覆盖的 spec 条目数 | 主要条目 |
| --- | --- | --- |
| 2.1 | 6 | BASE-2, BASE-2.1, BASE-3, BASE-3.1, BASE-3.2, EVT-8 |
| 2.2 | 4 | BASE-1, BASE-1.2, BASE-8, BASE-8.1 |
| 2.3 | 5 | BASE-1.1, EVT-3, EVT-3.1, EVT-3.2, EVT-1.1 |
| 2.4 | 6 | EVT-1, EVT-1.2, EVT-2, EVT-2.2, EVT-3.2, EVT-4 |
| 2.5 | 6 | EVT-3.1, EVT-6.2, EVT-6.3, EVT-7, EVT-7.1, EVT-7.2 |
| 2.6 | 5 | BASE-4, BASE-8, BASE-8.3, REP-2.2, EVT-8 |
| 3.1–3.5 | 9 | BASE-1.2, BASE-2.2, BASE-4.1, BASE-5, BASE-6.1, BASE-7.1, BASE-8.1/8.2, REP-8.2, TIM-9 |
| 4.1–4.7 | 14 | BASE-2.1/3.1/3.2/4.2/5.1、EVT-1.1、EVT-2.1、EVT-4.1/4.2、EVT-5.1/5.2、EVT-6.1、REP-8.1 |
| 5.1–5.6 | 11 | BASE-6, BASE-7, REP-2.1、REP-3.1/3.2/3.3、REP-4.1/4.2、TIM-5.2、TIM-7.1/7.2、TIM-8.1–8.3 |
| 6.1–6.6 | 19 | 全部 TIM 条目 |
| 7.1 | 4 | REP-1, REP-1.1, REP-1.2, TIM-1 |
| 7.2–7.5 | 8 | REP-2, REP-2.1/2.2、REP-4/5/5.1/5.2、EVT-8 |
| 8.1–8.5 | 8 | BASE-6/6.2、EVT-7、REP-6.1/6.2、REP-7.1/7.2 |
| 9.1–9.6 | 全部 69 | 总体验证（任务 9.1 与样本设计共同构成主回归网） |
| 10.2 | 全部 102 | `verification.md` 需求→证据汇总（最终台账） |

---

## 9. 使用说明

1. 本表是**计划**，不是通过证据；任务 10.2 的 `verification.md` 必须逐条把"TODO"替换为
   具体用例名/命令/结果（通过、失败、跳过、未运行四态），未运行项不得勾选。
2. 每条 Scenario 落地时，测试用例名建议直接包含编号（如
   `test_evt_2_1_batch_relabel_one_tx`），便于反向猜测覆盖情况与 CI 报告对齐。
3. 样本（任务 1.3）只覆盖其中 19 条 Scenario（见 `samples-design.md` §5），其余用例必须自建内存对象，
   不得依赖样本目录（保持纯逻辑测试的快速与独立）。

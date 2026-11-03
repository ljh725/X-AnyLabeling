# 第二轮修正独立复核

日期：2026-11-02（Asia/Shanghai）。范围：当前密集复核工作区的撤销顺序修正及前两轮已复现问题回归。

## 结论与证据

**上轮发现的撤销目标顺序错误已修复，第二轮仍有两处可复现的撤销边界问题，暂不判定撤销契约完整通过。**

- 当前 `tests/test_dense_review` 与前两轮独立探针合跑：**75 passed in 47.37s**，见 `round2.xml`。
- 新增 `test_round2_edges.py`：**2 failed in 3.05s**，见 `round2-edges.xml`。失败为行为断言与产品方法抛出的异常，不是临时目录或DLL环境错误。
- 上轮“手动把框移回原位置后，撤销误优先处理旧确认”的状态模型及主窗口探针均已通过。
- 早先的卡片旧裁图、全图往返倍率与连续审核撤销探针也通过本次合跑。
- 本轮使用既有Python环境、Qt离屏模式和临时样本；没有修改应用代码或任务勾选，没有执行真实屏幕减负及性能验收。

## R2-1 — [P2] 撤销两次移框后没有恢复原有确认

位置：`anylabeling/services/dense_review/session.py::sync_shapes`（约222、245行）及 `undo_after_canvas`（约1058行）。

复现序列：

1. 对象a处于原位置，确认其类别和框。
2. 将框右移10像素并提交，再手动左移10像素并提交。
3. 按正确顺序撤销左移和右移两个编辑。

预期：回到第1步之后的完整状态——原位置及类别/框已确认；随后再撤销才应撤回第1步确认。

实际：框虽回到原位置，类别/框仍为未确认。新增探针的 `confirmed_both()` 为false。现有新增测试仅验证这时下一步撤销类型为progress，未检查应当恢复的确认值。

原因：操作顺序已经增加独立历史记录，但审核状态快照仍按内容哈希唯一存放。手动移回原位置时，后来的未确认状态覆盖了相同哈希对应的早期已确认状态；撤销时无法取回该历史位置的真实状态。

建议：将编辑前的审核状态绑定到具体历史事务/版本，不能仅用内容哈希唯一定位。相同坐标、标签内容在不同时间可以对应不同确认与查漏状态；应同时恢复状态和值，而不只是恢复下一步撤销类型。

探针：`test_undo_both_moves_restores_original_confirmation`。

## R2-2 — [P2] 审核事务栈与快照栈容量不一致导致空栈异常

位置：`session.py::__init__` 与 `next_undo_kind` / `undo_progress`（约1022–1040行）。

复现：对同一对象交替标记疑难和解除疑难，共51次真实状态变化；连续撤销50次，然后再次触发撤销。

预期：若保留上限是50次，此时应停止提供审核撤销；若继续提供，必须存在对应快照。

实际：`can_undo_progress()`仍返回true，随后 `undo_progress()` 执行 `_progress_undo.pop()` 抛出 `IndexError: pop from an empty deque`。主窗口使用同一判定选择撤销入口，因此会把没有快照的事务暴露为可撤销操作。

原因：`_progress_undo`最多保留50项，而 `_history`最多保留100项；快照淘汰后，对应progress事务仍存在。当前可撤销检查未验证匹配快照。

建议：以统一历史条目持有快照，或同步淘汰事务与快照并校验匹配；不能仅捕获空栈异常而保留失配历史。应补充达到历史上限和审核/编辑混合上限的测试。

探针：`test_progress_history_limit_does_not_expose_missing_snapshot`。

## 可复现命令

项目根目录执行，basetemp使用新的临时目录而非业务数据目录：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_dense_review reports/dense_review_audit_20261102/test_audit_probes.py reports/dense_review_audit_20261102/test_fix_review_edges.py -q --color=no -p no:cacheprovider --basetemp reports/dense_review_audit_20261102/round2-rerun-temp
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest reports/dense_review_audit_20261102/test_round2_edges.py -q --color=no -p no:cacheprovider --tb=short
```

本报告保留此前修正已通过的结论，同时指出更完整撤销序列的剩余问题；不扩大到尚未验证的性能、人工使用效果或整个OpenSpec最终验收。

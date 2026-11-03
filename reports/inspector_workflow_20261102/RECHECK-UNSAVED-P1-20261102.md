# 历史恢复忽略未保存标注：修复复核

日期：2026-11-02。本轮只核对修复和执行定向测试，未修改应用代码或任务状态。

## 结论

此前 P1 的复现场景已通过，未发现该场景仍恢复为 CURRENT 的问题。

修复路径：Inspector 恢复报告时取得当前画布内存快照，传入 `verify_report_context(memory_files=...)`；核验按规范化对象内容比较内存和历史快照。当前未保存内容不一致时记录 pending_files，界面保留 PENDING_RECHECK；磁盘内容变化仍记录 STALE，不能因内存与报告一致而覆盖磁盘变化。

核对位置：
- `anylabeling/views/labeling/inspector/dialog.py:948`：采集并传递当前内存快照。
- `anylabeling/services/inspection/verification.py:59`：未保存内容差异判定。
- `anylabeling/views/labeling/label_widget.py:4063`：快照来自当前文档，unsaved 取当前 dirty 状态。

## 测试

执行原独立复现用例 `test_restore_must_respect_unsaved_canvas_changes`：先加载磁盘报告为 CURRENT，移动当前框且不保存，确认 PENDING_RECHECK，再恢复同一报告；仍保持待复查，断言通过。

同时运行历史核验单元测试与 Inspector 界面测试，涵盖匹配内存不误报、未保存变化、磁盘变化优先、配置变更、缺失清单及历史恢复。

结果：**17 passed**。证据：`recheck-unsaved-p1-v2.xml`。

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe' -m pytest tests/test_inspection/test_verification.py tests/test_inspection/test_inspector_dialog.py reports/inspector_workflow_20261102/test_recheck_history_unsaved.py -q --tb=short --color=no -p no:cacheprovider --basetemp reports/inspector_workflow_20261102/recheck-unsaved-p1-v2-temp --junitxml=reports/inspector_workflow_20261102/recheck-unsaved-p1-v2.xml
```

该结论限于本次历史恢复 P1 及上述相关回归，不代表整个 OpenSpec 变更的全部实施与人工验收完成。

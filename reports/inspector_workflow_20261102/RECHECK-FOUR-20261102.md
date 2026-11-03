# 四项发现的修复复核

日期：2026-11-02。本轮仅复核，未修改生产代码或任务状态。

## 结论

| 上轮发现 | 本轮结果 |
| --- | --- |
| 删除一个对象却删除整对 | 原复现场景通过；删除集合现取画布选中且未锁定的问题对象 |
| 恢复历史报告不验证当前内容 | 磁盘标注变更场景通过，但未保存画布修改仍被忽略，修复不完整 |
| 旧绑定覆盖新选方案 | 原复现场景通过；同项目开始运行尊重当前选定方案 |
| 清单读取失败仍显示完成 | 原复现场景通过；请求数和失败数正确，返回部分完成 |

## 仍需修复：[P1] 历史恢复忽略未保存标注

位置：`anylabeling/views/labeling/inspector/dialog.py:948`，以及 `anylabeling/services/inspection/verification.py:52`。

恢复历史报告时，核验函数只通过 `load_file_snapshot()` 读取磁盘，没有接收当前已提交但尚未保存的画布内容。复现顺序：

1. 生成磁盘版本检查报告，恢复后机器状态为 CURRENT。
2. 在当前画布移动相关框并标 dirty，发送正常 shape_moved 编辑通知，问题正确变为 PENDING_RECHECK。
3. 尚未保存，重新加载同一历史报告，机器状态又成为 CURRENT。

这使旧输入的检查证据对已经修改的当前标注重新生效。应以同一文件当前内存快照核验；无法核验时显示过期/待复查，或要求先保存/放弃修改后恢复，不能只根据旧磁盘内容认定有效。

## 测试证据

- `tests/test_inspection` 当前 75 项通过；首次联合执行为 78 passed / 1 failed，失败来自旧探针要求 `manifest.errors` 非空的内部断言。实现已将坏尺寸保留为 error 文件快照，因此调整该探针以支持两种错误表示，并增加 requested_files=2、failed_files=1 断言；这是测试前置条件更新，不是修改应用逻辑。
- 更新后的四个原始复现场景：**4 passed**。
- 新增未保存画布修改边界：**1 failed**，明确失败于恢复后 CURRENT，本轮证据见 `recheck-four-final.xml`。

复现文件：`test_review_probes.py`、`test_recheck_history_unsaved.py`。

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe' -m pytest reports/inspector_workflow_20261102/test_review_probes.py reports/inspector_workflow_20261102/test_recheck_history_unsaved.py -q --tb=short --color=no -p no:cacheprovider --basetemp reports/inspector_workflow_20261102/recheck-four-final-temp --junitxml=reports/inspector_workflow_20261102/recheck-four-final.xml
```

再次运行请使用新的 basetemp 与结果文件名以保留证据。以上仅核验这四项问题及其直接边界，不代表整个 55 项实施任务通过验收。

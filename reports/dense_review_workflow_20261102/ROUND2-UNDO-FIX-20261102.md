# 第二轮撤销边界修复

日期：2026-11-02（Asia/Shanghai）。范围：独立复核 R2-1、R2-2，以及前两轮已复现问题回归。

## 修复

- **R2-1**：`session.py` 的每条内容历史保存本次编辑前的完整 `ReviewState`。撤销从最近的内容事务取回对应状态；哈希仅用于匹配画布恢复的内容，不再作为审核快照的唯一键。相同坐标和类别在不同历史位置可分别保留已确认和未确认状态，查漏、批次、当前对象和区域游标也随快照恢复。
- **R2-2**：移除独立的 `_progress_undo` 和 `_content_states` 存储。审核与内容事务直接持有各自快照，共用原动作历史的100条上限，事务与快照同时淘汰。连续审核超过50次仍可撤销，最多保留最近100条审核/编辑事务；耗尽后 `can_undo_progress()` 和 `undo_progress()` 都返回 false。
- 画布撤销未改变审核内容哈希时，保留已有内容事务，避免仅显示样式的撤销消耗更早的内容编辑。

本次修改服务会话、状态模型/主窗口回归测试及本功能记录。原有未提交改动保留；不修改真实业务标注。现有画布仍无 redo，任务3.6继续保持未完成。

## 回归覆盖

- 两次手动移框再依序撤销：逐次比较完整审核 payload，验证原有确认、空间查漏和流程完成恢复；第三次撤销才撤回确认。
- 主窗口通过实际 `undo_shape_edit()` 路径验证同一顺序及确认值。
- 连续50/51/99/100/101/151次真实审核变更：逐次验证快照值，达到100条上限后不再提供审核撤销。
- 130条审核/编辑交错历史：在重复坐标、不同疑难状态间撤销最近100条，每次完整状态和撤销类型一致。
- 画布内容未变的撤销保留内容历史；前两轮旧裁图、全图倍率及连续审核探针继续通过。

## 实测证据

环境：既有 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，Qt 离屏，项目报告目录下独立临时样本。受沙箱 DLL 加载限制，测试使用同一环境在沙箱外执行；初次沙箱收集失败不计入行为结果。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 修改前原 R2 探针 | **2 failed in 2.80s**，确认值断言及空 deque 异常均复现 | [baseline XML](../dense_review_audit_20261102/round2-fix-baseline.xml) |
| 修改后定向状态、主窗口及原 R2 探针 | **30 passed in 2.76s** | [focused XML](../dense_review_audit_20261102/round2-fix-focused.xml) |
| 密集复核测试与三轮独立探针合跑 | **85 passed in 44.80s** | [regression XML](../dense_review_audit_20261102/round2-fix-regression.xml) |
| 三个修改的 Python 文件 | Black（79列）、flake8（复杂度18）通过 | 本轮命令输出 |

完整合跑命令（项目根目录）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_dense_review reports/dense_review_audit_20261102/test_audit_probes.py reports/dense_review_audit_20261102/test_fix_review_edges.py reports/dense_review_audit_20261102/test_round2_edges.py -q --color=no -p no:cacheprovider --tb=short --basetemp reports/dense_review_audit_20261102/round2-fix-regression-temp --junitxml reports/dense_review_audit_20261102/round2-fix-regression.xml
```

本轮未进行真实屏幕减负、性能门槛或两位使用者试用验收，不据此宣称完整功能验收通过。

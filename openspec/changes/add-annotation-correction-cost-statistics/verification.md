# 修正成本统计：验证记录

- 变更：`add-annotation-correction-cost-statistics`
- 当前状态：**第 1 批（实施基线 / 数据契约与纯逻辑 / 本地存储）已完成并验证**；业务 UI、Qt 接入、汇总与导出界面未实施，功能对用户仍不可用。
- 更新日期：2026-11-10（Asia/Shanghai）

## 1. 批次总览

| 批次 | 范围 | 状态 | 证据 |
| --- | --- | --- | --- |
| 第 1 批 | tasks.md 1.2–1.4、2.1–2.6、3.1–3.5 | 已完成，含 3 条缺陷修复；少量子项保留 | [implementation-batch1-20261110.md](implementation-batch1-20261110.md) |
| 第 2 批 | 4.x 预标注与编辑接入、5.x 保存/完成状态、6.x 计时 | 未开始 | — |
| 第 3 批 | 7.x 界面、8.x 导出、9.x 回归与性能、10.x 交付 | 未开始 | — |

## 2. 自动化验证（第 1 批）

环境：Windows + 项目 conda 环境 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`（Python 3.12.12、PyQt6 已装）；离屏 `QT_QPA_PLATFORM=offscreen`。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 本批新增单元测试 | `python -m pytest tests/test_correction_metrics -q -p no:cacheprovider` | **64 passed**（0 failed / 0 skipped / 0 xfail），0.92 s |
| 设置 schema 相邻回归 | `python -m pytest tests/test_settings/test_schema.py -q` | 7 passed |
| 统计菜单 gate 相邻回归 | `python -m pytest tests/test_labeling/test_correction_metrics_gate.py -q` | 1 passed + 1 `ERROR at setup`（沙箱 `tmp_path` ACL 拒绝，见 §4） |
| OpenSpec 结构校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | 见 §5 |

测试包：`tests/test_correction_metrics/`（Qt-free，64 用例），覆盖 2.3 净差异、2.4 计数与幂等、2.5 类别映射、2.6 范围与完整性、3.1–3.3 存储与降级、3.4–3.5 检查点与恢复，以及本批 M1/M3/M4 修复的回归。

## 2.1 提交后复跑（green gate）

- 提交：`e5748a9c`（第 1 批实现与文档），工作区 0 项待提交。
- 命令：`pytest tests/test_correction_metrics -q --tb=short --color=no -p no:cacheprovider`
- 结果：**64 passed in 0.96 s**；连续第二次重跑 `exit code 0`。
- 说明：该复跑发生在所有实现改动之后，用于确认提交内容与验证结果一致。

## 3. 需求到证据

四份 spec 共 33 Requirement / 69 Scenario，逐条映射见 [scenario-coverage.md](scenario-coverage.md)。第 1 批后：

| spec 目录 | Requirement | Scenario | 本批后自动化覆盖 |
| --- | ---: | ---: | --- |
| `annotation-correction-events` | 8 | 17 | 净差异、计数、撤销、类别映射等核心 Scenario 有用例 |
| `annotation-correction-baseline` | 8 | 16 | 身份、起点来源、保存检查点、恢复与外部修改有用例 |
| `annotation-correction-reporting` | 8 | 17 | 仅 `exclusion_reasons`/`outcome`/`density_groups` 逻辑层有用例；界面与 CSV 未实施 |
| `annotation-work-timing` | 9 | 19 | `WorkClock` 存在但**本批未新增测试**；界面计时未接入 |

`scenario-coverage.md` 中的逐条覆盖状态是第 1 批开始前的快照，本批补齐后未逐条回填，不得据此宣称已覆盖。

## 4. 未完成、未运行与既有失败

- **功能仍不可用**：`views/labeling/correction_metrics/` 缺 `controller.py`/`panel.py`/`report_dialog.py`，`metrics_available()` 恒为假，22 处 `notify_metrics` 记录点空转。因此"能采集成本"目前不成立，本批只证明服务层数据契约与存储可用。
- 未运行全项目测试；只运行上述三组命令。
- 未做：GUI 场景回归（快捷输入、拖动、撤销、自动保存、切图）、保存/数据库/队列/崩溃故障矩阵的 GUI 级注入、性能门槛（30/300 矩形 p95 ≤ 5 ms、10,000 图库首屏 p95 ≤ 2 s、导出取消 ≤ 1 s）、CSV 逐项核对、人工试用与两位使用者对照。
- `tests/test_labeling/test_correction_metrics_gate.py::test_actual_workflow_menu_disables_unfinished_statistics` 在本沙箱 `ERROR at setup`：pytest 以 `0o700` 建临时目录被 ACL 拒绝（`PermissionError: [WinError 5]`）。带 `pytest_tmp777` 插件时会在离屏 `MainWindow` 构造阶段挂起（既有环境问题，见 `openspec/PENDING_TASKS.md` 与 `fix-digit-rectangle-label-save/verification.md`）。这些属于**既有失败**，与本批改动无关，也未计入通过数。

## 5. OpenSpec 结构校验

```text
openspec validate add-annotation-correction-cost-statistics --strict
→ Change 'add-annotation-correction-cost-statistics' is valid
```

## 6. 结论

第 1 批交付的是**可测试的数据契约与本地存储**：净差异、计数、类别映射、范围与完整性判定、版本化 SQLite、有界写入队列、保存检查点与恢复。三条与 spec 冲突的缺陷（来源未知被误判为不可比、预测来源静默丢失、空基线分母为 0）已修复并有回归用例。

本变更**尚未交付可用功能**：UI 接入、计时界面、汇总与导出、性能与人工验收均未完成，`tasks.md` 中未勾选项保持未完成状态，不将本记录视为功能验收通过。

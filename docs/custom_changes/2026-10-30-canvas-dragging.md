# CUSTOM-003：大数据集拖动响应优化

- 分类：原项目交互性能修复；不是新增产品功能。
- 状态：**已实施，补证与验收完成**（2026-10-30；1.3、4.1、4.4、4.5、5.4 均已按证据勾选）。
- OpenSpec：[smooth-canvas-dragging](../../openspec/changes/smooth-canvas-dragging/proposal.md)。方法见 design.md，执行顺序见 tasks.md。
- 依据：[真实PRW定位报告](../../reports/drag_diagnosis_20261029/REAL_DATA_REPORT_20261030.md)（修复前 42.34 ms）；[实施结果与复测数据](../../reports/drag_fix_20261030/REPORT.md)；[全量回归证据](../../reports/drag_fix_20261030/regression/SUMMARY.md)。
- 改动文件：`anylabeling/views/labeling/label_widget.py::show_shape`（去掉全列表遍历）、`anylabeling/views/labeling/widgets/canvas.py::mouseMoveEvent`（合并经确认的移动刷新路径）。
- 新增测试：`tests/test_labeling/test_show_shape_status.py`、`tests/test_canvas/test_drag_refresh.py`、`tests/test_labeling/test_drag_commit.py`。
- 实施结果：无后台拖动中位数 42.34→10.38 ms（第一轮）、44.53→11.27 ms（冻结配置第二轮）；每 100 次移动绘制 200→100 次、`image_list` 读取 200→0 次；1/1000/11792 条目中位数极差 0.27 / 1.95 ms。
- 依赖：现有分阶段加载、矩形迁移交互及对象身份；未回滚这些已存在功能。
- 备份/回退：见 [BACKUP-20261030.md](BACKUP-20261030.md)。代码恢复与标注数据恢复分开；单项撤销按反顺序 revert 实现提交。

## 提交

分支 `codex/smooth-canvas-dragging`（自 `backup/pre-drag-fix-20261030` 建立）：

| 内容 | 提交 |
|---|---|
| 状态栏脱离数据集规模（CUSTOM-003） | `b0df8c11` |
| 合并拖动绘制请求（CUSTOM-003） | `8fa96795` |
| 实施结果、基准产物与台账更新 | `ef6a730d` |
| 回归证据、固定配置复跑与验收结论文档 | 本提交 |

`git log --grep CUSTOM-003` 可复查两个实现提交。撤销时按反顺序 revert：先 `8fa96795`，再 `b0df8c11`；文档提交不影响运行代码。

## 验证摘要

- 新增 21 项测试；放到修复前源码树运行时有 11 项按预期失败（状态栏 7 项全失败、合并绘制 4 项断言失败），说明测试确实约束本次改动。
- 全量回归补证（[SUMMARY.md](../../reports/drag_fix_20261030/regression/SUMMARY.md)）：核心范围修复后 11 failed / 682 passed（9 用例级 + 2 子测试），基线 12 failed / 660 passed（10 + 2）；**仅修复后失败 0 项**，仅基线失败 1 项（`test_brightness_contrast_updates_are_throttled`，负载敏感）。失败并集重复两轮：9 项稳定、1 项间歇。
- 扩展范围（auto_labeling、auto_training、config、models、ppocr、utils、updates、ui_density）两树均 5 failed / 466 passed，失败 node ID 逐条一致。
- 性能补证：第二次对照使用同一冻结生效配置快照 `config_snapshot_20261030.json`（61 键，SHA256 `facd7cfe7dce50bc7eb457caaf3d6977f30ca0dc24eaccb578c965577c7e8ccf`，两树逐字节一致），原第一轮样本未被覆盖；门槛 7 项全通过。
- 人工体验：用户于 2026-10-30 在可见窗口实际拖动并反馈无异常；属人工确认，不等同帧率测量。
- `openspec validate smooth-canvas-dragging --strict` 通过。

## 最终验收结论

| 任务 | 结论 | 依据 |
|---|---|---|
| 1.3 基线可核验失败集合 | 完成 | `regression/core_baseline.log`、`failures_baseline.txt`、`command_fixed.txt` |
| 4.1 全量回归差集与既有/新增/偶发区分 | 完成 | `failure_diff.txt`（仅修复后失败 0 项）、`flaky_matrix.md` |
| 4.2 四条件两轮计时 | 完成（含第二轮） | `summary.md`、`summary_r2.md` |
| 4.3 规模对照与门槛 | 完成（第 0.27/1.95 ms，均 ≤3） | `summary.md`、`summary_r2.md` |
| 4.4 人工体验 | 用户确认无异常 | 本文件与 REPORT.md 记录 |
| 4.5 固定生效配置补跑 | 完成 | `config_snapshot_20261030.json`、`results_*_r2.json` |
| 5.4 最终结论 | 本表 | — |

未覆盖项（不计为通过）：`tests/test_pointcloud`、`tests/test_settings` 在本机离屏环境进程崩溃（access violation），未纳入回归对比，证据与两树复现见 `regression/crash_probe/`。该问题与本功能无关，如需覆盖应另立变更处理离屏兼容性。

## 与旧版说明的偏差

- 实现提交 `8fa96795` 的说明把普通拖动释放笼统写成 `end_move`；实际普通释放走 `mouseReleaseEvent() → store_moving_shape()`（`store_shapes()` + `shape_moved` + `update()`），`end_move()` 用于右键复制/移动提交。两者本次都未改动，代码与结论不受影响，此处更正表述。

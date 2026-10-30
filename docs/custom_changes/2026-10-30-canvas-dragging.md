# CUSTOM-003：大数据集拖动响应优化

- 分类：原项目交互性能修复；不是新增产品功能。
- 状态：**已实施并本机验证**（人工屏幕体验未验收，见下）。
- OpenSpec：[smooth-canvas-dragging](../../openspec/changes/smooth-canvas-dragging/proposal.md)。方法见 design.md，执行顺序见 tasks.md。
- 依据：[真实PRW定位报告](../../reports/drag_diagnosis_20261029/REAL_DATA_REPORT_20261030.md)（修复前 42.34 ms）；[实施结果与复测数据](../../reports/drag_fix_20261030/REPORT.md)。
- 改动文件：`anylabeling/views/labeling/label_widget.py::show_shape`（去掉全列表遍历）、`anylabeling/views/labeling/widgets/canvas.py::mouseMoveEvent`（合并经确认的移动刷新路径）。
- 新增测试：`tests/test_labeling/test_show_shape_status.py`、`tests/test_canvas/test_drag_refresh.py`、`tests/test_labeling/test_drag_commit.py`。
- 实施结果：无后台拖动中位数 42.34→10.38 ms；每 100 次移动的绘制 200→100 次、`image_list` 读取 200→0 次；1/1000/11792 条目中位数极差 0.27 ms。
- 依赖：现有分阶段加载、矩形迁移交互及对象身份；未回滚这些已存在功能。
- 实现提交：见下方“提交”一节（状态栏、绘制各一个提交，均带 CUSTOM-003）。
- 备份/回退：见 [BACKUP-20261030.md](BACKUP-20261030.md)。代码恢复与标注数据恢复分开；单项撤销按反顺序 revert 实现提交。
- 未完成：可见窗口的人工拖动体验与保存重开（tasks 4.4）。离屏处理时间不作为屏幕帧率结论。

## 提交

分支 `codex/smooth-canvas-dragging`（自 `backup/pre-drag-fix-20261030` 建立）：

| 内容 | 提交 |
|---|---|
| 状态栏脱离数据集规模（CUSTOM-003） | `b0df8c11` |
| 合并拖动绘制请求（CUSTOM-003） | `8fa96795` |
| 实施结果、基准产物与台账更新 | 本提交 |

`git log --grep CUSTOM-003` 可复查两个实现提交。撤销时按反顺序 revert：先 `8fa96795`，再 `b0df8c11`。

## 验证摘要

- 新增 21 项测试；修复前源码树运行同一测试集时状态栏 7 项、合并绘制 4 项按预期失败。
- 画布/标注/控件/分阶段加载相关 692 项：修复后 681 通过、11 失败；修复前 660 通过、12 失败，失败集合相同（既有问题，非本次引入）。
- `openspec validate smooth-canvas-dragging --strict` 通过。

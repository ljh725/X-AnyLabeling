# 原始功能修改与迁移记录

此目录单独保存本项目对原始功能的定制记录，供升级、代码迁移和回退参考。它与上游 `CHANGELOG.md` 分开维护。

## 记录约定

- 每项功能一个稳定编号、一份记录；后续修复追加到同一记录，明显独立的变更另建记录。
- 状态明确区分：方案、实施中、已实现待验证、已验证、已回退。方案不得作为已完成修改使用。
- 实施时记录基线提交、实际文件和函数、行为差异、依赖、数据格式影响、验证命令和结果、回退步骤。
- 迁移优先依据函数职责和行为定位；行号仅作辅助。提交后补充提交号或 PR，跨多个提交时逐项列明。
- 不将整个工作区的混合差异作为单项补丁；只归集该功能相关改动。已有未提交改动需要明确依赖和边界。
- 测试未运行、部分通过、失败均如实记录；性能目标与实测结果分开。
- 使用 [记录模板](TEMPLATE.md) 新建记录。后续本定制工作的实现、修复和迁移应同步更新记录及索引。

## 索引

总入口：[截至2026-10-30的功能分类台账](CATALOG-20261030.md) · [实施前备份与恢复](BACKUP-20261030.md) · [相对上游的逐文件清单](inventory/source-files.json)。历史功能按“原功能增强/新增能力”归类，文件是否新增另行记录。

| 编号 | 功能 | 状态 | 记录 |
| --- | --- | --- | --- |
| CUSTOM-001 | 统计总览、标签管理器后台扫描与进度反馈 | 方案，未实施；11-02 已完成真实共享盘诊断 | [修改方案](2026-10-29-dataset-scan-progress.md) · [实测与代码分类](../../reports/tool_scan_diagnosis_20261102/REPORT.md) |
| CUSTOM-002 | 分阶段标注加载、搜索与审核一致性 | 已有实现，历史验证见报告 | [实现归档](2026-10-30-staged-loading.md) |
| CUSTOM-003 | 大数据集拖动响应优化 | OpenSpec方案，未实施 | [修复记录](2026-10-30-canvas-dragging.md) |
| CUSTOM-109 | Inspector 检查与复核工作流 | 实施中，自动化验证通过 | [实施记录](2026-11-02-inspector-workflow.md) |
| CUSTOM-110 | 密集标注复核工作流 | 实施中，自动化验证通过；人工/性能/翻译未完成 | [实施记录](2026-11-02-dense-annotation-review-workflow.md) · [验证](../../openspec/changes/add-dense-annotation-review-workflow/verification.md) · [报告](../../reports/dense_review_workflow_20261102/REPORT.md) |
| CUSTOM-101/103-显示 | 矩形创建与单点拟合预览的共边显示修复 | 已实施，自动化验证通过；真实屏幕验收未完成 | [方案与实施记录](2026-11-02-rectangle-preview-overlap-plan.md) · [验证](../../openspec/changes/fix-rectangle-preview-overlap/verification.md) |
| CUSTOM-010～014、101～108 | 4.2.1上的既有增强/迁移功能 | 已含于历史混合快照，非本轮新增实施 | [完整分类台账](CATALOG-20261030.md) |

## 已有相关材料

[密集标注复核工作流实施记录](2026-11-02-dense-annotation-review-workflow.md)：CUSTOM-110，默认关闭的批次/卡片/空间查漏工作区，顶层 `xanylabeling_dense_review` 进度，类别与框独立确认，新增/删除/撤销和保存恢复。自动化验证通过；人工试用、性能门槛、翻译和训练导出往返未完成。证据见 [OpenSpec 验证](../../openspec/changes/add-dense-annotation-review-workflow/verification.md) 与 [实施报告](../../reports/dense_review_workflow_20261102/REPORT.md)。

[矩形与十字线、拟合预览共边显示调整方案](2026-11-02-rectangle-preview-overlap-plan.md)：CUSTOM-101/103 的后续显示修复，明确创建草稿共线边避让、Shift/Shift+Alt 候选橙色虚线、原框共边局部避让及恢复验证。2026-11-02 已实施并通过自动化验证，见 [验证记录](../../openspec/changes/fix-rectangle-preview-overlap/verification.md)；真实屏幕深浅背景人工验收仍未完成。

[2026-11-02 十字线定位、代码分类与工具卡顿诊断](../../reports/tool_scan_diagnosis_20261102/REPORT.md)：区分原始/个人 beta.4 和当前 4.2.1 的十字线颜色来源；按上游已有文件修改、新增扩展模块、测试工程、生成翻译导出当前代码快照；对 14003 张真实共享盘图片对应标注完成只读分段测量。该次未改运行源码，未实施 CUSTOM-001。

[分阶段标注加载报告](../../reports/staged_annotation_loading/REPORT.md)记录了此前目录加载工作的实现、测量及复核；对应 [OpenSpec 变更](../../openspec/changes/staged-annotation-loading/proposal.md)。本次仅建立引用，没有重新核验或追认其实现状态；迁移时应一并检查该功能与工具扫描的交互。

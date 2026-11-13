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

当前总览：[2026-11-06 项目改动核对](2026-11-06-project-change-audit.md) · [当前相对上游的逐文件清单](inventory/source-files-20261106.tsv)。

历史入口：[截至2026-10-30的功能分类台账](CATALOG-20261030.md) · [实施前备份与恢复](BACKUP-20261030.md) · [历史逐文件清单](inventory/source-files.json)。历史功能按“原功能增强/新增能力”归类，文件是否新增另行记录。历史记录中“未提交”等表述有其当时含义，当前保存状态以最新核对及 Git 为准。

| 编号 | 功能 | 状态 | 记录 |
| --- | --- | --- | --- |
| CUSTOM-001 | 统计总览、标签管理器后台扫描与进度反馈 | 方案，未实施；11-02 已完成真实共享盘诊断 | [修改方案](2026-10-29-dataset-scan-progress.md) · [实测与代码分类](../../reports/tool_scan_diagnosis_20261102/REPORT.md) |
| CUSTOM-002 | 分阶段标注加载、搜索与审核一致性 | 已有实现，历史验证见报告 | [实现归档](2026-10-30-staged-loading.md) |
| CUSTOM-003 | 大数据集拖动响应优化 | 已实施，历史回归与用户体验确认见修复记录 | [修复记录](2026-10-30-canvas-dragging.md) |
| CUSTOM-109 | Inspector 检查与复核工作流 | 11-05 已提交保存；代码/自动化 52/55，人工验收 3 项待做 | [实施记录](2026-11-02-inspector-workflow.md) · [操作说明](../zh_cn/inspector.md) · [验证](../../openspec/changes/archive/2026-11-10-refactor-data-inspector-workflow/verification.md) |
| CUSTOM-110 | 密集标注复核工作流 | 11-05 已提交保存；功能/性能专项有通过证据，人工试用与完整组合回归仍待验收 | [最新实施结果](../../openspec/changes/add-dense-annotation-review-workflow/implementation-20261105.md) · [实施记录](2026-11-02-dense-annotation-review-workflow.md) · [任务](../../openspec/changes/add-dense-annotation-review-workflow/tasks.md) |
| CUSTOM-111 | 修正成本统计 | 代码实施完成、自动化验证通过（任务 37/54）；真实屏幕人工验收与 GUI 性能未完成，变更未归档 | [状态记录](2026-11-03-correction-cost-statistics.md) · [任务](../../openspec/changes/add-annotation-correction-cost-statistics/tasks.md) · [验证](../../openspec/changes/add-annotation-correction-cost-statistics/verification.md) |
| CUSTOM-112～116 | v4.3.0 五项画布能力恢复（工具栏、滚轮导航、三态审核、仅填充透明度、显示参数保持） | 11-05 已提交保存；专项与配置自动联测通过，性能/真实屏幕等验收未全部完成 | [恢复记录](2026-11-04-canvas-controls-restore.md) · [最新实施结果](../../openspec/changes/restore-v430-canvas-controls/implementation-20261105.md) · [验证](../../openspec/changes/restore-v430-canvas-controls/verification.md) |
| CUSTOM-117 | Ctrl + 左键拖拽多选（部分覆盖即选中） | 已验收并提交同步 GitHub（c58e16b6）；41 项交付专项通过，历史 225 项相关回归通过；11-06 用户实测确认 | [实现、修复与交付记录](2026-11-06-marquee-selection.md) |
| 配置持久化修复 | 配置按字段保存、冲突处理、数字绑定/设置/显示保持同步、重启恢复 | 11-05 已提交保存；用户原启动方式的可见交互验收仍待做 | [任务与状态](../../openspec/changes/fix-user-settings-persistence/tasks.md) · [验证](../../openspec/changes/fix-user-settings-persistence/verification.md) |
| 数字矩形标签保存修复 | 弹窗关闭且预选其他类别时数字绑定优先级 | 仅登记任务，尚未实施；不能作为已修复功能 | [任务](../../openspec/changes/fix-digit-rectangle-label-save/tasks.md) |
| CUSTOM-101/103-显示 | 矩形创建与单点拟合预览的共边显示修复 | 11-06 单点拟合按键刷新与小框防跳修复用户验收通过，132 项隔离 Qt 回归通过；原创建/共边完整屏幕验收另见记录 | [方案与实施记录](2026-11-02-rectangle-preview-overlap-plan.md) · [操作说明](../zh_cn/rectangle_point_fit.md) · [验证](../../openspec/changes/fix-rectangle-preview-overlap/verification.md) |
| CUSTOM-101 | 框内单点拟合锁角即时预览与单击确认 | 11-12 单击版已实测，固定对角修订已通过自动化验证 | [实施记录](2026-11-12-point-fit-lock-click.md) · [操作说明](../zh_cn/rectangle_point_fit.md) |
| CUSTOM-101-统一手势 | Shift 单点拟合统一：框外进框锁角、按下捕获/松开提交、无效落点保留锁角、移除 Shift+Alt 同侧角 | 11-13 已验证，独立规格 87 项全部通过，用户确认人工验收通过 | [实施记录](2026-11-12-point-fit-unify-shift.md) · [操作说明](../zh_cn/rectangle_point_fit.md) · [OpenSpec](../../openspec/changes/unify-shift-rectangle-point-fit/proposal.md) |
| CUSTOM-010～014、101～108 | 4.2.1上的既有增强/迁移功能 | 已含于历史混合快照，非本轮新增实施 | [完整分类台账](CATALOG-20261030.md) |

## 已有相关材料

[密集标注复核工作流实施记录](2026-11-02-dense-annotation-review-workflow.md)：CUSTOM-110，默认关闭的批次/卡片/空间查漏工作区，顶层 `xanylabeling_dense_review` 进度，类别与框独立确认，新增/删除/撤销和保存恢复。自动化验证通过；人工试用、性能门槛、翻译和训练导出往返未完成。证据见 [OpenSpec 验证](../../openspec/changes/add-dense-annotation-review-workflow/verification.md) 与 [实施报告](../../reports/dense_review_workflow_20261102/REPORT.md)。

[矩形与十字线、拟合预览共边显示调整方案](2026-11-02-rectangle-preview-overlap-plan.md)：CUSTOM-101/103 的后续显示修复，明确创建草稿共线边避让、Shift/Shift+Alt 候选橙色虚线、原框共边局部避让及恢复验证。2026-11-02 已实施并通过自动化验证；2026-11-04 修复原框几何变化后旧候选未失效的 P2，并补充真实 Canvas 事件与像素回归，见 [验证记录](../../openspec/changes/fix-rectangle-preview-overlap/verification.md)；真实屏幕深浅背景人工验收仍未完成。

[2026-11-02 十字线定位、代码分类与工具卡顿诊断](../../reports/tool_scan_diagnosis_20261102/REPORT.md)：区分原始/个人 beta.4 和当前 4.2.1 的十字线颜色来源；按上游已有文件修改、新增扩展模块、测试工程、生成翻译导出当前代码快照；对 14003 张真实共享盘图片对应标注完成只读分段测量。该次未改运行源码，未实施 CUSTOM-001。

[分阶段标注加载报告](../../reports/staged_annotation_loading/REPORT.md)记录了此前目录加载工作的实现、测量及复核；对应 [OpenSpec 变更](../../openspec/changes/staged-annotation-loading/proposal.md)。本次仅建立引用，没有重新核验或追认其实现状态；迁移时应一并检查该功能与工具扫描的交互。

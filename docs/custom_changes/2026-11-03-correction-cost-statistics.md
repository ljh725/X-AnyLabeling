# CUSTOM-111 修正成本统计

- 状态为部分代码已保存，完整功能实施中。
- OpenSpec 为 [add-annotation-correction-cost-statistics](../../openspec/changes/add-annotation-correction-cost-statistics/proposal.md)。
- 部分服务、计时和入口接入随混合快照 `9673d3b9` 保存，包含在 UI P2 提交 `6b98b76e` 的祖先中。
- 服务文件位于 `anylabeling/services/correction_metrics/`。视图目录已有 hooks、clock_adapter 和 i18n，controller、panel、report_dialog 尚缺，专用功能测试尚缺。
- 当前整理阶段对工作流入口增加可用性门控和开发状态提示，防止调用缺失控制器。该门控的两个回归用例已通过。
- 完整功能的任务按 [tasks.md](../../openspec/changes/add-annotation-correction-cost-statistics/tasks.md) 继续执行。保存快照和基础服务存在不能作为完整功能验收依据。
- 实施前恢复点、文件备份、失败清单和新开发起点见 [开发基线](../version-management/2026-11-03-development-baseline.md) 及 [核验报告](../../reports/baseline_organization_20261103/REPORT.md)。

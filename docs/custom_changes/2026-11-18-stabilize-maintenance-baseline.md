# CUSTOM-125：维护基线规格校正与训练停止复核

- 状态：已验证（规格、证据链接和对照诊断）。
- 功能分类：工程配套。
- 创建及更新日期：2026-11-18（Asia/Shanghai）。
- 起点：维护分支已提交节点 `0e4a223e2b8f74f9c8a9e093643b3fa581d8c293`。
- 工作分支：`codex/4.2.1/stabilize-maintenance-baseline`。本地集成对照 `codex/4.2.1-baseline-organization` 固定于 `a7a9a1048f2eab1e3a0272cd57b5c400becca970`。
- 本地提交：规格与链接 `bc23d674`，诊断和后续提案 `1ef8b148`，以及本台账收尾提交。
- 开工前已有的 `.gitignore`、开发资料及审计输入继续保留在原工作区。

## 问题与目标

使预览主规格与当前 Shift 单点拟合一致，为旧验证页提供可点击证据入口，并确定 Windows 停止静默训练时发生 3 秒等待超限的退出路径。

## 修改位置与方法

- 校正拟合入口、Alt 和橙色实心点。候选虚线、共边避让和预览恢复条款保留。 [主规格](../../openspec/specs/rectangle-preview-rendering/spec.md)
- 补齐七个 Git 跟踪的证据目标。 [归档审计](../../reports/maintenance_baseline_20261117/ARCHIVES.md)
- 在两个固定提交的独立工作树各执行 4 次指定 pytest 节点，保留逐轮证据和复现脚本。 [诊断报告](../../reports/stabilize_maintenance_baseline_20261118/REPORT.md)

## 兼容与数据影响

运行源码、回归断言、标注数据、原 18/18 维护交付和历史 delta 均保持原样。密集复核重设计保持停止。

## 验证

OpenSpec strict 28 项通过，七个目标均存在且由 Git 跟踪，`git diff --check` 通过。训练节点在两侧共 8 次退出 1，均无外层超时。6 次带观测的运行确认终止命令失败后仍等待 5 秒，工作线程约 5.75–5.78 秒才停止。归因为产品停止路径延迟。

工具栏布局、点云、可见训练界面、真实训练和完整 Windows 回归本轮未覆盖。其他回归失败和人工验收边界继续见 [上轮报告](../../reports/maintenance_baseline_20261117/REPORT.md)。

## 迁移与回退

规格和导航可按 `bc23d674` 单独撤销，诊断证据随 `1ef8b148` 保留。训练修复另按后续方案实施，修复经定向验收后才安排完整 Windows 回归。 [后续修复清单](../../openspec/changes/fix-windows-training-stop/tasks.md)

# 2026-11-17 维护候选基线

状态：四步维护已实施，完整回归已结束但未通过；候选不是已验证稳定版。四步唯一任务入口为
[organize-maintenance-baseline](../../openspec/changes/organize-maintenance-baseline/tasks.md)。

## 保存点与授权

沿用 `codex/4.2.1/maintenance-baseline-plan`。方案起点 `8d87a93b`，
执行及方案提交 `aebb1804f2199ca47f342d8f485d37cae0214d8e`；
固定本地标签 `backup/4.2.1-20261117-maintenance-candidate` 指向该完整对象。
候选源码树 `HEAD:anylabeling` 为 `01efe6fe526f49a44353ffcbc5efc5e089a1e77f`。
本轮仅本地分批提交，不推送、不开 PR、不合入。
约定集成目标 `codex/4.2.1-baseline-organization` 当时本地对象
`a7a9a1048f2eab1e3a0272cd57b5c400becca970`，比较为 0 behind / 37 ahead，
不是远端实时状态或合入授权。

开工暂存区为空。其他任务的 `.gitignore`、`docs/development/README.md`、
`docs/development/understand-20261112/`、`reports/openspec_audit_20261117/`
保持原状，不进入本轮提交或备份标签。无本任务未保存源码或新测试。

## 候选保留范围与依赖

相对本地集成分支有 37 个独有提交、58 个生产/测试/脚本文件差异。
主要是密集复核显示解析、画布覆盖层与命中/分组、工作区卡片及原图对照、
会话恢复和偏好配置，以及生成的四语言资源、样本生成器、配套测试。
`resources.py` 为生成物，未手工修改。候选保留现有完整依赖链，
不拆除混合快照，也不回退整个旧文件。

关键依赖：`3b09eefd` 显示解析 → `96e93981` 覆盖层 → 后续一致性修复；
`5d2d3002` 保存依赖 → `a4efb042` 四项修复；`216e903f` 会话恢复 →
`7c6ccff3` 样本证据 → `a9381688` 停止时源码/测试/生成物快照；
`286a43f9` 终止归档和 `8d87a93b` Inspector 用户验收归档均保留。
全部提交可由固定标签及 `git log <集成分支>..aebb1804` 恢复。

停止快照包含缓存、标签避让、候选选择、关联点/裁切、小地图、布局偏好和
快捷键等部分实现；最后任务审计 33/91 不能代表最终代码完成数。
遵守[停止决定](../../openspec/changes/archive/2026-11-17-redesign-dense-review-workspace/archive-decision-20261117.md)，
不恢复原任务，不将五份草案发布为正式契约。

## 验证边界

历史密集复核 304 passed / 842 subtests、画布 750 / 83、设置
90 passed / 1 skipped / 9 subtests、Inspector 217 passed 来自不同阶段，
不能合并成同一候选全绿。最新交接批次 1 failed / 9 passed，缺少
`snapshot_digest`；标注全目录由用户中止。两个 `commit-fit/cancel-fit`
失败在 `7c6ccff3` 也复现。历史原生退出 0xC0000409 不应仅凭单跑消失定责。

本轮将使用 conda `x-anylabeling-cu12`、真实隔离配置、外层硬超时验证，
实际结果统一写入[维护验证报告](../../reports/maintenance_baseline_20261117/REPORT.md)。
真实屏幕、字体/DPI、读屏、性能对照和双人试用仍无完整证据；
Inspector 双屏人工通过依据用户声明，未新增截图。工具栏布局及点云须单列覆盖。

## 后续结论

本轮核心 991 passed / 1 skipped / 107 subtests；工作台合跑 525 passed /
1 failed / 842 subtests；拟合集成修正后 36 passed，旧窗口启动修正后 15 passed。
生产源码树不变，测试修正分别保存于 efb172b9、8d9ab779；后续仅对新参数行换行，AST 相同。
完整 Windows 首轮因旧窗口未建配置会话被硬超时结束，未得完整 JUnit；
原始错误、堆栈、失败和中间原生退出均保留。修正后再执行整组，不以子集通过替代。
候选尚未达到已验证稳定，实际最后结论见维护报告。
候选固定、任务勾选、规格 strict 和归档均不能替代功能验收。

## 最终完整回归

测试保存点 `77f9ced5`，生产树与候选固定标签相同；测试树为
`b33383b8fba80fbbcd2648507a0bde66a212d0c2`，与交付相同。
2679 主用例完整执行，2632 passed / 29 skipped / 18 主用例失败；另 2 子测试失败，
pytest 汇总为 20 failed / 1015 subtests passed，1511.58s，退出码 1，无超时。
工具栏布局与 Windows 点云未跑。修复的是旧测试输入和初始化，未修改业务行为。
11 个符合条件的目录已归档，原密集复核/成本统计/关键点暂停及 P2 缺口保留；
不能将维护完成解释为产品或人工验收全通过。详细失败与本地提交见维护报告及归档审计。

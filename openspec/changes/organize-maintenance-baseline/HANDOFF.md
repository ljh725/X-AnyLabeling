# 维护整理执行交接

状态：四步维护 18/18 已完成；完整回归已结束但有失败，候选未达稳定基线。
执行证据与归档映射见 reports/maintenance_baseline_20261117/，不恢复停止任务。唯一执行清单为 [tasks.md](tasks.md)，方法和边界见 [design.md](design.md)。

## 推荐方式

在当前仓库新开一个 agent 会话，交给它下面的启动指令。只让一个 agent 写文件和提交；可在批次完成后另开一个只读审阅会话。无需同时启动多个实现 agent。

用户已接受四步整理。执行 agent 可按该范围连续执行、维护任务勾选和作本地提交，无需为每一批重复询问。缺少人工验收时保持真实状态；涉及推送、PR、合入、整体回退或重启停止任务时不擅自扩大授权。

## 可直接复制的启动指令

```text
请执行本仓库的维护整理任务，暂停新增功能。

先读根目录 AGENTS.md，再读：
openspec/changes/organize-maintenance-baseline/HANDOFF.md
openspec/changes/organize-maintenance-baseline/proposal.md
openspec/changes/organize-maintenance-baseline/design.md
openspec/changes/organize-maintenance-baseline/tasks.md
以及其中引用的停止归档决定和当前台账。

使用 $openspec-apply-change，目标变更 organize-maintenance-baseline。
沿用 codex/4.2.1/maintenance-baseline-plan 分支，先核对实际 HEAD 和改动归属。
按四步顺序执行；仅在成果和证据满足条目要求时勾选 tasks.md。
本地分批提交，不推送、不开 PR、不合入，不修改 versions/4.2.1。
保留其他任务的未提交文件。先核对暂存区，禁止 git add .。
不开发关键点显示，不恢复已终止的密集复核重设计，不删除备份。
人工验收、失败、挂起和未测均如实保留；不要为清零任务强行归档。
某项受阻时继续独立工作，最后列出具体阻塞、证据和所需决定。
每批更新既有 CUSTOM-124 和版本操作记录，最终报告提交与验证状态。
```

## 执行起点与输入可靠性

- 方案前代码起点：`8d87a93b`；实际执行时读取最新方案提交，登记到版本操作记录。
- 约定集成目标：`codex/4.2.1-baseline-organization`，不是本次自动合入指令。
- 原始 DeepSeek 输入：`reports/openspec_audit_20261117/REPORT.md`，交接时为用户已有未跟踪文件，本方案没有把它纳入提交。换机器执行时不能假定该文件存在；本方案已自包含必要约束，缺失时以任务、源码和版本记录重新核实，不照抄统计。
- 原工作树还包括 `.gitignore`、`docs/development/README.md`、`docs/development/understand-20261112/` 的其他任务改动，保留、不代为提交。
- CUSTOM-118 对应数字键提示条；数字键矩形保存对应 CUSTOM-011。
- 历史 15 个活跃变更 / 32 项未完成不含本协调变更。执行时必须重算。
- 停止任务明确保留部分实现及失败：见 [归档决定](../archive/2026-11-17-redesign-dense-review-workspace/archive-decision-20261117.md)。

## 批次交付格式

每批简要给出：完成的任务编号、改动原因、实际提交号、被测代码修订、命令和结果、保留的失败/未测、下一步。持续证据写在既有台账及本轮报告中，不创建另一个待办系统。

## 可选只读复核指令

```text
请只读复核 organize-maintenance-baseline 本轮已提交批次。
先读 AGENTS.md、design.md 和 tasks.md，再检查实际 Git diff、源任务和证据。
重点检查：是否混入其他工作；是否把勾选/行政关闭写成人工验收；
是否重启停止任务；是否破坏规格依赖、丢场景或历史引用；
测试是否对应同一代码修订；是否越权推送/合入。
只报告可复现的问题、文件位置和修正建议，不修改文件、不创建提交。
```

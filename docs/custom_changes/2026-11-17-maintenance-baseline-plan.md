# CUSTOM-124：维护基线整理与 agent 执行交接

- 状态：实施中；第一步候选已固定，其余按源任务逐项执行。
- 功能分类：工程配套。
- 创建日期、最后更新日期：2026-11-17（Asia/Shanghai）。
- 原始版本与基线提交：X-AnyLabeling 4.2.1，`8d87a93b`。
- 实现提交 / PR：无产品实现；交接方案见本次本地文档提交，无 PR。
- 工作分支：`codex/4.2.1/maintenance-baseline-plan`；约定集成目标：`codex/4.2.1-baseline-organization`，尚未合入。
- 工作区已有修改：其他任务的 `.gitignore`、`docs/development/`，以及用户提供的未跟踪审计报告，均保留。

## 问题与目标

用户接受暂停功能扩展并按四步整理，要求可交给其他 agent 执行。本轮将执行顺序、完成标准、验证要求和授权范围落到现有 OpenSpec，避免只靠会话记忆交接。

## 修改位置与方法

| 位置 | 方法 |
| --- | --- |
| [交接入口](../../openspec/changes/organize-maintenance-baseline/HANDOFF.md) | 可直接复制的执行与只读复核指令 |
| [任务清单](../../openspec/changes/organize-maintenance-baseline/tasks.md) | 四阶段唯一勾选来源；方案建立时全部未勾选 |
| [设计](../../openspec/changes/organize-maintenance-baseline/design.md) | 基线、证据、归档与停止任务边界 |
| [提案](../../openspec/changes/organize-maintenance-baseline/proposal.md) | 整理目标与影响范围 |

## 兼容与数据影响

本轮仅文档交接，不改生产代码、配置、标注数据或资源。协调变更使用 skip_specs，不发明新的产品规格；后续既有产品契约的归档必须单独核对。

## 验证

实际：`openspec validate --all --strict` 为 23 passed / 0 failed；`openspec status --change organize-maintenance-baseline` 显示 proposal/design/tasks 已备齐，specs 按文档协调范围 skipped。检查本轮新文档 9 条本地 Markdown 链接，0 条失效；18 项执行任务全部未勾选。`git diff --check` 通过，提交前核对显式暂存范围。不为纯交接文档重跑 Qt 功能测试；本轮未运行工具栏布局或点云套件。

## 迁移与回退

其他 agent 从 HANDOFF.md 进入并使用 OpenSpec apply 继续。方案按独立文档提交保存，必要时只撤销该提交；不回退原密集复核源码快照，不改版本入口。

## 后续修订

执行四步时在本记录追加实际批次、验证范围和状态；仓库级操作继续登记现有 `docs/version-management/操作记录.md`。

## 批次一：候选固定

执行起点 `aebb1804`；本地固定标签 `backup/4.2.1-20261117-maintenance-candidate`
实际对象 `aebb1804f2199ca47f342d8f485d37cae0214d8e`。
37 个独有提交及停止快照依赖核对见[候选说明](../version-management/2026-11-17-maintenance-baseline.md)。
本批不改生产代码，不运行产品测试；其他任务文件保留。

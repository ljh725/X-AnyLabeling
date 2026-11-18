# CUSTOM-126：退役 Inspector 和 Dense Review

- 状态：方案。
- 功能分类：本地定制退役。
- 创建日期、最后更新日期：2026-11-18（Asia/Shanghai）。
- 起点：`ade2d67c`。工作分支：`codex/4.2.1/remove-inspector-and-dense-review`。
- 集成目标：`codex/4.2.1-baseline-organization`。
- 实现提交 / PR：未实施，无 PR。
- 工作区已有修改：`.gitignore`、`docs/development/` 和用户审计报告由原任务保留。

## 问题与目标

取消两个工作台并保留其他定制、现有标注的数据兼容和项目整理证据。当前代码与历史回退点的比较见[设计](../../openspec/changes/remove-inspector-and-dense-review/design.md)。

## 修改位置与方法

方案包含[提案](../../openspec/changes/remove-inspector-and-dense-review/proposal.md)、九份规格增量及[执行清单](../../openspec/changes/remove-inspector-and-dense-review/tasks.md)。实施先迁出共享写入依赖，再独立移除两个工作台和整理规格。

## 兼容与数据影响

计划保留旧标注扩展、对象身份和三态审核，以及用户数据集中的旧检查和复核材料。普通画布、成本统计、批处理和训练导出按既有契约验证。

## 验证

方案经 `openspec validate --all --strict` 检查，29 项通过。临时副本验证七份规格完整退役、画布规格替换和兼容规格新增的处理顺序，15 份现行主规格通过 strict。产品回归和数据往返检查属于实施阶段任务。

## 迁移与回退

当前分支和移除前节点保留完整历史。实施批次独立提交，回退时核对两项公共接线和后继依赖，按范围撤回。

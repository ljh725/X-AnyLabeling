# CUSTOM-126：退役 Inspector 和 Dense Review

- 状态：已验证退役及旧数据兼容。Windows 全量仍有既有失败，详见验证报告。
- 功能分类：本地定制退役。
- 创建日期、最后更新日期：2026-11-18（Asia/Shanghai）。
- 起点：`ade2d67c`。工作分支：`codex/4.2.1/remove-inspector-and-dense-review`。
- 集成目标：`codex/4.2.1-baseline-organization`。
- 实现提交：`6cba0176` 公用写入迁移，`651177f7` 退役 Inspector，`959a166f` 退役 Dense Review，`4658c66d` 重编资源并清理当前入口文档。
- 工作区已有修改：`.gitignore`、`docs/development/` 和用户审计报告由原任务保留。

## 问题与目标

取消两个工作台并保留其他定制、现有标注的数据兼容和项目整理证据。当前代码与历史回退点的比较见[设计](../../openspec/changes/remove-inspector-and-dense-review/design.md)。

## 修改位置与方法

迁出共享原子 JSON 写入，分批移除两个工作台的动作、后台任务、配置和覆盖层，并重新编译四语资源。普通画布、图片三态审核、即时保存、撤销重做、批处理及统计面板的独立复核计时继续使用既有入口。实施范围见[提案](../../openspec/changes/remove-inspector-and-dense-review/proposal.md)与[执行清单](../../openspec/changes/remove-inspector-and-dense-review/tasks.md)。

九份增量已同步。旧[密集复核](../../openspec/changes/archive/2026-11-18-add-dense-annotation-review-workflow/retirement-20261118.md)和[界面打磨](../../openspec/changes/archive/2026-11-18-polish-inspector-dense-review-ui/retirement-20261118.md)按原任务勾选归档，原增量留存于归档。关键点显示预设的范围收回普通画布，保持暂停。

## 兼容与数据影响

旧工作台偏好和快捷键允许留在用户配置，应用启动后走普通标注。`LabelFile` 继续往返保存已有标注扩展，保留对象身份和三态审核。数据集中的检查报告、规则方案、密集复核配置和进度仍按原样存放。兼容边界见[现行规格](../../openspec/specs/retired-review-data-compatibility/spec.md)。

## 验证

原子写入 33 项通过，退役后定向回归 152 项通过，旧数据往返 3 项通过，四语磁盘和内嵌资源加载通过。Windows 完整范围 2110 通过、30 跳过，14 个失败项均有移除前记录。另跑工具栏布局，两项断言在移除前独立副本同样失败。点云、真实屏幕、真实训练与推理未覆盖。OpenSpec strict 21 项通过。详见[验证报告](../../reports/remove_inspector_dense_review_20261118/REPORT.md)。

## 迁移与回退

完整旧产品可从 `20cba258f6f7fb23cb794c8e9606d537e2d5e9b6` 独立检出。只恢复 Dense Review 时，以 `959a166f` 的反向改动为起点，定向还原密集复核的入口、资源和契约。只恢复 Inspector 时，以 `651177f7` 的反向改动为起点，按仍可用的工作流恢复接线，原交接需单独核对 Dense Review 依赖。两种情况均保留 `6cba0176` 的共享写入，按恢复范围重新生成四语资源并运行受影响测试。

交付提交 `fca3a711` 已推送至 GitHub 的 `codex/4.2.1/remove-inspector-and-dense-review`。2026-11-18 复验后，本地 `codex/4.2.1-baseline-organization` 已快进合入该提交。GitHub 集成分支本轮未推送，未创建 PR。合入起点和复验范围见[版本操作记录](../version-management/操作记录.md)。

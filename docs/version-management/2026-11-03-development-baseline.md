# 2026-11-03 开发基线整理

本次整理由用户授权，覆盖功能状态、恢复点、测试产物和基线回归。DeepSeek 已完成的 Inspector / Dense Review UI 调整纳入当前开发起点。

## 当前起点

| 项目 | 记录 |
| --- | --- |
| UI 开发分支 | `feat/ui-polish-p2` |
| UI 提交 | `6b98b76eefd06e499089fbb2082e18dde98aeea4` |
| UI 前混合快照 | `9673d3b9`，包含原有定制和部分修正成本代码 |
| 本次整理分支 | `codex/4.2.1-baseline-organization` |
| 整理前固定标签 | `backup/4.2.1-20261103-pre-baseline-cleanup` |
| 整理后恢复入口 | `backup/4.2.1-20261103-organized-baseline`，对应本次整理完成提交 |
| 离线完整历史 | `backups/4.2.1-20261103-pre-baseline-cleanup.bundle` |
| 后续整理增量 | `backups/4.2.1-20261103-organized-baseline.bundle`，与完整 bundle 配套使用 |
| 清理前明细 | [inventory-before.json](../../reports/baseline_organization_20261103/inventory-before.json) |
| 本轮验证 | [REPORT.md](../../reports/baseline_organization_20261103/REPORT.md) |

整理分支保留 UI 提交的祖先关系。已有 `versions/4.2.1` 是此前的版本入口，当前开发成果应按本页分支和标签定位。当前开发基线带有下文列出的失败项，验收状态逐项记录。

## 功能状态

| 功能 | 代码与保存状态 | 验证状态 | 待处理 |
| --- | --- | --- | --- |
| Inspector / CUSTOM-109 | 已在快照保存，P2 UI 在 `6b98b76e` | 本轮目录测试 83 通过 | 真实屏幕和真实数据验收、表格搜索等后续需求 |
| 密集复核 / CUSTOM-110 | 已在快照保存，P2 网格与快捷键等在 `6b98b76e` | 本轮目录测试 87 通过 | 真实标注者试用、性能门槛和训练导出往返验收 |
| UI P2 | 网格、详情分节、快捷键、主题图标、中英本地化已提交 | 两目录合计 170 通过；历史离屏截图仍保留 | 日/韩各 413 条新增文案待翻译，真实屏幕验收待做 |
| 矩形交互与预览 | 既有实现和提交已保存 | canvas 578 通过、1 项固定屏幕标签宽度失败 | 该失败单独修复，真实屏幕验收 |
| 共享盘统计扫描优化 / CUSTOM-001 | 诊断和方案已保存 | 历史实测记录可查 | 后台扫描方案尚待实施 |
| 修正成本统计 / CUSTOM-111 | 部分服务与接入代码已收进 `9673d3b9` | 完整工作区尚未接入；本轮只验证入口保护 | controller、panel、report_dialog、专用测试和后续 OpenSpec 任务 |

修正成本统计的工作流菜单显示开发状态并禁用入口。直接调用入口也会显示提示。该保护是本次唯一运行逻辑调整，避免访问缺失控制器时报错。统计实现后应按其完整集成验证恢复入口。

## 测试产物整理

清单共 887 个文件，执行 `git rm --cached` 移出跟踪。本地文件保留，原内容仍可从整理前标签和完整 bundle 恢复。

- 862 个文件属于五个 pytest 运行目录，包含测试生成的图片、JSON、设置和临时链接。
- 15 个文件属于本地实施前文件复制备份。
- 9 个文件属于画布/拖动诊断的本地 profile。
- 1 个文件属于 UI 渲染生成的本地 `.xanylabelingrc`。

具体路径见 [cleanup-paths.txt](../../reports/baseline_organization_20261103/cleanup-paths.txt)。正式报告、验证脚本、离屏截图和代码分类证据共 235 个已跟踪报告文件保留。新增忽略规则限定已识别目录，并将后续测试运行目录统一放入 `.local/pytest/`。报告和测试运行数据分别保存。

## 后续开发顺序

1. 从整理后标签建立统计功能开发分支，沿用该标签对应代码和本轮测试失败清单。
2. 优先补全统计工作区、控制器与实际编辑/保存入口，保留 DeepSeek 的 UI 调整。
3. 根据 OpenSpec 完成专用测试、故障恢复和性能验证，再安排真实标注者试用。
4. 完成项按证据勾选。待验收状态继续保留在功能记录中。

## 恢复方式

优先在新目录恢复，完整 bundle 可独立克隆。

```powershell
git clone --branch feat/ui-polish-p2 D:/X-AnyLabeling-4.2.1/backups/4.2.1-20261103-pre-baseline-cleanup.bundle D:/X-AnyLabeling-recovery
```

恢复整理后版本时，在该新目录导入增量 bundle 后检出整理后标签。

```powershell
git -C D:/X-AnyLabeling-recovery fetch D:/X-AnyLabeling-4.2.1/backups/4.2.1-20261103-organized-baseline.bundle refs/tags/backup/4.2.1-20261103-organized-baseline:refs/tags/backup/4.2.1-20261103-organized-baseline
git -C D:/X-AnyLabeling-recovery switch --detach backup/4.2.1-20261103-organized-baseline
```

bundle 校验与 SHA-256 写在 `backups/4.2.1-20261103-baseline.receipt.json`。这些恢复步骤只还原仓库文件，图片数据集、模型及运行环境需要各自的备份。

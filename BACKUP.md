# 4.2.1 备份节点

## 2026-11-10 整理后备份节点

- 备份日期：2026-11-10（Asia/Shanghai）。
- GitHub 仓库：`ljh725/X-AnyLabeling`。
- 独立分支：`backup/4.2.1-20261110-organized-baseline`。
- 固定标签：`backup/4.2.1-20261110-organized-baseline`（与分支同名，指向同一提交）。
- 精确引用：分支与标签同名时，普通命令会提示 refname 歧义但仍能解析；需要精确定位时用 `refs/heads/backup/4.2.1-20261110-organized-baseline` 或 `refs/tags/backup/4.2.1-20261110-organized-baseline`。
- 开发线：`codex/4.2.1-baseline-organization`，本节点即该分支当时的提交。
- 整理前保存点：`cd26f5f825ffdea5ec8804e9c0bde1f033163fea`（2026-11-06 的 `docs(canvas): record marquee selection delivery and backup`）。
- 目的：在开始 `add-annotation-correction-cost-statistics` 实施前，保存一次**整理过的工作区**——完整的数据/文档归位、OpenSpec 产物入库、未提交但已验证的代码改动一并记录。

本节点相对上一个节点新增：数字键矩形类别保存修复（10/10 任务已完成并验证）、Inspector 问题导航与双屏导航变更、翻译资源重新生成、OpenSpec 归档与主规格、2026-11-10 数据整理文档。任务状态详见 `openspec/PENDING_TASKS.md`。

节点包含应用代码、迁移扩展、资源与翻译、测试、`openspec/` 全部变更与证据、`docs/`、`reports/`、`benchmarks/`。运行日志、Python 缓存、`.tmp/`、`.local/`、`backups/` 与 `.installers/` 仍按 `.gitignore` 排除。

备份同样采用「官方/既有提交为父节点、再提交本地差异」的方式，不是重新压缩源码包，也不替换仓库已有分支或标签。

数据整理本身的范围、归档清单与核对结果见 [2026-11-10 工作区数据整理](docs/version-management/2026-11-10-workspace-organization.md) 与 [整理报告](reports/workspace_organization_20261110/REPORT.md)。

## 2026-10-29 备份节点

- 备份日期：2026-10-29（Asia/Shanghai）。
- GitHub 仓库：`ljh725/X-AnyLabeling`。
- 独立分支：`backup/4.2.1-20261029`。
- 固定标签：`backup-v4.2.1-20261029`。
- 官方基础：`v4.2.1`，提交 `6d250499d2dd81f78723b9217c7a9abf0443ca25`。
- 目的：保存当前工作区，作为后续数据集加载性能修改前的恢复点。

节点包含当前应用代码、迁移扩展、资源和翻译、测试，以及
`benchmarks/` 中的测试脚本/结果和 `reports/` 中的加载方式对比记录。
已有 `.gitignore` 继续排除运行日志、Python 缓存和其他忽略文件。

备份采用官方 4.2.1 提交作为父节点，再提交本地差异；不是重新压缩源码包，
也不替换仓库中已有分支。

## 恢复到单独目录

```powershell
# 2026-11-10 整理后节点
git clone --branch backup/4.2.1-20261110-organized-baseline https://github.com/ljh725/X-AnyLabeling.git D:\X-AnyLabeling-restored-20261110

# 2026-10-29 初始节点
git clone --branch backup-v4.2.1-20261029 https://github.com/ljh725/X-AnyLabeling.git D:\X-AnyLabeling-4.2.1-restored
```

这样会在新目录检出固定备份标签，原工作目录不受影响。
若需要从该恢复点继续修改，可在恢复目录建立新分支：

```powershell
git -C D:\X-AnyLabeling-restored-20261110 switch -c work/from-4.2.1-organized-baseline
```

查看当前节点和相对官方版本的变化：

```powershell
git log -1 backup/4.2.1-20261110-organized-baseline
git diff --stat v4.2.1 backup/4.2.1-20261110-organized-baseline
```

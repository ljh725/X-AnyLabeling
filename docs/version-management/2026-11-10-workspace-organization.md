# 2026-11-10 工作区数据整理

- 状态：已执行并核对；与备份节点 `backup/4.2.1-20261110-organized-baseline` 一同保存。
- 执行前提交：`cd26f5f8`（分支 `codex/4.2.1-baseline-organization`）。
- 详细报告：[reports/workspace_organization_20261110/REPORT.md](../../reports/workspace_organization_20261110/REPORT.md)。

## 做了什么

1. **根目录去杂**：与项目无关的 `_chair_research/`、`_t_jd.py` 归档；空目录 `dsh选型-20261109/` 删除。
2. **开发工具文档归位**：根目录两个 `dsh*.md` 与 `dsh_selection_20261109/` 移入 [`docs/development/dsh/`](../development/dsh/)。
3. **过期本机工作副本归档**：`.local/` 下 4 份已完成任务的工作树（约 1.6 GB）与 `.p2-render/`、`.dsh-asar-out/` 移入 `.local/workspace-archive/20261110/`，逐项原路径与理由见该目录 `manifest.json`。
4. **可重建文件清理**：`.tmp/` 全部、`pytest-of-JJH/`、`.pytest_cache/`、`.pytest-bt/`、`.local/pycache/` 与 60 个 `__pycache__` 删除，共回收约 647.6 MB；pytest 沙箱插件保留到 `.tooling/pytest_tmp777.py`。
5. **未跟踪产物入库**：OpenSpec 归档、主规格、`simplify-inspector-dual-screen-navigation` 变更、各变更证据与验收文档、`PENDING_TASKS.md`、双屏导航测试等全部纳入版本控制。
6. **忽略规则补齐**：新增 `/pytest-of-*/`、`/.pytest-bt/`，避免 pytest 临时工作区再次出现在 `git status`。

## 核对结果

- 受版本控制文件 2019 项，整理前后索引哈希逐项一致；没有改写既有受控内容。
- 归档 14 项全部落位，原路径已清空；`.tmp` 已清空。
- 工作区总占用（不含 `.git`）2545.2 MB → 1897.6 MB；`.local/` 内归档的 1.61 GB 可随时删除再回收。

## 恢复与后续

- 归档项恢复：查 `.local/workspace-archive/20261110/manifest.json`，按 `original` 移回。
- 历史源码恢复：用 `backups/*.bundle` 克隆，或检出提交 `cd26f5f8`。
- 未做：`.git` 未 `gc`；`.installers/deva-test` 因占用未移动；未运行全项目测试。

## 权限说明（重要）

当前会话的受限模式对 `reports/`、`docs/`、`openspec/`、`anylabeling/`、`tests/`、`scripts/`、`tools/`、`benchmarks/`、`assets/`、`.git/`、`backups/` 没有写授权。按 `diagnose-windows-sandbox-acl` 的官方诊断流程结论为 `NOT_THIS_CLASS`（根目录权限齐全、无外来程序包条目），因此本次整理与提交在单次提升权限的命令中完成，未手工改动任何权限条目。后续实施功能前建议把会话切到「完全权限」。

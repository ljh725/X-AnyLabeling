# 工作区目录说明

整理日期：2026-11-05；2026-11-10 追加一次完整数据整理。

| 目录 | 用途 |
| --- | --- |
| `anylabeling/` | 应用源码、配置、资源和翻译 |
| `tests/` | 自动化测试，包括尚未提交的新测试 |
| `scripts/`、`tools/` | 开发、验证和辅助脚本 |
| `docs/`、`openspec/` | 使用文档、变更方案和验收记录 |
| `reports/`、`perf_reports/`、`benchmarks/` | 验证证据、性能报告和基准记录 |
| `samples/`、`images/`、`assets/`、`examples/` | 样本、截图、资源和示例，保留现有引用路径 |
| `packaging/` | 打包配置 |
| `backups/` | 原有备份，使用方式见根目录备份说明 |
| `.local/`、`.tooling/`、`.tmp/` | 本机工具、隔离环境和运行临时文件，已忽略 |

## 本次整理

测试临时目录、权限探测目录、权限诊断日志和编辑器 `~RF*.TMP`
恢复文件集中归档到 `.local/workspace-archive/20261105/`，保留相对路径。
归档未删除文件内容；源码、测试、开发文档、样本及报告保持原位。

安装器暂存目录 `.installers/` 中有文件被进程占用：可移动的内容已归档，
占用文件留在原位。该目录已加入忽略规则。

归档目录中的 `manifest.json` 记录各项目的原路径、目标路径和结果；
`tracked-before.json` 保存整理前受版本控制文件的 SHA-256，
`untracked-before.json` 保存整理前可见的未跟踪文件列表。
`verification.json` 记录整理后的完整性检查结果。

需要恢复某一项时，先查清单，再把对应文件从归档路径移回原路径。
如果原路径已有文件，请先比较内容，避免覆盖后续修改。安装器条目为部分归档，
恢复时应逐文件合并并保留仍在原位的占用文件。

后续临时实验优先放入 `.tmp/`，本机工具和归档放入 `.local/`；
需要保留的性能与验收结果继续放在各自报告目录。

## 2026-11-10 数据整理

本次按同一套约定做了一次完整整理，详细清单见
[工作区数据整理](../reports/workspace_organization_20261110/REPORT.md) 与
[版本管理记录](version-management/2026-11-10-workspace-organization.md)。

- 无关材料与过期本机工作副本归档到 `.local/workspace-archive/20261110/`（14 项，约 1.61 GB），
  逐项原路径、理由与校验值见该目录 `manifest.json`，恢复时按 `original` 移回。
- `.tmp/` 清空，`pytest-of-JJH/`、pytest 缓存与 `__pycache__` 删除，共回收约 647.6 MB；
  本沙箱跑测试所需的临时目录插件保留在 `.tooling/pytest_tmp777.py`。
- `dsh_selection_20261109/` 与根目录两个 `dsh*.md` 移入 `docs/development/dsh/`。
- 未跟踪的 OpenSpec 归档、主规格、变更证据与验收文档全部纳入版本控制。
- `.gitignore` 增加 `/pytest-of-*/`、`/.pytest-bt/`。
- 未做：`.git` 未 `gc`；`.installers/deva-test` 因文件占用未移动。

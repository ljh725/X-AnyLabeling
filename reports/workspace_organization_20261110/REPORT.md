# 工作区数据整理报告（2026-11-10）

整理日期：2026-11-10（Asia/Shanghai）。执行前提交：`cd26f5f825ffdea5ec8804e9c0bde1f033163fea`，分支 `codex/4.2.1-baseline-organization`。

## 1. 结论摘要

| 项目 | 结果 |
| --- | --- |
| 归档本机材料 | 14 项，约 1.61 GB，移入 `.local/workspace-archive/20261110/` |
| 清理可重建文件 | 约 647.6 MB（`.tmp/` 全部、pytest 临时工作区、60 个 `__pycache__`） |
| 工作区总占用（不含 `.git`） | 2545.2 MB → **1897.6 MB** |
| 其中仍可回收 | `.local/workspace-archive/20261110/` 约 1.61 GB，确认无误后可直接删除 |
| 受版本控制文件 | 2019 项，整理前后索引逐项一致（`trackedIndexUnchanged=true`） |
| 根目录状态 | 已无无关材料；`_chair_research/`、`_t_jd.py`、两个 `dsh*.md`、`dsh_selection_20261109/` 均已归位或归档 |
| 未跟踪文件收敛 | 95 个 → 63 个，剩余全部为本次应入库的项目产物（见 §5） |

整理没有改写任何受版本控制文件的内容，也没有删除图片、标注或既有报告；删除项全部为缓存与可重建的临时产物。

## 2. 环境前置：沙箱写权限不完整

本次整理开始时就遇到 Windows 文件权限拒绝：在当前会话的受限模式下，工作区内**部分目录不可写**，`mkdir` 与文件写入被拒（`reports/`、`docs/`、`openspec/`、`anylabeling/`、`tests/`、`scripts/`、`tools/`、`benchmarks/`、`assets/`、`.git/`、`backups/`），而 `.local/`、`.tmp/`、`.tooling/`、`samples/`、`perf_reports/` 可写。

处理经过：

1. 按 `diagnose-windows-sandbox-acl` 技能的官方流程执行了一次一次性诊断 + 修复脚本（工作区根目录，授权范围 = 工作区根目录）。
2. 结论为 `NOT_THIS_CLASS`：根目录的写权限与取得所有权权限齐全，扫描到的前 2000 个对象中没有需要清理的外来程序包权限条目；子树扫描被截断，未发现需要修复的对象。
3. 该技能规定此情形应停止修复并把决定交给用户，因此**没有手工改动任何权限条目、所有者或继承设置**。诊断记录保存在 `.local/acl-repair-20261110/acl-report-0a371290566e41ef985a172d3f926df2.jsonl`。
4. 本次整理、提交与推送改为在**单次提升权限的命令**中执行，每次都在命令说明里写明用途；受限模式下的普通读写行为未改变。

**对后续工作的影响**：受限模式下无法直接编辑 `anylabeling/`、`tests/`、`openspec/`、`docs/`、`reports/`，也无法 `git add/commit`。实施 `add-annotation-correction-cost-statistics` 前建议把本会话切到「完全权限」，否则每一次写文件与提交都需要单独批准。

## 3. 归档清单（14 项，约 1.61 GB）

归档根目录：`.local/workspace-archive/20261110/`。逐项原路径、目标路径、字节数、文件数与理由见同目录 `manifest.json`；恢复时按 `original` 移回即可。

| 原路径 | 体积 | 文件数 | 归档理由 |
| --- | ---: | ---: | --- |
| `.local/restore-v430-20261104` | 792.0 MB | 4231 | 4.3.0 画布能力恢复的本机工作副本；结论已在 `openspec/changes/restore-v430-canvas-controls/`，源码可由 `restore-v430-20261104.bundle` 与 Git 历史重建 |
| `.local/canvas-implementation-20261105` | 577.5 MB | 11486 | 画布实现过程的临时树与基准脚本；实施结果已入库并写入验收文档 |
| `.local/baseline-recovery-check` | 230.9 MB | 34 | 为区分既有失败而导出的 HEAD 源树；可用 `git archive` 重建 |
| `.local/restore-v430` | 0.6 MB | 5 | 恢复过程用的补丁与 blob 片段 |
| `.p2-render` | 8.1 MB | 31 | 离屏渲染输出；`openspec/changes/polish-inspector-dense-review-ui/verification.md` 记录的 `UI_REVIEW_OUT=.p2-render` 可重建 |
| `.dsh-asar-out` | 0.0 MB | 3 | DSH 应用包解出片段，可由已安装应用重建 |
| `.tmp/dsh-sel-20261109/candidates.csv` 等 6 项 | 5.1 MB | 6 | 2026-11-09 选型过程的脚本与摘要；选型结论已归位到 `docs/development/dsh/selection-20261109/` |
| `_chair_research/` | 0.1 MB | 11 | 与项目无关的人体工学椅调研材料 |
| `_t_jd.py` | 0.0 MB | 1 | 与项目无关的抓取脚本 |

未归档但已删除的项目见 §4；`.installers/deva-test`（30.1 MB）因目录内文件被进程占用，移动失败，保持原位（该目录已被忽略规则覆盖）。

## 4. 删除清单（可重建）

| 路径 | 整理前体积 | 理由 |
| --- | ---: | --- |
| `.tmp/*` | 624.7 MB | pytest 沙箱、性能试跑工作区（`perf-20261109/` 等）、会话日志、解出的基线源码（`baseline-src/`、`baseline.tar`）与配置隔离目录；`openspec/.../performance-acceptance-20261109.md` 已注明可随时重建 |
| `pytest-of-JJH/` | 22 项文件 | pytest 生成的临时工作区，且原先**未被** `.gitignore` 覆盖，会污染 `git status` |
| `.pytest_cache/`、`.pytest-bt/` | — | pytest 缓存与残留 |
| `.local/pycache/` | 35 MB | 本机 Python 缓存 |
| `**/__pycache__/` | 60 个目录 | Python 字节码缓存（`anylabeling/` 由此减少 18.7 MB） |

**保留**：`.tmp/harness/pytest_tmp777.py` 已复制到 `.tooling/pytest_tmp777.py`。该插件把 pytest 临时目录权限从 `0700` 改为 `0777`，是本沙箱内跑测试的必要前置；后续测试使用 `PYTHONPATH=.tooling -p pytest_tmp777` 即可。

## 5. 入库清单（本次提交内容）

| 类别 | 内容 |
| --- | --- |
| 代码 | `anylabeling/views/labeling/inspector/dialog.py`、`label_widget.py`、`resources.py`（重新生成）、四份翻译 `.ts`/`.qm`、`configs/xanylabeling_config.yaml`、`settings/{schema,runtime_applier}.py` |
| 测试 | 修改 `tests/test_inspection/*`、`tests/test_labeling/test_digit_rectangle_save.py`、`tests/test_settings/test_schema.py`；新增 `tests/test_inspection/test_dual_screen_navigation.py` |
| OpenSpec | 归档 Inspector 重构（`changes/archive/2026-11-10-...`）、主规格 `openspec/specs/`（5 份）、`simplify-inspector-dual-screen-navigation/` 整个变更、`add-dense-.../`、`restore-v430-.../`、`fix-*/` 的证据与验收文档、`openspec/PENDING_TASKS.md` |
| 组织文档 | 本报告、`docs/version-management/2026-11-10-workspace-organization.md`、`docs/development/dsh/`、`docs/workspace.md`、`BACKUP.md`、`版本与备份目录.md`、`.gitignore` |

## 6. 数据核对

整理前后体积（KB，`du -sk`，不含 `.git` 总计）：

| 目录 | 整理前 | 整理后 | 变化 |
| --- | ---: | ---: | --- |
| `.tmp` | 624.7 MB | 0 | −624.7 MB |
| `anylabeling` | 41.1 MB | 22.4 MB | −18.7 MB |
| `tests` | 6.4 MB | 2.1 MB | −4.3 MB |
| `.local` | 1680.6 MB | 1689.7 MB | +9.1 MB（归档项移入） |
| `reports` | 20.6 MB | 20.3 MB | −0.3 MB |
| `docs` | 0.9 MB | 1.3 MB | +0.4 MB（新增 dsh 文档） |
| `.git` | 543.0 MB | 543.0 MB | 未改动 |
| `backups` | 688.2 MB | 688.2 MB | 未改动 |
| **总计（不含 `.git`）** | **2545.2 MB** | **1897.6 MB** | **−647.6 MB** |

验证项（脚本见 `.local/workspace-archive/20261110/verification.json`）：

- `trackedIndexUnchanged=true`：2019 项受版本控制文件的索引哈希与 blob 逐项一致。
- `archivedItemsMissing=[]`、`originalPathsStillPresent=[]`：14 项归档全部落位，原路径已清空。
- `tmpRemainingEntries=[]`：`.tmp` 已清空。
- `pytestHarnessPreserved=true`：pytest 沙箱插件已保留在 `.tooling/`。

## 7. 恢复方法

1. 查 `.local/workspace-archive/20261110/manifest.json`，按 `original` 把条目从 `archivedTo` 移回。
2. 需要 4.3.0 恢复过程或拖动修复前的完整代码时，用 `backups/` 下的 bundle：`git clone <bundle> <新目录>`。
3. 需要整理前的源码状态时，检出本节点之前的提交 `cd26f5f8`。

## 8. 未完成与风险

- **权限**：见 §2。受限模式下 `anylabeling/` 等目录不可写，实施新功能前需切到完全权限或逐次批准。
- `.installers/deva-test` 移动失败（占用），保持原位；已被忽略规则覆盖，不影响 `git status`。
- `_chair_research/_ptmp/` 归档后仍存在权限拒绝告警（移动本身成功），未深入处理。
- 未运行全项目测试；本次只复核了与未提交改动相关的定向回归（53 passed，见 `openspec/changes/fix-digit-rectangle-label-save/verification.md` 与下方复跑记录）。
- `.git` 未执行 `gc`/`repack`，保持 543 MB 原状，避免整理过程引入不可逆的仓库压缩操作。
- 归档区 1.61 GB 仍在磁盘上（本机、已被忽略）。确认不再需要后可整目录删除以回收空间。

## 9. 定向回归复跑（2026-11-10 14:07）

命令（仓库根目录，离屏 Qt）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTEST_DEBUG_TEMPROOT = 'D:/X-AnyLabeling-4.2.1/.tmp/digit-review-20261110'
$env:PYTHONPATH = '.tmp/harness'
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_labeling/test_digit_rectangle_save.py tests/test_labeling/test_digit_label_actions.py tests/test_labeling/test_label_file_save.py tests/test_settings/test_digit_shortcut_flow.py -q --tb=short --color=no -p no:cacheprovider -p pytest_tmp777
```

结果：**53 passed in 86.07s**。与 `fix-digit-rectangle-label-save/verification.md` 记录的 53 项通过一致。

## 10. 备份节点与推送核对

整理完成后把工作区提交为本节点，并推送到 `ljh725/X-AnyLabeling`：

- 节点提交：`e40c537c56fcca7ff4db8c3702b02dd9c333d9f6`
- 分支 / 标签：`backup/4.2.1-20261110-organized-baseline`（同名）
- 远端核对与本地 bundle 校验：见 [verification.md](verification.md)
- 相对整理前保存点 `cd26f5f8`：103 files changed, 41309 insertions(+), 34683 deletions(-)

# CUSTOM-124：维护基线整理与 agent 执行交接

- 状态：实施中；候选、入口与验证记录已建立，完整回归复验和规格归档继续按源任务执行。
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

## 2026-11-17 维护批次二：当前入口整理

第一批提交 `0e5472cb`；本批从 16 份活动 tasks 重算，304/347，
43 未勾（产品 32、协调 11），11 份全勾、1 份移交目录。PENDING_TASKS
新增当前摘要并保留历史；修正 CUSTOM-109 行政关闭、122 暂停，区分 118/011，
补现存记录链接。修正 smooth-canvas-dragging 的 3 处导航并新增证据入口。
本批链接审计发现成本统计 3 份历史实施报告指向本地已缺失的 .local/stage 文档，
保留历史原文，不补造证据；未修改机器清单或移动原证据。
验证：OpenSpec all strict、git diff --check；本批纯文档，不跑 Qt。
本地提交标题 `docs(maintenance): 重算任务状态并修复当前导航`，不推送、不开 PR、不合入。

## 维护测试修正：补全拟合输入事件

第二批提交 `cdd25660`。风险复核复现两项拟合集成失败后，仅在旧测试中补齐
真实 Shift 按下/释放与固定指针坐标，保留全部原断言，不改产品行为。
完整集成文件 36 passed / 124.78s，退出码 0；定向 diff 检查通过。
更正静态检查：flake8 退出 1，14 条既有 F811，基线对照同样 14 条；不宣称全绿。
见[修正证据](../../reports/maintenance_baseline_20261117/FIT_FIX.md)。
运行修订为 `cdd25660` 加本批唯一测试差异，源码树不变。
本批为独立本地测试提交，不推送、不合入；停止快照交接失败保留。

## 维护测试修正：旧窗口启动会话

在 `6c9af4dc` 的完整回归记录初始化模态挂起，最小观察保留原始 No active
configuration session 错误和堆栈。按 AGENTS 修正两个旧测试文件，使用
get_config 返回配置与真实启动覆盖，并清理失败时遗留的本测试窗口。
最终 15 passed / 54.30s，flake8 及定向 diff 检查通过；生产代码及写保护不变。
中间断言失败和 0xC0000409 原生退出均保留，详见
[启动修正证据](../../reports/maintenance_baseline_20261117/STARTUP_FIX.md)。
本批只本地提交，随后重跑完整 Windows 回归；不推送、PR 或合入。

## 2026-11-17 维护批次三：当前验证基线

此前启动夹具修正 `8d9ab779`，本批仅对新增参数行换行、AST 对照相同。
保存同一生产树上的 priority/core/review/collect/完整首轮/最小失败证据，
完整首轮无输出超时，未得到完整 JUnit；不将结果写成全绿或完整完成。
已知 Windows、测试桩、停止快照失败及人工缺口分类见
[维护报告](../../reports/maintenance_baseline_20261117/REPORT.md)。
任务 3.1/3.2/3.3/3.5 已有证据，3.4 等待修正后的整组复验；
本批提交后启动第二轮，期间按交接推进独立的文档归档。
代码/文档定向 diff 检查通过；原始日志/XML 的行尾空白按原样保留，整批检查有相应告警。
其他任务输入不暂存；本地提交 `docs(maintenance): 建立当前验证证据与失败分类`，不推送、PR、合入。

## 2026-11-17 维护批次四准备：归档预演与证据核验

第三步证据提交 `77f9ced5`；3.4 在第二轮整组结果出现前保持未勾。
按 HANDOFF 继续独立文档工作，测试不读取将移动的 OpenSpec 文档，生产/测试树不变。
.tmp 副本预演 11 目录、14 个新增主规格能力，strict 26 passed / 0 failed；
主目录此时仍未执行这些归档，副本通过不冒充产品验收。
逐项资格、单点拟合 18 个旧场景/17 个新场景与最终 7 需求/28 场景对照、
原三份密集契约与停止五份草案的未发布边界，见
[归档审计](../../reports/maintenance_baseline_20261117/ARCHIVES.md)。
restore 本机旧路径实际已按 11-10 manifest 迁移；只读 bundle verify 完整，
独立克隆 HEAD 70975046 与回执一致，10/10 文件指纹相同，DPI/性能原材料仍在。
未移动/删除备份，未新做人机或性能验收；修正 CUSTOM 索引的过时待验收描述。
本地提交 `docs(maintenance): 核实归档资格与场景语义映射`；无推送、PR、合入。

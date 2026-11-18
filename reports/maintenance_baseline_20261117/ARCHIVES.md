# 维护归档审计与旧路径映射

执行起点 `aebb1804`，候选源码树 `01efe6fe526f49a44353ffcbc5efc5e089a1e77f`。
使用 openspec-archive-change / openspec-sync-specs：逐项 status 验证工件，
只读取 artifactPaths.specs.existingOutputPaths；archive 附加输入均无 context/guidance，
每项 specs instructions 均成功取得有效 JSON、无额外 rules。
用户已授权四步顺序执行及符合条件的同步归档，无推送/PR/合入授权。

## 独立副本预演

在 `.tmp/maintenance-archive-rehearsal/` 复制 OpenSpec 后按下表顺序合并和移动。
预演 strict 26 passed / 0 failed；合并使用规范的 Purpose/Requirements，
保留现有 Purpose，不创建 TBD、重复能力名或虚假场景改名。主目录逐批复验。
实际采用 agent 合并及整目录移动（保留 .openspec.yaml），不冒称运行过 CLI archive。

## 资格及证据边界

| 范围 | 归档依据与限制 |
| --- | --- |
| smooth-canvas-dragging | 19/19；原报告有匹配配置的性能对照、回归差集及 10-30 用户可见拖动确认；本轮完整画布与拖动集成通过。非当前物理 FPS 证明 |
| staged-annotation-loading | 31/31；真实 PRW 三轮原始结果、只读审计及两轮修复报告；当前加载/保存/取消相关范围实测另见 REPORT。历史 native 堆栈不追认为本轮失败 |
| fix-user-settings-persistence | 27/27；R1–R6、独立进程、真实窗口及 11-09 用户原终端验收；本轮 config/settings 完整合跑通过 |
| fix-digit-rectangle-label-save | 10/10；16 组合及 0–9、保存重开、放弃绑定回归；本轮全文件通过。原界面验收为 offscreen，不虚构物理屏幕 |
| improve-rectangle-edge-adjustment | 6/6；四边/把手/边界/撤销回归；本轮完整画布通过。原任务未要求物理屏幕门槛，未做的体验观察照实保留 |
| fix-rectangle-preview-overlap | 24/24；真实 Canvas 事件/像素及 11-09 用户深浅背景声明；无新增物理截图。历史 Qt 桩缺项已在候选修复，本轮相关与完整画布通过 |
| restore-v430-canvas-controls | 31/31；11-09 匹配性能及 12 组真实 DPI/双屏报告，用户目视声明；旧路径已迁移，bundle 完整且独立恢复 10/10 指纹一致。非本轮新增 DPI 人工验收 |
| rectangle-point-fit 三项依赖 | 5/5 → 6/6 → 8/8；最终行为以 unify 为准，11-13 用户人工确认；本轮画布通过，旧集成测试事件已修正 36/36。基础/锁角历史模式不独立重发为最终行为 |
| migrate-canvas-controls-from-v430 | 31 条历史文字已移交 restore，无可执行任务；五份 delta 与 restore 逐字节相同，并逐需求核对已发布后才作零增量移交归档。不是再次实施或新验收 |

restore 原本机路径 `.local/canvas-implementation-20261105/` 已在 11-10 迁至
`.local/workspace-archive/20261110/local-work/canvas-implementation-20261105/`，
依据现存 manifest 及仓库 [11-10 报告](../workspace_organization_20261110/REPORT.md)。
[本轮恢复核对](restore-recovery.json)：bundle SHA256 与原回执相同，完整历史，
独立恢复 HEAD `7097504691159af10cade7bf3fc09339b6fa4a0c`、10 文件指纹全部一致。
DPI 原始目录 32 项、性能 summary 仍在；未移动/删除/改写这些附件。
回执中的历史 23 passed 未在本轮重跑；本轮当前代码测试见 REPORT。
这些附件仍为本机材料，跨机器复核需另带该归档；候选源码另有固定 Git 标签。

## 主目录结果与路径映射

旧前缀均为 `openspec/changes/<变更>/`，新前缀为下表 `openspec/changes/` 下路径；
子文件名不变。历史报告与机器清单按原位置解释相对路径，通过本表转至新位置。
只修正当前索引和 proposal/design/tasks/HANDOFF 导航，不改写冻结报告或原始证据。

| 旧变更名 | 新前缀 | 实际状态 / 本地提交 |
| --- | --- | --- |
| `smooth-canvas-dragging` | `archive/2026-11-17-smooth-canvas-dragging` | 已归档；`ffd1a0471d1f83054400533e5b07535c67eff112` |
| `staged-annotation-loading` | `archive/2026-11-17-staged-annotation-loading` | 已归档；`8678f3eb7f94c8864c955d05fe24a19527cf6115` |
| `fix-user-settings-persistence` | `archive/2026-11-17-fix-user-settings-persistence` | 已归档；`2267cc6c8d9e3b738b69f7b907626e9e87ae7d26` |
| `fix-digit-rectangle-label-save` | `archive/2026-11-17-fix-digit-rectangle-label-save` | 已归档；`5453c11f5947ea687b6488622efc188aaae902eb` |
| `improve-rectangle-edge-adjustment` | `archive/2026-11-17-improve-rectangle-edge-adjustment` | 已归档；`9caa239e5f8bb0239e6eee3e47696687f6d33eed` |
| `fix-rectangle-preview-overlap` | `archive/2026-11-17-fix-rectangle-preview-overlap` | 已归档；`57dc597903ab7147967a32bf75e2f301c3f43d7b` |
| `restore-v430-canvas-controls` | `archive/2026-11-17-restore-v430-canvas-controls` | 已归档；`89e3785ec9a629974fab58d7ee8c3b86683a62ae` |
| `improve-point-fit-algorithm` | `archive/2026-11-17-improve-point-fit-algorithm` | 已归档；`4ec0a3cda47292f60b9fde377110b3c939a91401` |
| `add-shift-corner-lock-point-fit` | `archive/2026-11-17-add-shift-corner-lock-point-fit` | 已归档；`4ec0a3cda47292f60b9fde377110b3c939a91401` |
| `unify-shift-rectangle-point-fit` | `archive/2026-11-17-unify-shift-rectangle-point-fit` | 已归档；`4ec0a3cda47292f60b9fde377110b3c939a91401` |
| `migrate-canvas-controls-from-v430` | `archive/2026-11-17-migrate-canvas-controls-from-v430` | 已归档；`a5486ba700f1469dd3cde823ee41a6e888d68840` |

## 单点拟合场景语义映射

按基础 ADDED → 锁角 ADDED → unify MODIFIED/REMOVED 顺序预演并执行，
三项放在一个关联批次提交，避免将中间历史模式单独作为最终版本交付。
合并前 8 需求/18 场景，最终 7 需求/28 场景：unify 的 17 个场景全部在主规格，
另保留 11 个未被改变的旧场景；其余旧场景按下表有明确替代/删除依据。
不丢掉未提及的旧场景；相同语义的中英文或旧新标题保留可追踪性。

| 原需求 | 原场景 | 处理 | 最终对应 |
| --- | --- | --- | --- |
| Shift 按下位置决定拟合流程 | 从框外或边线开始 | 行为被后续场景替代 | 从框外或边线进框 |
| Shift 按下位置决定拟合流程 | 从框内十字缓冲区开始 | 原场景保留 | 从框内十字缓冲区开始 |
| 锁角立即生成预览 | 在框内明确区域按下 Shift | 原场景保留 | 在框内明确区域按下 Shift |
| 锁角立即生成预览 | 从同一侧出框再返回 | 原场景保留 | 从同一侧出框再返回 |
| 锁角立即生成预览 | 鼠标跨区或越过固定角 | 原场景保留 | 鼠标跨区或越过固定角 |
| 单击提交与预览一致 | 直接单击当前落点 | 原场景保留 | 直接单击当前落点 |
| 单击提交与预览一致 | 超出图片的有效落点 | 原场景保留 | 超出图片的有效落点 |
| 单击提交与预览一致 | 无效落点 | 行为被后续场景替代 | 无效落点后继续调整 |
| 框内手势结束后等待新的 Shift 按下 | 先松 Shift | 同名场景更新 | 先松 Shift |
| 框内手势结束后等待新的 Shift 按下 | 手势结束仍按着 Shift | 行为被后续场景替代 | 已提交且仍按着 Shift |
| Captured gesture keeps its anchor and mode | Cross the centre after pressing | 原场景保留 | Cross the centre after pressing |
| Captured gesture keeps its anchor and mode | Release Alt first | 行为被后续场景替代 | 组合键的 Alt 变化 |
| Preview matches clipped geometry | Pointer outside image | 原场景保留 | Pointer outside image |
| Preview matches clipped geometry | Cancel Shift | 原场景保留 | Cancel Shift |
| Shift 加 Alt 提供同侧角单击 | 组合键单击收框 | 需求按 REMOVED 撤销 | 组合键的 Alt 变化（普通 Shift，不再同侧角） |
| Shift 加 Alt 提供同侧角单击 | 左键按下后增加 Alt | 需求按 REMOVED 撤销 | 组合键的 Alt 变化（普通 Shift，不再同侧角） |
| Continuous size-aware corner inference | Cross the top edge | 未修改需求原样保留 | Cross the top edge |
| Continuous size-aware corner inference | Narrow rectangle | 未修改需求原样保留 | Narrow rectangle |

四项行为替代分别为：框外进框可锁角、无效点击保留锁角、Alt 不再切换模式、
仅成功确认后等待新 Shift；这都是原 unify delta 的显式行为变化。
Shift+Alt 同侧角需求及两个场景按 REMOVED 撤销，迁移为普通 Shift，对角锁定。

## 原密集复核、停止草案与当前实现

| 原三份契约 | 停止的五份草案关联 | 当前实现及发布结论 |
| --- | --- | --- |
| dense-review-workspace | workbench-layout / object-cards / display-policy | 当前 workspace、卡片、显示解析和画布覆盖层含部分后续实现；自动化仅在报告范围有证据，真实字体/读屏/四语可用性等仍缺；不发布 |
| batch-review-progress | progress-compatibility | 当前 session/ledger/signatures 接入进度、保存恢复和撤销；停止快照交接用例仍失败，原工作流完整组合交付未闭环；不发布 |
| spatial-omission-review | spatial-navigation / progress-compatibility / display-policy | 原 CoveragePlan/区域网格与部分小地图/查漏显示共存；两位用户交叉试用、独立质量复核及减负证据仍缺；不发布 |

表中草案简名都带 `dense-review-` 前缀。三份原契约保持活动且未发布，原任务
61/66 的 5 项保持不勾；五份停止草案继续留在停止归档，既不发布，也不宣称
全部被取代。当前部分代码存在不构成验收，不重启停止计划。

## 明确保留的活动项

原密集复核 61/66、成本统计 49/54、关键点暂停 0/22 保留。
P2 polish 虽 20/20，但 delta 承诺 Inspector Ctrl+F 搜索，verification 明确未做，
当前 dialog 也没有该绑定；真实屏幕/部分本地化另有缺口。故保留原独立契约，
不删需求、不把它强行并入已归档 Inspector，也不为归档扩展搜索功能。
协调变更按源 tasks 的真实验证状态保留，不为清零而自动归档。

## 最终复核

9 个独立/关联归档批次共 11 目录，21 主规格（原有 7 + 新增 14）与预演一致，
主目录 strict 26 passed / 0 failed。197 既有工件字节/Git blob 不变，7 份只改导航，
2 份协调状态更新，0 丢失和意外改写；详见[最后实核](final-audit.json)。
当前链接检查只涵盖当前导航和新报告；冻结历史报告/清单按路径映射解释，未改写。
首批提前改未来链接的问题由 15153e76 单独修正，归档文件未丢失。
完整运行已结束但有 20 failed（18 主 + 2 子），见 REPORT；不宣称候选稳定。
保留 5 个活动目录，协调变更本身不自动归档，不以清零为完成标准。
## 2026-11-18 归档证据直达

以下入口对应归档前文档中的七处引用。目标均已纳入 Git，原验证页保留当时的记录。

| 原引用所在文档 | 现存目标 |
| --- | --- |
| 11 月 6 日项目变更审计，数字矩形保存实施记录所在行的「任务」 | [数字矩形保存任务与验证范围](../../openspec/changes/archive/2026-11-17-fix-digit-rectangle-label-save/tasks.md) |
| 矩形预览验证页，「实施与交付记录」 | [矩形预览实施与交付记录](../../docs/custom_changes/2026-11-02-rectangle-preview-overlap-plan.md) |
| 矩形预览验证页，「矩形单点拟合」 | [矩形单点拟合用户手册](../../docs/zh_cn/rectangle_point_fit.md) |
| 单点拟合验证页，「canvas-regression.log」 | [联合画布回归日志](../../openspec/changes/archive/2026-11-17-improve-rectangle-edge-adjustment/canvas-regression.log) |
| 单点拟合验证页，「canvas-regression.xml」 | [联合画布回归 JUnit](../../openspec/changes/archive/2026-11-17-improve-rectangle-edge-adjustment/canvas-regression.xml) |
| 单点拟合验证页，「边界修复回归」 | [矩形边界修复回归日志](../rect_boundary_20261030/canvas_regression.log) |
| 画布恢复联合复核，「迁移 tasks.md」 | [画布迁移移交任务与映射](../../openspec/changes/archive/2026-11-17-migrate-canvas-controls-from-v430/tasks.md) |

单点拟合验证页还引用了本机存在、未纳入 Git 的 `reports/drag_fix_20261030/regression/core_baseline.log`。可移植的历史结论见仓库内 `reports/drag_fix_20261030/regression/SUMMARY.md`。

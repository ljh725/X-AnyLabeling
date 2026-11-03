# CUSTOM-109：Inspector 检查与复核工作流

- 状态：实施中（自动化验证通过，人工试用与部分交付项未完成）
- 功能分类：新增本地能力（部分算法从 beta4 迁移）
- 创建日期、最后更新日期：2026-11-02（Asia/Shanghai）
- 原始版本与基线提交：X-AnyLabeling 4.2.1；基线提交 `9a37c5474c390e93243e33a88e8232a19c833280`（父提交 `1038d555c997e8c42ba589d648ca2e45abd52c26` 保存既有编译资源）
- 实现提交 / PR：实施工作区尚未提交；基线备份见下
- 工作区已有修改、前置依赖：实施前存在 `migrate-canvas-controls-from-v430` 未提交的 `resources.py` 与四语种 `.qm`，已单独保存在备份父提交；本功能依赖持久 Shape 身份、编辑命令、分阶段加载和配置/翻译设施

## 问题与目标

当前 4.2.1 没有 Inspector/质检入口，检查规则、批量运行、问题队列和人工复核分散在旧版外部工作树。目标是在当前版本建立可选的检查工作流：选择方案与范围、后台运行、按稳定身份定位问题、记录人工结论、复查并可靠恢复；普通画布始终可独立使用。检查只读，正式修改继续走画布编辑与保存链路。

不在本项中：模型推理/下载、双屏界面、SQLite 索引、自动删除框、以问题清零代替最终验收。

## 迁移来源

旧版来源：`D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4`，Git 提交 `b45af4adcbbfb13d4ae1fcffa04afe5678b463e0`（工作树另有未提交改动，因此同时固定文件 SHA256）。

采用的文件与指纹：

| 文件 | SHA256 | 字节 |
| --- | --- | --- |
| `widgets/category_dual_screen/duplicate_detector.py` | `331217da16707d11d5fabc74b4d95c909d836e2105ab40ae468cef34c8ee0643` | 9466 |
| `widgets/category_dual_screen/settings.py` | `ea1ebec357d5380b9c63757ac9ab5b6f0753b03f5df4677dc7ef6abf281b8ba5` | 3761 |
| `widgets/category_dual_screen/spatial_index.py` | `30ec3b2a3a10b79dfc4313ba661941a222ebf062d34dfb872ae768f09312a6a5` | 2547 |
| `widgets/category_dual_screen/types.py` | `80607daac4cbccbd7c2345da484b4b4641ff2b49109e8a87743a7d2085627a0e` | 2918 |
| `widgets/inspector/quality/quality_issue.py` | `a6e17eafb6761ae212e0bb3c56ab6b7d94583701b4cbf2f59bac8ac8be1be0c4` | 11975 |
| `widgets/inspector/quality/geometry.py` | `e72579ba9b89a0fe5069556a077ed661b6fa4af0194c6ff1ac34cc5fd06c6a29` | 8101 |
| `widgets/inspector/quality/l1_rules.py` | `11aef9e647ef1e5a0e0454a7b02582906f4c2232c80b4b60f434d0411b37d2f9` | 7921 |
| `widgets/inspector/quality/report_writer.py` | `c6d43d2c685e940a7047f88d31b232bdec09fb732086d01248da7db99beec463` | 7059 |

采用：重复框几何指标/阈值/空间索引/增量核心、几何基础函数、结构化 L1 思路、报告与问题字段语义。

不采用：旧 `inspector_panel.py` 整包界面、双屏窗口与控制器、旧 CLI 全量扫描器、未登记的人体关系自动规则、SQLite/历史报告索引、旧文件的路径兜底导航。旧 `l2_rules.py`、`matching.py`、`quality_review_queue.py` 仅作为行为参考，不整文件复制。

## 修改位置与方法

实际修改：

| 文件 / 函数 | 原行为 | 改后行为 | 迁移注意事项 |
| --- | --- | --- | --- |
| `anylabeling/services/inspection/models.py` | 不存在 | 版本化 issue/evidence/coverage/report/feedback/session/candidate 契约 | 纯 Python；人工判断/动作/机器验证三轴独立 |
| `duplicate.py` | 不存在 | beta4 几何指标、阈值、空间索引、全扫/增量、L2-13 | 取消显式返回 cancelled；不导入 Qt |
| `rules.py` | 不存在 | 结构、分组、数量、角点、课堂关系、重复框规则 | 前提不足返回 not_applicable/issue，不伪通过 |
| `profiles.py` | 不存在 | 规则目录、三套模板、校验、复制/导入导出、冻结快照 | 未知规则阻止完整执行，保留可用子集 |
| `manifest.py` | 不存在 | 完整清单、输出目录隔离、缺失/损坏 JSON、身份快照 | 不回写修复；临时身份仅当前快照 |
| `runner.py` | 不存在 | 后台可取消运行、逐文件逐规则覆盖、终态与证据合并 | 空范围/失败/取消不显示零问题通过 |
| `storage.py` | 不存在 | 原子 report/manifest、feedback/session revision、冲突副本 | 报告与反馈分离；不写训练标注 |
| `importers.py`、`candidates.py`、`handoff.py` | 不存在 | 旧问题导入/完整导出、候选校验/接受意图、五维状态 | 路径歧义和未知版本显式报告 |
| `verification.py` | 不存在 | 恢复报告时核验当前磁盘与未保存画布、对象身份、方案/规则版本 | 未保存变化标 pending，磁盘/配置变化标 stale |
| `anylabeling/views/labeling/inspector/` | 不存在 | 方案/范围/运行/取消、问题队列、反馈、复查、导入导出、候选 | 非模态；关闭不改变原画布流程 |
| `label_widget.py::open_inspector` 及 `inspection_*` | 无入口 | Workflow 菜单入口、内存快照、稳定身份导航、删除/重标、候选接受 | 编辑走现有画布命令与拖动/保存链路 |
| `tests/test_inspection/` | 不存在 | 80 项服务与 GUI 集成测试 | 覆盖取消、身份、冲突、往返、内存/磁盘恢复核验和复查 |

## 兼容与数据影响

- 运行报告、反馈和会话保存到数据/输出目录旁的 `.xanylabeling/inspection/`；不改标注 JSON 和旧 `checked`/`review_status` 语义。
- 新报告为版本化 schema；未知版本、损坏文件和不可信身份均保留原文件并显式降级。
- 检查阶段只读；接受/删除/重标等操作必须经现有画布编辑命令，保留持久身份、锁定和撤销语义。

## 验证

实际（2026-11-02，`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，Python 3.12.12 / PyQt6 6.10.2 / Qt 6.10.0，`QT_QPA_PLATFORM=offscreen`）：

| 检查 | 结果 |
| --- | --- |
| `tests/test_inspection` | 80 passed |
| 定向 labeling | 25 passed, 11 subtests passed |
| labeling 全量 | 192 passed, 8 既有失败, 45 subtests passed |
| canvas | 543 passed, 1 既有失败, 83 subtests passed |
| widgets | 29 passed, 3 既有失败, 2 subtests passed |
| staged | 32 passed |
| settings schema/controller | 20 passed |
| utils/config | 85 passed, 8 skipped, 28 subtests passed |
| beta4 重复框对照 | 160 矩形、38,160 对；指标差 0.0、分级差 0、候选对集合差 0 |
| flake8/Black/`git diff --check` | 通过 |
| `openspec validate ... --strict` | 通过 |

既有失败已在基线 worktree `9a37c547` 复跑确认。JUnit、对照 JSON 与完整说明见 [实施报告](../../reports/inspector_workflow_20261102/REPORT.md)。

未验证：方案改名/编辑/停用、批量删除/按类别重标预览、i18n/快捷键、逐次编辑增量结果、候选覆盖层/批量接受/撤销关联、密集复核交接的真实 UI 流程、性能时延、两位使用者试用和人工验收。2026-11-02 密集复核工作区已可用，handoff 协议改为 `dense-review.v1`；仅完成能力声明与测试更新，未进行真实交接试用。

## 迁移与回退

- 实施分支：`codex/refactor-data-inspector-workflow`。
- 实施前备份：分支/标签 `backup/refactor-data-inspector-workflow-20261102`，基线提交 `9a37c5474c390e93243e33a88e8232a19c833280`，已通过 `git ls-remote origin` 核验。
- 恢复：`git clone --branch backup/refactor-data-inspector-workflow-20261102 https://github.com/ljh725/X-AnyLabeling.git <目录>`，或 `git switch -c recovered/inspector 9a37c547`。
- 回退：关闭 Inspector 入口并逆序 revert 本功能提交；保留独立报告/反馈文件，不逆向修改标注数据。

未纳入备份：`.commandcode/`、`.workbuddy/`、性能 profile、pytest 临时数据及其他无关未跟踪报告。

## 后续修订

| 日期 | 原因 | 实际改动 / 提交 | 验证结果 |
| --- | --- | --- | --- |
| 2026-11-02 | 建立实施基线 | 备份分支/标签与 OpenSpec 基线提交 `9a37c547` | 远端 SHA 已核验 |
| 2026-11-02 | 实施核心服务、UI 与主窗口入口 | 工作区未提交；新增 `anylabeling/services/inspection/`、`anylabeling/views/labeling/inspector/`、`tests/test_inspection/`，修改 `label_widget.py` | 回归既有失败已对照基线 |
| 2026-11-02 | 处理评审四项 | 删除仅提交画布选中未锁定对象；恢复报告核验当前输入/配置；binding 不覆盖用户选择；manifest 错误计入范围/终态 | 通过 |
| 2026-11-02 | 恢复核验纳入未保存画布 | 增加规范化 shape 摘要与 memory_files 对照；未保存变化 pending，磁盘/配置变化 stale | 80 项新测试通过 |
| 2026-11-02 | 密集复核交接可用 | `handoff.py` 改为 `dense_review_available=True`、`dense-review.v1`；更新交接测试 | `tests/test_inspection` 80 passed；真实交接 UI 未人工验证 |
| 2026-11-03 | UI 重构（P0） | 接入 `get_dialog_style()` + `get_workbench_qss()`；工具条两行化；外部候选并入右栏标签；问题表改 5 列自适应；五轴改徽标行；按钮主次变体；空状态与运行后自动选中 | `tests/test_inspection` 80 passed；截图见 `reports/ui_review_20261103/`；详见 [实施记录](../../reports/ui_review_20261103/UI-IMPLEMENTATION.md) |

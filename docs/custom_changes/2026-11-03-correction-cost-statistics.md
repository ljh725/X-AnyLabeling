# CUSTOM-111 修正成本统计

- 状态：**代码实施完成，自动化验证通过；真实屏幕人工验收未完成，变更未归档。**
- 分类：新增本地能力（可选工作流，默认关闭）。
- 创建日期：2026-11-03；最后更新：2026-11-12（Asia/Shanghai）。
- OpenSpec 变更：[add-annotation-correction-cost-statistics](../../openspec/changes/add-annotation-correction-cost-statistics/proposal.md) · [任务台账](../../openspec/changes/add-annotation-correction-cost-statistics/tasks.md)（49/54）· [验证记录](../../openspec/changes/add-annotation-correction-cost-statistics/verification.md)
- 原始版本与基线提交：`cd26f5f8`（官方 `v4.2.1` 之上）；实施提交见下"实施提交"。
- 工作区已有修改、前置依赖：依赖已完成并提交的 Inspector/密集复核、配置持久化、数字键改类修复；本功能不改这些既有业务语义，只消费其完成/编辑事件。

## 历史（2026-11-03 记录，保留原文以便追溯）

- 当时状态为部分代码已保存、完整功能实施中。
- 部分服务、计时和入口接入随混合快照 `9673d3b9` 保存，包含在 UI P2 提交 `6b98b76e` 的祖先中。
- 当时视图目录只有 hooks、clock_adapter 与 i18n，controller、panel、report_dialog 尚缺，专用功能测试尚缺。
- 当时对工作流入口增加可用性门控与开发状态提示，防止调用缺失控制器。
- 实施前恢复点、文件备份、失败清单和新开发起点见 [开发基线](../version-management/2026-11-03-development-baseline.md) 及 [核验报告](../../reports/baseline_organization_20261103/REPORT.md)。

## 实施更新（2026-11-11）

### 实施提交

全部在 `codex/4.2.1-baseline-organization` 上，逐段提交（均为本功能单独提交，不混入工作区其他改动）：

| 提交 | 内容 |
| --- | --- |
| `e5748a9c` | 数据契约测试与 3 条服务层缺陷修复（来源未知误判不可比、预测来源静默丢失、空基线分母为 0） |
| `da79e3b3` | 适配层：controller / panel / report_dialog / i18n，`metrics_available()` 由恒假变为可用 |
| `9c6fef6c` | 几何编辑归属对象、全局改名通知、计时适配器与 30 个计时用例 |
| `c93ff01a` | 预标注来源字段、批量预标注逐图上报、复核来源与撤销关联、redo 不计事务 |
| `61e32372` | 完成/质量状态、取消导航、空闲确认、面板焦点与窄窗口 |
| `e8028af9` | 7.x：默认关闭的入口设置、面板字段、汇总范围/版本筛选、批量完成按钮、CSV 口径 |
| `4475de84` | 8.x/9.x：CSV 契约与安全、故障矩阵、服务层性能基准、回归与静态检查记录 |

### 修改位置与方法

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 纯数据与存储 | `anylabeling/services/correction_metrics/{core,storage,timing,reporting,export}.py` | 净差异 B/F/G/C 与去重、事务/触达计数、类别版本映射、范围与完整性、版本化 SQLite（单写队列）、WorkClock 计时、汇总投影、CSV 导出 |
| 适配与界面 | `anylabeling/views/labeling/correction_metrics/{controller,panel,report_dialog,hooks,clock_adapter,i18n}.py` | 会话协调、当前图片面板、汇总与导出对话框、观察者入口与降级、前台/挂起适配、四语文案 |
| 接入点 | `label_widget.py`、`widgets/canvas.py`/`point_fit.py`/`rectangle_edge.py`（经 shape_moved）、`widgets/label_dialog.py`、`dense_review/workspace.py`、`utils/batch.py`、`settings/{schema,runtime_applier}.py` | 菜单入口与开关、几何完成边界、单框字段对话框、全局类别改名、密集复核确认、批量预标注、设置项 |
| 来源兼容 | `services/auto_labeling/model_manager.py` | 为 `AutoLabelingResult` 补充可选 `provenance`（白名单；排除密钥/授权头/带凭据链接；`mode` 由 replace 标志推导） |

### 配置、数据与兼容

- 开关：设置项 `correction_metrics_enabled`（默认 **False**）；未启用时不建库、不采集、不计时。
- 统计库：本机应用数据目录 `~/.xanylabeling/correction_metrics/<dataset-id>.sqlite3`（可用环境变量 `XANYLABELING_METRICS_DIR` 覆盖）；`PRAGMA user_version = 1`，未知版本拒绝打开且不覆盖；不允许放在网络盘。
- 标注 JSON：**格式零变化**，统计事件不写入标注文件；训练导出字段保持兼容。统计库与标注文件非同一事务（两阶段 pending-checkpoint + 摘要核对）。
- 时间口径：应用内处理时间（单调时钟），显式暂停/后台/锁屏停表；120 秒无输入只提示、不自动扣；后台推理与审图并行不重复相加。
- 质量：默认 `not-assessed`；`set_quality` 要求明确来源，内容变化时质量与完成一起失效；完成 ≠ 质量通过。

### 验证

- 自动化：`tests/test_correction_metrics/` 四个语言无关测试包共 **299 用例**（另 schema 7 例、批量相邻 2+6 subtests、数字矩形 48 例），全部通过；`openspec validate --strict` 通过；新增代码 flake8 零告警、三个新建 UI 文件 black 通过。
- 服务层性能（`benchmarks/correction_metrics_20261111/`）：采集 p95 0.07–0.10 ms、首屏 `rows(50)` 约 5 ms、导出取消 6.3 ms、心跳 0.003–0.02 ms；**GUI 主线程 p95 未测**。
- 故障矩阵：独占锁/只读库/磁盘错误/队列饱和/崩溃恢复/外部改动 12 行全部按降级契约披露，统计故障不影响标注保存。
- **未完成的人工验收**：真实屏幕 GUI 回归（各矩形入口、锁屏休眠、密集复核/Inspector 交接）、GUI 拖动性能、两位使用者对照试用；`.ts/.qm` 尚未重编译。

### 备份与回退

1. **关闭功能**：设置里关闭 `correction_metrics_enabled`（或打开旧版本程序）——不再采集、不建新库；标注打开/编辑/保存/训练导出完全不受影响。
2. **停用运行中的会话**：菜单/设置关闭后 `controller.stop()` 会收尾计时、flush 并关闭统计库。
3. **保留统计库**：库文件可独立复制备份（先关闭会话，避免 WAL 未合并）；保留后可随时用更高版本工具导出历史。
4. **彻底移除**：删除统计库只损失历史统计，不删除图片与标注；回退代码时移除本功能的适配器/服务/UI 与可选 `provenance` 字段即可，标注 JSON 与业务审核状态不依赖统计库。
5. 实施前的恢复点仍是备份节点 `backup/4.2.1-20261110-organized-baseline`（`e40c537c`）与提交 `cd26f5f8`。

### 后续修订

| 日期 | 原因 | 实际改动 / 提交 | 验证结果 |
| --- | --- | --- | --- |
| 2026-11-11 | 实施第一版（批次 1–3） | 见上方"实施提交" | 自动化 299+ 用例通过；人工与性能 GUI 验收待做 |
| 2026-11-11 | 遗留代码项收尾（批次 4） | 图片摘要下沉服务层、显式类别版本、存储重试入口、矩形入口用例、连续自动保存用例、完成时关闭计时器（真缺陷修复）、模型运行/阻塞等待分列展示、崩溃尾段用例；`tasks.md` 49/54 | `tests/test_correction_metrics` **334 passed**；`openspec validate --strict` valid；真实屏幕与 GUI 性能仍待人工 |
| 2026-11-12 | 点击工作流菜单缺少可见反馈，统计面板未接入布局 | 关闭时打开设置中的启用项；启用后在右侧栏顶部显示可滚动面板，重新打开时恢复隐藏侧栏；面板创建失败显示错误，模块可用性使用 Python 导入器检测 | [菜单入口回归](../../openspec/changes/add-annotation-correction-cost-statistics/verification.md#菜单入口回归) |

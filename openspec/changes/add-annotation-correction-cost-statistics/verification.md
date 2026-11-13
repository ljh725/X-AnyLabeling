# 修正成本统计：验证记录

- 变更：`add-annotation-correction-cost-statistics`
- 当前状态：**代码实施完成、自动化验证通过（任务 49/54）；真实屏幕人工验收与 GUI 性能未完成，变更未归档。**
- 更新日期：2026-11-12（Asia/Shanghai）

## 0. 交付状态

- **代码**：第 1–4 批实施完成；`tasks.md` 49/54 已勾选，剩余 5 项全部需要真实桌面/人工。
- **自动测试**：`tests/test_correction_metrics` **334 passed**；另 `test_settings/test_schema.py` 7、批量相邻 2+6 subtests、数字矩形 48。
- **可用路径**：工作流菜单定位启用设置 → 保存 → 再次打开菜单 → 右侧栏记录/暂停/完成/复核 → 汇总筛选 → 两种 CSV 导出。开关默认关闭。
- **未完成**：7.5 尾项（`.ts/.qm` 重编译与真实屏幕焦点核对）、9.2 GUI 定向回归、9.4 GUI 主线程 p95 与 10,000 图规模、9.5 两位使用者试用、10.4 的 GUI 打开/保存部分。
- **结论**：自动化通过不等于功能验收通过。未完成 [人工验收清单](manual-acceptance-checklist.md) 前不得归档，也不得宣称质量或提速结论。

## 菜单入口回归

2026-11-12，Windows、`x-anylabeling-cu12`、PyQt6 离屏主窗口。通过实际工作流菜单动作验证默认关闭时定位启用开关、保存设置前后都未自动启动统计、已启用时显示可滚动的右侧栏面板、重新打开时展开面板、关闭统计时隐藏面板，以及面板初始化失败时显示错误且不启动统计。两项 SQLite 独占锁用例在施加故障前等待初始化写入结束，以便稳定触发预期的锁故障。

`python -m pytest tests/test_labeling/test_correction_metrics_gate.py tests/test_settings/test_schema.py tests/test_correction_metrics -q -p no:cacheprovider --basetemp=.tmp/pytest-metrics-menu-20261112-e` 共 **345 passed**。`openspec validate add-annotation-correction-cost-statistics --strict` 通过。真实屏幕、打包程序、工具栏布局和点云测试未运行。

## 1. 批次总览

| 批次 | 范围 | 状态 | 证据 |
| --- | --- | --- | --- |
| 第 1 批 | 1.2–1.4、2.1–2.6、3.1–3.5（数据契约、纯逻辑、存储） | 完成（3 条缺陷修复；2.2/2.5/3.3 部分保留） | [implementation-batch1-20261110.md](implementation-batch1-20261110.md) |
| 第 2 批 | 4.x 预标注与编辑接入、5.x 保存/完成状态、6.x 计时 | 完成 4.1/4.2/4.3/4.5/4.6/4.7、5.1/5.2/5.4/5.6、6.1–6.4 | [batch2a](implementation-batch2a-20261110.md) · [2b](implementation-batch2b-20261110.md) · [2c](implementation-batch2c-20261110.md) · [2d](implementation-batch2d-20261111.md) |
| 第 3 批 | 7.x 界面、8.x 导出、9.x 自动化、10.x 交付 | 7.1–7.4 与 8.x/9.1/9.3/9.6 完成；7.5 尾项、9.2/9.4/9.5 未完成 | [7x](implementation-batch3-7x-20261111.md) · [8x/9x](implementation-batch3-8x-9x-20261111.md) |
| 第 4 批 | 遗留代码项：2.2、2.5、3.3、4.4、5.1、5.3、5.5、6.5、6.6 | 完成；修复完成不关计时器的真缺陷 | [batch4](implementation-batch4-20261111.md) |

## 2. 自动化验证（第 1 批）

环境：Windows + 项目 conda 环境 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`（Python 3.12.12、PyQt6 已装）；离屏 `QT_QPA_PLATFORM=offscreen`。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 本批新增单元测试 | `python -m pytest tests/test_correction_metrics -q -p no:cacheprovider` | **64 passed**（0 failed / 0 skipped / 0 xfail），0.92 s |
| 设置 schema 相邻回归 | `python -m pytest tests/test_settings/test_schema.py -q` | 7 passed |
| 统计菜单 gate 相邻回归 | `python -m pytest tests/test_labeling/test_correction_metrics_gate.py -q` | 1 passed + 1 `ERROR at setup`（沙箱 `tmp_path` ACL 拒绝，见 §4） |
| OpenSpec 结构校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | 见 §5 |

测试包：`tests/test_correction_metrics/`（Qt-free，64 用例），覆盖 2.3 净差异、2.4 计数与幂等、2.5 类别映射、2.6 范围与完整性、3.1–3.3 存储与降级、3.4–3.5 检查点与恢复，以及本批 M1/M3/M4 修复的回归。

## 2.1 提交后复跑（green gate）

- 提交：`e5748a9c`（第 1 批实现与文档），工作区 0 项待提交。
- 命令：`pytest tests/test_correction_metrics -q --tb=short --color=no -p no:cacheprovider`
- 结果：**64 passed in 0.96 s**；连续第二次重跑 `exit code 0`。
- 说明：该复跑发生在所有实现改动之后，用于确认提交内容与验证结果一致。

## 2.2 第 2 批 A 段（适配层）验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **114 passed**（0 failed），约 2 s |
| 相邻设置 schema | `pytest tests/test_settings/test_schema.py -q` | 7 passed |

新增用例：`test_controller.py` 15、`test_wiring.py` 5、`test_panel.py` 14、`test_report_dialog.py` 16。
覆盖：会话启用/禁用、起点冻结与重开复用、事务幂等、保存检查点仅成功推进、丢弃回到已保存版本、
来源未知仅披露、无 ID 几何信号按不完整披露、预测新一轮、观察者故障不抛异常、面板 N/A 与"未保存"
标记、汇总分页与排除原因、CSV BOM/原子发布/取消不留文件。
详见 [implementation-batch2a-20261110.md](implementation-batch2a-20261110.md)。

## 2.3 第 2 批 B 段（几何/改名/计时）验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **159 passed**（0 failed），3.06 s |

新增用例：`test_geometry_wiring.py` 8（几何完成边界与单事务归属）、`test_taxonomy_wiring.py` 5
（全局改名只影响已有轮次、合并传播 N/A）、`test_timing.py` 30（WorkClock 假时钟状态机与绝对快照）、
`test_wiring.py` +2（Qt 时钟适配器接管与绝对快照写入）。
详见 [implementation-batch2b-20261110.md](implementation-batch2b-20261110.md)。

## 2.4 第 2 批 C 段（预标注/批量/复核）验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **188 passed**（0 failed），3.4 s |
| 批量相邻回归 | `pytest tests/test_auto_labeling/test_batch_range.py -q` | 2 passed + 6 subtests |

新增用例：`test_prediction_provenance.py` 13、`test_batch_prediction.py` 5、`test_review_wiring.py` 8、
`test_controller.py` +3（批量入口与 undo_of 关联）。覆盖：来源白名单与 mode 推导、旧式结果兼容、
批量逐图 applied/failed/skipped 与部分失败、复核不计框修改、redo 不计修正事务、撤销关联。
详见 [implementation-batch2c-20261110.md](implementation-batch2c-20261110.md)。

## 2.5 第 2 批 D 段（完成/质量/导航/空闲）验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **227 passed**（0 failed），5.0 s |

新增用例：`test_completion.py` 13、`test_navigation.py` 10、`test_panel_completion.py` 10、
`test_completion_extra.py` 5。覆盖：完成只绑定保存版本、完成失效、幂等、resume 新 id、
质量需来源且随内容变化失效、取消导航不改轮次、批量完成 skipped 原因、review 阶段新轮次、
空闲确认不自动扣时、模态对话框计时。详见 [implementation-batch2d-20261111.md](implementation-batch2d-20261111.md)。

## 2.6 第 3 批 7.x（界面入口/面板/汇总）验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **253 passed**（0 failed），6.6 s |

新增用例：`test_settings_gate.py` 9（默认关闭零负担、启用/停用）、
`test_panel_review.py` 11（字段齐备、复核入口、焦点不被抢、窄窗口）、
`test_report_dialog.py` +8（范围/版本筛选、排除计数、批量完成按钮、跳过原因、
CSV 快照一致、无 accuracy 类列）。详见
[implementation-batch3-7x-20261111.md](implementation-batch3-7x-20261111.md)。

## 2.7 第 3 批 8.x/9.x（自动化）验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **299 passed** |
| 设置 schema | `pytest tests/test_settings/test_schema.py -q` | 7 passed（字段数随新设置更新） |
| 批量相邻 | `pytest tests/test_auto_labeling/test_batch_range.py -q` | 2 passed + 6 subtests |
| 数字矩形 | `pytest tests/test_labeling/test_digit_rectangle_save.py test_digit_label_actions.py -q` | 48 passed |
| 静态检查 | `flake8` 新增代码零告警；`black --check` 三个新建文件通过 | 3 处既有代码风格告警未改（避免无关 diff） |
| 结构校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | valid |

新增用例：`test_csv_contract.py`（17+7 参数化）、`test_fault_matrix.py` 18、`test_export_snapshot.py` 5。
性能基准：`benchmarks/correction_metrics_20261111/`（服务层实测，GUI p95 未测）。
详见 [implementation-batch3-8x-9x-20261111.md](implementation-batch3-8x-9x-20261111.md)。

## 2.8 第 3 批 10.x（交付与回退）验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **311 passed**（含回退 12 用例） |
| 用户说明 | `docs/zh_cn/correction_cost_statistics.md`、`docs/en/correction_cost_statistics.md` | 13 节，事实逐项对照代码 |
| 回退验证 | `tests/test_correction_metrics/test_rollback.py` | 12 passed：关闭零副作用、stop 安全降级、统计库保留/备份/删除、标注 JSON 字节不变、训练导出键集不变 |
| 人工验收清单 | [manual-acceptance-checklist.md](manual-acceptance-checklist.md) | 26 项，全部待执行 |

详见 [implementation-batch3-10x-20261111.md](implementation-batch3-10x-20261111.md)。

## 2.9 第 4 批（遗留代码项）验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **334 passed**（新增 23 用例） |
| 设置/组件回归 | `pytest tests/test_settings tests/test_widgets -q --tb=no -rf` | 142 passed / 1 skipped / 4 failed（画布调整、工具栏几何，本功能未触及） |
| 标注回归（抽样） | `pytest tests/test_labeling/test_edit_mode_shortcut.py tests/test_labeling/test_label_widget_brush_mode.py` | 8 passed / 1 failed（沙箱 `config.yaml` 写保护，非功能失败） |
| 静态检查 | `flake8`（7 个改动文件） | 新增代码零告警；仅 3 条既有告警（W504 / E129） |
| 结构校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | valid |

新增用例：`test_identity_digest.py` 5（2.2）、`test_taxonomy.py` +4（2.5）、
`test_fault_matrix.py` +3（3.3）、`test_net_diff.py` +3（4.4）、`test_checkpoint.py` +2（5.1）、
`test_completion_extra.py` +2（5.5 / 6.5）、`test_timing.py` +1（6.6）、
`test_panel_review.py` +2、`test_report_dialog.py` +1。
详见 [implementation-batch4-20261111.md](implementation-batch4-20261111.md)。

## 3. 需求到证据

四份 spec 共 33 Requirement / 69 Scenario。逐条映射与实现状态的当前快照见
[scenario-coverage.md](scenario-coverage.md)；本文件只汇总可执行证据，**不据 spec 数量推断
全部 Scenario 已覆盖**。自动化证据集中在 `tests/test_correction_metrics/`（334 用例），
真实屏幕语义（计时、焦点、快捷键、拖动体验）仍依赖 §7 的人工验收。

## 4. 当前未完成、未运行与既有失败

- **未完成（必须真实桌面/人工）**：7.5 的 `.ts/.qm` 重编译与真实屏幕焦点/快捷键核对、
  9.2 GUI 逐入口回归、9.4 GUI 主线程 p95 与 10,000 图规模、9.5 两位使用者对照试用、
  10.4 的 GUI 关闭/回退验证。
- **未运行**：全项目测试（`pytest tests`）。`tests/test_labeling` 在沙箱内运行极慢并出现
  配置写保护失败，本次只抽样运行；`tests/test_pointcloud` 按项目约定在 Windows 上不运行。
- **既有失败（与本功能无关，未计入通过数）**：
  - `tests/test_widgets/test_canvas_adjustment.py` 2 例（调整节流与 tooltip 文案）、
    `tests/test_widgets/test_toolbar_layout.py` 2 例（工具栏几何；CI 亦排除该文件）；
  - `tests/test_labeling/test_edit_mode_shortcut.py::test_ctrl_j_returns_from_rectangle_creation`
    在沙箱内把 `config.yaml` 写到 `tests/conftest.py` 隔离区之外，触发写保护断言。
  未放宽任何写保护断言。

## 5. OpenSpec 结构校验

```text
openspec validate add-annotation-correction-cost-statistics --strict
→ Change 'add-annotation-correction-cost-statistics' is valid
```

## 6. 结论

第 1–4 批完成了从纯数据契约、版本化本地存储、编辑/预标注/保存/完成/计时接入，到面板、汇总、
CSV 与交付文档的代码实施；自动化测试 334 通过，服务层故障矩阵与性能基准已有记录。第 4 批修复了
"完成本轮后计时器未关闭"的真实缺陷，并补齐身份摘要、类别版本、存储重试、模型运行/阻塞等待展示
与崩溃尾段处理。

**仍然不能宣称功能验收通过**：真实屏幕 GUI 回归、GUI 性能与 10,000 图规模、两位使用者试用、
以及 `.ts/.qm` 重编译尚未完成。在这些项目完成并回填证据前，`tasks.md` 的 7.5/9.2/9.4/9.5/10.4
保持未勾选，本变更不归档。

## 7. 人工验收（未完成）

必须在真实桌面执行的验收项已整理为 [人工验收清单](manual-acceptance-checklist.md)：GUI 各矩形入口回归（9.2）、关闭统计后的 GUI 回归（10.4）、GUI 性能与 10,000 图规模（9.4）、计时语义人工确认、两位使用者对照试用（9.5）、四语资源重编译与分发检查（7.5 尾项）。

在这些项目完成并回填证据之前：

- 不勾选 `tasks.md` 的 9.2、9.4、9.5、10.4 与 7.5；
- 不宣称"功能已验收""能减少工作量"或任何质量/绩效结论；
- 不归档本变更。

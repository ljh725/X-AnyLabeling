# 第 3 批（7.x）实施记录（2026-11-11）：工作流入口、面板、汇总与导出界面

范围：tasks.md **7.1、7.2、7.3、7.4**（本批确认完成）；**7.5 除 `.ts/.qm` 重编译与真实屏幕核对外完成**。

## 1. 7.1 默认关闭的工作流入口与零负担

- 新增设置项 `correction_metrics_enabled`（bool，默认 **False**）：`configs/xanylabeling_config.yaml` 与 `settings/schema.py` 的默认表一致；`settings/runtime_applier.py` 增加 `apply_correction_metrics()`：停用即 `controller.stop()` 并清空引用，异常只记 warning。
- `open_correction_metrics()` 在 **import controller 之前**判断开关：未启用时提示"统计未启用，可在设置中开启"并返回 —— 不创建 controller、不建统计库、不启动计时器；启用时按原流程启动并在状态栏显示启动范围（图片根/标注根）。
- 面板新增"数据集"行显示 `controller.scope_label`（无则 N/A），与状态栏共同满足"启动范围可见"。
- 验证：`tests/test_correction_metrics/test_settings_gate.py` 9 用例（未启用零副作用、启用生效、停用 stop、schema 默认值、面板作用域显示）。

## 2. 7.2 当前图片面板

- 字段核对：原有 14 个字段 + 草稿/已保存各 6 个净结果行 + 未保存徽标全部在位；本轮补 **数据集行**与**阶段标签**。新增测试用真实 controller/SQLite 断言 **26 个字段**存在且非空，并真实编辑验证 `draft_added=1 / saved_added=0`、徽标出现、`transactions=touches=1`。
- 动作：开始/暂停/继续、完成本轮（`finish_round`）、查看汇总、**继续修正**（`resume_round`）、**开始复核**（`start_review`，复核轮文案切换为"完成复核"、按钮在复核轮内禁用并给原因）、空闲确认。
- 时间显示修正：实时轮次改取实时计数器；已完成或存在排除空闲时取持久化的 `adjusted_working`，避免显示过期检查点。

## 3. 7.3 汇总的范围、可比集合与批量完成

- 工具栏新增「范围」下拉（全部 / 当前有效完成 / 全部历史）与「模型版本」下拉；`refresh()` 只读一次库冻结快照，切换筛选走 `reporting.filter_rounds`（当前范围再叠加 `completed`）**不重读库**；表格、分组、排除统计与 CSV 全部使用同一份冻结快照。
- 顶部显示可比/排除数量与**排除原因计数**（沿用 `exclusion_reasons`），无排除时显示 "Nothing excluded"。
- 新增「完成可完成项…」按钮（5.3 的界面入口）：调用 `controller.complete_scope()`，非模态展示 `已完成 N 轮 · 跳过 M` 与跳过原因计数，随后刷新；不写任何完成/checked 状态，未保存/失败项只按 controller 返回的 skipped 展示。**已知限制**：作用于全库、与当前筛选无关，且为同步调用（万级库会短暂阻塞）。
- 验证：`test_report_dialog.py` 扩到 **24 用例**（范围不重读库、版本过滤、排除计数随范围变化、完成按钮调用与刷新、跳过原因、CSV 与快照一致）。

## 4. 7.4 口径与分组

- 类别方向表保留 `denominator`/`rounds` 列并加说明（分母=该方向适用样本量，N/A=无适用样本，比较状态列不伪装 0）。
- 目标数量分组新增 `range` 列（同桶 `final_count` min–max）与既有样本量列；空图 0 目标组保留；0 对象时秒/百对象为 N/A。
- 模型版本分组注明"同图重复预测不是独立对照"。
- 三张表均**不含**准确率、每类精确用时、自动提速等列（测试同时断言列定义与真实表头）。

## 5. 7.5 语言资源、窄窗口与焦点

- **焦点**：定位到根因是"给带 parent 的子控件设置 `Qt.Tool` 会把它变成独立顶层窗口、导致宿主失活"，并非 `show_panel()` 抢焦点。修正为：`Qt.Tool` 仅用于无父窗口的独立用法；侧栏用法保持普通子控件 + `WA_ShowWithoutActivating`，面板与全部子控件 `NoFocus`。测试断言打开面板后 `focusWidget()` 仍是画布、`selected_shapes` 不变。
- **窄窗口**：复核阶段（阶段标签+复核按钮可见）在 240/320 px 下断言最小宽 ≤ 240（实测 56）、所有可见控件不越界、两两不重叠。
- **i18n**：`i18n.py` 四语文案补至 MESSAGES 201 / TRANSLATIONS 81（面板 4 条 + 汇总 18 条全部四语）。
- **未完成**：`.ts/.qm` 未重新编译（新文案走 `TRANSLATIONS` 回落，界面语言正确；分发前需 `lupdate + lrelease + pyrcc6`），真实屏幕焦点/快捷键核对未做 —— 故 7.5 不勾选。

## 6. 验证汇总

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **253 passed / 0 failed**（6.6 s） |
| 新增用例 | — | settings_gate 9 + panel/review 11 + report 8（净增） |
| OpenSpec 校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | valid |

## 7. 工作区说明

本批改动与另一会话的"数字快捷键栏"工作共享 4 个文件（`configs/xanylabeling_config.yaml`、`settings/schema.py`、`settings/runtime_applier.py`、`label_widget.py`）。提交时按 hunk 精确分离：只把本批的 `correction_metrics` 相关行写入索引，对方改动完整保留在工作区、未提交、未修改。

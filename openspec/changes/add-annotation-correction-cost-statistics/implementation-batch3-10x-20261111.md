# 第 3 批（10.x）交付记录（2026-11-11）

范围：tasks.md **10.1、10.2、10.3**（本批确认完成）；**10.4 仅服务层验证通过，GUI 部分待人工**（不勾选）。

## 1. 10.1 用户说明（中英双语）

- `docs/zh_cn/correction_cost_statistics.md`（主文档，13 节）
- `docs/en/correction_cost_statistics.md`（英文对应版）

覆盖：起点 B/过程/净值/草稿/已保存的概念；启用与统计范围；面板字段、按钮、空闲确认；过程与净值口径；时间口径（应用内处理时间、暂停/后台/锁屏、120 秒只提示不自动扣、后台推理不重复相加、不能据此做绩效结论）；来源未知仅披露；类别一对一改名/合并拆分与 N/A；分母与零基线；记录完整性 issues 的中文含义；汇总范围与 CSV（两表 + 字典、冻结快照）；**可复现示例**（30 矩形自制合成样本：B30/F30、+2/−2、改框 5、改类 4、修改原对象 10、原样保留 20、修改率 33.3%、事务 11/触达 13/去重 12，并注明非真实数据）；已知限制（完成≠质量通过、面板为侧栏子面板、`.ts/.qm` 未重编译、仅普通矩形）。

文档中的事实逐条对照代码（设置键与默认值、状态栏文案、计时六态、`DISCLOSURE_ISSUES`、issues 标签、`filter_rounds`、CSV 列与 BOM、统计库位置）；没有写入未实现的能力（无 PDF、无自动质量评分、无排名/准确率/节省金额）。

**已修正**：示例中"改框/改类重叠"的叙述与数值不一致（写成 3 个对象重叠），实际为 1 个对象既改框又改类；中英文同步更正。未改动 `docs/*/user_guide.md`（该文件含另一会话未提交改动），建议后续加一行目录链接。

## 2. 10.2 verification.md 汇总

`verification.md` 重构为可交付形态：

- 顶部"当前状态"改为**第一版代码完成、自动化通过、真实屏幕人工验收未完成、未归档**；
- 新增 **§0 交付状态**：代码进度 37/54、自动测试数量、可用路径、未完成项、明确"自动化通过 ≠ 功能验收通过"；
- §1 批次总览按实际交付更新（批次 1/2/3 及各自证据文件）；
- 新增 **§7 人工验收**：指向 [manual-acceptance-checklist.md](manual-acceptance-checklist.md)，并规定未完成前不勾选 9.2/9.4/9.5/10.4/7.5、不宣称质量或绩效结论、不归档。

新增 [manual-acceptance-checklist.md](manual-acceptance-checklist.md)：A（GUI 定向回归 12 项）、B（关闭统计后的回归 3 项）、C（GUI 性能与规模 4 项）、D（计时语义人工确认 4 项）、E（两位使用者试用 4 项）、F（语言资源与分发 3 项），并规定记录方式。

## 3. 10.3 定制台账更新

- 重写 `docs/custom_changes/2026-11-03-correction-cost-statistics.md`：保留 2026-11-03 历史原文，新增实施更新——实施提交表（7 个提交）、修改位置与方法（三层 + 来源兼容）、配置/数据/兼容（开关默认 False、统计库位置与 schema 版本、标注 JSON 零变化、时间口径、质量语义）、验证（299+ 自动用例、性能实测、故障矩阵、未完成人工项）、**备份与回退 5 步**、后续修订表。
- 更新 `docs/custom_changes/README.md` 索引中 CUSTOM-111 的状态为"代码实施完成、自动化验证通过（37/54）；真实屏幕人工验收与 GUI 性能未完成，变更未归档"，并补验证链接。

## 4. 10.4 回退验证（服务层通过，GUI 待人工）

`tests/test_correction_metrics/test_rollback.py` **12 用例全部通过**（实现零改动）：

| 场景 | 结果 |
| --- | --- |
| 关闭设置 → 调入口 | 不建 controller / sqlite / QTimer；`notify_metrics` 空转不抛 |
| 停用运行中会话 | `enabled False`；edit/prepare_save/save_result/discard/prediction_applied 返回安全默认值；重复 stop 幂等 |
| 保留统计库 | stop 后新 `MetricsStore` 可打开并读回行、可继续导出 CSV |
| 备份统计库 | 先 `close()`（无 `-wal` 残留）再复制，副本与原库各读出 1 行 |
| 删除统计库 | 标注 JSON 字节不变；新会话新建空库、旧 round_id 不复活 |
| 旧标注可用 | 启用→记录→保存→关闭全流程后 JSON 字节完全一致，键集合不变 |
| 训练导出兼容 | payload 键集合不增长 |
| 未知 schema 版本 | 错误可见、不覆盖原库，标注不受影响 |

**核心结论**：删除统计库只损失历史统计（轮次/计数/时间/完成记录），不损失图片与标注。

**未覆盖（需人工）**：菜单 QAction 启用态与快捷键、panel/report_dialog 的隐藏与导出进度、真实 `LabelFile.save` 原子替换、`utils/export.py` 各格式训练导出实跑、设置重启持久化、关闭后后台线程/计时器的界面级断言 —— 已列入人工验收清单 A12/B2。

## 5. 验证汇总

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **311 passed**（299 + rollback 12） |
| OpenSpec 校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | valid |

## 6. 已知限制（交付时如实记录）

- **面板未停靠右侧栏**：`controller.show_panel()` 以标注窗口内的可收起浮层显示（父控件 `raise_`），没有加入 `right_sidebar_layout`。这是可用的第一版形态，但非"侧栏停靠面板"；若要停靠，宿主侧加一行 `right_sidebar_layout.insertWidget(<scroll_area 之后>, panel)`，并在面板外套 `QScrollArea`/设最大高度（面板完整数据约 660 px 高）。
- 面板高度较大时可能遮挡画布区域；收起后仅 27 px。
- `.ts/.qm` 未重编译（新文案走内置四语言回退）。

## 7. 仍然未完成

9.2（GUI 回归）、9.4（GUI p95 与万级规模）、9.5（两位使用者试用）、10.4 的 GUI 部分、7.5 尾项（`.ts/.qm` 重编译）、5.3/5.5 统一评估、6.5/6.6、4.4、批次 1 遗留 2.2/2.5/3.3。全部在人工验收清单中有对应条目。

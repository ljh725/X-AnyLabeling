# 第 3 批（8.x + 9.x 自动化部分）实施记录（2026-11-11）

范围：tasks.md **8.1–8.5、9.1、9.3、9.6**（本批确认完成）；**9.4 仅服务层实测**（GUI 目标未测，不勾选）；9.2、9.5 未做（不勾选）。

## 1. 8.x 可追溯导出（全部为验证，不改实现）

| 任务 | 验证内容 | 证据 |
| --- | --- | --- |
| 8.1 | 三种表头逐项等于 `export.CSV_COLUMNS`；images 行含来源/图片/版本/会话/阶段/完成/完整性/计数/时间；classes 行含方向与分母；dictionary 覆盖 images∪classes 全部列名且含 N/A 与公式转义说明；两 session 的轮次只导出 1 行且时间求和（10.5 s） | `test_csv_contract.py`（17 用例 + 7 参数化） |
| 8.2 | 导出使用调用方冻结快照：冻结后新增轮次不进入导出；不传 `rows` 时读当前行；已保存行不含草稿值 | `test_export_snapshot.py`（5）、`test_report_dialog.py` |
| 8.3 | UTF-8 BOM；逗号/双引号/换行/中文可被 `csv.reader` 还原；`=`/`+`/`-`/`@`、前导空格、真实制表/换行开头均加 `'` 前缀且读回保留原值；`None→N/A`、`0→0`、`""→""`；数值不加引号 | `test_csv_contract.py` |
| 8.4 | 取消后无目标/临时残留；目标已存在时取消保持字节不变；发布异常时旧目标不变且临时文件清理；成功发布后清理 | `test_csv_contract.py`、`test_report_dialog.py` |
| 8.5 | 面板投影（`view_records`/`class_details`）与 CSV 单元格逐项相等且 UI 列 ⊆ CSV 列；含 `api_key/authorization/token` 的行经白名单后 CSV 无密钥形态；统计链路**不写标注 JSON**（保存前后字节不变）、不修改传入 shapes | `test_csv_contract.py`、`test_export_snapshot.py` |

## 2. 9.1 纯服务场景覆盖

核对后：9 类场景中 3 类**完全缺失**、2 类**只测一半**，本批补齐（写在 `test_fault_matrix.py`）：

- 改类与改框重叠（同一事务既换 label 又改 points）→ `modified_original` 去重为 1；
- 撤销回起点后的净结果（此前只测 `undo_of` 关联）；
- 新增后再删除 → 净结果归零、过程成本保留；
- 1 px 真实位移必须算改框（此前只测 int/float 等价）；
- 整图零对象的可比性与零分母 N/A。

其余 4 类由既有套件覆盖并在覆盖表指名到用例：多对象事务、重复回调幂等、类别更名/合并、混合范围。

## 3. 9.3 故障矩阵（12 行全绿）

| 故障 | 预期 | 实测 |
| --- | --- | --- |
| 统计库被 `BEGIN EXCLUSIVE` 独占 | 写入记 `storage-gap`、`comparable=False`、不抛异常 | 通过 |
| 库文件只读（`stat.S_IREAD`） | `store.error` 可见、降级；恢复可写后新会话继续 | 通过 |
| 磁盘错误（monkeypatch `MetricsStore._write`） | 缺口可见、不静默丢 | 通过（`sqlite3.Connection.execute` 是 C 类型不可 patch） |
| 队列饱和（`queue_size=1` 灌 200 次） | 记 `storage-gap` | 通过 |
| 崩溃恢复 pending 匹配 | 恢复为已保存、`completed=False` | 通过 |
| 崩溃恢复 pending 不匹配 | `external-annotation-change`、不冒充完成 | 通过 |
| 统计彻底坏掉时保存 | 假保存流程仍成功（hooks 吞异常） | 通过 |
| 导出包含未保存草稿？ | `final_count is None` + `unsaved-result`，不冒充交付 | 通过 |

`storage-gap` 会经 `_fault()` 合并进 state 的 `issues` 并使 `comparable=False`，披露链路完整（曾怀疑"缺口只在 `store.gaps` 不进行"，实测否证）。

## 4. 9.6 回归与静态检查

| 检查 | 结果 |
| --- | --- |
| `pytest tests/test_correction_metrics`（含本批新增 46 用例） | **299 passed** |
| `pytest tests/test_settings/test_schema.py`（字段数随新设置更新：151→152、非快捷键 57→58、General 9→10） | **7 passed** |
| `pytest tests/test_auto_labeling/test_batch_range.py` | 2 passed + 6 subtests |
| `pytest tests/test_inspection/test_translations.py` | 通过 |
| `pytest tests/test_labeling/test_digit_rectangle_save.py test_digit_label_actions.py` | **48 passed**（96 s） |
| `flake8 anylabeling/services/correction_metrics anylabeling/views/labeling/correction_metrics` | 新增代码零告警；剩余 3 处（`core.py` W504、`storage.py` 两处 E129）为**既有代码**风格问题，未改动以避免无关 diff |
| `black --check` 三个新建文件（controller/panel/report_dialog） | 通过（本批已格式化；其余既有文件未被 black 覆盖，保持原状） |
| `openspec validate --strict` | valid |

**未运行并如实列出**：GUI 级回归（`tests/test_labeling` 整体、`tests/test_canvas`、Inspector 对话框等）在本沙箱离屏构造 `MainWindow` 会挂起（既有环境限制）；全项目测试未跑；9.2 因此不勾选。

本批还修复了静态检查发现的真实缺陷：`panel.py` 中 `_on_summary_clicked` 被重复定义（F811）；`core.differences` 的分母表达式为重排这段逻辑做了等价改写（`class_kinds` 常量 + 括号化，行为不变、测试全绿）。

## 5. 9.4 服务层性能（部分，未勾选）

基准目录 `benchmarks/correction_metrics_20261111/`（`bench.py` 可复跑、`RESULTS.md`、`results.json`）。
机器：Windows 10 19045 / 12 CPU / Python 3.12.12；种子 20261111。

| 项目 | p95 | 目标 | 结论 |
| --- | --- | --- | --- |
| 采集 30 矩形 `controller.edit` | 0.095 ms（p50 0.035） | GUI ≤ 5 ms（未测） | 服务层远低于目标 |
| 采集 300 矩形 | 0.073 ms（p50 0.050） | 同上 | 同上 |
| 无统计基线 | 0.0027 ms | 对照 | 增量 +0.03 ms 量级 |
| 首屏 `rows(50)` 热/冷 | 5.68 / 4.29 ms（2,000 轮库） | ≤ 2 s | 毫秒级 |
| `count()` 热/冷 | 2.73 / 1.49 ms | — | — |
| 导出第 100 行取消 | 6.29 ms | ≤ 1 s | **通过**，无残留 |
| `tick()` / `time_checkpoint()` | 0.0029 / 0.0222 ms | ≤ 100 ms | **通过** |

**未达标/未测（如实记录）**：10,000 轮库在 60 s 预算内只建成 2,000 轮（约 31.5 ms/轮），5,000 行导出同理降为 2,200 行源；**GUI 主线程拖动 p95 未测**（无 GUI 事件循环），`RESULTS.md` 顶部已显著标注不得当作 GUI 验收。

**工程事实（非 spec 缺陷）**：`MetricsStore.flush()` 默认 2 s 在 200 条排队写入下返回 `False`，但数据随后仍落库且 `gaps` 为空 —— 调用方若把 `False` 当写失败会误报（建议批量路径显式加长 timeout）；写队列默认 256，批量 `open_round` 需分段 flush，否则超出部分按降级契约记 `storage-gap`。

## 6. 仍未完成

- **9.2** GUI 定向回归（沙箱无法离屏构造主窗口；需真实桌面执行）。
- **9.4** GUI 主线程 p95、10,000 图/5,000 行规模未测。
- **9.5** 两位使用者人工试用（未做）。
- 批次 1 遗留：2.2（图片摘要计算）、2.5（显式类别版本对象）、3.3（重试入口）。
- `.ts/.qm` 重编译（分发前）。

# 第 1 批实施记录（2026-11-10）

范围：`tasks.md` **1.2–1.4、2.1–2.6、3.1–3.5**（实施基线、数据契约与纯逻辑、本地存储）。
批前基线提交：`52b7a2a2`（分支 `codex/4.2.1-baseline-organization`）；备份节点 `backup/4.2.1-20261110-organized-baseline` = `e40c537c`。

## 1. 本批交付

| 类别 | 交付 | 证据 |
| --- | --- | --- |
| 入口矩阵（1.2） | 30 个矩形修改入口，标注事务完成边界、保存路径与采集状态 | [entry-matrix.md](entry-matrix.md) |
| 固定样本（1.3） | 8 类合成场景（空图 / 30 人多类 / 300 框压力 / 遮挡小目标 / 部分锁定 / 混合非矩形 / 未知来源 / 5 人工+3 AI），确定性生成、固定对象 ID、预期净值 | [samples.md](samples.md)、`tests/test_correction_metrics/synthetic.py` |
| 场景覆盖表（1.4） | 四份 spec 的 33 Requirement / 69 Scenario 逐条映射到任务与证据 | [scenario-coverage.md](scenario-coverage.md) |
| 服务层缺口审计 | 12 条任务逐项判定 + 缺陷复现 | [gap-audit-20261110.md](gap-audit-20261110.md) |
| 单元测试 | 新增 `tests/test_correction_metrics/`（Qt-free）：9 个文件、**64 个用例** | 见 §3 |
| 缺陷修复 | M1、M3、M4 三条与 spec 冲突的实现缺陷已修；M2 经复核**不成立**（见 §4） | 见 §4 |

测试包结构：

| 文件 | 用例数 | 覆盖 |
| --- | ---: | --- |
| `synthetic.py` | — | 8 类固定合成样本 + 脚本化编辑序列 + 内存 store 替身 |
| `test_net_diff.py` | 12 | 2.3 几何规范化与 B/F/G/C 净差异 |
| `test_transactions.py` | 9 | 2.4 事务 / 触达 / 去重计数与幂等 |
| `test_taxonomy.py` | 7 | 2.5 类别版本、一对一映射、合并传播 N/A |
| `test_scope.py` | 9 | 2.6 支持范围、类型转换、来源未知、缺口 |
| `test_storage.py` | 10 | 3.1–3.3 版本化 SQLite、有界队列、饱和降级 |
| `test_checkpoint.py` | 10 | 3.4–3.5 保存检查点、恢复、外部修改、另存为、中断 |
| `test_completeness_and_faults.py` | 7 | 本批修复的 M1/M3/M4 回归（新增） |

## 2. 测试结果

命令（仓库根目录，离屏 Qt，使用项目 conda 环境）：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='D:/X-AnyLabeling-4.2.1'
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_correction_metrics -q --tb=short --color=no -p no:cacheprovider
```

结果：**64 passed in 0.92 s**（0 failed / 0 skipped / 0 xfail）。

定向回归（受影响模块相邻用例）：

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_settings/test_schema.py` | 7 passed |
| `pytest tests/test_labeling/test_correction_metrics_gate.py` | 1 passed；1 项 `ERROR at setup`：`tmp_path` 在 `PermissionError: [WinError 5] .tmp/.../pytest-of-JJH` 处失败 |

该 `ERROR` 是**本沙箱已知限制**（pytest 以 `0o700` 建临时目录被 ACL 拒绝），不是本批改动引入；同一用例在带 `pytest_tmp777` 插件时会在离屏 `MainWindow` 构造阶段挂起，属 `verification.md` 已记录的既有环境问题。这些既有失败与本批新增测试的运行结果分开记录，未计入通过数。

红→绿记录（本批修复）：

1. 先写 `test_completeness_and_faults.py` 并运行 → **5 failed, 2 passed**（M1 三条、M4 一条、M3 一条红）。
2. 应用修复后重跑 → 仍 2 failed：① 分母表达式优先级写错（`or None` 落在条件真分支上，`added/final` 行仍取 `len(b)=0`）；② 既有 `test_scope.py` 断言旧语义（`comparable is False`）。
3. 修正优先级并把该断言更新为"来源未知是披露项"后 → **64 passed**。

## 3. 缺陷修复明细

### M1（2.6）来源未知被当成"不可比"，历史标注轮次在汇总里全部消失

- 现象：任意 `origin="unknown-existing"` 的轮次 `comparable` 恒为 `False`，`reporting.outcome / density_groups / class_groups` 因此把它整体排除。真实使用中"从已有标注开始统计"是最常见起点，等于统计在汇总页一条都不出现。
- 与 spec 冲突：baseline `BASE-2.1` 只要求披露未知来源；events spec 只允许范围、类型转换、日志/计时缺口使完整对照失效。
- 修复：`core.py` 新增 `DISCLOSURE_ISSUES = frozenset({"unknown-origin"})`，`report_row` 改为 `comparable = not (issues - DISCLOSURE_ISSUES)`；`reporting.exclusion_reasons` 只把非披露项列为排除理由（仍保留 `unsaved`/`unfinished`）。
- 证据：`test_completeness_and_faults.py` 三个用例；`test_scope.py::test_unknown_origin_leaves_ai_count_unknown` 由"不可比"改为"可比且披露"。范围缺口（`partial-scope`）仍阻断，见 `test_scope_gap_is_still_a_blocking_reason`。

### M3（3.3）无归属故障永不可见，预测来源静默丢失

- 现象：`_fault()` 允许空 `round_id`，`gaps("")` 没有任何读取方；`record_prediction()` 队列满时只返回 `None`，受影响轮次 issues 里没有缺口标记。批量预标注的预测来源会安静消失。
- 修复：`storage.py` 增加按图片/标注归属的故障表与 `gaps_for(image, label)`；`record_prediction` 失败写 `prediction-gap` 到该图片；`CorrectionRound.row()` 与 `iter_rows()` 合并轮次缺口 + 图片缺口。
- 证据：`test_completeness_and_faults.py::test_failed_prediction_record_leaves_a_visible_gap`（关闭库后调用，断言 `gaps_for` 含 `prediction-gap`、`row()["issues"]` 含 `prediction-gap` 且 `comparable is False`）。

### M4（2.5）B 为空时类别明细分母输出 0 而非 N/A

- 与 spec 冲突：baseline `BASE-6`／events `EVT-6` 明确"分母为零时输出 N/A 而非零或无穷"。
- 修复：`core.differences()` 的 `denominator` 改为 `(… if kind in (initial/geometry/deleted/class_changed) else len(b)) or None`。
- 证据：`test_empty_baseline_class_rows_report_na_denominators` 断言 B 为空时两行分母均为 `None`。

### M2（审计提出，复核后**不成立**）

- 审计主张：baseline `A` → 个人改为 `A2` → `taxonomy({"A": "A2x"})` 后 `class_changed=1` 是"幻影改类"，应为 0。
- 复核：events spec 的场景明确规定"改名前已有个别改类…保留该对象从 B 到 A2 的语义改类"，即个人改类**必须**保留为一次真实改类。实测三种情形均符合 spec：
  1. `B --个人--> A --全局改名 A→A2-->` → `class_changed=1`（保留语义改类）；
  2. `A --个人--> A2 --全局改名 A→A2x-->` → `class_changed=1`（个人目标类不在映射内，保留）；
  3. 无个人修改、纯一对一改名 → `class_changed=0` 且 `comparable=True`。
- 结论：**保持现状**，不修改实现；若未来要支持"个人改类恰好是全局改名的一部分"，应通过显式类别版本对象表达，而不是靠别名链猜测。

### 遗留观察 OBS-1

`CorrectionRound.patch()/sync()` 返回 `True` 表示"草稿已记录变化"，不表示"已落库"。落库失败通过 `store.error` / `gaps()` / `row()["issues"]` 三层披露（用例已断言披露，不断言返回值），避免锁死尚未定稿的返回值语义；接入 GUI 时若用返回值提示"已记录"需注意此区别。

## 4. 未完成项（本批明确保留）

| 任务 | 仍未完成的部分 |
| --- | --- |
| 2.2 | 服务层只接收调用方传入的图片内容摘要，**图片摘要计算未实现**（属 UI/加载层接入） |
| 2.5 | 映射与 N/A 传播已实现并有测试，但**缺显式类别版本对象**（当前只有 `alias` 字典 + `provenance.category_version` 字段） |
| 3.3 | 降级与缺口可见已实现；**缺重试/恢复入口**与只读、磁盘满的专门用例（其余依赖 SQLite 异常透传） |
| 3.4 | 保存检查点与回读核对已实现并有测试；故障注入以 API 状态模拟，**未做 SQLite 层 monkeypatch 注入** |
| 4.x–8.x | 全部未实施（编辑/预标注接入、完成状态、计时 UI、汇总与 CSV 界面），属第 2、3 批 |

## 5. 统计库备份与回退说明（配合任务 3.5）

- 统计库位置：应用数据目录 `correction_metrics/<dataset-id>.sqlite3`，**只允许本地盘**；`MetricsStore.__init__` 对 UNC/网络盘直接拒绝（`_local_path()`），避免在共享目录并发写。
- 备份：库为独立 SQLite 文件，可直接复制/压缩；WAL 模式下请先 `flush()` 并关闭连接（`MetricsStore.close()`）再复制，或用 SQLite 在线备份接口。
- 回退：关闭统计功能即不建库、不写事件（`metrics_available()` 为假时全部记录点空转）；删除或改名统计库不影响标注 JSON 与训练导出，重新启用会为新轮次建立新起点，历史标注按 `unknown-existing` 处理。
- 版本：`PRAGMA user_version = SCHEMA_VERSION = 1`；遇到未知版本号会拒绝打开并保留原文件（不覆盖、不猜测迁移），见 `test_version_mismatch_is_refused_without_overwriting_the_file`。

## 6. 环境与权限记录

- 本会话受限模式对 `anylabeling/`、`tests/`、`openspec/`、`docs/`、`.git/` 无写权限；本批所有写入与提交均在单次提升权限的命令中完成，未改动任何文件权限或所有者。
- 测试临时目录：`tests/test_correction_metrics/conftest.py` 优先使用 pytest `tmp_path`，在本沙箱不可用时回退到 `.tmp/correction_metrics_work/`（已被 `.gitignore` 覆盖）。
- 团队审计报告作者当时未使用项目 conda 环境（`x-anylabeling-cu12`，已装 PyQt6），因此 `gap-audit-20261110.md` 与 `scenario-coverage.md` 中"仓库测试无法运行"的表述**不成立**；已在两份文件顶部标注更正，其余分析结论有效。

# 01 · L1/L2 数据质检引擎
#### L1/L2 Quality Inspection Engine

> 一套纯 Python 的双层质检引擎：L1 检查 JSON 结构合法性，L2 用 12 条几何/视觉规则评估 face/head/person 三类的跨类关系，配合跨类匹配算法和阈值评估系统。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

姿态标注数据集通常包含三类对象：**face（人脸框）、head（头部框）、person（人体框）**，外加 person 上的 COCO 17 关键点。质检时需要验证大量几何/视觉关系：

- face 是否落在匹配的 head 框内？
- head 是否位于 person 的上端（而非脚部）？
- face/head、head/person 的面积比是否合理？
- 关键点是否越出 person 框或身体垂直分区？
- 三类框的大小顺序（face < head < person）是否被破坏？

人工逐张检查成本极高，且这些规则难以在团队成员间复用。本引擎把这些规则**固化为可配置、可批跑、可审计的代码**。

---

## 架构设计

```
                    ┌─────────────────────────────────────┐
                    │     threshold_profile.yaml          │  ← 阈值配置（YAML 驱动）
                    │  (l1_l2_threshold_profile_v0)       │
                    └─────────────────┬───────────────────┘
                                      │ load
                                      ▼
  LabelMe JSON ──► QcShapeLoader ──► QcFile[] ──► ┌──────────────────────┐
                                                  │  L1 Rules (5条)       │  结构合法性
                                                  │  字段/标签/shape/      │
                                                  │  points/group_id/bbox │
                                                  └──────────┬───────────┘
                                                             │
                                                  ┌──────────▼───────────┐
                                                  │  Cross-class Matching │  face→head→person
                                                  │  (hard filter+score)  │  临时推断，不写回
                                                  └──────────┬───────────┘
                                                             │
                                                  ┌──────────▼───────────┐
                                                  │  L2 Rules (12条)      │  几何/视觉关系
                                                  │  + severity_eval      │  + 阈值评估降级
                                                  └──────────┬───────────┘
                                                             │
                                          ┌──────────────────┼──────────────────┐
                                          ▼                  ▼                  ▼
                                   review.tsv          report.json     threshold_suggestion.json
                                  (人工复核)         (完整证据账本)        (非约束建议)
```

**关键架构约束**：整个 `quality/` 子包**零 PyQt 依赖**，因此：
- CLI（`scripts/run_l1l2_qc.py`）与 UI 扫描流共享同一份逻辑，避免双实现漂移
- 可在无显示器的 CI/headless 环境直接跑批
- 全部测试在纯 Python 下 `pytest` 运行，无需 Qt 事件循环

---

## 技术亮点

### 1. 纯 Python / PyQt 严格分层

`quality/` 目录下 12 个 .py 文件，**没有任何一行** `from PyQt` 或 `import PyQt`（已 grep 验证）。唯一的 PyQt 依赖被刻意隔离在 `quality/` 包**之外**：

- `inspector/quality_scan_worker.py` — `QualityScanThread(QThread)`，把 `run_quality_check` 包成后台线程
- `inspector/quality_review_widget.py` — 纯 UI 层

**为什么重要**：跨类匹配是**临时 QA 推断**（见 `matching.py` docstring），永不写回 `group_id` 或 JSON。分层使"只读"语义在代码结构上无法被破坏——质检代码物理上无法触碰持久化层。

### 2. 12 条 L2 规则速查

| 规则 | 检查内容 | 主指标 |
|------|---------|--------|
| L2-01 | face 找不到/弱匹配 head | `face_head_match_gap` |
| L2-02 | face 框超出匹配 head 框比例 | `overflow_ratio` |
| L2-03 | face/head 面积比超出 [0.05, 0.70] | `area_ratio` (two_sided) |
| L2-04 | face 与 head 中心偏移过大 | `center_alignment` |
| L2-05 | head 找不到/弱匹配 person | `head_person_match_gap` |
| L2-06 | head 相对 person 空间位置异常 | 综合分（x重叠/y_rel/出扩展框） |
| L2-07 | head/person 面积比超出 [0.015, 0.35] | `area_ratio` (two_sided) |
| L2-08 | 跨类大小顺序 face<head<person 被破坏 | 比值阈值 |
| L2-09 | person 同组关键点越出扩展框 | 越界点数+类型 |
| L2-10 | 关键点 y_rel 越出身体垂直分区 | `y_rel` |
| L2-11 | 头部关键点远离 face/head 框 | 远离点数 |
| L2-12 | 单图各类计数 z-score 异常 | `z_score` |

### 3. face→head→person 跨类匹配

两条独立协议，核心设计是**硬过滤先裁候选，再对幸存者加权打分**：

```python
# anylabeling/views/labeling/widgets/inspector/quality/matching.py:10-23
face → head (strict):
    hard filter: x_overlap >= 0.25, y_overlap >= 0.15,
                 face/head area <= 0.85, face center in expanded head 15%,
                 overflow <= 0.30
    score = .35 containment + .20 center_alignment
            + .20 area_ratio + .25 overlap

head → person (loose):
    hard filter: x_overlap >= 0.15,
                 head_center_y <= person_top + 0.60*person_h,
                 head/person area <= 0.40,
                 head center in expanded person 20%
    score = .30 upper_body_position + .25 x_overlap
            + .20 area_ratio + .15 center_distance + .10 keypoint_support
```

打分用**三角函数峰值衰减**（如 `area_ratio_score` 在理想值处峰值，两侧平滑下降），比硬阈值更鲁棒。阈值与权重全部来自 YAML profile，改参不动代码。

### 4. 阈值评估系统（direction + error_requires 降级）

`severity_eval.py` 把所有跨规则的阈值判断集中到一处，让 12 条 L2 规则只管算指标：

- **4 种 direction**：`higher_is_worse` / `lower_is_worse` / `two_sided`（warning 看上下界，error 仅看上界）/ `higher_abs_is_worse`（z-score 用）
- **error_requires 二次确认降级**：规则配了非空 `error_requires` 且 `error_requires_satisfied=False` 时，**error 命中也不升 error，而是 fall-through 到 warning**

这是"宁可降级交人工复核"的保守哲学在代码里的落点。

### 5. 9 级阈值建议触发表

`threshold_suggestion.py` 基于每规则的人工复核统计（true_error_rate / false_positive_rate / acceptable_rate），按优先级决策表产出建议：

| 优先级 | 触发条件 | 建议动作 |
|--------|---------|---------|
| P1 | reviewed < 30 | require_more_review |
| P2 | discussion_rate ≥ 0.25 | definition_review（规则定义存疑） |
| P3 | fp ≥ 0.60 且 true_err < 0.30 | disable_as_strong_rule |
| P4 | fp ≥ 0.50 | relax_threshold |
| P5 | acc ≥ 0.40 且 fp < 0.30 | downgrade_severity |
| P6 | true_err ≥ 0.75 且 fp ≤ 0.15 | keep_threshold |
| P7 | true_err ≥ 0.85, fp ≤ 0.10, reviewed ≥ 100 | tighten_threshold |
| P8 | true_err < 0.40, acc ≥ 0.35 | downgrade_severity |

**关键**：输出永远非约束——`requires_human_approval: True`、`approval.status` 恒为 `"pending"`，不自动改 YAML。

---

## 输出契约

三个文件由 `issue_id`（md5(file|shape|rule|metric)[:16]，不含 run_id）串成闭环：

| 文件 | 用途 | 关键字段 |
|------|------|---------|
| `review.tsv` | 人工复核（8 列，Inspector 可导入） | issue_id, file_path, shape_index, rule_name, severity, message, label, group_id |
| `report.json` | 完整证据账本（schema `l1_l2_qc.v1`） | summary + issues[]（含 primary_metric/metrics/thresholds_hit/match/candidates） |
| `threshold_suggestion.json` | 阈值建议（schema `threshold_suggestion.v1`） | rule_suggestions[]（current/review_stats/suggested_action/proposed/confidence） |

`run_id` 由 `input_root + profile_id + 排序后路径` 的 md5 确定性生成，同批次重跑产出稳定 ID。

---

## 代码定位

| 文件 | 行数 | 职责 |
|------|------|------|
| [`quality/l2_rules.py`](../../anylabeling/views/labeling/widgets/inspector/quality/l2_rules.py) | 1273 | 12 条 L2 规则实现 + `_L2_RUNNERS` 注册表 |
| [`quality/matching.py`](../../anylabeling/views/labeling/widgets/inspector/quality/matching.py) | 456 | face→head / head→person 跨类匹配 |
| [`quality/quality_review_queue.py`](../../anylabeling/views/labeling/widgets/inspector/quality/quality_review_queue.py) | 823 | 纯 Python 复核队列模型 |
| [`quality/quality_issue.py`](../../anylabeling/views/labeling/widgets/inspector/quality/quality_issue.py) | 360 | QcShape/QcFile/QualityIssue 核心数据结构 |
| [`quality/feedback.py`](../../anylabeling/views/labeling/widgets/inspector/quality/feedback.py) | 387 | 人工复核 TSV 读取/聚合 |
| [`quality/threshold_profile.py`](../../anylabeling/views/labeling/widgets/inspector/quality/threshold_profile.py) | 373 | 阈值 YAML 加载器 + 校验器 |
| [`quality/threshold_suggestion.py`](../../anylabeling/views/labeling/widgets/inspector/quality/threshold_suggestion.py) | 369 | 9 级阈值建议生成器 |
| [`quality/l1_rules.py`](../../anylabeling/views/labeling/widgets/inspector/quality/l1_rules.py) | 265 | L1 硬规则（结构合法性） |
| [`quality/geometry.py`](../../anylabeling/views/labeling/widgets/inspector/quality/geometry.py) | 292 | 纯几何原语（bbox/IoU/containment/overflow） |
| [`quality/report_writer.py`](../../anylabeling/views/labeling/widgets/inspector/quality/report_writer.py) | 213 | 运行编排器 + 报告写入 |
| [`quality/severity_eval.py`](../../anylabeling/views/labeling/widgets/inspector/quality/severity_eval.py) | 163 | 阈值评估 + error_requires 降级 |
| [`scripts/run_l1l2_qc.py`](../../scripts/run_l1l2_qc.py) | 172 | CLI 批跑入口 |
| [`configs/quality/l1_l2_threshold_profile_v0.yaml`](../../anylabeling/configs/quality/l1_l2_threshold_profile_v0.yaml) | 307 | 阈值配置 |

**合计：4,354 行**（`quality/` 目录，12 个 .py）

---

## 测试覆盖

| 测试文件 | 用例数 |
|---------|--------|
| [`tests/test_quality_geometry.py`](../../tests/test_quality_geometry.py) | 39 |
| [`tests/test_quality_review_queue.py`](../../tests/test_quality_review_queue.py) | 25 |
| [`tests/test_quality_thresholds.py`](../../tests/test_quality_thresholds.py) | 23 |
| [`tests/test_quality_matching.py`](../../tests/test_quality_matching.py) | 17 |
| [`tests/test_quality_suggestion.py`](../../tests/test_quality_suggestion.py) | 17 |
| [`tests/test_quality_review_widget.py`](../../tests/test_quality_review_widget.py) | 15 |
| [`tests/test_quality_output.py`](../../tests/test_quality_output.py) | 12 |
| **合计** | **148** |

除 `test_quality_review_widget.py`（测 Qt 桥接层）外，其余 6 个文件在纯 Python 下运行。

---

## 截图

> `[截图待补]` — 计划补充：Inspector 质检复核 Tab 界面、report.json 输出示例、CLI 运行截图

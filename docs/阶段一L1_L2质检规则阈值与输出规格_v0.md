# 阶段一 L1/L2 质检规则阈值与输出规格 v0

本文档记录阶段一 L1/L2 目标框质量校验的 v0 决策基线。阶段一定位是
“高风险样本发现器”，不是自动判官；跨类几何关系只作为 QA 临时推断，
不写回正式 `group_id`，也不写回正式 JSON。

## 1. 阶段一定位

- L1：硬规则，检查 JSON 字段、label、shape_type、points、group_id、
  基础几何合法性。
- L2：几何 / 视觉关系规则，通过同图 QA 临时匹配检查空间合理性。
- 正式 `group_id` 只用于正式任务语义：
  - `person + pose` 按 group_id 检查。
  - `head/face` 作为独立检测目标检查自身 group_id 合法性。
- 跨类关系只作为 QA 临时关系：
  - `face -> 候选 head`
  - `head -> 候选 person`
  - `nose/eye/ear -> 候选 face/head`
- 第一阶段不把 `qa_entity_id` 写入正式 JSON。
- 输出采用双文件：
  - `review.tsv`：给 Inspector 导入、点击跳转复核。
  - `report.json`：保存完整 QA 证据、匹配关系、阈值、统计信息。

## 2. L2 默认阈值

阶段一阈值先采用保守 v0：宁可把不确定样本作为 `warning` / `info`
交给人工复核，也不把合法的单类 `head` / `face` 场景直接判成错误。

| 规则 | 默认阈值 | 初始风险 |
|---|---|---|
| L2-01 face 找 head | 候选 head 需满足：x 重叠 >= 0.25，y 重叠 >= 0.15，face/head 面积比 <= 0.85，face 中心落在 head 扩展框 15% 内；最高分 < 0.55 报无可靠候选 | warning |
| L2-02 face 超出 head | `overflow_ratio = face 在 head 外的面积 / face_area`；> 0.10 warning，> 0.20 error | warning/error |
| L2-03 face/head 面积比 | 合理区间先设 `0.08 ~ 0.70`；`>= 0.85` 或 `face >= head` 直接 error；`< 0.05` 只 warning | warning/error |
| L2-04 face/head 中心偏移 | `dx/head_w > 0.35` 或 `dy/head_h > 0.35` 报 warning；> 0.50 升 error | warning/error |
| L2-05 head 找 person | 候选 person 需满足：x 重叠 >= 0.15，head 中心 y 在 person 上方扩展区到 0.60H 内，head/person 面积比 <= 0.40；无候选只 info/warning | info/warning |
| L2-06 head/person 空间关系 | `x_overlap < 0.15` warning；head 中心 y > 0.65H warning，> 0.80H error；head 明显完全离开 person 扩展框 error | warning/error |
| L2-07 head/person 面积比 | 合理区间先设 `0.015 ~ 0.25`；> 0.35 warning，> 0.50 error | warning/error |
| L2-08 大小顺序 | 匹配链中要求 `face < head < person`；`face >= head * 0.95` error，`head >= person * 0.50` error | warning/error |
| L2-09 pose 点出 person | person bbox 扩展 5% 或 8px 取大；关键点出扩展框 warning，躯干点/多点同时出框 error | warning/error |
| L2-10 人体垂直分区 | nose/eye/ear 期望 `y_rel <= 0.35`；shoulder `0.10~0.50`；hip `0.35~0.85`；ankle `>= 0.55`；极端跨区才 error | warning |
| L2-11 头部点靠近 face/head | nose/eye 应落在 face 扩展 20% 或 head 扩展 15% 内；ear 可只要求 head 扩展 20%；作为辅助证据，不单独判死 | warning |
| L2-12 单图密度异常 | 有历史分布后用 P99 或 z-score > 3.5；没有历史分布时只做日报统计，不拦截 | info/warning |

## 3. L2 阈值挂载表

`primary_metric` 是每条规则用于排序、复盘和阈值回流的主指标。
辅助指标仍应保存在 `report.json` 的 `metrics` 中。`error_threshold = -`
表示不建议仅凭 `primary_metric` 直接升为 error。

| 规则 | primary_metric | direction | warning_threshold | error_threshold | error_requires |
|---|---|---|---|---|---|
| L2-01 face 找 head | `face_head_match_gap` | `higher_is_worse` | `>= 0.45`，即 best score `< 0.55` | `-` | 无直接 error；无候选只 warning，除非由 L2-02/L2-03/L2-11 另行触发高风险 |
| L2-02 face 超出 head | `face_head_overflow_ratio` | `higher_is_worse` | `> 0.10` | `> 0.20` | 无 |
| L2-03 face/head 面积比 | `face_head_area_ratio` | `two_sided` | `< 0.05` 或 `> 0.70` | `>= 0.85` 或 `face_area >= head_area` | error 只挂上界；过小默认 warning |
| L2-04 face/head 中心偏移 | `face_head_center_distance_norm` | `higher_is_worse` | `> 0.35` | `> 0.50` | 无 |
| L2-05 head 找 person | `head_person_match_gap` | `higher_is_worse` | `>= 0.45`，即 best score `< 0.55` | `-` | 无直接 error；无 person 可能合法 |
| L2-06 head/person 空间关系 | `head_person_spatial_violation_score` | `higher_is_worse` | `>= 0.35` | `>= 0.70` | 需同时满足硬异常之一：`head_center_y_rel > 0.80`、`x_overlap_ratio < 0.05`、`outside_expanded_person == true` |
| L2-07 head/person 面积比 | `head_person_area_ratio` | `two_sided` | `< 0.015` 或 `> 0.35` | `> 0.50` | error 只挂上界；过小默认 warning |
| L2-08 大小顺序 | `size_order_violation_score` | `higher_is_worse` | `> 0` | `>= 0.95` for `face/head`，或 `>= 0.50` for `head/person` | `face_area >= head_area * 0.95` 或 `head_area >= person_area * 0.50` |
| L2-09 pose 点出 person | `keypoint_outside_distance_norm` | `higher_is_worse` | `> 0` | `> 0.08` | error 需满足：躯干点越界，或越界点数量 `>= 3`，或最远越界距离明显超过扩展框 |
| L2-10 人体垂直分区 | `body_part_band_violation_distance` | `higher_is_worse` | `> 0` | `> 0.20` | error 需满足：关键点跨到明显错误身体区，或同一 person 多个点同时异常 |
| L2-11 头部点靠近 face/head | `head_keypoint_box_distance_norm` | `higher_is_worse` | `> 0` | `> 0.20` | error 需满足：nose/eye/ear 中至少 2 个头部点同时远离候选 face/head |
| L2-12 单图密度异常 | `class_density_zscore` | `higher_abs_is_worse` | `abs(z) > 3.5` | `-` | 无历史分布时不设 error；只做 info/warning 和日报观察 |

总规则：

```text
error_threshold 只有在几何违背足够确定时才直接生效。
存在合法单类、遮挡、小目标、多人重叠可能性的规则，必须通过
error_requires 二次确认。
```

## 4. face -> head 匹配协议

`face -> head` 可以偏严格，因为 face 通常应被 head 包含或接近包含。

硬过滤：

```text
同图 head 候选
  keep if x_overlap_ratio >= 0.25
  keep if y_overlap_ratio >= 0.15
  keep if face_area / head_area <= 0.85
  keep if face_center in expanded_head(15%)
  keep if overflow_ratio <= 0.30
```

打分：

```text
score =
  0.35 * containment_score
+ 0.25 * center_alignment_score
+ 0.20 * area_ratio_score
+ 0.20 * overlap_score
```

最高分 < 0.55 输出 `face_without_matched_head`。top1 与 top2 分差
< 0.12 输出 `face_head_match_ambiguous`，不强行把几何推断当真值。

## 5. head -> person 匹配协议

`head -> person` 必须宽松，因为只有 `head` / `face`、没有 `person`
在项目语义中可能合法。

硬过滤：

```text
同图 person 候选
  keep if x_overlap_ratio >= 0.15
  keep if head_center_y <= person_y1 + 0.60 * person_h
  keep if head_area / person_area <= 0.40
  keep if head_center in expanded_person(20%)
```

打分：

```text
score =
  0.30 * upper_body_position_score
+ 0.25 * x_overlap_score
+ 0.20 * area_ratio_score
+ 0.15 * center_distance_score
+ 0.10 * keypoint_support_score
```

`head_without_matched_person` 默认不是 error：图里没有 person 时为 info；
图里有 person 但都匹配不上时为 warning；head 明显落在某 person 下半身
或远离所有 person 时才升为 error。

## 6. review.tsv 字段

`review.tsv` 作为 Inspector 入口，保持轻量：

```text
issue_id
file_path
shape_index
rule_name
severity
message
label
group_id
```

## 7. report.json 字段

`report.json` 作为主结果与复盘账本，保存完整证据。它必须能回答：

```text
哪条规则报了什么问题？
使用了哪个阈值版本？
触发了哪些指标？
候选匹配关系是什么？
后续人工反馈如何回连？
```

顶层字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 固定为 `l1_l2_qc.v1` |
| `run_id` | 是 | 本次质检运行 id，用于回连 review/threshold 结果 |
| `created_at` | 是 | ISO 8601 时间 |
| `source` | 是 | 输入数据、脚本版本、数据目录等来源信息 |
| `threshold_profile` | 是 | 当前阈值版本，例如 `v0_default` |
| `thresholds` | 是 | 本次运行实际使用的规则阈值快照 |
| `summary` | 是 | 文件数、shape 数、问题数、按规则/严重级别统计 |
| `issues` | 是 | 问题列表 |

每条 issue 字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `issue_id` | 是 | 稳定 id，建议由 `run_id + file_path + shape_index + rule_name + metric_key` 生成 |
| `rule_id` | 是 | 例如 `L2-02` |
| `rule_name` | 是 | 规则稳定名称 |
| `severity` | 是 | `error` / `warning` / `info` |
| `file_path` | 是 | 标注 JSON 路径，可供 Inspector 回跳 |
| `image_path` | 否 | 原图路径，便于外部工具使用 |
| `shape_index` | 是 | 问题 shape 下标；文件级问题为 `-1` |
| `label` | 否 | 问题 shape 的 label |
| `group_id` | 否 | 问题 shape 的 group_id |
| `bbox` | 否 | 当前 shape 的 bbox，格式 `[x1, y1, x2, y2]` |
| `message` | 是 | 给人工看的摘要 |
| `primary_metric` | 是 | 当前规则主指标，用于排序、复盘和阈值回流 |
| `metrics` | 是 | 完整指标证据 |
| `thresholds_hit` | 是 | 命中的 warning/error 阈值及判断分支 |
| `match` | 否 | QA 临时匹配关系 |
| `candidates` | 否 | 候选匹配列表，至少保留 top N |
| `review` | 是 | 复核状态占位，默认 `unreviewed` |

推荐结构：

```json
{
  "schema_version": "l1_l2_qc.v1",
  "run_id": "...",
  "created_at": "...",
  "source": {
    "input_root": "...",
    "checker_version": "stage1_l1_l2_v0",
    "file_count": 0
  },
  "threshold_profile": "v0_default",
  "thresholds": {
    "L2-02": {
      "primary_metric": "face_head_overflow_ratio",
      "warning_threshold": 0.10,
      "error_threshold": 0.20
    }
  },
  "summary": {
    "total_files": 0,
    "total_shapes": 0,
    "total_issues": 0,
    "issues_by_rule": {},
    "issues_by_severity": {}
  },
  "issues": [
    {
      "issue_id": "...",
      "rule_id": "L2-02",
      "rule_name": "face_inside_matched_head",
      "severity": "error",
      "file_path": "...",
      "image_path": "...",
      "shape_index": 6,
      "label": "face",
      "group_id": 10,
      "bbox": [0, 0, 0, 0],
      "message": "face 明显超出候选 head，请复核 face/head 框边界",
      "primary_metric": {
        "name": "face_head_overflow_ratio",
        "value": 0.24,
        "direction": "higher_is_worse"
      },
      "metrics": {
        "face_head_overflow_ratio": 0.24,
        "face_head_area_ratio": 0.62,
        "face_head_center_distance_norm": 0.18
      },
      "thresholds_hit": {
        "level": "error",
        "warning_threshold": 0.10,
        "error_threshold": 0.20,
        "error_requires_satisfied": true
      },
      "match": {
        "qa_entity_id": 2,
        "matched_head_shape_index": 4,
        "matched_person_shape_index": 1,
        "confidence": 0.81
      },
      "candidates": [
        {
          "shape_index": 4,
          "label": "head",
          "score": 0.81,
          "metrics": {
            "containment_score": 0.72,
            "center_alignment_score": 0.86
          }
        }
      ],
      "review": {
        "status": "unreviewed"
      }
    }
  ]
}
```

## 8. 人工复核结果字段

人工复核结果另存 `review_feedback.tsv` 或 `review_feedback.jsonl`，
通过 `issue_id` 回连原始 issue，不直接覆盖原始 `report.json`。

### 8.1 review_feedback.tsv

`review_feedback.tsv` 是每个 issue 的最终复核结论表，适合第一阶段
最小闭环。

字段：

```text
issue_id
run_id
file_path
shape_index
rule_name
original_severity
decision
final_action
reviewer
reviewed_at
note
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `issue_id` | 是 | 回连 `report.json` 的主键 |
| `run_id` | 是 | 回连本次质检批次 |
| `file_path` | 是 | 便于人工表格独立查看 |
| `shape_index` | 是 | 问题 shape 下标 |
| `rule_name` | 是 | 便于按规则聚合 |
| `original_severity` | 是 | 原始严重级别 |
| `decision` | 是 | 人工判断结果 |
| `final_action` | 是 | 人工实际动作 |
| `reviewer` | 否 | 复核人 |
| `reviewed_at` | 是 | ISO 8601 时间 |
| `note` | 否 | 边界样本或仲裁说明 |

`decision` 固定枚举：

| decision | 含义 | 调参统计 |
|---|---|---|
| `confirmed_error` | 确认是真错误，但还没修 | 计入 true error |
| `fixed` | 确认是真错误，且已修正 | 计入 true error |
| `false_positive` | 规则误报，样本本身没问题 | 计入 false positive |
| `acceptable` | 规则抓到边界情况，但业务可接受 | 计入 acceptable |
| `needs_discussion` | 复核员无法判断，需要二次仲裁 | 不进入前三个率的分母 |

`final_action` 固定枚举：

```text
none
fixed_box
fixed_label
fixed_group_id
fixed_points
ignored
escalated
```

### 8.2 review_feedback.jsonl

`review_feedback.jsonl` 是可选事件日志，用于记录多轮复核、仲裁或返工。
第一阶段可以先不实现，但格式预留如下：

```json
{
  "issue_id": "...",
  "run_id": "...",
  "event": "review_decision",
  "decision": "fixed",
  "final_action": "fixed_box",
  "reviewer": "alice",
  "reviewed_at": "...",
  "note": ""
}
```

## 9. threshold_suggestion.json 字段

`threshold_suggestion.json` 是不会直接生效的建议文件。它只回答三件事：

```text
这条规则现在健康吗？
建议怎么调？
为什么这么调？
```

顶层字段：

```json
{
  "schema_version": "threshold_suggestion.v1",
  "generated_at": "...",
  "source": {
    "report_files": ["report.json"],
    "feedback_files": ["review_feedback.tsv"],
    "base_threshold_profile": "v0_default"
  },
  "target_threshold_profile": "v1_after_review",
  "global_summary": {
    "total_rules": 12,
    "total_issues": 0,
    "total_reviewed": 0,
    "rules_ready_for_adjustment": 0,
    "rules_need_more_review": 0
  },
  "rule_suggestions": []
}
```

每条规则建议：

```json
{
  "rule_id": "L2-02",
  "rule_name": "face_inside_matched_head",
  "current": {
    "severity": "error",
    "thresholds": {
      "overflow_warning": 0.10,
      "overflow_error": 0.20
    }
  },
  "review_stats": {
    "all_review_rows": 92,
    "reviewed_count": 86,
    "true_error_count": 65,
    "false_positive_count": 7,
    "acceptable_count": 14,
    "needs_discussion_count": 6,
    "true_error_rate": 0.756,
    "false_positive_rate": 0.081,
    "acceptable_rate": 0.163,
    "discussion_rate": 0.065
  },
  "metric_analysis": {
    "primary_metric": "face_head_overflow_ratio",
    "confirmed_error_p10": 0.23,
    "confirmed_error_median": 0.34,
    "false_positive_p90": 0.16,
    "acceptable_median": 0.18
  },
  "suggested_action": "keep_threshold",
  "secondary_actions": ["rewrite_message"],
  "proposed": {
    "severity": "error",
    "thresholds": {
      "overflow_warning": 0.10,
      "overflow_error": 0.20
    },
    "message_hint": "face 明显超出候选 head，请复核 face/head 框边界"
  },
  "confidence": "high",
  "reason": "真错率高，误报率低；acceptable 样本集中在 warning 区间。",
  "requires_human_approval": true,
  "approval": {
    "status": "pending",
    "approved_by": null,
    "approved_at": null,
    "note": ""
  }
}
```

`suggested_action` 固定枚举：

```text
keep_threshold
relax_threshold
tighten_threshold
downgrade_severity
upgrade_severity
rewrite_message
split_rule
disable_as_strong_rule
require_more_review
definition_review
```

触发规则按优先级判断：

| 优先级 | 条件 | suggested_action |
|---:|---|---|
| 1 | `reviewed_count < 30` | `require_more_review` |
| 2 | `discussion_rate >= 0.25` | `definition_review` |
| 3 | `false_positive_rate >= 0.60` 且 `true_error_rate < 0.30` | `disable_as_strong_rule` |
| 4 | `false_positive_rate >= 0.50` | `relax_threshold` |
| 5 | `acceptable_rate >= 0.40` 且 `false_positive_rate < 0.30` | `downgrade_severity` |
| 6 | `true_error_rate >= 0.75` 且 `false_positive_rate <= 0.15` | `keep_threshold` |
| 7 | `true_error_rate >= 0.85` 且 `false_positive_rate <= 0.10` 且 `reviewed_count >= 100` | `tighten_threshold` |
| 8 | `true_error_rate < 0.40` 且 `acceptable_rate >= 0.35` | `rewrite_message` 或 `downgrade_severity` |
| 9 | 规则内误报集中在某个子场景 | `split_rule` |

一句话口径：

```text
false_positive_rate 高才调阈值。
acceptable_rate 高先降级或改文案。
discussion_rate 高先回到规则定义。
true_error_rate 高才说明规则可靠。
```

## 10. 阈值回流与版本化策略

人工复核不直接触发阈值即时变化，而是批次级回流：

```text
report.json + review_feedback
        ↓
按 rule_name 聚合
        ↓
计算 confirmed_rate / false_positive_rate / acceptable_rate
        ↓
看触发指标分布：误报集中在哪个阈值边缘
        ↓
生成 threshold_suggestion.json
        ↓
人工确认后升级 threshold_profile
```

初始调参原则：

| 情况 | 动作 |
|---|---|
| 某规则 reviewed >= 30 且 false_positive_rate > 50% | 放宽阈值或降 severity |
| confirmed_error_rate > 70% 且 issue 数量可控 | 保持或略收紧 |
| acceptable_rate 很高 | 规则不一定错，但 message/severity 应改得更温和 |
| high 规则误报多 | 优先降级为 warning，不急着删除 |
| 某指标的 confirmed/false_positive 分布明显分离 | 用分位数重设阈值，例如取误报 P90 和真错 P10 之间 |

阈值必须版本化，例如 `v0_default -> v1_after_500_reviewed`。阶段一
不做静默漂移，所有阈值变更都应能追溯到复核统计和人工确认。

第 7、8、9、10 节共同构成第一阶段输出与回流规格。后续不再
拆新文档，除非进入实现阶段需要生成机器可读配置文件。

## 11. 暂不做事项

- 不进入模型二检。
- 不进入半自动修正。
- 不做 UI 改造。
- 不批量改写 JSON。
- 不把 `qa_entity_id` 写入正式 JSON。

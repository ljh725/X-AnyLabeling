# 阶段一 L1/L2 质检实现任务文档

本文档用于把阶段一 L1/L2 质检规格转换为代码实现任务。它不是新的
业务规格，所有规则阈值、输出字段和回流口径以以下文档为准：

- `docs/qc-040_spec_v0_阶段一l1_l2质检规则阈值与输出规格.md`

## 1. 实现目标

第一阶段实现一个可复跑、可导入 Inspector、可保留证据、可回流阈值的
L1/L2 质检最小闭环。

目标链路：

```text
标注 JSON
  ↓
L1/L2 规则扫描
  ↓
review.tsv + report.json
  ↓
人工复核 review_feedback.tsv
  ↓
threshold_suggestion.json
```

第一版代码目标：

```text
规则能跑
结果能看
证据能存
反馈能回流
阈值不自动改
```

## 2. 实现边界

### 2.1 本阶段要做

- 加载机器可读阈值配置。
- 扫描 LabelMe / X-AnyLabeling JSON 标注文件。
- 复用或适配现有 Inspector 平铺索引能力。
- 实现 bbox、点、关键点相关基础几何指标。
- 实现 `face -> head` QA 临时匹配。
- 实现 `head -> person` QA 临时匹配。
- 实现阶段一 L1/L2 规则 issue 生成。
- 输出 `review.tsv`。
- 输出 `report.json`。
- 读取 `review_feedback.tsv`。
- 生成 `threshold_suggestion.json`。

### 2.2 本阶段不做

- 不改 Inspector UI。
- 不做模型二检。
- 不做半自动修正。
- 不批量改写正式 JSON。
- 不把 `qa_entity_id` 写入 shape `attributes`。
- 不把 `head/face/person` 强行绑定到同一个正式 `group_id`。
- 不让阈值自动静默生效。

## 3. 输入输出

### 3.1 输入

| 输入 | 说明 |
|---|---|
| 标注 JSON 目录或文件列表 | 必填，作为质检对象 |
| 图片目录 | 可选，用于补充路径和导出证据，不作为规则必需输入 |
| 阈值配置 YAML | 必填，默认使用 v0 profile |

### 3.2 输出

| 输出 | 说明 |
|---|---|
| `review.tsv` | Inspector 可导入的问题列表 |
| `report.json` | 完整证据账本，包含 metrics、primary_metric、thresholds_hit、candidates |

### 3.3 后续输入输出

| 文件 | 说明 |
|---|---|
| `review_feedback.tsv` | 人工复核结论输入 |
| `threshold_suggestion.json` | 阈值调整建议输出，不自动生效 |

## 4. 机器可读阈值配置

Markdown 规格用于人读，代码应读取 YAML 配置。建议路径：

```text
anylabeling/configs/quality/l1_l2_threshold_profile_v0.yaml
```

配置应包含：

```text
profile_id
schema_version
rules
  rule_id
  rule_name
  enabled
  default_severity
  primary_metric
  direction
  warning_threshold
  error_threshold
  error_requires
```

规划原则：

```text
规则算法写在代码里。
阈值参数写在配置里。
后续调参只改配置，不改规则代码。
```

## 5. 模块拆分建议

优先新增独立质检模块，避免第一版直接耦合 UI。

建议模块位置：

```text
anylabeling/views/labeling/widgets/inspector/quality/
```

建议子模块：

| 模块 | 职责 |
|---|---|
| `threshold_profile.py` | 加载和校验阈值 YAML |
| `geometry.py` | bbox、点、距离、overflow、归一化指标 |
| `matching.py` | `face -> head`、`head -> person` 候选过滤和打分 |
| `quality_issue.py` | issue、candidate、metric、report 数据结构 |
| `l1_rules.py` | L1 硬规则适配和输出 |
| `l2_rules.py` | 12 条 L2 规则 |
| `report_writer.py` | 输出 `review.tsv` 和 `report.json` |
| `feedback.py` | 读取 `review_feedback.tsv` |
| `threshold_suggestion.py` | 生成 `threshold_suggestion.json` |

如后续确认不希望放在 Inspector 目录下，可迁移为服务型目录：

```text
anylabeling/services/quality/
```

## 6. 任务清单

### 阶段 A：基础设施

- [x] A1. 新增 v0 阈值 YAML 配置。
- [x] A2. 定义阈值配置 schema 与枚举值。
- [x] A3. 实现阈值配置 loader。
- [x] A4. loader 校验必填字段、阈值类型、`direction`、`error_requires`。
- [x] A5. 定义 `QualityIssue`、`MatchCandidate`、`PrimaryMetric`、`QualityReport` 数据结构。

### 阶段 B：几何能力

- [x] B1. 实现 bbox 面积、中心点、宽高、合法性检查。
- [x] B2. 实现 bbox overlap、intersection、containment。
- [x] B3. 实现 face/head/person overflow ratio。
- [x] B4. 实现 bbox 扩展与点落框判断。
- [x] B5. 实现点到 bbox / 扩展 bbox 的归一化距离。
- [x] B6. 实现关键点 `y_rel` 与 body band violation distance。

### 阶段 C：QA 临时匹配

- [x] C1. 实现 `face -> head` 硬过滤。
- [x] C2. 实现 `face -> head` 打分和 top candidates。
- [x] C3. 实现 `face_head_match_gap`。
- [x] C4. 实现 `head -> person` 硬过滤。
- [x] C5. 实现 `head -> person` 打分和 top candidates。
- [x] C6. 实现 `head_person_match_gap`。
- [x] C7. 标记 ambiguous match，不强行绑定低置信候选。

### 阶段 D：L2 规则实现

- [x] D1. L2-01 `FaceMatchedHeadCandidateRule`。
- [x] D2. L2-02 `FaceInsideMatchedHeadRule`。
- [x] D3. L2-03 `FaceHeadAreaRatioRule`。
- [x] D4. L2-04 `FaceHeadCenterAlignmentRule`。
- [x] D5. L2-05 `HeadMatchedPersonCandidateRule`。
- [x] D6. L2-06 `HeadInsideMatchedPersonRule`。
- [x] D7. L2-07 `HeadPersonAreaRatioRule`。
- [x] D8. L2-08 `CrossClassSizeOrderRule`。
- [x] D9. L2-09 `KeypointInsidePersonRule`。
- [x] D10. L2-10 `BodyPartVerticalBandRule`。
- [x] D11. L2-11 `HeadKeypointsNearHeadFaceRule`。
- [x] D12. L2-12 `ImageLevelClassDensityRule`。

### 阶段 E：输出闭环

- [x] E1. 生成 `review.tsv`，字段兼容 Inspector 外部导入。
- [x] E2. 生成 `report.json`，字段符合 v0 规格。
- [x] E3. 每条 issue 包含 `primary_metric`、`metrics`、`thresholds_hit`。
- [x] E4. L2 匹配类 issue 保存 `match` 与 `candidates`。
- [x] E5. 输出 `run_id`、`threshold_profile`、`summary`。
- [x] E6. 确认运行过程不修改任何原始 JSON。

### 阶段 F：人工反馈与阈值建议

- [x] F1. 读取 `review_feedback.tsv`。
- [x] F2. 校验 `decision` 与 `final_action` 枚举值。
- [x] F3. 按 `rule_name` 聚合 `true_error_rate`、`false_positive_rate`、`acceptable_rate`、`discussion_rate`。
- [x] F4. 生成 rule health summary。
- [x] F5. 根据优先级规则生成 `suggested_action`。
- [x] F6. 输出 `threshold_suggestion.json`。
- [x] F7. 保持建议文件为 pending，不自动修改 YAML。

### 阶段 G：命令入口与集成

- [x] G1. 提供命令行入口或工具脚本运行阶段一质检。
- [x] G2. 支持输入 JSON 目录、输出目录、阈值配置路径。
- [x] G3. 支持只生成 `review.tsv + report.json`。
- [x] G4. 支持从 `report.json + review_feedback.tsv` 生成 `threshold_suggestion.json`。

## 7. 验收标准

### 7.1 基础验收

- [x] 能扫描一批标注 JSON。
- [x] 能生成 Inspector 可导入的 `review.tsv`。
- [x] 能生成符合 v0 字段结构的 `report.json`。
- [x] 每条 issue 都包含稳定 `issue_id`。
- [x] 每条 L2 issue 都包含 `primary_metric`。
- [x] 命中阈值的 issue 包含 `thresholds_hit`。
- [x] 匹配类 issue 包含候选匹配证据。
- [x] 不修改任何原始 JSON。

### 7.2 反馈回流验收

- [x] 能读取 `review_feedback.tsv`。
- [x] 能计算 `true_error_rate`、`false_positive_rate`、`acceptable_rate`。
- [x] `needs_discussion` 不进入前三个率的分母。
- [x] 能生成 `threshold_suggestion.json`。
- [x] `threshold_suggestion.json` 默认 `approval.status = pending`。
- [x] 不自动改写阈值 YAML。

### 7.3 测试验收

- [x] 单元测试覆盖 bbox 几何计算。
- [x] 单元测试覆盖 `face -> head` 匹配。
- [x] 单元测试覆盖 `head -> person` 匹配。
- [x] 单元测试覆盖双向阈值规则。
- [x] 单元测试覆盖 `error_requires`。
- [x] 单元测试覆盖 `review.tsv` / `report.json` 输出结构。
- [x] 单元测试覆盖 `threshold_suggestion.json` 触发规则。

## 8. 实现顺序建议

推荐先跑通主路径，再补齐所有规则：

```text
1. YAML loader + geometry
2. face/head 匹配 + L2-01~L2-04
3. review.tsv + report.json 输出
4. head/person 匹配 + L2-05~L2-08
5. keypoint/density 规则 + L2-09~L2-12
6. review_feedback.tsv reader
7. threshold_suggestion.json writer
```

第一版可先选择少量样例 JSON 做烟测，确认输出结构稳定后，再扩展到完整
12 条 L2 规则。

## 9. 风险与注意事项

- `head_without_matched_person` 不能默认判 error，因为无 person 可能合法。
- `face_without_matched_head` 是 warning 信号，不是自动判错。
- 双向指标必须区分上界和下界，例如 area ratio。
- 复合空间规则不能只靠一个 composite score 判死，必须保留
  `error_requires`。
- 低置信匹配不强行绑定，只输出 issue 与候选证据。
- 阈值建议不能自动生效，必须人工确认后生成新 profile。

## 10. 暂不做事项

- 不做 UI 改造。
- 不做模型二检。
- 不做半自动修正。
- 不批量改写正式 JSON。
- 不写回 `qa_entity_id`。
- 不把复核反馈直接覆盖原始 `report.json`。

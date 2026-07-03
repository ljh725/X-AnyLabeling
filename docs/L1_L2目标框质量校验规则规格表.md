# L1/L2 目标框质量校验规则规格表

> 阶段一规则规格。本文只定义规则、输入输出、风险等级与复核策略，
> 不涉及模型二检、自动修正或代码实现。

## 1. 规则边界

正式数据关系：

```text
person + pose 关键点 依赖正式 group_id
head 独立 group_id
face 独立 group_id
```

QA 临时关系：

```text
face -> 候选 head
head -> 候选 person
头部关键点 -> 候选 head / face
```

`head` / `face` 与 `person` 的跨类关系只服务质检，不覆盖正式
`group_id`。解耦的含义是“不和 person 共用 id”，不是“没有 id”。

## 2. 统一输出字段

每条 issue 建议输出：

```text
file_path
shape_index
rule_name
severity: error | warning | info
risk_level: high | medium | low
label
group_id
message
extra
```

L2 几何匹配类 issue 的 `extra` 可包含：

```text
matched_head_shape_index
matched_person_shape_index
candidate_count
overflow_ratio
area_ratio
center_distance
```

## 3. L1 硬规则

L1 原则：不需要理解图片内容，只看 JSON 字段和基础坐标即可判断。

| ID | 规则名 | 检查对象 | 输入字段 | 触发条件 | 风险 | 复核策略 |
|---|---|---|---|---|---|---|
| L1-01 | LabelAllowlistRule | 全部 shape | label | label 不在允许标签集 | high | 必须修 |
| L1-02 | ShapeTypeBindingRule | 全部 shape | label, shape_type | `person/head/face` 非 rectangle；pose 点非 point | high | 必须修 |
| L1-03 | RequiredPointsRule | 全部 shape | points | points 为空 | high | 必须修 |
| L1-04 | RectangleGeometryValidRule | person/head/face | points | 无法解析 bbox；宽高 <= 0 | high | 必须修 |
| L1-05 | RectangleInsideImageRule | person/head/face | points, imageWidth, imageHeight | 框明显越界 | high/medium | 高风险必看，贴边截断可降级 |
| L1-06 | PointInsideImageRule | pose 点 | points, imageWidth, imageHeight | 点明显越界 | high/medium | 必看或抽查 |
| L1-07 | GroupIdValidRule | 需分组 shape | group_id | group_id 为 null、负数、字符串、bool | high | 必须修 |
| L1-08 | PersonPoseGroupSubjectRule | pose 点 | label, group_id | pose 点同组找不到 person rectangle | high | 必须修 |
| L1-09 | PersonGroupDuplicateKeypointRule | pose 点 | label, group_id | 同一 person group 内同一关键点重复 | high | 必须修 |
| L1-10 | HeadFaceGroupIdRequiredRule | head/face | label, group_id | head/face 缺合法 group_id | high | 必须修 |
| L1-11 | HeadFaceGroupIdUniquenessRule | head/face | label, group_id | 同一文件内 head/face group_id 复用 | high | 必须复核 |
| L1-12 | SameClassDuplicateBoxRule | person/head/face | label, bbox | 同图同类框高度重叠，疑似重复标注 | medium/high | 按 IoU 高低分级复核 |

## 4. L2 几何 / 视觉关系规则

L2 原则：不要求同 `group_id`，而是在同一张图里建立 QA 临时匹配。

```text
face 先匹配 head
head 再匹配 person
pose 点仍按正式 group_id 找 person
```

| ID | 规则名 | 检查对象 | 输入字段 | 触发条件 | 风险 | 复核策略 |
|---|---|---|---|---|---|---|
| L2-01 | FaceMatchedHeadCandidateRule | face -> head | face bbox, head bbox | 为 face 找不到合理 head 候选 | medium | 抽查；若 face 明显孤立则必看 |
| L2-02 | FaceInsideMatchedHeadRule | face -> 候选 head | bbox | face 大面积超出 head | high | 必须复核 |
| L2-03 | FaceHeadAreaRatioRule | face -> 候选 head | bbox area | face 面积 >= head 面积，或比例极端 | high | 必须复核 |
| L2-04 | FaceHeadCenterAlignmentRule | face -> 候选 head | bbox center | face 中心明显偏离 head 合理区域 | medium | 抽查 |
| L2-05 | HeadMatchedPersonCandidateRule | head -> person | head bbox, person bbox | 为 head 找不到合理 person 候选 | low/medium | 记录或抽查，不能默认判错 |
| L2-06 | HeadInsideMatchedPersonRule | head -> 候选 person | bbox | head 明显远离 person 上部，或 x 轴几乎无重叠 | medium/high | 视偏离程度复核 |
| L2-07 | HeadPersonAreaRatioRule | head -> 候选 person | bbox area | head/person 面积比极端 | medium | 抽查 |
| L2-08 | CrossClassSizeOrderRule | face/head/person | bbox area | 候选关系中不满足 face < head < person | medium/high | face > head 必看 |
| L2-09 | KeypointInsidePersonRule | pose 点 -> 同组 person | point, person bbox | 关键点明显超出 person 扩展框 | medium/high | 头部点、躯干点高风险优先 |
| L2-10 | BodyPartVerticalBandRule | pose 点 -> person | point, person bbox | nose/eye/ear 在下半身；ankle 在上半身 | medium | 抽查，异常极端时必看 |
| L2-11 | HeadKeypointsNearHeadFaceRule | nose/eye/ear -> 候选 head/face | point, bbox | 头部关键点远离候选 head/face | medium/high | 优先复核 face/head 定位 |
| L2-12 | ImageLevelClassDensityRule | 单图 | class counts | 同类框数量/密度异常，或远超历史分布 | low/medium | 日报监控，抽查 |

## 5. 风险分级

| 风险 | 典型规则 | 处理 |
|---|---|---|
| high | group_id 非法、框退化、face 大面积超出 head、pose 点无 person | 必须复核 |
| medium | face 找不到 head、head/person 面积比异常、关键点区域异常 | 排序复核或抽查 |
| low | 合法单类 head/face、轻微贴边、弱统计异常 | 记录到日报，必要时抽查 |

## 6. 人工复核结果

```text
confirmed_error   确认错误
fixed             已修正
false_positive    规则误报
acceptable        可接受边界情况
```

阶段一的定位是“高风险样本发现器”，不是自动判官。人工反馈应后续回流，
用于调阈值、识别误报规则，以及判断是否需要进入模型二检。

## 7. QA 辅助字段策略

第一阶段不建议把 `qa_entity_id` 直接写入正式 JSON。

原因是 `qa_entity_id` 来自几何匹配推断，不是人工标注事实。多人重叠、
小目标、侧脸、只有 `face` / `head` 的场景都可能导致误配。如果直接写回
正式 JSON，容易把“质检推断”伪装成“数据真值”。

推荐分层：

```text
正式 JSON:
  group_id = 训练 / 检测任务语义

质检输出:
  qa_entity_id / matched_head / matched_person = 临时 QA 关系
```

第一阶段先把 QA 辅助字段放在外部结果中：

```json
{
  "file_path": "s22.json",
  "shape_index": 6,
  "label": "face",
  "group_id": 10,
  "qa_entity_id": 2,
  "matched_head_shape_index": null,
  "matched_person_shape_index": null,
  "rule_name": "face_without_matched_head"
}
```

等人工复核证明匹配规则稳定后，再考虑写入 shape 的 `attributes`：

```json
{
  "attributes": {
    "qa_entity_id": 2,
    "qa_matched_head_gid": 8,
    "qa_match_confidence": 0.91
  }
}
```

阶段一决策：

```text
不写 qa_entity_id 到正式 JSON。
先作为外部 QA 结果字段保存。
```

## 8. 输出格式策略

不建议只输出 TSV。TSV 适合 Inspector 跳转复核，但不适合承载完整几何证据、
候选匹配关系、阈值和统计信息。

推荐双输出：

```text
review.tsv      给 Inspector 导入、点击跳转
report.json     保存完整 QA 证据、统计、匹配关系、阈值
```

TSV 字段保持轻量：

```text
file_path
shape_index
rule_name
severity
message
```

JSON 保存完整细节：

```text
bbox
matched_shape_index
candidate_count
area_ratio
overflow_ratio
center_distance
qa_entity_id
risk_level
```

阶段一决策：

```text
TSV 作为复核入口。
JSON 作为主结果与复盘账本。
不要只输出 TSV。
```

## 9. 几何匹配设计原则

几何匹配只服务 QA，不写回正式 `group_id`。匹配流程采用“硬过滤 + 打分 +
不确定即报告”的方式：

```text
同图候选
  ↓
硬过滤：排除明显不可能的关系
  ↓
打分：从剩余候选中选择最可信关系
  ↓
低置信或无候选：输出 issue，不强行匹配
```

### 9.1 face -> head

硬过滤建议：

- `face` 与 `head` 至少有 x/y 方向重叠；
- `face` 面积不能明显大于 `head`；
- `face` 中心应在 `head` 内或扩展 `head` 内；
- `face` 超出 `head` 的比例不能过大。

打分因子：

```text
score =
  containment_score
  + center_alignment_score
  + area_ratio_score
  + overlap_score
```

风险规则：

- 无候选：`face_without_matched_head`，medium；
- `face` 面积 >= `head`：high；
- `face` 大面积超出 `head`：high；
- 多个候选分数接近：medium，提示匹配不确定。

### 9.2 head -> person

`head -> person` 必须比 `face -> head` 更宽松，因为项目允许只标 `head`
或 `face`，没有 `person` 也可能合法。

硬过滤建议：

- `head` 与 `person` 有一定 x 轴重叠；
- `head` 中心大致位于 `person` 上部；
- `head` 面积明显小于 `person`；
- `head` 不应远离 `person` 框。

风险规则：

- 无候选：low / medium，不能默认判错；
- `head` 明显不在 `person` 上部：medium / high；
- `head/person` 面积比极端：medium。

### 9.3 关键点辅助

头部关键点可作为 L2 辅助证据：

```text
nose / eye / ear
  应靠近候选 face / head
```

它不要求 pose 精度特别高，但可以帮助判断 `face` / `head` 是否离谱。
例如：`face` 没有匹配到 `head`，但 nose / eye 都落在 `face` 内，这个
`face` 可能是合法单类 `face`；反过来，`face` 远离所有头部关键点，则更可疑。

阶段一决策：

```text
face -> head 可以较严格。
head -> person 必须宽松。
关键点作为辅助证据，不作为强制真值。
低置信匹配不强行绑定，输出 issue 交给人工复核。
```

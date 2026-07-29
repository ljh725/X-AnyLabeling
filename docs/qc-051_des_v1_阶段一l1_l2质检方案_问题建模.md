【已确认事实】

- `person + pose关键点` 使用正式 `group_id` 关联。
- `head`、`face` 是独立检测类别，各自拥有自己的 `group_id`。
- `group_id` 解耦不等于允许 `head/face group_id = null`。
- 一个真实人物目标可以只标 `head`、只标 `face`、只标 `head + face`，不要求 `person/head/face` 同时存在。
- 阶段一定位是“高风险样本发现器”，不是自动判官。
- QA 几何匹配关系只作为临时推断，不写回正式 JSON。
- v0 规格已沉淀到：
  `docs/qc-040_spec_v0_阶段一l1_l2质检规则阈值与输出规格.md`
- `docs/qc-050_des_阶段一l1_l2质检方案_问题建模.md` 保持为问题建模文档，不承载 v0 细则。

【核心问题表述】

在 `person/head/face` 正式 `group_id` 解耦后，如何设计阶段一 L1/L2 质检体系，使系统既能检查正式任务语义下的 `person + pose` 组内一致性，又能通过 QA 临时几何关系检查 `face/head/person/keypoint` 的空间合理性，同时不破坏正式训练数据语义。

【不要带入实现的探索性假设】

- 不假设 `person/head/face` 必须共用同一个 `group_id`。
- 不假设 `head/face` 可以没有 `group_id`。
- 不假设每个 `person` 都必须配套 `head/face`。
- 不假设几何匹配结果是真值。
- 不假设第一阶段要写回 `qa_entity_id`。
- 不假设只输出 TSV 就足够。
- 不进入模型二检、半自动修正、UI 改造、批量改写 JSON。
- 不让阈值自动静默漂移，阈值调整必须有人工确认和版本记录。

【待验证假设】

- L2 几何匹配规则在真实数据上的稳定性：
  - `face -> head`
  - `head -> person`
  - 头部关键点 -> 候选 `face/head`
- `face_without_matched_head`、`head_without_matched_person` 中，真实错误与合法单类标注的比例。
- v0 默认阈值是否适合真实数据分布。
- `primary_metric + warning_threshold + error_threshold + error_requires` 是否足以支撑复核排序和阈值回流。
- `review.tsv + report.json + review_feedback + threshold_suggestion.json` 是否能形成最小闭环。
- 人工复核样本量达到多少后，阈值建议才足够可靠。

【当前决定采用的方案】

- 阶段一采用 L1/L2 规则体系：
  - L1：字段、label、shape_type、points、group_id、基础几何合法性。
  - L2：跨类几何/视觉关系，通过 QA 临时匹配检查空间合理性。
- 跨类关系只作为 QA 临时关系：
  - `face -> 候选 head`
  - `head -> 候选 person`
  - `nose/eye/ear -> 候选 face/head`
- 输出采用双文件：
  - `review.tsv`：Inspector 导入、跳转复核。
  - `report.json`：主结果与完整证据账本。
- 人工复核另存：
  - `review_feedback.tsv`：每个 issue 的最终复核结论。
  - `review_feedback.jsonl`：可选事件日志。
- 阈值建议另存：
  - `threshold_suggestion.json`：只生成建议，不自动生效。
- 规则质量口径：
  - 规则质量看 `true_error_rate`
  - 复核负担看 `false_positive_rate`
  - 业务容忍区看 `acceptable_rate`
- 已在 v0 文档中锁定：
  - 12 条 L2 默认阈值。
  - 12 条 L2 的 `primary_metric`。
  - `warning_threshold / error_threshold / error_requires` 挂载表。
  - `report.json` 字段结构。
  - `review_feedback.tsv/jsonl` 字段结构。
  - `threshold_suggestion.json` 字段结构与 `suggested_action` 触发规则。

【下一步只允许围绕什么展开】

- 继续做阶段一 L1/L2 质检规格收尾。
- 只讨论：
  - 是否需要再补充机器可读阈值配置草案。
  - 是否创建 OpenSpec/change 或实现任务文档。
  - 实现边界、输入输出、验收标准。
  - 最小代码闭环如何拆任务。
- 暂不讨论：
  - 模型二检。
  - 半自动修正。
  - UI 改造。
  - 批量改写 JSON。
  - 正式写回 `qa_entity_id`。

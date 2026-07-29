【已确认事实】

- 项目数据中 `person + pose关键点` 是一组，`head`、`face` 是各自独立检测目标。
- 因此正式数据语义上，不应强制让 `person/head/face` 共用同一个 `group_id`。
- `group_id` 解耦后，`person + pose关键点` 仍然依赖 `group_id` 做完整性和一致性检查。
- `head/face` 仍然应该有合法 `group_id`，不能因为解耦而变成 `null`。
- 当前 `group_merger.py` 的“统一真实人物 id”逻辑会覆盖正式 `group_id` 语义。
- `s22-none.json` 中出现 `face.group_id = null`，本质上应作为待复核或数据问题，而不是正常最终状态。
- `docs/meth-020_guide_标注质量方法论prompt指南.md` 强调：先建立质量判断体系，再决定规则、统计、模型或工具实现。
- `pose_qa/docs/quality_strategy.md` 建议四层质检：L1 硬规则、L2 人体结构/几何规则、L3 模型差异、L4 主动复查队列。

【核心问题表述】

在 `person/head/face` 的正式 `group_id` 不再强制关联后，如何继续进行有效的数据检查，尤其是如何检查同一个真实人物下 `person/head/face/pose关键点` 之间的空间关系和语义一致性，同时不破坏训练/交付数据本身的 `group_id` 语义。

【不要带入实现的探索性假设】

- 不假设必须继续用 `group_merger.py` 覆盖 `group_id`。
- 不假设 `person/head/face` 必须同一个 `group_id` 才能做质检。
- 不假设 `group_id = null` 是可接受的最终数据状态。
- 不假设几何匹配结果一定正确，匹配只能作为质检辅助或复核线索。
- 不假设模型结果可以直接替代人工标注。
- 不直接进入 UI 或脚本实现细节，除非先明确规则体系和数据语义。

【待验证假设】

- 是否需要在 JSON 中新增 `attributes.qa_entity_id` / `qa_matched_person_gid` 这类质检辅助字段。
- `head -> person`、`face -> head` 的几何匹配规则是否在真实数据上足够稳定。
- 对 `face` 找不到 `head`、`head` 找不到 `person` 的情况，哪些是正常遮挡/截断，哪些是真错误。
- `FaceInsideHeadRule`、`KeypointInsidePersonRule`、`BodyPartVerticalBandRule` 等规则的默认阈值是否适合当前数据集。
- 是否需要保留“外部 TSV 复核结果”而不是写回 JSON 辅助字段。
- L3 模型差异检查在当前阶段是否必要，还是先做 L1/L2 即可。

【当前决定采用的方案】

- 正式 `group_id` 语义保持解耦：
  - `person + pose关键点` 共用 `group_id`
  - `head` 独立 `group_id`
  - `face` 独立 `group_id`
- 数据检查分层进行：
  - L1：检查 label、shape_type、points、group_id 合法性、必填字段。
  - L2：通过几何匹配建立临时 QA 关系，检查 `face/head/person/keypoint` 空间合理性。
  - L3：后续可用模型结果做差异排序，不自动覆盖人工标注。
  - L4：输出高风险复核队列，让人工确认。
- `group_id` 不再承担“同一个真实人物”的质检聚合职责。
- 如需按真实人物聚合，应使用临时匹配关系或新增 QA 辅助字段，而不是覆盖正式 `group_id`。

【下一步只允许围绕什么展开】

- 围绕“解耦 `group_id` 后的数据检查规则体系”展开。
- 优先明确 L1/L2 规则清单、输入输出、风险等级和人工复核策略。
- 可以讨论是否新增 `qa_entity_id`、是否只输出 TSV、以及几何匹配规则如何设计。
- 暂不进入模型接入、UI 改造、自动修正、批量重写 JSON，除非先完成规则体系确认。

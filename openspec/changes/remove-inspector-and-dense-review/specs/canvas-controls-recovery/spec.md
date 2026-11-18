## ADDED Requirements

### Requirement: Recovery preserves supported annotation workflows

恢复后的系统 MUST 同时保留五项既定画布迁移能力，以及当前受支持的数字改类、本地矩形编辑、对象身份、锁定、撤销和共享视图行为。恢复操作 MUST 维持标注格式与扩展字段兼容，并遵守当前版本的功能范围。

#### Scenario: 恢复后继续普通标注

- **WHEN** 用户在恢复后的应用中打开旧标注，调框、数字改类、撤销并保存重开
- **THEN** 五项迁移入口可用，普通标注的对象身份、编辑结果、图片审核状态和旧扩展字段按各自规则保留

## REMOVED Requirements

### Requirement: Recovery preserves current annotation workflows

**Reason**: 原条款要求恢复 Inspector 和密集复核，并指定继续密集复核的验收场景。这两项工作流随产品退役。

**Migration**: 以 Recovery preserves supported annotation workflows 验证五项画布迁移能力、普通标注操作与旧数据兼容。退役功能的原验收场景可通过历史规格和移除前的保存点查阅。

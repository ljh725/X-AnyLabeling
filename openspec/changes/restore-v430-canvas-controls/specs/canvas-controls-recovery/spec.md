## Purpose

让恢复后的画布功能与用户已确认的迁移范围、当前其他定制和交付记录保持一致，使后续维护者能够验证来源、重现已验证的行为，并从保存点恢复实际交付内容。

## ADDED Requirements

### Requirement: Recovery preserves current annotation workflows
恢复后的系统 MUST 同时保留五项既定画布迁移能力以及实施开始时已有的 Inspector、密集审核、数字改类、本地矩形编辑、对象身份、锁定、撤销和共享视图行为；恢复操作不得改变既有标注格式或把旧源码中的缺失功能带回当前版本。

#### Scenario: Continue dense review after restoration
- **WHEN** 用户在恢复后的应用中继续已保存的密集审核，调框、数字改类、撤销并保存重开
- **THEN** 审核状态和对象身份遵循当前工作流，五项迁移入口可使用，标注内容及原有扩展字段不因恢复而丢失

### Requirement: Delivery has verifiable recovery evidence
交付 MUST 提供五项能力与验证结果、源码保存点、恢复来源的对照；实施前的已跟踪修改和未跟踪源码 MUST 能从独立备份恢复。未验证或未通过的项目 MUST 明确保留待完成状态，不能沿用历史通过记录宣称当前版本通过。

#### Scenario: Restore the delivered version independently
- **WHEN** 维护者依据交付说明在独立位置还原保存点并执行对应行为验证
- **THEN** 所列源码和测试可获取，验证结果可追溯到该保存点，仍待人工确认的项目清晰可见

### Requirement: Recovery stays within the approved migration scope
恢复后的系统 MUST 只恢复原定五项迁移，不以恢复为由新增四种显示模式、MultiTask、OCR、测量、旋转或跳图步长改造；实施记录 MUST 明确关联原迁移并防止同一能力重复发布规格。

#### Scenario: Inspect restored controls
- **WHEN** 用户检查恢复后的工具栏、设置和画布面板
- **THEN** 原定迁移入口可用，原有类别颜色及其他工作流继续保留，没有混入上述排除功能

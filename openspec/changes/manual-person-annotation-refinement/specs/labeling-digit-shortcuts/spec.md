## ADDED Requirements

### Requirement: 数字快捷键提供互斥操作模式

系统 SHALL 使用持久配置 `digit_shortcut_mode` 在 `rename` 与 `bind_draw` 两种模式之间互斥分流，同一次数字键事件 MUST 只执行其中一个模式的行为。

#### Scenario: rename 模式重命名

- **GIVEN** 当前模式为 `rename` 且编辑态选中了可重命名对象
- **WHEN** 标注员按下已配置数字键
- **THEN** 系统 SHALL 修改选中对象 label
- **AND** 系统 MUST 不进入新 shape 绘制

#### Scenario: bind_draw 模式创建绑定目标

- **GIVEN** 当前模式为 `bind_draw` 且存在合法来源
- **WHEN** 标注员按下已配置数字键
- **THEN** 系统 SHALL 将数字映射解释为绑定目标并进入相应绘制模式
- **AND** 系统 MUST 不重命名来源对象

#### Scenario: 默认模式保持旧行为

- **GIVEN** 用户没有修改新增模式配置
- **WHEN** 应用加载默认配置
- **THEN** `digit_shortcut_mode` SHALL 为 `rename`
- **AND** 既有数字快捷重命名流程 SHALL 保持可用

### Requirement: 绑定绘制复用现有数字映射和分页

绑定绘制模式 SHALL 从现有 `digit_shortcuts` 与数字分页管理器解析目标 label 和 shape type，不得维护第二套重复映射。

#### Scenario: 当前页存在数字映射

- **GIVEN** 当前数字页将按键 2 映射为 `head rectangle`
- **WHEN** 标注员在 bind_draw 模式按 2
- **THEN** 系统 SHALL 使用 `head rectangle` 作为绑定目标

#### Scenario: 数字未配置

- **GIVEN** 当前页没有对应数字映射
- **WHEN** 标注员按下该数字键
- **THEN** 系统 SHALL 拒绝执行并提示在数字快捷管理器中配置

#### Scenario: 数字映射目标不受支持

- **GIVEN** 数字映射目标不是 `person/head/face rectangle`
- **WHEN** 标注员在 bind_draw 模式触发该映射
- **THEN** 系统 SHALL 拒绝进入绑定绘制

### Requirement: pending bind 是单次绘制瞬时状态

数字键触发成功后，系统 SHALL 只保存一个 pending bind context；在该 context 完成或取消前，后续数字键 MUST 不得堆叠或覆盖它。

#### Scenario: pending 期间再次按数字键

- **GIVEN** 一个绑定绘制正在进行
- **WHEN** 标注员再次按下数字键
- **THEN** 系统 SHALL 拒绝第二次触发
- **AND** 原 pending context SHALL 保持不变

#### Scenario: pending 成功消费

- **GIVEN** pending bind 已通过最终校验
- **WHEN** 新 shape 完成落标
- **THEN** 系统 SHALL 清理 pending context 和数字目标标签

### Requirement: 数字快捷操作提供明确反馈

bind_draw 模式 SHALL 在模式切换、来源选择变化、数字键触发和拒绝执行时显示状态反馈，反馈 SHALL 包含判断当前动作所需的来源、目标或拒绝原因。

#### Scenario: 成功进入绑定绘制

- **GIVEN** 来源和数字目标均合法
- **WHEN** 标注员触发绑定绘制
- **THEN** 提示 SHALL 包含数字键、来源 label、目标 label 和将继承或分配的 `group_id`

#### Scenario: 来源无 group_id

- **GIVEN** 合法来源没有 `group_id`
- **WHEN** 标注员触发绑定绘制
- **THEN** 提示 SHALL 明确说明完成绘制后会创建并回填新 `group_id`

#### Scenario: 操作被拒绝

- **GIVEN** 未配置映射、来源非法、多选来源或同组目标重复
- **WHEN** 系统拒绝数字快捷操作
- **THEN** 提示 SHALL 明确指出本次拒绝原因

### Requirement: 模式和文件切换清理快捷键瞬时状态

切换数字快捷模式、进入编辑模式、切换图片或撤销当前绘制时，系统 SHALL 清理 pending bind context 与尚未消费的数字目标标签。

#### Scenario: bind_draw 切换为 rename

- **GIVEN** 当前存在未完成 pending bind
- **WHEN** 用户将模式切换为 `rename`
- **THEN** 系统 SHALL 清理 pending bind
- **AND** 来源对象 SHALL 保持未修改

#### Scenario: 切换图片

- **GIVEN** 当前图片存在未完成数字绑定绘制
- **WHEN** 用户加载另一张图片
- **THEN** 上一图片的 pending context MUST 不得泄漏到新图片

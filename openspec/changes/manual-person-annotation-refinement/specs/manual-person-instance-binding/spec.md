## ADDED Requirements

### Requirement: 手动新建 person 自动创建人物实例

当“新建 person 自动创建人物实例”开启时，系统 SHALL 为没有绑定绘制上下文的手动新建 `person rectangle` 分配新的合法 `group_id`，且该行为 SHALL 优先于沿用上一个 `group_id`。

#### Scenario: 连续绘制 person 创建不同实例

- **GIVEN** 自动人物实例和自动沿用上一个标签均已开启
- **WHEN** 标注员连续手动绘制多个 `person rectangle`
- **THEN** 每个新 person SHALL 获得不同且递增的 `group_id`
- **AND** 每个 shape 的 label SHALL 保持为 `person`

#### Scenario: 功能关闭时保持原行为

- **GIVEN** 自动人物实例功能已关闭
- **WHEN** 标注员手动绘制 `person rectangle`
- **THEN** 系统 SHALL 不因本功能自动分配新的 `group_id`

#### Scenario: 自动标注结果不触发人物实例创建

- **GIVEN** 自动人物实例功能已开启
- **WHEN** auto-labeling 结果落地为 `person rectangle`
- **THEN** 系统 MUST 不调用手动人物实例自动分配流程

### Requirement: 绑定绘制使用单个明确来源

绑定绘制模式 SHALL 要求 `head` 和 `face` 的快捷创建选择且只选择一个来源对象；无来源快捷创建的唯一例外 SHALL 是自动人物实例已开启时的新建 `person rectangle`。

#### Scenario: 单选人物成员作为来源

- **GIVEN** 标注员选中一个 `person`、`head` 或 `face` 矩形
- **WHEN** 按下映射到另一个人物成员矩形的数字键
- **THEN** 系统 SHALL 接受该对象作为唯一绑定来源并进入目标绘制模式

#### Scenario: 无来源创建 head 或 face

- **GIVEN** 当前未选择任何来源对象
- **WHEN** 标注员按下映射到 `head` 或 `face` 的数字键
- **THEN** 系统 SHALL 拒绝进入绘制并提示先选择来源对象

#### Scenario: 无来源创建 person

- **GIVEN** 当前未选择来源且自动人物实例功能已开启
- **WHEN** 标注员按下映射到 `person rectangle` 的数字键
- **THEN** 系统 SHALL 进入 person 绘制并在完成后分配新的 `group_id`

#### Scenario: 多选来源

- **GIVEN** 当前选择了两个或更多对象
- **WHEN** 标注员触发绑定绘制
- **THEN** 系统 SHALL 拒绝执行且不创建 pending bind context

### Requirement: 绑定来源和目标限制为人物成员矩形

系统 SHALL 仅接受 label 属于 `person`、`head`、`face` 且 `shape_type == "rectangle"` 的绑定来源和目标，不得把任意 rectangle 自动解释为人物实例成员。

#### Scenario: 非人物标签作为来源

- **GIVEN** 唯一选中来源为 `car rectangle`
- **WHEN** 标注员触发人物绑定绘制
- **THEN** 系统 SHALL 拒绝来源并保持画布数据不变

#### Scenario: 人物标签使用非矩形形状

- **GIVEN** 来源或快捷目标为 `person polygon`
- **WHEN** 标注员触发绑定绘制
- **THEN** 系统 SHALL 拒绝执行并说明仅支持 rectangle

### Requirement: 绑定绘制继承或延迟分配 group_id

若来源具有合法 `group_id`，目标 SHALL 继承该 ID；若来源没有 `group_id`，系统 SHALL 只在 pending context 中记录拟分配的新 ID，并延迟到成功提交时回填来源。

#### Scenario: 来源已有合法 group_id

- **GIVEN** 来源对象的 `group_id` 为非负整数 7
- **WHEN** 绑定目标绘制成功
- **THEN** 新目标的 `group_id` SHALL 为 7
- **AND** 来源对象 SHALL 保持 `group_id == 7`

#### Scenario: 来源没有 group_id

- **GIVEN** 来源对象的 `group_id` 为 `null`
- **WHEN** 标注员开始绑定绘制但尚未完成目标
- **THEN** 来源对象的 `group_id` SHALL 继续为 `null`
- **AND** pending context SHALL 保存拟分配的新 ID 和回填标记

#### Scenario: 来源 group_id 不合法

- **GIVEN** 来源 `group_id` 为字符串、负数或 bool
- **WHEN** 标注员触发绑定绘制
- **THEN** 系统 SHALL 拒绝执行并提示先修正 `group_id`
- **AND** 系统 MUST 不因类型转换发生崩溃

### Requirement: 同一人物实例内成员标签唯一

系统 SHALL 允许一个合法 `group_id` 同时包含一个 `person`、一个 `head` 和一个 `face`，但 SHALL 拒绝同组内出现第二个相同成员标签。

#### Scenario: 同组 head 与 face 共存

- **GIVEN** group 3 已包含一个 `head`
- **WHEN** 标注员绑定创建一个 `face`
- **THEN** 系统 SHALL 允许创建且两者 SHALL 共享 `group_id == 3`

#### Scenario: 同组重复 head

- **GIVEN** group 3 已包含一个 `head`
- **WHEN** 标注员尝试再绑定创建一个 `head`
- **THEN** 系统 SHALL 在进入绘制前拒绝创建

#### Scenario: 绘制期间出现重复目标

- **GIVEN** 绑定绘制开始时目标标签尚未重复
- **WHEN** 最终提交前同组中已经出现相同标签
- **THEN** 系统 SHALL 在提交校验中拒绝本次目标并丢弃临时框

### Requirement: 来源回填与目标落标原子提交

绑定提交 SHALL 明确区分无 pending、可提交和已拒绝三种结果；只有全部校验通过时，系统 SHALL 在同一 undo 快照中提交来源回填与目标 label、shape type、`group_id`。

#### Scenario: 标签校验失败

- **GIVEN** pending bind 要求为无 ID 来源回填新 ID
- **WHEN** 目标标签未通过 label 校验
- **THEN** 系统 SHALL 丢弃临时目标
- **AND** 来源 `group_id` SHALL 保持不变

#### Scenario: 来源在绘制期间变化

- **GIVEN** pending bind 已记录来源和 `group_id`
- **WHEN** 提交前来源被删除、类型改变或 `group_id` 改变
- **THEN** 系统 SHALL 拒绝提交且不得降级为普通数字绘制

#### Scenario: 成功提交后撤销

- **GIVEN** 无 ID 来源与新目标已原子提交到同一个人物实例
- **WHEN** 标注员执行一次 undo
- **THEN** 新目标 SHALL 被撤销
- **AND** 来源的自动回填 SHALL 同时恢复

### Requirement: 取消路径清理全部瞬时绑定状态

取消绘制、Backspace 清空最后一点、矩形裁剪失败、切换图片、撤销或切换模式时，系统 SHALL 同时清理 pending bind context 与数字目标标签，并 SHALL 不修改来源对象。

#### Scenario: Esc 取消绑定绘制

- **GIVEN** 来源无 `group_id` 且绑定绘制正在进行
- **WHEN** 标注员按 Esc
- **THEN** pending context 和数字目标标签 SHALL 被清理
- **AND** 来源 `group_id` SHALL 保持为 `null`

#### Scenario: 裁剪失败取消目标

- **GIVEN** 绑定目标矩形无法裁剪为合法图像内矩形
- **WHEN** Canvas 终止本次绘制
- **THEN** 系统 SHALL 清理绑定状态且不得留下目标 shape

### Requirement: 人物实例 group_id 使用统一合法性定义

创建、绑定、分配和质检流程 SHALL 将合法 `group_id` 统一定义为非 bool 的非负整数；关键点工具的姿态主体 SHALL 继续由 `person` 充当锚点。

#### Scenario: 分配新 group_id 时存在脏数据

- **GIVEN** 当前文件含字符串、负数或 bool 类型的历史 `group_id`
- **WHEN** 系统生成新的 `group_id`
- **THEN** 系统 SHALL 忽略非法值并基于合法整数计算下一个 ID

#### Scenario: 质检同组成员

- **GIVEN** 同一合法 group 内各有一个 `head` 和一个 `face`
- **WHEN** 执行人物实例唯一性质检
- **THEN** 系统 SHALL 不把二者共享 `group_id` 报告为重复错误

## Purpose

让用户对跨图片收集的具体标记对象执行明确、可预检、可恢复的字段批量设置，并在字段缺失时安全创建该字段，同时保证未选择字段、未标记对象和独立的数据格式补全流程不受影响。

## ADDED Requirements

### Requirement: 系统必须提供独立的已标记对象字段编辑动作
系统 SHALL 提供“批量编辑已标记对象”动作，并 MUST 使用启动时冻结的跨图标记快照作为目标集合。一次请求 SHALL 包含一个或多个明确的字段设置，标记手势本身 MUST NOT 修改 JSON。

#### Scenario: 启动字段编辑
- **WHEN** 用户已经跨图片标记对象并打开字段编辑动作
- **THEN** 系统显示本次快照对象数、文件数和字段设置编辑界面

#### Scenario: 取消字段编辑
- **WHEN** 用户在预检确认前取消字段编辑
- **THEN** 系统不修改文件并保留启动前的全部活动标记

### Requirement: 字段编辑必须使用明确白名单和类型
系统 MUST 对可编辑字段使用明确的字段路径与类型约束。首版 SHALL 支持非空字符串 `label`、布尔值 `difficult`、整数或空值 `group_id`、字符串 `description`、数值或空值 `score`、布尔值 `flags.<key>`，以及 JSON 标量 `attributes.<key>`。系统 MUST 拒绝通用修改 `xanylabeling_shape_id`、`points`、`shape_type`、`direction` 和 `kie_linking`。

#### Scenario: 设置合法字段
- **WHEN** 用户为白名单字段输入符合类型要求的值
- **THEN** 系统接受该设置并将其纳入预检

#### Scenario: 请求修改受保护字段
- **WHEN** 用户或调用方请求修改对象身份、几何、类型或关系结构字段
- **THEN** 系统在创建执行计划前拒绝请求且不修改文件

#### Scenario: 字段值类型错误
- **WHEN** 用户输入的目标值不符合所选字段类型
- **THEN** 系统显示类型错误且不允许进入提交阶段

### Requirement: 设置缺失字段时必须直接创建且单独计数
系统 MUST 区分字段不存在、字段已存在且等于目标值、字段已存在但值不同三种状态。对顶层字段执行设置时，字段不存在 SHALL 被分类为 `created` 并直接写入目标值；字段存在且值相同 SHALL 被分类为 `unchanged`；字段存在但值不同 SHALL 被分类为 `updated`。系统 MUST NOT 使用运行时默认值把缺失字段误判为无变化。

#### Scenario: 缺失 difficult 时设置 false
- **WHEN** 目标 Shape 没有 `difficult` 且用户设置 `difficult = false`
- **THEN** 预检显示该字段将被新增，提交后 JSON 包含显式的 `"difficult": false`

#### Scenario: 已有相同值
- **WHEN** 目标 Shape 已有 `difficult = false` 且用户设置相同值
- **THEN** 系统把该字段结果报告为无变化并不因该字段单独产生写入

#### Scenario: 已有不同值
- **WHEN** 目标 Shape 已有 `difficult = true` 且用户设置 `difficult = false`
- **THEN** 预检显示该字段将被修改，提交后只把该字段改为 false

### Requirement: 嵌套字段缺失与类型冲突必须有确定行为
对 `flags.<key>` 或 `attributes.<key>` 执行设置时，父字段缺失 SHALL 创建空对象后写入子键；父字段为对象但子键缺失 SHALL 直接创建子键；父字段存在但不是对象 MUST 报告类型冲突。包含类型冲突目标的文件 MUST 保持不变，以免一次文件替换混合可靠与不可靠修改。

#### Scenario: flags 父字段缺失
- **WHEN** 目标 Shape 没有 `flags` 且用户设置 `flags.orphan_head = true`
- **THEN** 系统把 `flags` 创建为对象并写入 `orphan_head`，其他字段保持不变

#### Scenario: flags 类型非法
- **WHEN** 目标 Shape 的 `flags` 是字符串、列表、数字或空值
- **THEN** 系统报告类型冲突并保持该 Shape 所在文件不变

#### Scenario: attributes 子键缺失
- **WHEN** 目标 Shape 已有合法 `attributes` 对象但目标子键不存在
- **THEN** 系统新增该子键并保留 `attributes` 中其他键值

### Requirement: 普通字段编辑不得隐式执行字段补全
系统 MUST 只修改用户明确选择的字段路径及创建该路径所必需的父对象。字段补全 MUST 作为独立数据规范化能力，不得由本动作自动调用，也不得成为字段编辑的前置条件。未选字段即使缺失也 MUST 保持缺失。

#### Scenario: 只设置 difficult
- **WHEN** 目标 Shape 同时缺少 `difficult`、`score`、`description` 和 `attributes`，而用户只设置 `difficult = false`
- **THEN** 系统只新增 `difficult`，其余缺失字段继续保持缺失

#### Scenario: 未先运行字段补全
- **WHEN** 用户从未执行独立字段补全功能但目标字段缺失
- **THEN** 系统仍允许预检并按缺失字段创建规则完成设置

### Requirement: difficult 的旧格式别名不得被静默迁移
顶层 `difficult` SHALL 是字段编辑动作的规范目标。发现 `flags.difficult` 时，系统 SHALL 在预检中提示旧格式别名；普通 `difficult` 设置 MUST NOT 静默删除或改写 `flags.difficult`。当两处值冲突时，系统 MUST 明确提示潜在不一致。

#### Scenario: 仅存在 flags.difficult
- **WHEN** Shape 没有顶层 `difficult` 但存在 `flags.difficult = true`，用户设置顶层 `difficult = false`
- **THEN** 系统把顶层字段分类为将新增并提示旧格式别名存在，不自动删除 `flags.difficult`

#### Scenario: 两处值冲突
- **WHEN** 顶层 `difficult` 与 `flags.difficult` 同时存在且值不同
- **THEN** 预检明确显示不一致提示，用户可以取消且取消时文件保持不变

### Requirement: 预检必须按对象和字段反映实际变化
系统 SHALL 在写盘前显示快照对象数、涉及文件数，以及字段级 `created`、`updated`、`unchanged`、类型冲突数量，并继续显示对象已删除、身份冲突和文件读取失败数量。只有用户明确确认后，系统才 SHALL 暂存和提交。

#### Scenario: 同一批次包含新增、修改和无变化
- **WHEN** 不同目标对象对同一字段分别处于缺失、不同值和相同值状态
- **THEN** 预检分别显示新增、修改和无变化数量，不把三者合并成同一种结果

#### Scenario: 一个对象包含多个字段设置
- **WHEN** 同一目标对象的一部分字段将新增、另一部分将修改、其余字段无变化
- **THEN** 预检显示该对象的逐字段结果，并把对象纳入需要提交的对象数

### Requirement: 字段编辑必须复用安全事务和精确结果同步
系统 SHALL 复用现有对象级批处理的严格身份定位、源文件指纹检查、暂存验证、备份、原子替换、恢复清单和项目级写互斥。成功满足全部字段意图、全部无变化或确认已删除的对象 SHALL 从活动标记中移除；冲突、读取失败、写入失败和取消的对象 MUST 保留标记以便重试。

#### Scenario: 非目标内容保持不变
- **WHEN** 一个文件中同时存在已标记和未标记对象
- **THEN** 系统只修改唯一命中的已标记对象及其明确选择的字段路径，未标记对象、未选字段和根对象其他内容保持不变

#### Scenario: 源文件预检后发生变化
- **WHEN** 源文件在预检后被外部修改
- **THEN** 系统拒绝覆盖该文件、报告失败并保留对应对象标记

#### Scenario: 部分文件提交失败
- **WHEN** 批次中一部分文件成功而另一部分文件失败
- **THEN** 系统只清除成功满足意图对象的标记，保留失败对象标记并提供实际成功文件的恢复信息

### Requirement: 现有标签专用入口必须保持兼容
现有“修改已标记对象的标签”动作 SHALL 保持原有用户行为、确认流程和结果语义。实现 MAY 把它适配为单字段 `label` 设置，但 MUST NOT 要求用户改用通用字段编辑界面。

#### Scenario: 使用现有改标签入口
- **WHEN** 用户从原有入口选择目标标签并确认
- **THEN** 系统继续只修改目标对象的 `label`，不补全或修改其他字段

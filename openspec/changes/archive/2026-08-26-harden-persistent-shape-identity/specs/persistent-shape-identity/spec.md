## Purpose

为 X-AnyLabeling JSON 生命周期中的每个 Shape 提供稳定、唯一且可验证的持久身份，使编辑历史、行为分析和复核等下游能力能够可靠关联同一标注对象，同时保持旧文件和外部交换格式兼容。

## ADDED Requirements

### Requirement: Shape 具有专用持久身份
系统 SHALL 在每个 Shape 的顶层 `xanylabeling_shape_id` 字段保存非空字符串身份。系统新生成的身份 MUST 使用随机 UUID，且同一标注文件内所有已加载 Shape 的身份 MUST 唯一。跨文件消费对象身份时，系统 SHALL 使用项目身份、图片身份和 Shape 身份组成完整键，而不假定 Shape ID 单独承担跨项目全局主键语义。

#### Scenario: 新建 Shape
- **WHEN** 用户手工创建或 AI 生成一个新 Shape
- **THEN** 系统在该 Shape 可被保存或下游模块引用前为其生成非空 UUID 身份

#### Scenario: 同一文件中的不同 Shape
- **WHEN** 一个标注文件包含多个可用 Shape
- **THEN** 每个 Shape 的 `xanylabeling_shape_id` 均非空且互不相同

### Requirement: 身份字段与业务字段分离
系统 MUST 将 `xanylabeling_shape_id` 作为 Shape 顶层专用字段处理，并 MUST NOT 使用 `group_id`、`flags`、`attributes`、`kie_linking`、标签、几何哈希或 Shape 数组下标代替持久身份。

#### Scenario: Shape 被分组并携带业务元数据
- **WHEN** Shape 同时包含 `group_id`、`flags`、`attributes` 和 `kie_linking`
- **THEN** 身份读写不会覆盖或改变这些字段，且这些字段也不会改变 Shape 身份

#### Scenario: 修改标签或几何
- **WHEN** 用户修改 Shape 的标签、点坐标、属性或描述
- **THEN** Shape 保留修改前的 `xanylabeling_shape_id`

### Requirement: 创建新对象与恢复既有对象采用不同身份语义
系统 SHALL 在恢复既有对象状态时保留身份，并在产生独立新对象时生成新身份。

#### Scenario: 撤销和重做编辑
- **WHEN** 系统通过撤销快照或重做恢复一个既有 Shape
- **THEN** 恢复后的 Shape 沿用该对象原有身份

#### Scenario: 删除后撤销
- **WHEN** 用户删除一个 Shape 后撤销删除
- **THEN** 恢复的 Shape 沿用删除前的身份

#### Scenario: 复制或粘贴
- **WHEN** 用户复制、Duplicate 或从剪贴板粘贴 Shape 以创建独立对象
- **THEN** 每个新对象获得不同于来源 Shape 且不同于当前文件其他 Shape 的新身份

#### Scenario: 导入为新对象
- **WHEN** 外部 Shape 被合并或导入当前标注文件并被视为新对象
- **THEN** 系统不信任来源身份并为导入对象生成当前文件内唯一的新身份

### Requirement: 旧文件和冲突输入在加载边界被规范化
系统 SHALL 兼容缺少身份字段的旧 JSON。加载现有标注文件时，系统 MUST 在 Shape 对下游可见前规范化缺失、非字符串、空字符串和同文件重复身份；首个有效非空字符串身份 SHALL 被保留，后续冲突 Shape SHALL 获得新身份。系统 SHALL 提供可诊断信息指出发生过身份修复。

#### Scenario: 旧 JSON 缺少身份
- **WHEN** 系统加载一个没有 `xanylabeling_shape_id` 的 Shape
- **THEN** 系统在内存中为其生成当前文件内唯一身份，且不会仅因补 ID 将文件标记为用户已修改

#### Scenario: 身份字段类型或内容非法
- **WHEN** Shape 的身份字段不是字符串或是空字符串
- **THEN** 系统在内存中替换为当前文件内唯一的新身份并记录诊断信息

#### Scenario: 同一文件存在重复身份
- **WHEN** 按文件顺序加载的两个或更多 Shape 使用相同有效身份
- **THEN** 系统保留首次出现者的身份，为后续出现者生成新身份，并记录重复修复诊断

### Requirement: 保存和重载保持身份稳定
系统 SHALL 将内存中的 Shape 身份随 X-AnyLabeling JSON 一起保存。保存入口 MUST 在写文件前验证所有 Shape 身份非空且唯一；若不变量仍被破坏，保存 MUST 明确失败而不能写出含歧义身份的 JSON。成功保存并重新加载后，各 Shape 身份 SHALL 保持不变。

#### Scenario: 旧文件发生真实标注修改后保存
- **WHEN** 缺失身份的旧文件已被加载，随后用户进行了真实标注修改并保存
- **THEN** 系统将内存补齐的身份写入 JSON

#### Scenario: 文件往返
- **WHEN** 系统保存一个包含多个 Shape 的文件并重新加载该文件
- **THEN** 每个 Shape 的身份与保存前一致且仍然唯一

#### Scenario: 保存前发现运行时重复身份
- **WHEN** 扩展或异常运行时路径造成两个 Shape 在保存前持有同一身份
- **THEN** 系统拒绝写出文件并提供可定位的错误，而不在保存阶段静默改变对象身份

### Requirement: 项目私有身份止于交换格式边界
系统 MUST 在 X-AnyLabeling JSON 中保留身份，但 MUST NOT 将 `xanylabeling_shape_id` 导出到没有对应身份扩展契约的 VOC、YOLO、COCO 等交换格式。转换过程 MUST NOT 修改源标注文件。

#### Scenario: 导出 VOC 或 YOLO
- **WHEN** 包含 `xanylabeling_shape_id` 的标注文件被导出为 VOC 或 YOLO
- **THEN** 目标文件不包含该私有身份，源 JSON 的身份和业务字段保持不变

#### Scenario: 导出 COCO
- **WHEN** 包含持久身份的标注文件被导出为 COCO
- **THEN** COCO 输出仅使用其格式定义的公共字段，不泄漏 `xanylabeling_shape_id`

### Requirement: 下游持久引用使用稳定身份
需要跨编辑、保存或重载关联同一 Shape 的下游模块 SHALL 使用持久 Shape 身份或包含它的完整对象键。仅限单次内存布局或瞬时渲染的内部逻辑 MAY 使用数组下标或运行时对象地址，但不得将其作为持久引用写出。

#### Scenario: 行为事件关联 Shape
- **WHEN** 系统记录针对某个 Shape 的跨时间行为事件
- **THEN** 事件使用包含持久 Shape 身份的对象键关联该 Shape

#### Scenario: 瞬时 UI 布局
- **WHEN** UI 仅在一次渲染或内存扫描中标识 Shape
- **THEN** 系统可以使用瞬时身份，但该身份不会作为跨保存周期的对象引用持久化

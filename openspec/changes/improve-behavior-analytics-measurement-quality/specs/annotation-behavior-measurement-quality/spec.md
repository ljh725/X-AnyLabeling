## Purpose

在不记录原始鼠标轨迹、完整几何或自由文本的前提下，把标注交互归一化为具有可靠边界、耗时、对象上下文和结果的语义动作，为对象效率、返工和功能效果分析提供可解释的测量基础。

## ADDED Requirements

### Requirement: 一个逻辑操作只产生一个语义动作
系统 SHALL 将一次连续拖拽、键盘连续微调、滚轮缩放、平移、标签修改或属性修改归一化为一个语义动作段。底层鼠标移动、几何变化回调和重复保存通知 MUST NOT 各自成为可计数的等价动作。

#### Scenario: 连续拖拽矩形边缘
- **WHEN** 用户按下矩形边缘、连续移动并释放
- **THEN** 系统只产生一个包含开始、结束、净变化、结果和耗时的矩形调整动作

#### Scenario: 同一动作触发多个变化回调
- **WHEN** 一个提交动作在 UI 内部触发多个 `shape_edited` 回调
- **THEN** 系统通过动作 ID 或关联 ID 将它们归并为一个可计数动作

### Requirement: 支持的编辑动作具有完整生命周期和单调耗时
每个支持的语义编辑动作 SHALL 记录 `started` 与 `committed`、`cancelled`、`no_change` 或 `interrupted` 之一的终态，并以单调时钟计算 `duration_ms`。动作异常中断时 MUST 保留不完整原因，不得补造成功结果或墙钟耗时。

#### Scenario: 提交有效几何修改
- **WHEN** 用户完成一次产生有效净变化的整体移动、边调整、角调整或关键点移动
- **THEN** 系统记录 `success` 结果、编辑目标、净变化摘要和有效单调耗时

#### Scenario: 取消或无变化提交
- **WHEN** 用户取消编辑或释放后几何摘要没有有效变化
- **THEN** 系统分别记录 `cancelled` 或 `no_change`，且不得计入成功编辑次数

### Requirement: 对象 episode 和活跃片段具有明确边界
系统 SHALL 在对象被选中时开始 episode，并在切换对象、取消选择、删除当前对象、切换图片或关闭项目时以明确原因结束。失焦和超过阈值的空闲 SHALL 结束当前活跃片段但不伪造对象完成；恢复操作时 SHALL 在同一 episode 内建立新的活跃片段，除非选择关系已经结束。

#### Scenario: 对象之间来回选择
- **WHEN** 用户依次选择 A、B、A
- **THEN** A 保持稳定对象身份，但产生两个 episode，且每个 episode 都有开始、结束和结束原因

#### Scenario: 选中对象后长时间空闲
- **WHEN** 用户保持对象选中但超过空闲阈值后恢复编辑
- **THEN** wall 时间包含空闲，active 时间排除空闲，并在 episode 中形成两个活跃片段

### Requirement: 对象完成状态来自可审计事实
系统 SHALL 为 episode 记录是否发生有效修改、修改后是否保存、最终退出原因以及是否在后续 episode 返回。系统 MUST NOT 仅因取消选择就断言对象已经完成标注。

#### Scenario: 修改并保存后切换对象
- **WHEN** 用户有效修改对象、保存标签并选择另一个对象
- **THEN** episode 显示 `changed=true`、`saved_after_change=true` 和 `end_reason=selection_changed`

#### Scenario: 仅查看后离开对象
- **WHEN** 用户选择对象但未发生有效修改就离开
- **THEN** episode 显示 `changed=false`，且不计入已完成编辑对象

### Requirement: 上下文维度采用隐私安全摘要
语义动作 SHALL 可携带 shape 类型、编辑目标、点数分桶、尺寸分桶、宽高比分桶、初始来源和受控标签类别等上下文。系统 MUST NOT 在行为日志中写入完整 points、自由文本标签、图片像素、用户名或绝对路径；不在安全标签注册表中的标签 SHALL 使用匿名稳定键或 `unknown`。

#### Scenario: 编辑一个小型矩形
- **WHEN** 用户调整一个被规则归类为小目标的 rectangle
- **THEN** 动作记录 `shape_type=rectangle`、`size_bucket=small` 和编辑目标，但不记录完整坐标

#### Scenario: 标签不在安全注册表中
- **WHEN** shape 的标签值不属于允许直接记录的受控集合
- **THEN** 系统记录匿名标签键或 `unknown`，不写入原始标签文本

### Requirement: 返工事实具有稳定且版本化的判定依据
系统 SHALL 记录或可确定性推导撤销关联、反向调整、新建后删除、保存后再编辑、无变化提交和对象重复返回等返工事实。每类返工规则 MUST 具有算法版本、时间窗口和上下文边界，不得跨项目会话或图片错误关联。

#### Scenario: 修改后立即撤销
- **WHEN** 一个撤销动作在配置时间窗内明确关联到前一个成功编辑
- **THEN** 系统把该编辑标记为 `undone`，并保留原始动作和撤销事实

#### Scenario: 对象保存后再次返回编辑
- **WHEN** 同一复合对象身份在保存后进入新的 episode 并发生有效修改
- **THEN** 系统记录一次返回编辑和一次保存后返工

### Requirement: 功能使用状态必须由实际动作证明
功能状态 SHALL 继续区分 `configured`、`active` 和 `used`；其中 `used=true` MUST 由功能实际参与的语义动作或唯一权威判定器产生，并与动作和状态版本关联。仅开启配置或处于适用模式不得自动视为已使用。

#### Scenario: 精修功能已开启但未参与动作
- **WHEN** 矩形精修已配置且当前可用，但用户没有执行精修动作
- **THEN** 系统记录 `configured=true`、`active=true`、`used=false`

#### Scenario: 精修功能实际参与调整
- **WHEN** 用户通过精修功能提交一次有效矩形调整
- **THEN** 相关动作引用该功能状态版本，且权威使用状态变为 `used=true`

### Requirement: 测量质量具有可验收覆盖率
系统 SHALL 输出支持动作的耗时覆盖率、episode 闭合率、低层重复事件率、上下文覆盖率、异常长轮次数和缺失终态数。验收夹具中支持编辑动作的有效耗时覆盖率 MUST 不低于 95%，episode 闭合率 MUST 不低于 99%，等价低层重复事件率 MUST 低于 5%。

#### Scenario: 测量覆盖率低于门槛
- **WHEN** 一次验收运行的有效编辑耗时覆盖率或 episode 闭合率未达到要求
- **THEN** 质量报告明确失败指标、分母、分子和受影响事件类型，且不得把结果标记为测量质量合格

### Requirement: 新旧事件版本可并存读取
系统 SHALL 为新增字段和语义动作契约升级事件 schema，并继续只读接受首版事件。旧事件缺少动作边界、上下文或耗时时 SHALL 仅退出依赖字段的指标，并在质量报告中统计，不得丢弃其仍然有效的动作次数。

#### Scenario: 同时分析版本 1 和新版事件
- **WHEN** 所选范围包含首版事件和新版语义动作事件
- **THEN** 系统输出合并动作次数，并分别报告各版本的耗时和上下文覆盖率

## Purpose

在矩形边精修期间持续呈现“正在操作哪条边、从哪里移动到哪里、结果是否已提交”的统一反馈，降低误操作、反复试探和撤销带来的认知负担。

## ADDED Requirements

### Requirement: 边状态具有稳定且互斥的视觉表达
系统 SHALL 区分 hover、活动、拖动和键盘活动边状态，同一时刻 SHALL 只有一条边作为正式活动目标。边样式 SHALL 以屏幕像素定义并在不同缩放下保持可辨认。

#### Scenario: hover 边转为拖动边
- **WHEN** 用户在 hover 边上按下并开始拖动
- **THEN** 该边 SHALL 转为拖动样式，其他边 MUST NOT 同时显示为活动目标

#### Scenario: 鼠标接管键盘活动边
- **WHEN** 键盘活动边存在且用户点击另一条矩形边
- **THEN** 新点击边 SHALL 成为唯一活动边，旧键盘活动边 SHALL 退出活动状态

### Requirement: 调整期间显示原边和实时数值
边拖动或离散微调期间，系统 SHALL 显示调整开始时的原边参照，以及当前边名、原坐标、当前坐标、有符号位移和当前矩形宽高。反馈 MUST NOT 遮挡目标边的主要观察区域。

#### Scenario: 左边向内移动
- **WHEN** 左边从 x=126 移动到 x=129
- **THEN** 系统 SHALL 显示原边参照和至少包含“left、126 → 129、Δ +3px、当前宽高”的反馈

#### Scenario: 连续离散微调更新同一反馈
- **WHEN** 用户对活动边连续执行 1px 微调
- **THEN** 系统 SHALL 相对本次调整开始位置更新累计位移，而不是每次只显示单步位移

### Requirement: 提交取消和拒绝结果明确
系统 SHALL 在鼠标释放或离散微调批次完成时提示已提交结果，在 Esc 或输入中断回滚时提示已恢复原位置，并在几何约束拒绝操作时说明拒绝原因。

#### Scenario: Esc 取消拖动
- **WHEN** 用户在活动边拖动期间按 Esc
- **THEN** 矩形 SHALL 恢复拖动前坐标且反馈 SHALL 明确显示“已取消并恢复”

#### Scenario: 最小尺寸约束拒绝
- **WHEN** 用户的候选移动会使矩形小于最小尺寸
- **THEN** 系统 SHALL 保持矩形不变并提示最小尺寸约束，而不是静默失败

### Requirement: 反馈不进入标注数据
所有精修反馈 SHALL 为瞬态界面状态，MUST NOT 写入 shape、标注 JSON、dirty 判断、undo 快照或导出数据。

#### Scenario: 仅显示反馈未修改几何
- **WHEN** 用户 hover 一条边但未执行任何移动
- **THEN** 标注数据、dirty 状态和 undo 栈 SHALL 保持不变


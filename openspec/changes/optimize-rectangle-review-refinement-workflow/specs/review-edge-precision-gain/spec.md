## Purpose

为矩形框审核提供与缩放无关、对低倍视图更友好的边拖动控制增益，使舒适的鼠标位移稳定映射为少量图像像素修正，同时保留快速粗调能力。

## ADDED Requirements

### Requirement: 精修增益限制最大图像位移
系统 SHALL 以“每个屏幕像素最多移动多少图像像素”定义矩形边精修增益，默认目标增益 SHALL 为 `0.5 image-pixel/screen-pixel`。有效增益 SHALL 为 `min(1 / canvas_scale, target_gain)`，系统 MUST NOT 在高缩放已经更精细时反向放大鼠标位移。

#### Scenario: 低倍视图获得更强降速
- **WHEN** 画布为 50% 缩放且用户在精修拖动中移动鼠标 8 个屏幕像素
- **THEN** 目标边 SHALL 移动 4 个图像像素，而不是普通拖动的 16 个图像像素

#### Scenario: 百分百缩放匹配舒适动作范围
- **WHEN** 画布为 100% 缩放且用户在精修拖动中移动鼠标 5 至 8 个屏幕像素
- **THEN** 目标边 SHALL 移动 2.5 至 4 个图像像素

#### Scenario: 高倍视图不被加速
- **WHEN** 画布缩放使普通拖动增益已经低于目标增益
- **THEN** 系统 SHALL 保持普通缩放带来的更精细增益并 MUST NOT 将其提高到目标增益

### Requirement: 矩形边拖动默认使用精修增益
当且仅当用户拖动单个已选矩形的明确活动边时，系统 SHALL 默认使用精修增益；整框拖动和非矩形对象拖动 SHALL 保持现有普通增益。

#### Scenario: 直接拖动活动边
- **WHEN** 用户按下并拖动单个已选矩形的活动边
- **THEN** 系统 SHALL 自动应用精修增益且不要求持续按住修饰键

#### Scenario: 整框移动不被降速
- **WHEN** 用户从矩形内部拖动整个矩形
- **THEN** 系统 SHALL 使用普通拖动增益

### Requirement: 粗调修饰键临时恢复普通增益
活动边拖动期间，系统 SHALL 使用 `Shift` 作为临时粗调修饰键；修饰键状态变化 MUST NOT 导致边坐标跳变。历史 Ctrl 精修入口 SHALL 在迁移期保持可用，但 MUST NOT 与 Shift 粗调产生歧义。

#### Scenario: 按住 Shift 粗调矩形边
- **WHEN** 用户拖动活动边并按住 Shift
- **THEN** 后续鼠标位移 SHALL 使用普通增益，松开 Shift 后 SHALL 从当前位置继续使用精修增益

#### Scenario: 拖动中切换速度不跳变
- **WHEN** 用户在同一次拖动中按下或松开 Shift
- **THEN** 系统 SHALL 重新建立位移累计基准且目标边 MUST NOT 因模式切换瞬移

### Requirement: 旧精修配置可迁移
系统 SHALL 优先使用新的目标增益配置；仅存在旧精修配置时，系统 SHALL 生成等价或保守的目标增益并提供一次迁移提示。迁移 MUST NOT 修改标注数据。

#### Scenario: 默认旧 zoom 配置迁移
- **WHEN** 用户配置仅包含旧的 zoom 精修模式和最大倍率 2.0
- **THEN** 系统 SHALL 将运行时目标增益解释为 0.5，并提示新的配置语义


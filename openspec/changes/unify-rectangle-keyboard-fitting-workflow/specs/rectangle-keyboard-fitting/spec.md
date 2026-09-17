## Purpose

让用户通过光标位置和可配置离散边界键直接调整普通矩形，明确半区保护、输入所有权、撤销和浮窗反馈，使被拒绝的定位不会触发标签操作，并在保持原图精度的前提下降低持续鼠标拖动的要求。

## ADDED Requirements

### Requirement: Configurable scoped boundary keys
系统 SHALL 提供顶右底左四个配置项、QWER 默认预设和 1234 预设，四极值与拟合共用。配置 SHALL 拒绝同模式重复键、任务控制保留键和未能受控分派的冲突；允许的临时重用 SHALL 显示模式内外用途。修改成功后 SHALL 同时更新执行与显示，失败时保留原配置。

#### Scenario: Controlled R reuse
- **WHEN** 用户采用 QWER 并进入拟合后按 R
- **THEN** R 只请求左边定位；退出后 R 恢复原创建矩形用途

#### Scenario: Duplicate mapping rejected
- **WHEN** 用户将顶边和底边配置为同一按键
- **THEN** 设置拒绝保存并指出冲突，原配置继续生效

### Requirement: Input ownership does not depend on geometric eligibility
拟合、拟合暂停和四极值草稿 SHALL 消费已映射边界键及其余裸数字，不执行数字标签／重命名／绑定操作。几何拒绝或步骤不符 MUST NOT 将按键回落至原动作；文本及对话框焦点 SHALL 保有其输入权，修饰键 SHALL 精确匹配。

#### Scenario: Numeric top rejected in lower half
- **WHEN** 1 映射顶边且光标处于矩形下半区，用户在拟合中按 1
- **THEN** 顶边不动，标签不变，不启动绘制，只显示拒绝原因

#### Scenario: Text field receives digits
- **WHEN** 标签或备注输入框有焦点且用户键入 1234
- **THEN** 输入框接收文字，画布不执行边界动作

#### Scenario: Unmapped digit is paused
- **WHEN** 拟合中用户按未映射为边界的裸数字
- **THEN** 显示标签操作暂停且不改变标签／工具

### Requirement: One physical press performs one boundary action
系统 SHALL 在独立按下时采样当前光标，每次按下至释放最多执行一次定位，忽略自动重复；启动草稿的数字事件 MUST NOT 同时记录第一边，完成时残余重复事件 MUST NOT 泄漏到新状态。

#### Scenario: Startup key is also top key
- **WHEN** 1 在普通状态启动四极值，同时配置为顶边键
- **THEN** 首次按下只启动，释放再按才采集顶边

#### Scenario: Hold final boundary key
- **WHEN** 用户按住第四边数字键直至创建完成
- **THEN** 仅提交一次形状，后续重复事件不重命名新形状

### Requirement: Current rectangle halves guard boundary placement
系统 SHALL 使用执行前矩形中心判断：顶 y<cy、右 x>cx、底 y>cy、左 x<cx。对应中心线上两个相反边均不可用，规则延伸至图像内的框外区域；执行前和每次修改／撤销／切目标后 SHALL 更新判定。未成框草稿 SHALL 不使用此半区规则。

#### Scenario: Quadrant eligibility
- **WHEN** 光标在当前矩形左上区域
- **THEN** 顶和左可定位，底和右不可定位

#### Scenario: Exact center
- **WHEN** 光标正好位于当前矩形中心
- **THEN** 四个边界定位键均被拒绝并给出提示

#### Scenario: Expand outside rectangle
- **WHEN** 光标在框左侧、图像范围内且左边定位后几何合法
- **THEN** 左边允许向外移动，其余三边不变

### Requirement: Image coordinates and atomic geometry are preserved
定位 SHALL 读取当前原图坐标，顶底只用 Y、左右只用 X，并保留浮点精度及原对象身份属性。失效目标、非有限值、图像越界、过小尺寸、鼠标按钮按住或光标位于浮窗／留白时 SHALL 拒绝；MUST NOT 使用旧光标位置、自动交换边或截断位移。每次实际变化 SHALL 是独立撤销单元；无变化和拒绝 SHALL 不增加 dirty 或历史。

#### Scenario: Zoomed coordinate sampling
- **WHEN** 用户缩放和平移后执行边界定位
- **THEN** 使用换算后的当前原图坐标，只修改目标一边并生成一个撤销单元

#### Scenario: Pointer over floating window
- **WHEN** 光标从图像移入浮窗并按边界键
- **THEN** 不使用先前图像坐标，提示移回图像

#### Scenario: Undo fitting independently
- **WHEN** 用户创建矩形、显式进入拟合、执行一次定位后撤销
- **THEN** 先还原该次边界定位，矩形仍存在；再次撤销才撤销创建

### Requirement: Floating feedback reflects executable actions
系统 SHALL 在任务期间显示可移动、不随光标漂移且不抢焦点的浮窗，使用实际配置键位和上右下左语义。创建显示步骤，拟合显示目标／区域／可用键；成功按键与目标边 SHALL 高亮，拒绝 SHALL 高亮对应键并说明原因，不只依赖颜色。模式结束 SHALL 关闭任务浮窗。

#### Scenario: Reconfigured key feedback
- **WHEN** 左边键改为 4 后用户在合法左半区按 4
- **THEN** 浮窗显示并高亮 4，左边同步高亮，显示本次位移

### Requirement: Deterministic nudging remains available
拟合定位成功后 SHALL 激活该边，方向键支持相应轴的 1px、Shift 5px 步进并遵守几何约束；该步进 SHALL 不依赖光标半区。浮窗选边按钮 SHALL 仅选边，不把浮窗坐标当成定位点；无活动边时方向键 MUST NOT 平移整框。

#### Scenario: Finish last pixel with keyboard
- **WHEN** 用户定位左边后把光标移开并按右方向键
- **THEN** 合法时仅左边增加 1 个原图像素，不重新采样光标

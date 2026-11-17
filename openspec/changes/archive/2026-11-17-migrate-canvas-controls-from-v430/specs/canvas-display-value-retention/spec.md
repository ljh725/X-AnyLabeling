## Purpose

为填充透明度、亮度和对比度提供独立的跨图保持控制，区分沿用当前显示值、恢复单图显示值与恢复默认值，并保留已有亮度/对比度配置、图像处理能力和同尺寸共享视图。

## ADDED Requirements

### Requirement: Each display value has an independent retention control
系统 SHALL 为透明度、亮度和对比度各提供保持按钮与恢复默认按钮；保持按钮具有可识别的启用状态及切图含义提示。亮度和对比度保持状态与已有菜单/设置双向同步；透明度保持默认开启且仅会话有效，不新增标注字段或要求重启持久化。

#### Scenario: Independent controls
- **WHEN** 用户只开启亮度保持、关闭对比度保持，并分别改变两个值
- **THEN** 切图时仅亮度沿用前图值，对比度遵循原有单图恢复规则；透明度由其自身按钮独立控制

#### Scenario: Change the existing setting
- **WHEN** 用户通过既有菜单或设置切换保持亮度/对比度
- **THEN** 对应面板按钮同步变化且不递归触发事件，重新启动时按已有配置读取两项保持状态

### Requirement: Successful image switches determine value restoration
系统 SHALL 在成功切到另一张图片后应用保持策略：开启时沿用切图前的值；关闭透明度保持时恢复 100%；关闭亮度/对比度保持时沿用已有按图片缓存恢复行为，未访问图片使用中性值 1.00。同一张图片重新加载不视为切至另一张。

#### Scenario: New and previously visited images
- **WHEN** 用户关闭三项保持，在图片 A、未访问 B 和已有单图显示值的 C 之间切换
- **THEN** B 使用透明度 100%、亮度/对比度 1.00；C 使用透明度 100% 及其既有亮度/对比度缓存，不从 A 泄漏参数

#### Scenario: Same-image refresh or failed switch
- **WHEN** 当前透明度为 40% 且不保持，用户重新加载当前图、取消切图或目标加载失败
- **THEN** 不把该操作当成成功切至另一张图片，不因保持策略提前清掉原有显示值

### Requirement: Resets and asynchronous display updates remain coherent
系统 SHALL 在恢复默认时同步滑块、数值和实际画面，但不改变保持开关；切图后不允许上一张待处理的亮度/对比度刷新覆盖目标图，16 位灰度图继续保留现有显示处理路径。显示参数保持不得重置共享缩放和中心点。

#### Scenario: Reset a retained value
- **WHEN** 用户在保持开启时恢复某项默认值
- **THEN** 当前图立即使用该默认值，保持仍开启且下一张沿用默认值，其他参数及缩放中心不变

#### Scenario: Rapid image navigation
- **WHEN** 用户拖动亮度滑块后立即连续切图，包括 16 位灰度图片
- **THEN** 画面与当前图片、当前滑块及保持策略一致，无上一张内容覆盖或修改原图，原有共享视图仍按尺寸分组恢复

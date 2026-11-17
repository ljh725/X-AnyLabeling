## Purpose

允许用户选择滚轮直接缩放或传统滚动浏览，通过明确且一致的修饰键规则区分导航和几何编辑，并确保切换模式、切图及本地共享视图恢复后画布位置仍准确可操作。

## ADDED Requirements

### Requirement: Wheel navigation is configurable and applies without restart
系统 SHALL 支持 `canvas.wheel_navigation_mode` 为 `direct` 或 `traditional`；缺省使用 `direct`，无效输入回退至 `direct` 并通过既有配置校验提示或日志报告。有效设置 SHALL 无需重启生效，设置窗口取消时不改变正在使用的模式，旧配置无需人工补字段。

#### Scenario: Default and saved mode
- **WHEN** 用户加载不含新字段的旧配置，或重新启动加载已保存的有效模式
- **THEN** 分别使用直接缩放或保存的模式，设置界面与实际行为一致

#### Scenario: Apply and cancel settings
- **WHEN** 用户应用传统模式，随后在设置中预选直接模式但取消
- **THEN** 应用后立即可用传统模式，取消不改变传统模式或当前标注几何

### Requirement: Wheel gestures have deterministic priority
系统 SHALL 采用以下优先级和映射：笔刷编辑中 Alt+滚轮调整笔刷；允许滚轮编辑且选中一个未锁定矩形时 Alt+滚轮沿用当前调框算法；有对比图时 Alt+Shift+滚轮调整分割位置；Ctrl+滚轮在两种模式下均缩放；无修饰键滚轮在 `direct` 下缩放、在 `traditional` 下滚动；Shift+滚轮沿用水平/垂直滚动分量。未匹配组合 SHALL 不触发几何修改。

#### Scenario: Navigate while a rectangle is selected
- **WHEN** 用户选中矩形并使用 Ctrl+滚轮，或在启用滚轮编辑后使用 Alt+滚轮
- **THEN** 前者只缩放视图，后者只执行已有矩形调整，单次事件不同时发生导航和几何修改

#### Scenario: Brush and compare gestures
- **WHEN** 笔刷编辑中使用 Alt+滚轮，或有对比图时使用 Alt+Shift+滚轮
- **THEN** 分别只调整笔刷半径或对比位置，不缩放视图；原 Ctrl+滚轮工具提示同步改为新映射

#### Scenario: Empty and horizontal wheel events
- **WHEN** 收到零增量滚轮事件、只有横向增量的事件或无图状态下的滚轮事件
- **THEN** 不产生错误、意外几何提交或重复处理；横向事件只在适用的滚动路径改变视图

### Requirement: Navigation modes preserve a coherent viewport
系统 SHALL 在传统模式按需显示滚动条，在直接模式沿用自由平移和隐藏滚动条；切换模式、缩放及切图后显示同一可达图像区域，传统模式允许依据图像边界夹紧中心。导航不改变对象坐标、身份或撤销记录。

#### Scenario: Switch navigation mode after zoom and pan
- **WHEN** 用户放大平移后切换模式并再次缩放或平移
- **THEN** 无双重位移、跳回旧滚动位置或无法到达的区域，右键/空格平移和导航器继续可用

#### Scenario: Shared view between same-size images
- **WHEN** 用户在任一模式调整视图并切换到同尺寸图片，再切换到不同尺寸图片
- **THEN** 同尺寸图片继续共享最近的缩放和图像中心，不同尺寸图片按既有分组恢复；传统模式仅按边界夹紧，不破坏共享视图重置入口

#### Scenario: Change mode during an active edit
- **WHEN** 拖边、单点拟合、四极值创建、绘制或平移尚在进行时请求切换模式
- **THEN** 不在交互中途重映射坐标或提交几何，至交互结束或取消后应用新模式，最终几何与保存结果一致

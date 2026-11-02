## Purpose

将既有画布显示控制集中到主工具栏，使用户能快速调整标注信息的可见性，并保持菜单、快捷键、设置与本地密集标注显示策略一致。本能力只增加操作入口，不引入新的着色或二值显示模式。

## ADDED Requirements

### Requirement: Existing visualization actions are reachable from the toolbar
系统 SHALL 在主工具栏提供遮罩、文本、标签、分数、角度、属性、关联线和群组显示开关，并提供适应窗口、适应宽度、既有成组/解组动作；已有动作的可用条件和数据修改语义 MUST 保持不变。

#### Scenario: Toggle an existing display action
- **WHEN** 用户从工具栏关闭标签或遮罩显示
- **THEN** 画布立即反映该显示状态，菜单、设置中的对应值保持一致，已有快捷键可再次切换同一状态

#### Scenario: Constrained grouping operations
- **WHEN** 用户从工具栏执行成组或解组
- **THEN** 沿用原有选择、锁定、撤销及保存规则，显示开关本身不创建或修改组号

### Requirement: Local label policies and narrow windows remain usable
系统 MUST 保留“仅选中显示标签”、悬停预览、隐藏与锁定规则；新增按钮后，窄窗口下的工具栏 SHALL 可以横向浏览至所有按钮，且图标有名称或提示。

#### Scenario: Selected-only labels
- **WHEN** 用户启用仅选中显示标签并通过工具栏切换标签显隐
- **THEN** 重新显示标签时仍应用原有仅选中规则，悬停预览沿用当前行为

#### Scenario: Overflowing toolbar
- **WHEN** 窗口宽度不足以容纳全部工具栏按钮
- **THEN** 用户可以通过工具栏横向滚动访问末尾按钮，滚轮事件不会穿透至画布触发缩放或几何编辑

### Requirement: Display modes remain outside this migration
系统 MUST 保持现有类别颜色和渲染方式，不增加四种显示模式选择器、实例着色、按组着色或二值画布渲染；既有群组和遮罩显隐不受此排除影响。

#### Scenario: Open the migrated toolbar
- **WHEN** 用户启动应用并查看工具栏
- **THEN** 可以使用迁入的显示开关，但看不到新增的标签/实例/群组/二值模式选择器，原有类别颜色不变

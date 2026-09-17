## Purpose

统一矩形工具的可发现入口和操作生命周期，使两点创建、四极值创建、已有单边精修与键盘快速拟合能够独立启动和明确结束，避免创建完成后隐式接管用户输入，并保留现有标注提交与保存语义。

## ADDED Requirements

### Requirement: Tools menu replaces persistent workbench activation
系统 SHALL 在“工具 → 矩形工具”提供创建、继续四极值、键盘拟合、单边精修、完成及相关视图／设置动作，移除主画面常驻工作台启用勾选。旧 enabled 偏好 MUST NOT 阻止工具可用或在启动时激活会话。

#### Scenario: Open with legacy preference
- **WHEN** 用户使用旧 enabled 为 true 或 false 的配置启动应用并加载图像
- **THEN** 工具菜单可发现，主画面无旧勾选，会话均未激活

### Requirement: Fitting requires explicit entry
系统 SHALL 仅在唯一选中合法普通矩形且无进行中鼠标拖动时允许通过菜单或自定义进入快捷键启动键盘拟合；进入不得改变形状或自动调整视图。

#### Scenario: Explicit valid entry
- **WHEN** 用户选中一个合法矩形并执行键盘快速拟合
- **THEN** 浮窗显示目标及按键，几何和视图不变，后续边界键归拟合处理

#### Scenario: Invalid entry
- **WHEN** 用户空选、多选、选择不支持形状或正在拖动时尝试进入
- **THEN** 动作不可用或提示原因，不进入拟合、不修改几何

### Requirement: Creation and refinement are decoupled
系统 SHALL 在四极值成功创建后选中新框并回到普通编辑；两点创建也 MUST NOT 自动进入精修或键盘拟合。继续创建、精修和拟合均要求独立明确动作。

#### Scenario: Complete four extremes
- **WHEN** 第四个有效边界及标签／属性提交成功
- **THEN** 创建一个普通矩形、选中它、释放草稿输入接管，不激活边、不自动拟合或缩放

#### Scenario: Continue explicitly
- **WHEN** 用户在成功创建后执行继续四极值画框
- **THEN** 使用上次有效标签显式开始新草稿，不经过拟合

### Requirement: Draft input has isolated completion and cancellation
四极值草稿 SHALL 按上右下左顺序接受鼠标点击或当前边界键；其他边界键只能提示。Backspace 和 Ctrl+Z SHALL 只撤回草稿一步；Esc SHALL 取消草稿。四边完成但标签确认取消时 SHALL 保留草稿供回退或重新提交，不留下正式空标签形状。

#### Scenario: Cancel label confirmation
- **WHEN** 四边完整但用户取消标签确认
- **THEN** 草稿保留、正式形状未提交、用户可回退或重试

#### Scenario: Empty draft undo
- **WHEN** 空草稿中按 Ctrl+Z
- **THEN** 不撤销已存在的其他标注

### Requirement: Fitting exit preserves committed edits
Enter、退出键盘拟合和 Esc SHALL 一次结束独立拟合会话并释放其输入接管，保留已提交修改与选择；完成 MUST NOT 额外保存文件或回滚整个会话。已有 dirty、自动保存及导航保存规则 SHALL 继续适用。

#### Scenario: Exit after adjustment
- **WHEN** 用户调整一条边后按 Esc 或 Enter
- **THEN** 拟合浮窗关闭、普通快捷键恢复、调整保留且可由 Ctrl+Z 撤销

### Requirement: Selection and navigation transitions are visible
同图显式选中新合法矩形 SHALL 更新拟合目标；空选、多选或无效目标 SHALL 暂停并显示原因，不恢复数字标签操作。成功切图、关闭图像或切换其他工具 SHALL 结束会话，取消切图 SHALL 保留会话。

#### Scenario: Selection becomes empty
- **WHEN** 拟合中用户取消所有选择并按边界数字键
- **THEN** 提示请选择一个矩形，不修改形状、标签或工具；重新唯一选中后恢复拟合

#### Scenario: Navigation canceled
- **WHEN** 拟合中切图被保存流程取消
- **THEN** 原图与拟合会话保留，不泄漏临时按键状态

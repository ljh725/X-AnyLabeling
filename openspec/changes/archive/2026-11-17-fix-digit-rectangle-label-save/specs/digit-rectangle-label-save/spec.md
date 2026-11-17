## Purpose

确保用户通过数字快捷键指定类别并绘制矩形时，完成后的类别与数字键绑定一致，不受标签弹窗开关或类别列表预选值干扰；同时确保自动保存、手动保存及重新打开后保留相同的类别与几何信息，防止文件成功写入但标注类别错误。

## ADDED Requirements

### Requirement: Digit binding determines the completed rectangle label

对于已配置矩形模式及合法类别的数字键，当画布没有选中对象且没有进行中的绘制时，系统 SHALL 使用该数字键绑定类别作为本次普通矩形绘制的最终类别，优先于类别列表预选值、复用上次类别及标签弹窗设置，且 SHALL 不要求用户再次通过类别弹窗确认。

#### Scenario: Popup disabled with another class selected

- **WHEN** 数字键 3 绑定矩形类别“车辆”，标签弹窗关闭，类别列表预选“其他类别”，用户在无画布对象选中的状态按 3 并完成矩形
- **THEN** 新矩形类别为“车辆”，不被“其他类别”覆盖，且不弹出类别确认框

#### Scenario: Popup enabled or no class selected

- **WHEN** 用户按已绑定矩形类别的数字键并完成矩形，标签弹窗开启或类别列表没有预选类别
- **THEN** 新矩形采用数字键绑定类别，且不弹出类别确认框

#### Scenario: Last label reuse enabled

- **WHEN** 用户启用复用上次类别，上次类别与数字键绑定类别不同，并通过该数字键完成矩形
- **THEN** 新矩形采用数字键绑定类别

### Requirement: Completed binding is consumed once

系统 SHALL 在成功完成本次数字键矩形创建并赋予类别后消费该次绑定。放弃本次绘制时，系统 SHALL 清除待用的数字键绑定。后续没有重新触发数字绑定的普通绘制 SHALL 遵循原有类别选择规则。

#### Scenario: Ordinary drawing after digit rectangle completion

- **WHEN** 用户完成数字键绑定为“车辆”的矩形，随后未按数字键而通过普通矩形工具按原有规则选择“其他类别”并完成下一矩形
- **THEN** 第一矩形保持“车辆”，第二矩形为“其他类别”

#### Scenario: Ordinary drawing after abandoning digit creation

- **WHEN** 用户按下已绑定类别的数字键，随后在完成矩形前按 Esc、切换绘制工具或切换图片
- **THEN** 下一次普通矩形绘制和保存采用普通类别选择规则

### Requirement: Saving and reopening preserve the completed rectangle

系统 SHALL 在自动保存或 Ctrl+S 保存成功后，将数字键确定的类别、矩形类型、全部顶点和正确图片尺寸写入 JSON；该要求 SHALL 同时适用于图片同目录和独立输出目录，重新打开图片后 SHALL 恢复相同类别及几何信息。

#### Scenario: Autosave and reload

- **WHEN** 用户开启自动保存并完成数字键矩形，在图片同目录或独立输出目录保存成功后重新打开图片
- **THEN** JSON 和重新加载的矩形均使用绑定类别，矩形类型、顶点及图片尺寸保持正确，界面没有未保存状态

#### Scenario: Manual save and reload

- **WHEN** 用户关闭自动保存，完成数字键矩形后按 Ctrl+S 保存到图片同目录或独立输出目录，再重新打开图片
- **THEN** 画完时界面提示待保存，保存成功后该状态清除，JSON 和重新加载的矩形均使用绑定类别并保留正确几何信息

### Requirement: Existing editing and annotation semantics remain compatible

系统 SHALL 保留画布选中对象时数字键改类的行为、普通非数字绘制的类别选择行为，以及自动标注特殊标记的既有处理语义。

#### Scenario: Selected objects are relabeled

- **WHEN** 用户选中可编辑对象并按已配置的数字键
- **THEN** 系统按既有规则修改选中对象类别，不启动新矩形绘制

#### Scenario: Ordinary rectangle has no digit binding

- **WHEN** 用户未触发数字键绑定，通过普通矩形工具绘制并选择类别
- **THEN** 系统遵循原有类别预选、弹窗及复用上次类别设置

#### Scenario: Automatic annotation special marks

- **WHEN** 用户处于自动标注模式并创建该模式的特殊标记
- **THEN** 系统保留特殊标记的原有语义和保存规则，不将其错误转换为普通数字键类别

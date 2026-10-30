## Purpose

为大数据集中的矩形编辑提供稳定、连续的交互响应，使单张图片的坐标状态反馈不随数据集总图片数量增长而明显变慢，同时保留现有几何约束、显示内容、锁定、撤销与保存语义，形成可用真实交互和性能对照验证的契约。

## ADDED Requirements

### Requirement: Dataset scale independent pointer feedback
系统 SHALL 在保持当前图像、对象数量和显示条件不变时，让鼠标坐标和矩形宽高反馈不因目录文件数增长而发生线性耗时增长，并保持原有文本和有效性条件。

#### Scenario: Large dataset pointer movement
- **WHEN** 用户在11792张图片的数据集中连续拖动当前矩形框
- **THEN** 状态栏准确显示最新坐标及宽高，反馈不需要等待处理其他图片的条目

#### Scenario: Filtered or empty list
- **WHEN** 当前图仍在编辑但不在筛选列表中，或列表尚在分批加载
- **THEN** 有效图像上的坐标和宽高仍正确显示，无图时保持既有空状态行为

### Requirement: Latest geometry is rendered continuously
系统 SHALL 在连续拖动及释放后显示最近的有效矩形几何，允许合并刷新但不得丢失最后位置或改变移动结果。

#### Scenario: Multiple movement updates before rendering
- **WHEN** 连续多个鼠标位置更新到达后界面获得一次绘制机会
- **THEN** 绘制最新有效位置，不必逐一呈现中间旧位置

#### Scenario: Release and boundary handling
- **WHEN** 用户拖到图像边缘并释放鼠标
- **THEN** 框停在原有边界规则允许的位置，最终图形与保存坐标一致

### Requirement: Editing semantics remain compatible
系统 MUST 保持选中、锁定、多选、Undo、取消、自动保存时机及其他既有画布交互的行为。

#### Scenario: Undo and autosave
- **WHEN** 用户完成一次拖动后撤销，或开启自动保存后完成一次拖动
- **THEN** 撤销恢复拖动前状态，自动保存沿用现有提交时机，不在每次鼠标移动时额外保存

#### Scenario: Adjacent editing interactions
- **WHEN** 用户进行顶点缩放、边调整、Shift单点拟合、旋转、创建预览、悬停或平移
- **THEN** 预览、最终几何、取消及锁定限制保持原有行为，不因拖动优化遗留旧画面

### Requirement: Measurable responsiveness on reference dataset
系统 SHALL 在约定同环境PRW基准中满足无后台移动处理中位数≤15ms、P95≤25ms且相对同轮基线改善≥60%；审核首次回填或同时扫描时中位数≤25ms、P95≤40ms。相同图像与对象条件下1和11792条目的中位数差 SHALL ≤3ms。

#### Scenario: Reference performance acceptance
- **WHEN** 在记录的同一硬件、Qt版本和显示配置下，至少两轮随机顺序、每轮100次移动进行对照
- **THEN** 保存完整样本与条件，并逐项报告上述门槛是否达到；离屏处理时间不得宣称为物理屏幕帧率

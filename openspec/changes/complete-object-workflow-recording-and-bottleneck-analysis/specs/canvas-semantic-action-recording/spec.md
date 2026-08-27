## Purpose

本能力确保标注画布、创建入口和对象属性界面的全部有效用户操作都被转换为唯一、可归属且具有真实时间边界的语义事实，为对象级耗时统计提供完整输入，同时避免记录高频原始输入和敏感标注内容。

## ADDED Requirements

### Requirement: 受支持用户动作必须具有完整覆盖契约
系统 SHALL 维护版本化动作目录，覆盖所有支持形状的创建、选择、整体移动、顶点或边调整、键盘微调、滚轮调整、删除、恢复、标签修改、属性修改、缩放和平移入口。每项目录 MUST 定义动作名、入口、开始条件、允许终态、必需上下文、预期语义事件数和验收回放。

#### Scenario: 新增 Canvas 用户操作
- **WHEN** Canvas 新增或启用一个会改变对象、选择状态或视图上下文的用户入口
- **THEN** 该入口必须先加入动作目录并具有至少一个受控回放用例
- **THEN** 未被目录覆盖的入口不得被声明为行为分析已支持

### Requirement: 一个用户意图只产生一个最终语义动作
系统 SHALL 在语义提交边界记录动作，不得将同一次拖动的连续 `mouseMove`、同一滚轮 burst 的脉冲或程序化 UI 回调写成多个等价动作。动作 SHALL 以 committed、no_change、cancelled、failed 或 interrupted 之一结束。

#### Scenario: 拖动对象后松开鼠标
- **WHEN** 用户按下并拖动对象且在松开前产生多次移动回调
- **THEN** 系统只输出一个具有真实开始和结束时间的几何动作
- **THEN** 动作结果反映对象是否发生净变化

#### Scenario: 程序化刷新画布或列表
- **WHEN** 图片加载、列表重建、缩放重绘或状态恢复触发程序化回调
- **THEN** 系统不把这些回调记录为用户对象动作

### Requirement: 对象几何动作必须携带画布已知目标
系统 SHALL 使用画布命中测试和当前编辑状态提供的事实确定 `edit_target`，不得由记录或分析模块事后根据坐标猜测。整体移动、顶点调整和边调整至少 SHALL 分别记录为 `move`、`vertex` 和 `edge`；当画布已知矩形具体边或角时 MUST 记录稳定枚举。

#### Scenario: 调整矩形左边
- **WHEN** 用户在已选中矩形的左边按下、拖动并提交
- **THEN** 系统记录一次 `rectangle_adjust`，其 `edit_target` 为 `left`
- **THEN** 事件包含对象身份、shape 类型、输入来源、起止单调时间和结果

#### Scenario: 移动非矩形形状
- **WHEN** 用户整体移动 polygon、rotation、quadrilateral、point、line、circle、linestrip 或 cuboid
- **THEN** 系统记录一次关联该对象的 `geometry_adjust`，其 `edit_target` 为 `move`

### Requirement: 所有支持形状具有最低一致记录能力
系统 SHALL 为 polygon、rectangle、rotation、quadrilateral、point、line、circle、linestrip 和 cuboid 提供创建、选择、整体移动、适用的顶点或边调整、删除、恢复、标签和属性修改记录。形状不支持某种编辑方式时 SHALL 标记为不适用，不得按缺失事件处理。

#### Scenario: 回放全部支持形状
- **WHEN** 受控回放依次创建并编辑每一种支持形状
- **THEN** 每个适用动作均产生一个可关联语义事件
- **THEN** 事件的 `shape_type` 与实际形状一致

### Requirement: 滚轮对象调整和视图滚轮必须可区分
系统 SHALL 按实际分支区分滚轮对选中矩形的缩放或边调整、画布缩放以及画布平移。连续脉冲 SHALL 在静默、对象切换、切图、失焦或关闭边界合并为有限 burst，并 MUST 保留对象归属和稳定目标。

#### Scenario: 滚轮调整选中矩形边缘
- **WHEN** 用户在矩形滚轮编辑条件下对矩形边缘滚动多个连续脉冲
- **THEN** 系统输出一个关联当前对象的 `rectangle_adjust` burst
- **THEN** 事件记录具体边、输入次数、持续时间和净变化结果

#### Scenario: 控制键加滚轮缩放画布
- **WHEN** 用户使用视图缩放组合键滚动鼠标滚轮
- **THEN** 系统记录 `zoom` 而不是矩形几何调整

### Requirement: 创建工作流必须从创建意图开始记录
系统 SHALL 区分 `r_then_label`、`digit_prefill`、`copy_paste`、`ai` 和 `import` 创建方式。手工创建 MUST 记录创建意图、几何绘制和适用的标签输入阶段，并在对象身份产生后将这些阶段关联到同一个创建工作流。

#### Scenario: R 键创建矩形并输入标签
- **WHEN** 用户按 R 进入矩形创建、完成画框、输入标签并确认
- **THEN** 系统记录 `r_then_label` 创建方式以及几何绘制和标签输入的独立起止时间
- **THEN** 创建提交和后续对象编辑属于同一可关联对象工作流

#### Scenario: 数字快捷键预置标签后创建
- **WHEN** 用户按数字快捷键预置标签并完成矩形绘制
- **THEN** 系统记录 `digit_prefill` 创建方式、快捷键到绘制开始的间隔和几何绘制耗时
- **THEN** 不生成不存在的标签输入阶段

#### Scenario: 用户取消创建
- **WHEN** 创建意图已开始但用户取消绘制或标签确认
- **THEN** 系统以 cancelled 结束创建工作流且不得产生成功的 `shape_created`

### Requirement: 标签和属性编辑必须以用户提交为边界
标签编辑 SHALL 从用户进入编辑状态开始，以确认、失焦提交或取消结束；连续文本变化不得逐字符计数。布尔或枚举属性 SHALL 在用户真实提交净变化时记录一次，并 MUST 排除程序化设置。

#### Scenario: 用户修改标签并确认
- **WHEN** 用户开始编辑标签、输入多个字符并确认
- **THEN** 系统记录一个 `label_edit` 动作及完整编辑耗时
- **THEN** 事件不包含原始标签文本

#### Scenario: 用户切换对象可见性
- **WHEN** 用户主动改变可见性且值发生变化
- **THEN** 系统记录一个 `attribute_edit` 及安全变化摘要

### Requirement: 缩放动作必须保留分析所需上下文
缩放 burst SHALL 记录开始比例、结束比例、输入次数、当时是否存在活动对象以及可用时的对象尺寸分桶。缩放发生在对象轮次内时 SHALL 关联对象；发生在选择或创建对象之前时 SHALL 关联图片访问并标记为无活动对象，不得丢弃。

#### Scenario: 选中小对象后放大
- **WHEN** 用户选中 size_bucket 为 small 的对象并从 100% 放大到 220%
- **THEN** 缩放事件记录起止比例、small 尺寸分桶和当前对象轮次

#### Scenario: 切图后先缩放再选择对象
- **WHEN** 用户在新图片中先缩放后选择对象
- **THEN** 缩放事件关联图片访问并明确标记 `no_active_object`
- **THEN** 系统不得事后推断该缩放属于某个具体对象

### Requirement: 记录失败不得影响标注且必须遵守隐私边界
行为记录失败 SHALL 保持非阻塞，不得改变 dirty、undo、保存、选择或切图行为。事件 MUST NOT 包含图片像素、完整 points、原始标签、自由文本、绝对路径或逐次鼠标坐标采样。

#### Scenario: 写入行为日志失败
- **WHEN** 记录器无法写入一个语义动作
- **THEN** 标注操作仍正常完成
- **THEN** 健康状态增加丢弃或写入错误计数且不写入敏感回退数据


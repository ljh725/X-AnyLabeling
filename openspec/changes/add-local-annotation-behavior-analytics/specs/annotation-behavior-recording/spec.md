## Purpose

在不干扰正常标注的前提下，把项目、图片、对象和功能状态相关的标注操作记录为本地、版本化、可追溯的语义事件，为后续精确统计和行为分析提供可信数据源。

## ADDED Requirements

### Requirement: 行为记录由用户控制且默认关闭
系统 SHALL 提供应用内行为记录开关，首次使用和升级后均保持关闭；启用后数据 SHALL 仅写入本机，关闭后 SHALL 停止产生新的行为事件。记录失败 MUST NOT 阻止标注、保存、导入或退出。

#### Scenario: 默认不记录
- **WHEN** 用户没有主动启用行为记录
- **THEN** 系统不创建新的行为事件或行为日志文件

#### Scenario: 记录故障放行
- **WHEN** 行为日志目录不可写、队列已满或单条事件无法序列化
- **THEN** 系统继续完成用户原本的标注操作，并在可用时累计记录丢弃或错误计数

### Requirement: 记录会话层级和两套时间边界
系统 SHALL 按 `AppSession -> ProjectSession -> DaySlice -> ImageVisit -> ObjectEpisode -> Event/ActionSpan` 组织记录。每条事件 MUST 包含 UTC 时间、当地自然日、时区偏移和用于耗时计算的单调时钟值；项目会话跨越午夜时 SHALL 保持同一 `project_session_id`，同时写入新的自然日切片。

#### Scenario: 项目跨越当地午夜
- **WHEN** 用户在同一次项目打开期间持续工作并跨过当地午夜
- **THEN** 午夜后的事件沿用原 `project_session_id`，但其 `local_date` 和 `day_slice_id` 归入新自然日

#### Scenario: 重新打开项目
- **WHEN** 用户关闭项目后再次打开同一路径的项目
- **THEN** 系统保留稳定的 `project_id`，并创建新的 `project_session_id`

### Requirement: 每个 shape 在本项目 JSON 生命周期内具有稳定标识
系统 SHALL 在 shape 顶层使用 `xanylabeling_shape_id` 保存稳定标识，并以 `project_id + image_id + shape_id` 作为行为记录中的对象身份。该标识 MUST NOT 写入 `flags`、`attributes`、`kie_linking` 或 `group_id`，也 MUST NOT 导出到 VOC、YOLO、COCO 等交换格式。

#### Scenario: 旧 JSON 首次载入
- **WHEN** 系统载入一个缺少 `xanylabeling_shape_id` 的现有 shape
- **THEN** 系统在内存中惰性生成唯一 ID，且不会仅因生成该 ID 就把文件标记为用户已修改

#### Scenario: 正常保存旧 JSON
- **WHEN** 已惰性生成 ID 的文件因真实标注变化而正常保存
- **THEN** 系统把 `xanylabeling_shape_id` 与 shape 一起写回 X-AnyLabeling JSON

#### Scenario: shape 身份的保留和重建
- **WHEN** 用户修改 shape 的几何、标签或属性
- **THEN** shape 保留原 ID；新建、复制、粘贴、导入或 AI 新生成的 shape 获得新 ID

#### Scenario: 删除后撤销
- **WHEN** 用户删除一个 shape 后执行撤销恢复
- **THEN** 恢复后的 shape 沿用删除前的 ID，删除事件仍作为历史记录保留

### Requirement: 每条记录使用版本化语义事件契约
系统 SHALL 以追加方式记录版本化语义事件。每条普通事件 MUST 至少包含 `schema_version`、`event_id`、`event_type`、`occurred_at_utc`、`local_date`、`timezone_offset`、`monotonic_ms`、会话与项目标识、当前 `feature_state_version`、输入来源和结果；涉及图片、shape、对象轮次、关联动作或耗时时 SHALL 分别携带相应 ID、`correlation_id` 或 `duration_ms`。

#### Scenario: 记录一次矩形调整
- **WHEN** 用户完成并提交一次矩形边界调整
- **THEN** 系统写入一个可关联到项目、图片、shape、对象轮次、功能状态版本和输入来源的成功语义事件，并记录动作耗时

#### Scenario: 不可识别的扩展字段
- **WHEN** 较旧读取器遇到已知 schema 版本中的可选扩展字段
- **THEN** 读取器忽略未知字段并继续读取该事件

### Requirement: 只记录可分析的语义动作
系统 SHALL 覆盖项目和焦点生命周期、图片导航与保存、shape 生命周期、对象选择、几何编辑、标签与属性编辑、视图与模式、撤销重做、AI、Inspector、质检和复核等语义动作。系统 MUST NOT 把每一个鼠标移动、拖拽采样点或滚轮脉冲作为独立行为事件。

#### Scenario: 连续拖拽一个控制点
- **WHEN** 用户按下、连续移动并释放同一个 shape 控制点
- **THEN** 系统记录一个包含起止摘要、结果和耗时的拖拽动作，而不是记录所有移动采样点

#### Scenario: 连续滚轮缩放
- **WHEN** 多个缩放输入落入同一可配置静默窗口
- **THEN** 系统把它们合并为一个缩放动作段，并保留输入次数、总变化量和持续时间摘要

#### Scenario: 动作未产生有效变化
- **WHEN** 用户取消操作或提交后对象状态没有有效变化
- **THEN** 系统记录取消或无变化结果，不伪造成功编辑事件

### Requirement: 功能状态采用快照、变化事件和版本引用
每个项目会话开始时，系统 SHALL 写入 `feature_state_snapshot` 并将版本设为 1；影响行为的功能发生有效状态变化时，系统 SHALL 写入一个 `feature_state_changed` 并把版本增加 1；之后的普通事件 SHALL 引用当前版本。无法获得启动状态时，系统 MUST 使用版本 0 并标记 `state_unknown`。

#### Scenario: 项目启动快照
- **WHEN** 一个项目会话开始且行为记录已启用
- **THEN** 系统记录当时所有白名单功能的配置值、生效值和可判定的使用状态，版本为 1

#### Scenario: 一个设置事务改变多个功能
- **WHEN** 用户一次确认操作同时改变多个白名单功能的有效状态
- **THEN** 系统写入一个包含全部差异的状态变化事件，并只增加一次状态版本

#### Scenario: 设置值未发生有效变化
- **WHEN** 用户打开设置界面后以原值确认或取消
- **THEN** 系统不增加状态版本

#### Scenario: 普通行为引用状态
- **WHEN** 用户在功能状态版本 4 下完成一个编辑动作
- **THEN** 该行为事件引用版本 4，而不是重复复制完整功能配置

### Requirement: 功能状态区分配置、生效和实际使用
系统 SHALL 对纳入白名单的功能区分 `configured`、`active` 和 `used`，并至少覆盖编辑模式、shape 类型、矩形复核精修、精确调整、边缘或滚轮编辑、放大镜或候选框、姿态/对比/导航、筛选/分组焦点/多选/可见性、Inspector/质检/虚拟复核/数据集队列、AI 生效状态、自动保存和数字键模式。纯外观主题默认 MUST NOT 纳入行为状态。

#### Scenario: 功能已配置但当前不适用
- **WHEN** 某功能在设置中启用，但当前 shape 类型或模式不满足生效条件
- **THEN** 快照或变化记录将其表示为 `configured=true`、`active=false`

#### Scenario: 功能首次实际参与动作
- **WHEN** 一个已生效功能首次影响本项目会话中的语义动作
- **THEN** 系统可判定该功能 `used=true`，且相关动作可追溯到对应状态版本

### Requirement: 对象交互轮次可区分来回选择
系统 SHALL 使用稳定 `shape_id` 表示对象身份，使用新的 `object_episode_id` 表示一次连续交互轮次。用户从对象 A 切换到对象 B 后再返回 A 时，A 的身份 MUST 保持不变，但 SHALL 开始新的对象轮次。

#### Scenario: 在两个对象之间来回选择
- **WHEN** 用户依次选择 A、B、A 并分别进行操作
- **THEN** A 的两段操作具有相同 `shape_id` 和不同 `object_episode_id`，B 使用自己的 `shape_id` 和轮次 ID

#### Scenario: 非对象操作打断轮次
- **WHEN** 当前对象被取消选择、图片切换或项目关闭
- **THEN** 系统结束当前对象轮次并记录结束原因和可计算耗时

### Requirement: 事件数据最小化、可清理且可恢复读取
系统 SHALL 默认避免记录图片像素、完整 points、用户输入文本和绝对项目路径；确需表达变化时 SHALL 使用类别、数量、差值或哈希化标识等摘要。系统 SHALL 提供本地记录保留期和显式清理能力，并能跳过尾部不完整记录继续读取此前完整事件。

#### Scenario: 应用在写入中异常退出
- **WHEN** 日志最后一条记录因异常退出而不完整
- **THEN** 后续读取跳过损坏尾记录，保留此前完整事件，并在数据质量信息中报告异常

#### Scenario: 用户清理行为数据
- **WHEN** 用户确认清理指定时间范围或项目的本地行为数据
- **THEN** 系统仅删除命中范围的行为记录和派生分析包，不修改标注 JSON 与图片

### Requirement: 与现有局部统计兼容且不重复计数
现有矩形框复核精修行为统计 SHALL 保持可用。若其事件映射到统一行为记录，系统 MUST 通过共享事件标识、来源标识或单一路径保证同一用户动作只计数一次。

#### Scenario: 矩形精修动作被统一记录
- **WHEN** 现有矩形精修模块已经为一次动作产生统计记录
- **THEN** 统一行为系统复用或映射该记录，不再生成第二条会被阶段二重复计数的等价动作

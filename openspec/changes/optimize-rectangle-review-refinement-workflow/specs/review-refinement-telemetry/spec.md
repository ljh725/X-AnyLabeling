## Purpose

以本地、可关闭、不可阻塞交互的方式记录单个矩形审核 episode 的耗时、缩放、拖动反向修正和撤销指标，为五阶段优化提供可比较的基线与验收证据。

## ADDED Requirements

### Requirement: 指标采集必须显式启用且仅保存在本地
系统 SHALL 默认关闭矩形精修指标采集，并 SHALL 仅在用户显式启用后写入本地度量文件。系统 MUST NOT 发送网络请求，也 MUST NOT 将指标写入标注 JSON、shape、undo、质检报告或导出数据。

#### Scenario: 默认关闭采集
- **WHEN** 用户未启用指标采集并完成矩形审核
- **THEN** 系统 SHALL 不创建或追加矩形精修指标记录

#### Scenario: 启用本地采集
- **WHEN** 用户启用指标采集并完成一个单框 episode
- **THEN** 系统 SHALL 在配置的本地目录追加一条版本化记录且不修改标注数据

### Requirement: 单框 episode 边界可重复判定
单框 episode SHALL 在一个矩形成为唯一审核目标时开始，并在目标选择变化、切图、精修会话结束或应用关闭时结束。窗口失焦时间 SHALL 从有效耗时中排除；系统 SHALL 同时记录总耗时与排除超过可配置空闲阈值后的活动耗时。

#### Scenario: 选择下一矩形结束 episode
- **WHEN** 用户从当前唯一矩形切换选择到另一个矩形
- **THEN** 系统 SHALL 完成当前 episode 并为新矩形开始新的 episode

#### Scenario: 窗口失焦暂停计时
- **WHEN** episode 进行中且应用窗口失去焦点 10 秒后恢复
- **THEN** 这 10 秒 SHALL 不计入有效耗时

#### Scenario: 长时间无输入不放大活动耗时
- **WHEN** episode 内两次有效审核输入的间隔超过配置的空闲阈值
- **THEN** 超出阈值的时间 SHALL 不计入活动耗时，但总耗时字段 SHALL 保留可审计的 wall-clock 口径

### Requirement: 缩放次数按操作批次计数
系统 SHALL 将相邻间隔不超过 300ms 的连续缩放输入合并为一次缩放操作，并 SHALL 同时记录规范化缩放步数。只有实际改变主画布缩放的输入 SHALL 被计数。

#### Scenario: 连续滚轮缩放合并
- **WHEN** 用户在 300ms 窗口内连续产生五个有效缩放步进
- **THEN** episode SHALL 记录 `zoom_action_count=1` 和 `zoom_step_count=5`

#### Scenario: 局部放大不计入主画布缩放
- **WHEN** P2 局部放大视图更新但主画布缩放未改变
- **THEN** episode 的缩放次数 SHALL 保持不变

### Requirement: 拖动反向修正排除输入抖动
系统 SHALL 只在矩形边拖动的锁定轴上统计方向反转。小于 0.5 图像像素的抖动 SHALL 被忽略；只有在已确认方向之后，反方向累计有效位移达到 1.0 图像像素时 SHALL 增加一次反向修正计数。每次新拖动 SHALL 重置方向状态。

#### Scenario: 细小抖动不计反向修正
- **WHEN** 用户沿活动轴产生小于 0.5 图像像素的正负抖动
- **THEN** `drag_reversal_count` SHALL 不增加

#### Scenario: 明确越过目标后反向修正
- **WHEN** 用户先将边向外拖动至少 1 图像像素，随后向内累计拖动至少 1 图像像素
- **THEN** `drag_reversal_count` SHALL 增加 1

### Requirement: 撤销次数只归因于当前目标矩形
只有在当前 episode 中触发 undo 且 undo 实际改变当前目标矩形几何时，系统 SHALL 增加撤销次数。撤销其他对象或无可撤销操作 MUST NOT 计入当前 episode。

#### Scenario: 撤销当前边调整
- **WHEN** 用户撤销当前 episode 中刚提交的边调整且目标矩形几何恢复
- **THEN** `undo_count` SHALL 增加 1

#### Scenario: 无效撤销
- **WHEN** 用户触发 undo 但当前目标矩形几何没有变化
- **THEN** 当前 episode 的 `undo_count` SHALL 保持不变

### Requirement: 记录格式版本化且默认不包含敏感内容
每条完成记录 SHALL 包含 schema version、匿名 session/episode/target 标识、功能阶段标记、开始结束原因、总耗时、活动耗时和四类指标。默认记录 MUST NOT 包含图像路径、图像内容、标签文本、group_id 或矩形坐标。

#### Scenario: 检查默认记录字段
- **WHEN** 系统完成并写入一个 episode
- **THEN** 记录 SHALL 可由 schema version 解析，并且不得出现图像路径、标签或坐标字段

### Requirement: 指标故障不得影响审核
目录不可写、序列化失败或单条损坏记录 MUST NOT 阻塞画布输入、保存标注、切图或退出。系统 SHALL 给出非阻塞警告，并 SHALL 能跳过损坏行导出其余有效记录。

#### Scenario: 指标目录不可写
- **WHEN** 用户完成 episode 但指标目录不可写
- **THEN** 标注工作流 SHALL 正常继续且系统 SHALL 显示一次非阻塞警告

#### Scenario: 导出包含损坏行的日志
- **WHEN** 本地日志包含一条损坏记录和多条有效记录
- **THEN** 汇总导出 SHALL 跳过损坏记录、报告跳过数量并保留有效记录

### Requirement: 支持按阶段比较的汇总导出
系统 SHALL 支持将有效 episode 汇总为 CSV 或等价表格格式，并 SHALL 至少按功能阶段输出样本数、单框耗时、缩放操作数、拖动反向修正数和撤销数，以支持基线与阶段结果比较。

#### Scenario: 导出阶段对比数据
- **WHEN** 日志同时包含基线和 P0-1 阶段 episode
- **THEN** 导出 SHALL 能区分两个阶段并为四类指标提供逐 episode 数据和聚合统计


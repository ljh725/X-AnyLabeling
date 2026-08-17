## Context

当前 `ViewportController` 已按文件名保存 `ViewportState`，并使用 `force_default_on_next_load` 支持 B 的一次性默认打开；`LabelingWidget.load_file()` 同时保留旧 `zoom_values` / `scroll_values` 回退。A 的开关只参与继承分支，但该语义尚未形成正式契约。视口捕获和应用直接操作 Qt 控件，部分失败没有结构化结果，缩放模式与 QAction 勾选也没有统一同步。参见 `proposal.md` 和 `specs/viewport-state-lifecycle/spec.md`。

## Goals / Non-Goals

**Goals:**

- 用可枚举、可查询、可测试的三态模型表达现有字典与一次性标记的真实语义。
- 使正常切图、A 的继承和 B 的失效共用一个解析器和一个恢复优先级。
- 把纯内存状态转换与 Qt 坐标/UI 应用分层，减少对 `LabelingWidget` 大文件的侵入。
- 迁移为单一恢复决策来源，同时保持 `keep_prev_scale` 的既有独立行为。
- 让失败结果可见，杜绝半应用被当作成功以及重置标记过早消费。

**Non-Goals:**

- 不把视口状态持久化到用户配置、图片或标注 JSON。
- 不改变 B 已有的三个菜单范围、文案和入口位置。
- 不新增撤销、确认弹窗、快捷键或跨程序恢复。
- 不按图片宽高比例重新定义中心坐标；继续使用图像坐标并在新图边界夹紧。
- 不改变 shape、文件检查状态、图片排序或导航行为。

## Decisions

### 1. 使用稀疏三态模型而不是为数据集所有图片创建记录

新增纯 Python `ViewportStateMachine`，内部保持：

- `states: dict[FileId, ViewportState]`：存在即 `CACHED`；
- `reset_pending: set[FileId]`：存在即 `RESET_PENDING`；
- 两者均不存在即 `UNKNOWN`；
- `active_file_id`：最后一个完成加载并可在离开时捕获的图片。

状态机强制 `states` 与 `reset_pending` 对同一文件互斥，并通过只读查询返回 `ViewportStatus`，不向调用方暴露可修改字典。选择稀疏模型而不是三态字典，是因为未访问图片通常占数据集大多数，不需要为每张图片分配对象。

`ViewportState` 改为 `frozen=True`，并在进入状态机时验证缩放模式、正缩放值和有限中心坐标。

### 2. 用解析计划统一 A、B 和旧缩放策略

状态机提供纯函数式 `resolve_load_plan(file_id, policies)`，返回不可变 `ViewportLoadPlan`，其来源枚举为：

1. `FORCE_DEFAULT`：目标为 `RESET_PENDING`；
2. `EXACT`：目标为 `CACHED`；
3. `PREVIOUS_VIEWPORT`：目标为 `UNKNOWN` 且 A 开启，继承活动图片的精确状态；
4. `PREVIOUS_SCALE`：前述均未命中且 `keep_prev_scale` 开启，只沿用前一张的缩放；
5. `DEFAULT`。

解析计划不修改状态。只有 Qt 应用成功后，控制器才提交 `active_file_id`，并在 `FORCE_DEFAULT` 情况下消费 pending 标记。这样失败不会吞掉用户的重置意图。

考虑过继续让 `LabelingWidget.load_file()` 逐层判断字典，但该做法正是优先级分散和双轨恢复的根源，因此不采用。

### 3. 纯状态机与 Qt 视口控制分层

新建 `widgets/viewport_state_machine.py`，只包含枚举、不可变数据模型、状态转换、解析计划、批量失效快照和回滚，不导入 PyQt。

保留 `widgets/viewport_controller.py` 作为 Qt facade：

- 从 Canvas、ZoomWidget、QScrollArea 捕获 `ViewportState`；
- 预检并原子应用完整视口；
- 调用纯状态机解析和提交转换；
- 向 `LabelingWidget` 返回结构化结果。

`LabelingWidget` 只保留生命周期调用、配置输入和一个窄范围 UI 同步 adapter。显式生命周期调用仍优于 signal，因为“reset 前捕获”和“pixmap 就绪后应用”的顺序是正确性的组成部分，异步或顺序不明的 signal 会增加竞态解释成本。

### 4. 捕获和应用使用结构化结果与两阶段提交

定义 `ViewportCaptureResult` 和 `ViewportApplyResult`，至少区分：

- `APPLIED` / `CAPTURED`；
- `NO_PIXMAP`；
- `INVALID_SCALE`；
- `NO_SCROLL_AREA`；
- `INVALID_STATE`；
- `NO_STATE`。

捕获先完成全部读取和计算，验证成功后才覆盖精确历史。失败保留最后一次有效快照，并返回原因用于测试和诊断。

应用先验证 pixmap、状态、滚动区域、缩放目标和滚动目标，再一次性更新 Qt 状态。不可在设置缩放后才发现滚动区域缺失。应用失败时不消费 reset pending，不把结果写入兼容缓存，也不报告完整恢复。

### 5. 统一 UI 同步，不允许恢复路径直接只改 `zoom_mode`

在 `LabelingWidget` 建立单一 `_sync_viewport_ui(result)` 窄 adapter，负责同步：

- `zoom_mode`；
- ZoomWidget 值；
- Canvas scale 与重绘；
- Fit Window / Fit Width QAction；
- 两个滚动条；
- navigator 缩放与视口。

默认视图、精确恢复、上一张继承和 B 的当前图片立即重置均复用该入口。adapter 不触发 dirty/save，不修改 shape。

### 6. B 复用状态机批量失效事务

现有三个范围继续在 UI 层解析为稳定文件序列，状态机负责规范化 FileId、去重、快照、清除精确状态、设置 pending 和失败回滚。

当前图片重置采用同一计划：事务提交后立即应用默认视图；只有默认应用成功才消费其 pending。非当前目标保留 pending 到未来成功加载。反馈继续使用有效目标数，不使用实际删除缓存数。

该设计兼容 `harden-reset-image-view` 已有行为，同时修正“当前标记过早消费”与“应用失败仍被视为完成”的边界。

### 7. 规范化文件身份并保持数据集作用域

状态机入口统一接受规范化绝对路径形式的 `FileId`；Windows 下执行路径规范化和大小写规范化，但 UI 与反馈继续保留原显示路径。所有 open-file、import-folder、close-file 数据集边界统一调用 `clear_session()`。

不引入跨数据集持久化和全局 LRU。正常数据集会话中每张已访问图片仅有一个小型不可变快照；批量 pending 最坏与当前数据集文件数相同，现有 O(N) 边界可接受。

### 8. 收口并移除旧恢复缓存

状态机先成为唯一加载计划解析器，并通过来源回归日志和 active FileId 提交断言锁定行为。窄范围状态、Qt、重置和菜单测试通过后，直接删除已经没有读取方的按文件 `scroll_values` / `zoom_values` 恢复缓存；`keep_prev_scale` 保留为计划中的临时上一张缩放策略，不再形成第二套每文件历史。

选择一次完成收口，是因为旧缓存已经没有生产读取方；继续保留它只会增加重置清理和状态一致性成本。用户视口状态不写入磁盘，因此没有数据迁移工作。

### 9. 测试以状态转换矩阵为主

纯 Python 测试覆盖三态、五级解析优先级、正序/倒序/跳转、批量失效、失败回滚、FileId 规范化和数据集清理。Qt offscreen 测试覆盖坐标捕获/应用往返、缺失滚动区域预检、跨尺寸夹紧、菜单勾选、导航器同步以及 B 的三个范围。

测试使用公开状态查询和结果对象，不再通过 `controller.states[...]` 直接修改内部字典。

## Risks / Trade-offs

- [状态源收口可能暴露隐藏的旧缓存依赖] → 先用 `rg` 确认生产代码无旧恢复读取方，再由 32 个窄范围测试覆盖正常切图、重置和菜单行为。
- [路径规范化可能让现有未规范化测试失效] → 提供单一 FileId 工厂并统一 fixture，迁移时增加同文件不同路径写法的回归测试。
- [Qt 原子应用无法提供真正的数据库事务] → 先完成所有可失败预检，再按固定顺序更新；异常时恢复进入应用前的 zoom、模式、滚动条和 QAction 快照。
- [保留最后一次有效快照可能在捕获失败后显得陈旧] → 明确其为 last-known-good，暴露捕获失败结果；下一次成功离开会覆盖，避免用不完整状态污染缓存。
- [跨尺寸图片使用绝对图像坐标可能落到边缘] → 保留现有坐标模型并夹紧有效范围，在文档中明确不是按百分比对齐。
- [状态机拆分增加文件数量] → 以纯状态和 Qt 边界换取可测试性，公共入口继续由 `ViewportController` facade 提供，调用方不感知内部拆分。

## Migration Plan

1. 新增不可变模型、FileId 规范化和纯 `ViewportStateMachine`，用新测试锁定三态与五级优先级，不接 UI。
2. 为现有 `ViewportController` 增加结构化捕获/应用结果和预检，保持旧公开方法兼容。
3. 将 `load_file()` 改为“解析计划 → 应用 → 成功提交”单一路径，并加入统一 UI 同步 adapter。
4. 把 B 的批量事务和数据集清理迁移到状态机，验证当前、区间、全部三个范围。
5. 删除按文件的旧缩放/滚动恢复分支和无读取方的缓存字段，将 `keep_prev_scale` 迁移为计划策略。
6. 更新设计文档与功能记录，运行视口相关测试、Black 和 Flake8；完成后再运行必要的交互回归。

回滚时可在第 1 至第 3 阶段保留兼容 facade 并切回旧加载路径；缓存删除前应保留独立提交点。该变更不涉及磁盘数据迁移。

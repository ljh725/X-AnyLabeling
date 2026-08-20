# 标注行为分析阶段一讨论总结

> 状态：讨论结论，尚未进入实现  
> 日期：2026-08-20  
> 范围：X-AnyLabeling 本地行为记录与对象身份设计

## 1. 背景与目标

现有矩形框复核精修统计只覆盖“唯一选中矩形”的单次审核
episode，记录耗时、缩放、拖动反向修正和撤销等指标。本次讨论希望把
统计范围扩展到整个标注软件，用于回答以下问题：

- 标注一个新对象通常会经过哪些操作？
- 编辑一个已有对象时，最常见的操作顺序是什么？
- 哪些动作或动作之间的等待耗时最多？
- 哪些动作经常反复出现，例如“缩放—调整—撤销—再调整”？
- 用户长期形成了哪些鼠标、滚轮、键盘和快捷键使用习惯？

阶段一的目标不是立即生成智能建议，而是建立可靠、结构化、可关联的
本地行为事件日志，为后续动作链分析和效率优化提供可信数据。

## 2. 阶段一范围

阶段一只完成“准确记账”，包含：

1. 定义应用、项目、图片、对象和动作的时间边界。
2. 记录有业务语义的标注行为，不记录原始鼠标轨迹。
3. 为每个 shape 建立可追踪的对象身份。
4. 使用结构化事件记录动作时间、上下文、来源和结果。
5. 本地保存并支持按自然日、项目、图片和对象导出。
6. 统计功能默认关闭，写入失败不得阻塞标注工作流。

阶段一暂不包含：

- 自动识别高频动作链。
- 自动给出操作习惯或界面优化建议。
- 行为分析仪表盘。
- 云端上传或多人行为汇总。
- 跨 YOLO、VOC、COCO 格式延续 shape 身份。

## 3. 核心设计结论

### 3.1 行为系统本质上是结构化日志系统

行为分析由三部分组成：

```text
结构化事件日志 + 会话边界 + 后续离线统计
```

行为日志与调试日志必须分开：

| 类型 | 用途 | 示例 |
| --- | --- | --- |
| 调试日志 | 查找程序错误 | 保存 JSON 失败 |
| 行为日志 | 分析用户操作 | 矩形左边拖动并提交 |
| 性能日志 | 分析系统等待 | 图片加载耗时 850 ms |

普通文本“用户拖动了矩形”无法稳定统计，因此行为日志必须使用固定事件名和
结构化字段。

### 3.2 记录语义动作，不记录所有底层输入

“记录所有行为”指记录所有有业务意义的行为，而不是记录每一次
`mouseMove`、每一个普通按键或每一个 Qt 原始事件。

高频输入应先在内存中聚合：

- 一次鼠标拖动最终写一条拖动摘要。
- 连续滚轮缩放合并为一次 zoom burst。
- 连续方向键微调合并为一次 nudge burst。
- 连续画布平移合并为一次 pan burst。
- 动作结束、取消或失败后再写入结果。

这样可以减少噪音和写盘压力，同时保留行为分析真正需要的信息。

## 4. 时间与会话模型

自然日和项目会话不二选一，两者同时保留：

```text
应用会话 AppSession
└── 项目会话 ProjectSession
    ├── 自然日切片 DaySlice
    ├── 图片访问 ImageVisit
    │   └── 对象操作 ObjectEpisode
    │       └── 动作 ActionSpan / Event
    └── 项目关闭
```

### 4.1 层级定义

| 层级 | 开始 | 结束 |
| --- | --- | --- |
| AppSession | 软件启动 | 软件退出 |
| ProjectSession | 打开图片目录或数据集 | 切换项目、关闭项目或退出软件 |
| DaySlice | 本地自然日 00:00 | 当日 24:00 |
| ImageVisit | 图片成功加载 | 切图、关闭项目或退出软件 |
| ObjectEpisode | 创建对象，或选中对象作为当前目标 | 切换目标、取消选择、切图、删除目标或关闭项目 |
| ActionSpan | 一次语义动作开始 | 提交、取消、拒绝、失败或中断 |

项目跨越零点时保持同一个 `project_session_id`，但事件按照自身本地日期进入
不同的自然日统计。

### 4.2 三类耗时

- `wall_elapsed_ms`：自然经过时间，便于审计完整时间线。
- `focused_elapsed_ms`：排除应用窗口失去焦点的时间。
- `active_elapsed_ms`：排除超过可配置阈值的长时间空闲。

动作耗时使用单调时钟计算，日志同时保存 UTC 时间、本地日期和时区偏移，
避免系统时间调整影响持续时间。

## 5. Shape 唯一标识策略

### 5.1 已确认决策

每个 shape 使用顶层字段 `xanylabeling_shape_id`：

```json
{
  "xanylabeling_shape_id": "shp_7d65a4638e534087",
  "label": "head",
  "score": null,
  "points": [[560.0, 53.0], [621.0, 53.0], [621.0, 136.0], [560.0, 136.0]],
  "group_id": null,
  "description": "",
  "difficult": false,
  "shape_type": "rectangle",
  "flags": {},
  "attributes": {},
  "kie_linking": []
}
```

不把 ID 放入以下字段：

- `flags`：约定保存布尔标记，不适合字符串 UUID。
- `attributes`：属于业务标注属性，内部身份会污染属性语义。
- `kie_linking`：专门用于 KIE 实体关系，结构和用途均不匹配。

### 5.2 身份层级

| 字段 | 含义 |
| --- | --- |
| `xanylabeling_shape_id` | JSON 标注阶段内“这是哪个对象” |
| `object_episode_id` | “这是第几次选中并操作该对象” |
| `event_id` | “这一轮操作中的某个具体动作” |

在 A、B 两个对象之间来回选择时：

```text
选中 A → shape-A + episode-A-01
选中 B → shape-B + episode-B-01
再次选中 A → shape-A + episode-A-02
再次选中 B → shape-B + episode-B-02
```

`shape_id`保持不变，`object_episode_id`每次重新进入对象时生成新值。

### 5.3 Shape ID 生命周期

以下行为保持原 ID：

- 移动、缩放、旋转或调整边和顶点。
- 修改 label、group_id、description、flags 或 attributes。
- 保存和重新打开 X-AnyLabeling JSON。
- 撤销删除并恢复原对象。
- 撤销或重做同一对象的几何修改。

以下行为生成新 ID：

- 新建 shape。
- 复制、粘贴或跨图片粘贴 shape。
- 删除后重新手工绘制相同位置的 shape。
- AI 或外部格式重新导入产生 shape。
- 一个对象拆分为多个对象。
- 多个对象合并为一个新对象。

删除 shape 时从正式 JSON 删除该 ID，但行为日志保留旧 ID 并记录
`shape_deleted`。如果随后撤销删除，应恢复原 ID。

### 5.4 旧 JSON 的迁移

旧 shape 没有 ID 时采用懒生成策略：

1. 加载时在内存中生成 ID。
2. 单纯加载或查看不把文件标记为 dirty。
3. 文件因真实标注修改而正常保存时，顺带持久化 ID。
4. 未保存即关闭时，本次临时 ID 不承诺跨会话延续。
5. 如需一次性初始化，后续提供显式迁移工具，而不是静默重写整个数据集。

行为数据库使用以下组合身份，避免复制项目后产生混淆：

```text
project_id + image_id + xanylabeling_shape_id
```

### 5.5 格式转换边界

`xanylabeling_shape_id`只保证在 X-AnyLabeling JSON 生命周期内稳定：

- JSON 转 YOLO、VOC、COCO 时默认不导出 shape ID。
- 原始 JSON 中的 ID继续保留。
- YOLO、VOC、COCO重新导入 JSON 时生成新 ID。
- 第一阶段不根据坐标猜测导入前后是否为同一对象。
- 如未来确需追踪转换关系，可额外生成导出映射 manifest，不改变目标格式。

## 6. 功能状态快照、变化事件与版本引用规则

阶段一必须记录会影响操作流程和行为解释的功能状态。功能状态采用
“启动快照＋变化事件＋行为引用状态版本”规则，避免在每条行为事件中重复
写入完整配置，同时保证任意行为都能还原其发生时的软件状态。

### 6.1 三类状态语义

必须区分以下三种含义：

| 状态 | 含义 | 记录方式 |
| --- | --- | --- |
| `configured` | 设置或配置中是否开启 | 状态快照和状态变化事件 |
| `active` | 当前运行上下文中是否正在生效 | 状态快照和状态变化事件 |
| `used` | 用户是否真正执行了相关动作 | 对应的语义行为事件 |

例如矩形精修可以处于以下状态：

```text
configured=true   设置中已经开启
active=false      当前没有唯一选中的矩形，因此未生效
used=false        用户尚未执行边拖动或微调
```

不能仅凭 `configured=true` 推断该功能影响了本次行为；只有 `active`状态和
实际行为事件共同出现时，才能判断功能是否真正参与操作。

### 6.2 启动快照

系统在以下时机写入 `feature_state_snapshot`：

1. 行为记录功能启动并完成配置加载后。
2. 新的 `AppSession`建立后。
3. 新的 `ProjectSession`建立或项目切换后。
4. 行为记录在运行中从关闭切换为开启时。
5. 状态恢复不确定、日志断点恢复或版本迁移后。

每个 `ProjectSession`的首个状态版本为 `1`。快照必须包含功能白名单中所有
功能的有效状态，而不是只记录值为 `true`的功能。

```json
{
  "schema_version": 1,
  "event_type": "feature_state_snapshot",
  "project_session_id": "project_session_01",
  "feature_state_version": 1,
  "features": {
    "edit_mode": {"configured": true, "active": true},
    "create_mode": {"configured": true, "active": false},
    "rectangle_refinement": {"configured": true, "active": false},
    "precision_mode": {"configured": true, "active": false},
    "pose_view": {"configured": false, "active": false},
    "virtual_review": {"configured": true, "active": false},
    "auto_labeling": {"configured": true, "active": false},
    "filter": {"configured": true, "active": false},
    "autosave": {"configured": true, "active": true}
  }
}
```

### 6.3 状态变化事件

功能的有效状态发生变化后，系统写入 `feature_state_changed`。事件必须在
运行时状态成功应用之后产生，不能仅依据设置控件被点击就提前记录。

每次有效变化将 `feature_state_version`加一：

```json
{
  "schema_version": 1,
  "event_type": "feature_state_changed",
  "project_session_id": "project_session_01",
  "previous_feature_state_version": 1,
  "feature_state_version": 2,
  "feature": "precision_mode",
  "previous": {"configured": true, "active": false},
  "current": {"configured": true, "active": true},
  "source": "shortcut"
}
```

状态变化规则：

- 有效状态没有变化时不增加版本。
- 一次设置事务同时改变多个功能时，写一条包含 `changes`列表的事件，并且
  只增加一次版本。
- 状态变化失败或被取消时不更新版本，可另写失败或取消行为事件。
- `active`因目标选择、模式、图片或复核上下文变化而改变时，也必须产生
  状态变化事件。
- 状态版本只要求在当前 `ProjectSession`内单调递增；新项目会话重新从
  `1`开始。

### 6.4 普通行为引用状态版本

除状态快照和状态变化事件外，每条行为事件必须写入当前
`feature_state_version`：

```json
{
  "event_type": "rectangle_edge_drag",
  "project_session_id": "project_session_01",
  "shape_id": "shp_7d65a4638e534087",
  "object_episode_id": "episode_08",
  "feature_state_version": 2,
  "input_source": "mouse",
  "duration_ms": 860,
  "result": "committed"
}
```

分析程序先读取版本 `1`的完整快照，再依次应用版本 `2`、`3`等变化事件，
即可还原每条行为发生时的完整功能状态。行为事件不得复制完整状态对象，
避免日志重复膨胀和不同字段之间产生矛盾。

如果当前状态无法可靠确定，事件使用 `feature_state_version=0`并标记
`state_unknown=true`，不得猜测或引用不存在的版本。

### 6.5 阶段一功能状态白名单

阶段一优先记录会改变操作流程、输入解释或统计结果的状态：

- 创建模式、编辑模式及当前绘制shape类型。
- 矩形精修、精度模式、边调整、滚轮矩形调整。
- 局部放大镜和候选边辅助。
- Pose View、Compare View和Navigator。
- 标签、shape、group和shape_type过滤状态。
- group聚焦、多选模式和标签可见性。
- Inspector、质检复核、虚拟复核和跨文件复核队列。
- AI自动标注及当前是否正在运行。
- 自动保存。
- 数字快捷键页、绑定绘制或其他会改变输入语义的模式。

主题、语言、字体、窗口颜色等纯外观设置默认不进入阶段一白名单。快照中
不得保存模型路径、图片路径、label文本或其他敏感配置值。

## 7. 事件基础结构

每条行为事件至少包含以下字段：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 行为日志结构版本 |
| `event_id` | 本条事件唯一编号 |
| `event_type` | 固定语义事件名称 |
| `occurred_at_utc` | 事件 UTC 时间 |
| `local_date` | 本地自然日 |
| `timezone_offset` | 时区偏移 |
| `monotonic_ms` | 计算持续时间的单调时钟值 |
| `app_session_id` | 本次软件启动会话 |
| `project_session_id` | 本次项目打开会话 |
| `project_id` | 匿名项目标识 |
| `image_id` | 匿名图片标识 |
| `shape_id` | 当前对象 ID，无对象时为空 |
| `object_episode_id` | 当前对象操作轮次，无对象时为空 |
| `correlation_id` | 关联动作开始、结束及其子事件 |
| `feature_state_version` | 当前项目会话中的功能状态版本 |
| `mode` | 当前创建、编辑、精修、复核或 AI 模式 |
| `input_source` | mouse、wheel、keyboard、shortcut 或 menu |
| `duration_ms` | 动作持续时间，瞬时事件可为空 |
| `result` | committed、canceled、rejected、noop、failed 或 interrupted |
| `payload` | 当前事件允许的非敏感上下文字段 |

示例：

```json
{
  "schema_version": 1,
  "event_id": "evt_01",
  "event_type": "rectangle_edge_drag",
  "occurred_at_utc": "2026-08-20T02:25:18Z",
  "local_date": "2026-08-20",
  "timezone_offset": "+08:00",
  "app_session_id": "app_01",
  "project_session_id": "project_session_01",
  "project_id": "project_a1",
  "image_id": "image_23",
  "shape_id": "shp_7d65a4638e534087",
  "object_episode_id": "episode_08",
  "correlation_id": "action_15",
  "feature_state_version": 2,
  "mode": "rectangle_refinement",
  "input_source": "mouse",
  "duration_ms": 860,
  "result": "committed",
  "payload": {
    "edge": "left",
    "geometry_changed": true,
    "reversal_count": 1
  }
}
```

## 8. 阶段一事件范围

### 8.1 应用和项目

- `app_started`、`app_closed`
- `window_focus_lost`、`window_focus_gained`
- `idle_started`、`idle_ended`
- `project_open_requested`、`project_opened`、`project_open_failed`
- `project_closed`、`project_switched`
- `output_directory_changed`
- `feature_state_snapshot`、`feature_state_changed`

### 8.2 图片和导航

- `image_load_requested`、`image_loaded`、`image_load_failed`
- `image_left`
- `navigate_previous`、`navigate_next`
- `file_list_navigated`
- `filter_navigated`、`review_issue_navigated`
- `annotation_save_requested`、`annotation_saved`、`annotation_save_failed`
- `annotation_autosaved`

### 8.3 对象生命周期

- `shape_create_started`、`shape_created`、`shape_create_canceled`
- `shape_selected`、`shape_deselected`、`shape_target_changed`
- `shape_deleted`、`shape_delete_undone`
- `shape_duplicated`、`shape_copied`、`shape_pasted`
- `object_episode_started`、`object_episode_ended`

### 8.4 几何编辑

- `shape_moved`
- `rectangle_edge_drag`
- `rectangle_vertex_drag`
- `polygon_vertex_drag`
- `vertex_added`、`vertex_removed`
- `shape_rotated`
- `keyboard_nudge_burst`
- `wheel_nudge_burst`
- `geometry_edit_canceled`、`geometry_edit_rejected`
- `undo_applied`、`redo_applied`

### 8.5 标签和属性

- `label_dialog_opened`、`label_change_committed`、`label_change_canceled`
- `group_id_changed`
- `attribute_changed`
- `description_changed`
- `difficult_changed`
- `batch_edit_started`、`batch_edit_completed`、`batch_edit_canceled`

默认只记录“发生了修改”和非敏感类型，不记录原始 label、group_id、描述内容。

### 8.6 视图和模式

- `mode_changed`
- `zoom_burst`
- `pan_burst`
- `fit_window_applied`、`fit_width_applied`
- `view_reset`
- `loupe_opened`、`loupe_closed`
- `precision_mode_changed`

### 8.7 AI 与复核

- `model_run_started`、`model_run_completed`、`model_run_failed`
- `model_result_accepted`、`model_result_modified`、`model_result_deleted`
- `review_started`、`review_completed`、`review_skipped`
- `quality_issue_opened`、`quality_issue_resolved`

## 9. 事件上下文与隐私边界

允许记录的粗粒度上下文：

- shape_type。
- small、medium、large 等对象尺寸等级。
- 点数量等级。
- manual、auto_label、imported 等对象来源。
- 当前缩放等级或区间。
- 当前选中对象数量。
- 输入来源和动作结果。
- 操作的是矩形哪条边。
- 是否实际改变几何。
- 功能开关快照。

阶段一默认禁止记录：

- 图片内容。
- 图片绝对路径。
- 原始坐标或完整 points。
- 原始 label 文本。
- 原始 group_id。
- description 内容。
- 每一次鼠标移动。
- 与标注无关的普通按键内容。

项目和图片使用本地匿名 token。统计文件属于本机用户数据，应提供明确的
启用、导出、保留期限和删除入口。

## 10. 存储和容错策略

阶段一可先采用 schema-versioned JSONL：

- 一行一条完成事件。
- 事件追加写入，不回写旧记录。
- 写入路径位于应用数据目录，不放入标注项目目录。
- 高频事件只在内存聚合，动作结束后写一次。
- 损坏行在导出时计数并跳过，不阻塞其他有效记录。
- 写盘失败只提示一次非阻塞警告。
- 行为系统故障不得影响标注保存、dirty、undo、切图或退出。

当事件量和跨维度查询需求明显增长后，再评估迁移到 SQLite。阶段一先验证
事件定义和对象身份是否可靠，避免过早增加存储复杂度。

## 11. 阶段一最小输出

阶段一至少支持导出：

1. 逐事件 CSV或JSONL。
2. 按自然日汇总的应用、项目、图片和对象 active time。
3. 按项目汇总的图片访问数、对象操作轮次和事件数量。
4. 按对象汇总的 episode 数、累计时间和动作计数。
5. 按功能状态版本对比关键动作数量、耗时和结果。
6. 写入失败、损坏行、未知状态版本和缺失字段数量。

阶段一只输出事实，不自动评价用户效率或推断操作意图。

## 12. 与现有矩形精修统计的关系

现有矩形精修 telemetry 继续负责精修实验的核心指标，不直接扩展成全应用
行为系统。新的行为记录能力应作为独立模块，并复用以下成熟原则：

- 纯 Python 数据模型和聚合逻辑不依赖 PyQt。
- UI 层只上报已确认的语义动作。
- 高频鼠标事件只做 O(1) 内存统计，不逐事件写盘。
- 默认关闭、本地保存、隐私最小化、失败不阻塞。
- 使用 schema version 管理日志演进。

二者可以通过 `project_session_id`、`image_id`、`shape_id`和
`object_episode_id`关联，但应保持文件、配置和职责边界独立。

## 13. 阶段一验收标准

- 同一图片加载期间，A→B→A能够恢复A的同一 `shape_id`，并建立新的
  `object_episode_id`。
- 修改坐标、label或属性不改变shape ID。
- 新建、复制、粘贴和重新导入生成新shape ID。
- 删除后撤销能够恢复原shape ID。
- 旧JSON未修改时不会仅因生成ID而自动变dirty。
- JSON正常保存后，shape ID能够重新加载并保持一致。
- YOLO、VOC、COCO导出不要求携带shape ID。
- 日志关闭时不创建行为文件。
- 日志开启时能够还原项目→图片→对象→动作的完整层级。
- 每个项目会话开始时存在版本 `1`的完整功能状态快照。
- 有效功能状态变化后版本严格递增，无效或失败变化不增加版本。
- 每条普通行为事件引用发生时有效的 `feature_state_version`。
- 分析程序能够用快照和变化事件还原任意行为发生时的功能状态。
- `configured`、`active`和实际行为事件能够区分，不能仅凭开启状态推断使用。
- 状态无法确定时使用版本 `0`和 `state_unknown`，不得引用不存在的版本。
- 长时间失焦和空闲不会被错误计入active time。
- 写盘失败不影响标注操作。
- 日志中不出现路径、原始坐标、label文本、group_id或描述内容。

## 14. 后续待讨论事项

- “项目”的精确定义是图片根目录、输出目录组合，还是未来显式项目文件。
- Shape ID采用UUID4、ULID还是带前缀的随机token。
- 懒生成ID是否在用户第一次启用行为统计时提供一次性迁移选项。
- 保存为新项目时保留还是重建shape ID。
- 行为原始数据默认保留30、90天还是由用户配置。
- 第一阶段事件白名单的最终数量和命名规范。
- 功能状态白名单的最终字段、默认值和状态变化触发点。
- 哪些AI、质检和虚拟复核事件进入首版。
- 第二阶段采用何种动作序列、循环和耗时分析方法。

## 15. 当前推荐结论

阶段一采用“结构化JSONL行为事件＋项目/图片/对象/动作层级＋JSON阶段
shape ID＋版本化功能状态”的最小方案：

```text
现在建立：xanylabeling_shape_id
现在记录：语义事件、时间、来源、结果和关联上下文
现在还原：启动状态快照、状态变化及每个行为引用的状态版本
现在保证：X-AnyLabeling JSON阶段内对象身份稳定
暂不保证：跨YOLO/VOC/COCO格式延续身份
后续分析：动作链、高频循环、耗时瓶颈和个体操作习惯
```

该方案能够支持第一阶段行为记账，同时把格式兼容、迁移和存储成本限制在
可控范围内。

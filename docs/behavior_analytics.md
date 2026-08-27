# 本地标注行为记录与统计

## 默认状态

行为记录默认关闭。开启后，软件只在本机追加写入 JSONL 行为日志，位置为
`<工作目录>/.xanylabeling/behavior_analytics/events/`。记录失败不会阻塞标注、保存或导出。

## 记录内容

每条事件包含匿名项目/图片/shape/对象轮次标识、UTC 时间、本地自然日、时区、单调时钟、
输入来源、结果和功能状态版本。shape 的 `xanylabeling_shape_id` 只在 X-AnyLabeling
JSON 生命周期内使用；复制、粘贴和 AI 新建会生成新 ID，撤销恢复保留原 ID。VOC、YOLO、
COCO 等交换格式不会导出这个字段，也不会改动 `group_id`、`flags`、`attributes` 或
`kie_linking`。

鼠标移动、滚轮脉冲和拖拽采样点不会逐条记录。滚轮缩放、键盘微调和平移会在静默窗口内
合并为 burst；矩形边缘精修记录一次开始—提交/取消动作段，并与原有精修统计共享一次
动作关联，避免双重计数。

## 统计与导出

菜单“View → Local Behavior Analytics（本地行为分析）”提供：

- 开关、当前项目/自然日/全部日志范围选择；
- 确定性统计包导出和进度取消；
- 结果目录、隐私说明和按保留期清理日志。

统计包只读取行为日志，不修改标注 JSON 或图片，包含摘要、固定 CSV 表和有限的代表性轨迹。
统计内容包括动作维度计数与耗时分位数、上下文转移和 3—6 阶语义序列、对象 episode、
wall/focused/active 时间、图片访问、返工事实、测量质量诊断以及功能状态观察性对比。

事件 schema v2 将一次拖拽、微调、滚轮/平移 burst 或编辑提交表示为一个 ActionSpan，
并记录动作终态、编辑目标、单调时长、隐私安全上下文和实际参与的功能。旧 schema v1
仍可读取；旧 `shape_edited` 只用于兼容次数，不进入新版精确耗时或重复率结论。

v2 分析包在保留首版文件的基础上增加 `image_metrics.csv`、`rework_metrics.csv` 和
  `measurement_quality.json`。耗时、吞吐和返工比例在分母或时间缺失时使用空值并声明
覆盖率；功能比较必须同时有完整状态引用的对照组和处理组，默认每组至少 30 个有效
  episode，否则输出结构化 `comparison_unavailable` 原因。

### v4 边界与版本断点

v4 事件 envelope 使用 `sequence_no` 作为同毫秒事件的确定性顺序；对象周期必须由
`object_episode_ended` 事实闭合。选择来源（画布、列表、多选、程序同步或恢复）和
`selection_batch_id` 用于解释选择边界，不能把程序刷新当作用户动作。v1—v3 仍可只读
回放，但缺失结束、焦点或空闲边界时标记为低可信，不伪造精确 active 时间；v4 分析、
统计和 bundle 版本不应与旧 v3 基线直接比较。

时间分解使用四层口径：`wall` 是周期墙钟跨度，`focused` 去除失焦，`active` 再去除
空闲，`action duration` 只取 `started_monotonic_ms` 到 `ended_monotonic_ms` 的半开区间。
动作重叠先求并集，等待/转换与中性剩余量共同满足守恒。`episode_cycle_metrics.json`
分别列出正耗时、同毫秒零耗时、未闭合、超过暂停阈值和暂停调整样本，并带有停顿规则版本
以及 median、P75、P90、P95。

质量状态按动作耗时、对象周期、focused/active、上下文比较、顺序完整性和导出完整性
分别报告 `available/pass/degraded/fail`、分子、分母、阈值和原因码。上下文缺失只会禁用
功能对比，不会让边界完整的动作耗时或对象周期失效；焦点/空闲缺失时 wall 仍可用，
focused/active 会明确降级。

中文界面从“View → Local Behavior Analytics”进入；范围、导出、清理和质量提示均通过
Qt 翻译资源显示，JSONL、UTC、CSV、文件名和内部原因码保持可核对的技术标识。

## 时间口径与隐私边界

- 自然日按事件记录时的本地时区计算；项目会话从打开到关闭；对象 episode 在 A→B→A
  时分开，但仍共享 A 的 shape ID。
- wall、focused、active 时间依赖生命周期、焦点和空闲边界；缺失边界不会伪造精确值。
- wall 是选择 episode 的墙钟跨度，focused 排除失焦区间，active 进一步排除空闲区间；
  action duration 只来自 press/commit 或明确 burst 边界，四种口径不可互换。
- `saved_after_change`、撤销关联、保存后再编辑、重复返回和新建后删除都是可审计事实
  或版本化派生事实，不因取消选择自动推断“已完成”。
- 分析包不包含图片像素、完整 points、自由文本、用户名、绝对路径或本机随机盐。
- 阶段二只做本地确定性读取、统计和导出，不调用模型、不上传数据；如需让外部大模型找规律，
  由用户另行选择并提供导出的分析包。
# Two-stage pipeline notes

The local recorder remains opt-in and writes only privacy-filtered facts. New
hourly JSONL shards are selected by UTC range before reading; legacy monthly
JSONL files remain read-only compatible. The export stage uses inclusive UTC
boundaries, deterministic sequence/source quality checks, half-open monotonic
intervals, versioned workflow stages, objective time-contribution rows and
observational range comparisons.

Exports are published atomically into a fixed compact bundle. High-cardinality
tables and representative traces have deterministic row/byte limits, and the
manifest records omission counts, file sizes and SHA-256 values. Cancellation
stops at bounded read batches and never replaces an existing output directory.

The software does not upload behavior data, call a model, or generate natural-
language optimization conclusions. `unattributed_active_ms` is a neutral
measurement remainder and must not be read as proof of logging loss or wasted
user time.

## Quality and external-analysis boundary

The first stage is opt-in and writes only anonymized event facts to UTC hourly
JSONL shards. Each completed shard has a manifest with event counts, sequence
ranges, errors, and a checksum; queue drops and write failures are therefore
visible to the second stage. Existing monthly JSONL files remain read-only
compatibility sources.

The second stage records the requested local-time range and resolved UTC range
in `manifest.json`, reports parse/schema/reference/time/terminal/sequence and
manifest quality facts, and marks legacy ordering explicitly. Action and
workflow-stage tables use deterministic percentile rules. Episode/object/image
tables have row/byte limits and an explicit `other` row when entities are
omitted. Baseline/comparison rows are observational facts; missing groups and
insufficient samples are represented as structured unavailable reasons.

Exports run in a background worker, check cancellation at bounded batch
boundaries, publish through a private temporary directory, and never overwrite
an existing target. Representative traces use a candidate-summary pass and a
bounded second scan. The package contains facts and quality state only. Any
manual or AI-assisted interpretation must be performed outside the application;
see [the requirement traceability checklist](behavior_analytics_requirement_traceability.md).
# Complete object workflow export (v4 events)

When the local behavior recorder is enabled, v4 events are converted by the
same deterministic, Qt-free timeline builder before export. The bundle adds:

- `object_workflow_timeline.jsonl`: one compact row for every object workflow;
- `object_workflow_summary.csv`: fixed-column per-workflow stage and time facts;
- `project_bottlenecks.csv`: non-overlapping project contributions with sample
  counts, coverage, percentiles and stable ranking.

`object_workflow_sequences.json` and `object_workflow_quality.json` document
sequence rules, exclusions, conservation checks and version boundaries.
Missing creation identity, action boundaries or old-log context is represented
as `null` or a structured exclusion; it is never filled with an inferred
duration. `representative_traces.jsonl` remains a bounded supplemental sample
and is not used to calculate full-project totals or rankings.

The calculation is local and deterministic. It does not call an external
model and does not record image pixels, raw points, labels, free text,
absolute paths or mouse-coordinate samples.

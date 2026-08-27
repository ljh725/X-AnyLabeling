# GLM-5.3 行为分析报告流程

本文档是行为分析导出包的固定分析规范。GLM-5.3 在分析报告前必须先阅读并遵守本文档，不得根据字段名称自行猜测含义。

## 1. 总原则

分析必须分为两步：

1. 先做数据和质量审计。
2. 审计通过后再解释指标和输出结论。

证据不足时必须写“无法判断”，不得补充、推测或编造参数。

每个结论都必须注明：来源文件、字段名称、样本数或分母、质量状态和限制条件。

## 2. 报告文件读取顺序

按以下顺序读取导出包：

1. `manifest.json`
2. `measurement_quality.json`
3. `summary.json`
4. `episode_cycle_metrics.json`
5. `episode_metrics.csv`
6. `action_metrics.csv`
7. `workflow_stage_metrics.csv`
8. `time_contribution.csv`
9. `range_comparison.csv`（只有进行基线/对比时才存在或有效）
10. `representative_traces.jsonl`（只用于抽样核对，不能代替聚合统计）

不要只读取 `summary.json` 就开始分析。详细表、质量状态、版本和省略信息可能决定某个结论是否有效。

## 3. 第一步：数据质量审计

### 3.1 检查 `manifest.json`

必须检查：

- `input_event_schema_versions`
- `event_version_distribution`
- `analytics_algorithm_version`
- `bundle_schema_version`
- 每个文件的 SHA-256、字节数和行数
- `omitted_rows`、`table_limits` 和 `other` 汇总
- 基线和对比时间范围是否重叠

如果同时存在 v3 和 v4，必须明确说明版本口径不同，不能直接把两者的周期时长当作同一指标比较。

版本号是计算口径标识，不是质量分数，也不是效率分数。

### 3.2 检查 `measurement_quality.json`

重点查看这些质量维度：

- 动作耗时：`action_duration` 或 `action_duration_coverage`
- 对象周期：`object_cycle` 或 `episode_closure_rate`
- 前台/活动时间：`focused_active`
- 上下文比较：`comparison_context` 或 `context_coverage`
- 顺序完整性：`sequence_continuity`
- 导出完整性：`export_completeness` 或 `manifest_completeness`

对每一项记录：

- `available`
- `status`
- `numerator`
- `denominator`
- `threshold`
- `exclusion_reason`

质量状态含义：

- `pass`：可以使用，但仍要看样本量和限制。
- `degraded`：只能谨慎使用，必须说明缺失边界或覆盖不足。
- `fail`：不能把该指标当作可靠结论。
- `unavailable`：没有足够数据，不能分析。

某一项失败只影响相关指标。例如上下文比较失败，只禁用功能比较，不会自动使边界完整的动作耗时和对象周期失效。

## 4. 字段口径，禁止混用

所有以 `_ms` 结尾的字段单位都是毫秒：

```text
1000 ms = 1 秒
60000 ms = 1 分钟
```

| 字段 | 正确含义 | 禁止的错误解释 |
|---|---|---|
| `wall_ms` | 从选中对象到下一对象、翻页、删除、清除或关闭等结束边界的总墙钟时间 | 纯操作时间、效率时间 |
| `focused_ms` | wall 时间中软件处于前台/有焦点的时间 | 直接等于 active 时间 |
| `active_ms` | focused 时间中进一步排除空闲后的时间 | 默认等于 wall 时间 |
| `duration_ms` | 某一个动作从开始到结束的时长 | 整个对象周期时长 |
| `started_monotonic_ms` | 动作真实开始边界 | 排序时间 |
| `ended_monotonic_ms` | 动作真实结束边界 | 下一条事件时间 |
| `median_ms` | 中位数，典型样本的代表值 | 平均值 |
| `p75_ms` | 75 分位数 | 最慢 25% 的平均值 |
| `p90_ms` | 90 分位数，较慢长尾的边界 | 平均值或最大值 |
| `p95_ms` | 95 分位数，极慢长尾的边界 | 所有样本的最大值 |
| `unattributed_active_ms` | 尚未归入具体动作的中性剩余时间 | 浪费时间、低效时间、日志丢失 |
| `null` | 数据缺失、不可用或没有有效样本 | 0 |
| `other` | 因行数/字节限制合并的其他记录 | 真实动作类别 |
| `threshold` | 判断标准或质量门槛 | 实际观测值 |

wall、focused、active 和 action duration 是四种不同口径，不能互相替代，也不能在没有定义的情况下相加。

## 5. 对象周期分析方法

优先读取 `episode_cycle_metrics.json`。

### 5.1 先看样本分类

- `positive_count`：正常的正耗时周期。
- `zero_duration_count`：开始和结束发生在同一毫秒的周期。
- `unclosed_count`：没有可靠结束边界的周期。
- `over_pause_count`：超过停顿阈值的周期。

正常周期分布只使用 `positive_count` 对应的有效样本。

### 5.2 再看分位数

使用：

- `median_ms`
- `p75_ms`
- `p90_ms`
- `p95_ms`

不要把零时长、未闭合和超过暂停阈值的样本混入正常周期分布。

推荐解释：

- 中位数下降：典型对象处理时间变短。
- P90 下降：较慢长尾也有所改善。
- 中位数稳定但 P90 上升：典型样本没变，但复杂或异常慢样本增加。
- 只有平均值变化而中位数和 P90 不变化：不能直接说整体效率发生变化。

## 6. 动作和工作流分析

读取 `action_metrics.csv` 和 `workflow_stage_metrics.csv`。

分析动作时至少同时查看：

- `count`
- `sample_count`
- `duration_coverage`
- `median_ms`
- `p90_ms`
- `result`
- `result_rate`

分母为 0 时不得输出比例。缺失时长不能用 0 补齐。

读取 `time_contribution.csv` 时，区分：

- 真实动作贡献
- `system_wait`
- `transition_gap`
- `unattributed`

`unattributed` 是中性剩余量，不代表用户浪费时间，也不代表系统丢日志。

## 7. 基线与对比分析

### 7.1 基本含义

- 基线：参考时期，例如改版前。
- 对比：被比较时期，例如改版后。

两组数据应尽量满足：

- 时间范围不重叠。
- 事件版本和算法版本一致。
- 两组都有足够样本。
- 质量状态允许比较。
- `comparison_unavailable` 为空。

### 7.2 分析顺序

读取 `range_comparison.csv`，对每个指标检查：

- `baseline`
- `comparison`
- `absolute_difference_ms`
- `relative_change`
- `comparison_unavailable`
- `algorithm_version`
- `workflow_stage_version`
- `percentile_rule_version`

只能描述“对比期比基线期高/低”，不能写成“某功能导致效率提升”。这是观察性比较，不是严格的因果实验。

如果 `comparison_unavailable` 有内容，必须输出：

> 当前指标无法比较，原因是：……

不能强行计算或补齐对比值。

## 8. 质量阈值和实际指标不能混淆

以下内容属于判断标准，不是实际测量结果：

- `duration_coverage_min`
- `episode_closure_min`
- `duplicate_rate_max`
- `anomaly_episode_event_count`
- `anomaly_episode_active_ms`
- `pause_threshold_ms`

例如，`duration_coverage_min = 0.95` 的意思是“至少希望 95% 动作有可靠时长”，不表示用户的动作耗时是 95%。

## 9. 推荐输出格式

分析结果必须按以下顺序输出：

### 一、数据质量审计

说明版本、文件完整性、质量状态、可用指标和不可用指标。

### 二、对象周期

报告正常样本数、零时长数、未闭合数、超暂停数、median、P75、P90、P95。

### 三、动作耗时

报告动作类型、样本数、时长覆盖率、中位数、P90 和结果分布。

### 四、工作流和时间贡献

区分动作、等待、转换间隔和中性剩余时间。

### 五、基线与对比

只报告质量允许的差异，不做未经实验设计支持的因果结论。

### 六、异常和长尾

说明未闭合、超暂停、缺少焦点/空闲边界、上下文缺失和被合并到 `other` 的情况。

### 七、可以确认的结论

只列出有证据支持的结论。

### 八、不能确认的结论

明确列出因质量、样本量、版本或范围问题不能确认的内容。

### 九、证据表

使用以下格式：

| 结论 | 来源文件 | 字段 | 基线值 | 对比值 | 样本数/分母 | 质量状态 | 限制 |
|---|---|---|---:|---:|---:|---|---|

## 10. 可直接给 GLM-5.3 的系统提示

```text
你是行为分析报告的统计审计员。请先阅读《GLM-5.3 行为分析报告流程》，再分析我提供的完整分析包。

必须遵守：

1. 先审计 manifest.json 和 measurement_quality.json，再解释指标。
2. 每个结论必须注明来源文件、字段、样本数或分母、质量状态和限制。
3. 不得根据字段名称猜测含义。
4. null 表示不可用，不得当作 0。
5. threshold 是判断标准，不是测量值。
6. 所有 _ms 字段都是毫秒，展示时换算成秒或分钟。
7. wall_ms、focused_ms、active_ms、action duration 不得混用。
8. unattributed_active_ms 是中性剩余量，不得解释为浪费时间或日志丢失。
9. 周期分布只使用正常正耗时样本；零时长、未闭合和超暂停样本必须单独报告。
10. 优先使用 median、P75、P90、P95，不得只根据平均值下结论。
11. comparison_unavailable 不为空时，不得输出该项比较结论。
12. v3 与 v4 的口径不同，不能直接比较。
13. 基线/对比只表示观察到的差异，不得直接写成因果关系。
14. 证据不足时必须写“无法判断”，不得补充或编造参数。

请按以下结构输出：

一、数据质量审计
二、对象周期分析
三、动作耗时分析
四、工作流阶段与时间贡献
五、基线与对比
六、异常和长尾
七、可以确认的结论
八、不能确认的结论
九、证据表
```

## 11. 最终自检清单

输出前必须确认：

- 是否先读取了 `manifest.json` 和 `measurement_quality.json`？
- 是否把毫秒正确换算成秒/分钟？
- 是否把 null 错误当成 0？
- 是否把阈值错误当成实际参数？
- 是否把 wall、focused、active 和 action duration 混在一起？
- 是否把未归属时间说成浪费时间？
- 是否把平均值当成中位数或 P90？
- 是否把 `other` 当成真实动作类别？
- 是否忽略了版本不一致？
- 是否在数据不可用时仍然强行给出结论？
- 是否把观察性差异写成因果关系？

## Context

参见 [proposal.md](proposal.md)。首版行为采集、统计和固定分析包已经完成，纯 Python 服务位于 `anylabeling/services/behavior_analytics/`，Qt 层在 `label_widget.py`、`canvas.py` 和各功能入口提供语义适配。实测数据暴露出四个结构性问题：低层 `shape_edited` 回调压倒语义动作、对象 episode 大多没有耗时、功能 `used` 缺少实际动作证明、序列和代表轨迹被无信息事件主导。

设计必须兼容现有 schema v1 JSONL，继续满足默认关闭、本地保存、故障放行、隐私最小化和 UI 线程不做常规磁盘 I/O。`label_widget.py` 与 `canvas.py` 是高成本文件，接入应集中、批量并保持薄适配。

## Goals / Non-Goals

**Goals:**

- 让一个用户可理解的操作对应一个可计数、可计时、可关联对象和功能状态的语义动作。
- 可靠区分对象身份、选择 episode、活跃片段和动作段，并诚实表达缺失边界。
- 在不记录完整几何和自由文本的前提下提供足够的对象复杂度与操作上下文。
- 产生能回答动作瓶颈、对象成本、图片吞吐、返工模式和功能观察性差异的确定性指标。
- 为测量覆盖不足、事件重复和异常长轮次提供自动诊断与验收门槛。

**Non-Goals:**

- 不把行为记录变成鼠标/键盘原始输入日志。
- 不在本变更中引入大模型分析、云上传、跨用户比较或绩效评分。
- 不宣称功能状态差异具有因果关系。
- 不用标签文本、完整 points 或图片内容推断对象难度。
- 不重写历史 schema v1 日志，也不回填无法证明的动作耗时。

## Decisions

### 1. 新增 schema v2 语义动作契约并兼容 v1

新增统一动作字段：`action_id`、`action_type`、`action_phase/result`、`edit_target`、`input_source`、`started_monotonic_ms`、`ended_monotonic_ms`、`duration_ms`、`net_change_summary`、上下文摘要和功能参与键。已完成动作以一个最终语义事件进入统计；开始事件仅用于崩溃恢复和诊断，不单独计数。

读取器同时接受 v1/v2。v1 的 `shape_edited` 仍可进入兼容次数，但标记 `legacy_low_granularity=true`，不得与 v2 语义动作直接比较耗时或重复率。替代方案是在统计层事后猜测 v1 连续回调的动作边界，但缺少 press/release 和取消事实，容易错误合并，因此只做有限的兼容归并，不宣称精确。

### 2. 建立集中式 ActionSpan 协调器

纯 Python 服务维护动作状态机，Qt 层只调用 begin、commit、cancel、interrupt 并提供摘要。协调器负责关联 ID、单调耗时、终态唯一性、无变化判断、功能使用归因和异常未闭合处理。

拖拽由 canvas 的 press/release 边界驱动；键盘微调、滚轮和平移使用既有 burst 静默窗口；标签和属性修改使用一次 UI 提交事务；保存只作为动作上下文事实，不重复生成 shape 编辑。这样避免每个接入点各自实现去重。

### 3. episode 内增加 ActivitySegment 而非用空闲强制换对象轮次

对象 episode 仍表示连续选择关系，选择 A→B→A 产生两个 A episode。失焦或长空闲只结束当前 active segment；恢复时创建新 segment，但不改变 shape 身份或选择 episode。切换对象、取消选择、删除对象、图片切换和项目关闭必须关闭 episode。

该模型既保留“连续选择”的业务含义，又能排除空闲耗时。直接在空闲时关闭 episode 会把一次持续选择拆成多个返回编辑，夸大 return count，因此不采用。

### 4. 上下文采用集中式版本化分桶器

建立上下文构造器，统一产生 `shape_type`、`edit_target`、`point_count_bucket`、`size_bucket`、`aspect_ratio_bucket`、`initial_source` 和安全标签键。分桶阈值、标签策略和上下文 schema 版本写入 manifest。

尺寸使用归一化 bbox 比例而非原始 points。标签默认使用本机加盐匿名稳定键；只有显式隐私安全 allowlist 中的受控类别才允许记录原值，无法安全归类时使用 unknown。这样既能比较对象复杂度，又不扩大隐私面或分析包基数。

### 5. 完成与返工分为事实层和派生层

采集层只记录可证明事实：创建、有效修改、保存、撤销关联、删除、episode 结束和功能参与。统计层用版本化规则推导 `saved_after_change`、`created_then_deleted`、`saved_then_reedited`、`returned_for_edit`、`reverse_adjustment` 和 `no_change_rate`。

每个派生指标保存规则版本、窗口、分子、分母和排除原因。这样可以升级返工定义而不重写原始日志，也避免 UI 层提前做不可审计判断。

### 6. 功能 used 通过动作参与键单向归因

每个语义动作可以携带 `participating_features`。只有权威适配器确认功能改变了动作执行方式时才加入；状态重放据此派生 used。配置开启或模式适用只影响 configured/active，不自动改变 used。

功能比较器要求至少两个状态组、完整状态引用和每组最小样本量。首版默认每组最少 30 个有效对象 episode，并允许配置覆盖；阈值写入算法配置和 manifest。不满足时输出结构化 unavailable reason，而不是空白 difference。

### 7. 统计按 Action、Episode、Object、Image 四层聚合

- Action：次数、结果、耗时、编辑目标、输入来源和上下文分桶。
- Episode：wall/focused/active、动作耗时、结束原因、保存事实和返工构成。
- Object：episode 数、返回次数、累计 active、主要动作、完成状态和返工次数。
- Image：访问次数、对象工作量、累计 active、返工对象和单位活跃时间吞吐。

所有时间指标携带覆盖率；缺失值保持 null。图片和对象吞吐只有在分母 active 时间有效时才计算。

### 8. 序列和轨迹以归一化动作为唯一输入

序列构建先移除生命周期辅助事件和 legacy 重复回调，再按项目、图片、episode/active segment 和长空闲边界切分。纯同类自循环进入 `measurement_quality.json`，不参与主要 common sequence 排名。

代表轨迹候选必须至少包含一个有效语义动作；按 common、median、P75、longest、rework、failure 和 measurement_anomaly 分类，使用固定 tie-breaker。单独 selection 只允许进入 anomaly，解决首版四条 common 轨迹只有一次选择的问题。

### 9. 分析包升级但保留首版文件

首版九个文件继续存在并升级字段；新增：

- `image_metrics.csv`
- `rework_metrics.csv`
- `measurement_quality.json`

bundle schema 升级，manifest 记录 v1/v2 输入占比、分桶版本、返工规则版本、覆盖率门槛和每文件哈希。继续使用同父目录临时目录和原子重命名，禁止覆盖已有完整包。

### 10. 用覆盖矩阵和受控回放验收

建立“用户动作 → Qt 入口 → 动作类型 → 终态 → 期望事件”的接入矩阵。固定回放覆盖整体移动、边/角调整、关键点、键盘微调、标签/属性、创建/删除、撤销、保存、A→B→A、空闲、失焦、图片切换和异常退出。

验收同时检查语义正确性和质量门槛：支持动作耗时覆盖率 ≥95%、episode 闭合率 ≥99%、重复等价事件率 <5%、缺失引用为 0。再用一段人工计时流程核对日志动作数与实际动作数。

异常长 episode 默认定义为有效语义事件数超过 100 或 active 时间超过 10 分钟，两个阈值都允许配置并写入 manifest；命中只产生诊断，不自动删除事件或拆分 episode。

## Risks / Trade-offs

- [Qt 接入点遗漏导致覆盖率不足] → 使用覆盖矩阵、集中协调器和每类动作最小集成测试。
- [动作合并过度丢失真实重复操作] → 仅在共享 action/correlation 或明确 burst 窗口内合并，并保留 input_count 和净变化摘要。
- [episode 与 active segment 概念增加复杂度] → 对外统计固定四层模型，manifest 明确口径，UI 不暴露内部状态机细节。
- [上下文分桶变化破坏历史可比性] → 分桶配置版本化，跨版本默认分开比较。
- [v1/v2 混合导致误解] → 每张表输出 schema 覆盖率和 legacy 占比，缺失字段不补造。
- [功能样本不足导致大量不可比较] → 输出明确 unavailable reason，允许积累更多自然日/会话后重算。
- [新增上下文增加日志体量] → 使用小型枚举和分桶，不记录采样点，继续受单事件大小和队列上限保护。
- [代表轨迹规则过滤过严] → 保留 measurement_anomaly 类，并在 manifest 记录候选数和排除原因。

## Migration Plan

1. 先增加 v2 schema、兼容读取器、上下文分桶器和动作状态机，保持现有 UI 接入行为不变。
2. 按覆盖矩阵逐类将几何、键盘、标签/属性和对象生命周期切换到统一 ActionSpan，旧事件适配器暂时保留。
3. 启用 episode/activity segment、功能参与和返工事实，验证记录覆盖率后停止重复 `shape_edited` 计数路径。
4. 升级分析算法和分析包，在固定 v1、v2、混合夹具上验证确定性与诚实降级。
5. 更新 UI/文档，明确新版指标口径和旧数据限制；发布后仍默认关闭采集。

回滚时可关闭 v2 采集并恢复 v1 适配入口；读取器继续接受已产生的 v2 日志。新版分析包是派生数据，可重新生成，不需要修改标注文件。

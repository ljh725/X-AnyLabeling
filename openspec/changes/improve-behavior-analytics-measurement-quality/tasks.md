## 1. 基线、契约与配置

- [x] 1.1 将本次分析包暴露的 `shape_edited` 过密、episode 耗时缺失、2057 事件长轮次、单状态功能比较和无效代表轨迹整理为匿名验收基线。
- [x] 1.2 建立“用户动作 → Qt 入口 → 语义动作类型 → 终态 → 必需上下文 → 期望事件数”的接入覆盖矩阵。
- [x] 1.3 定义 event schema v2、analytics algorithm v2、bundle schema v2 以及上下文/返工规则的独立版本常量。
- [x] 1.4 在默认配置中加入动作合并、功能比较最小样本量 30、异常 episode 事件数 100、active 时间 10 分钟及测量质量门槛。
- [x] 1.5 创建 v1、v2、v1/v2 混合、低覆盖率、异常长 episode、功能单组和功能双组的固定测试夹具。

## 2. Schema v2 与语义动作核心

- [x] 2.1 扩展事件契约，定义 `action_id`、动作终态、编辑目标、起止单调时间、净变化摘要、上下文版本和参与功能字段。
- [x] 2.2 更新事件目录、payload 白名单和 schema 校验，使 v2 必需字段按事件类型严格验证且不接受完整 points 或自由文本。
- [x] 2.3 实现纯 Python ActionSpan 状态机，支持 begin、commit、cancel、no_change、interrupt 和终态幂等。
- [x] 2.4 实现动作摘要比较器，用隐私安全摘要判断有效净变化，不保存原始几何快照。
- [x] 2.5 将滚轮、平移和键盘微调 burst 适配到统一 ActionSpan 终态，并保留 input_count 与净变化摘要。
- [x] 2.6 为异常退出和生命周期切换实现未闭合动作 interrupt，确保不会补造成功或持续时间。

## 3. 对象 Episode 与 ActivitySegment

- [x] 3.1 扩展会话状态机，在 ObjectEpisode 内维护一个或多个 ActivitySegment 及其开始、暂停、恢复和结束原因。
- [x] 3.2 在对象切换、取消选择、当前对象删除、图片切换和项目关闭时可靠结束 episode，并验证重复结束幂等。
- [x] 3.3 在窗口失焦、重新聚焦、空闲开始和空闲结束时切分 active segment，但保持连续选择 episode 不变。
- [x] 3.4 记录 episode 的 `changed`、`saved_after_change`、结束原因、动作数和终态完整性事实。
- [x] 3.5 验证 A→B→A 产生同一 A 身份的两个 episode，空闲恢复只产生新 active segment 而不增加返回次数。
- [x] 3.6 增加删除后撤销恢复、图片加载失败和运行中开启/关闭记录时的 episode/segment 回归测试。

## 4. 上下文摘要与隐私策略

- [x] 4.1 实现版本化上下文构造器，输出 shape_type、edit_target、point_count、size、aspect_ratio 和 initial_source 分桶。
- [x] 4.2 使用归一化 bbox 和固定阈值计算尺寸/宽高比分桶，覆盖空 points、退化几何和非矩形 shape。
- [x] 4.3 实现标签隐私策略：默认本机加盐匿名键，显式安全 allowlist 可保留受控类别，其余使用 unknown。
- [x] 4.4 把上下文摘要接入动作提交时刻，确保编辑前后采用同一版本规则且不改变 shape JSON。
- [x] 4.5 增加隐私测试，证明日志和分析包不含完整 points、原始非白名单标签、绝对路径、图片像素或盐值。

## 5. Qt 语义动作接入与去重

- [x] 5.1 审计 `canvas.py` 的整体移动、边、角、关键点和矩形精修 press/release/cancel 边界，标注唯一接入点。
- [x] 5.2 将整体移动、边调整、角调整和关键点移动接入统一 ActionSpan，并记录正确 edit_target 与单调耗时。
- [x] 5.3 将矩形边缘精修接入统一动作，复用现有 refinement 关联 ID，验证同一动作不被双重计数。
- [x] 5.4 将键盘连续微调、滚轮缩放和平移接入统一 burst/ActionSpan，验证静默窗口和图片切换边界。
- [x] 5.5 将标签修改和属性修改按一次 UI 提交事务记录为一个动作，并区分 cancelled、no_change 与 success。
- [x] 5.6 将 shape 新建、复制/粘贴、AI 生成、导入和删除的 initial_source 与对象事实接入统一协调器。
- [x] 5.7 调整 `shape_edited` 旧接入，使其只作为动作内部变化信号或 v1 兼容事件，不再逐回调进入 v2 可计数动作。
- [x] 5.8 增加最小 Qt offscreen 集成测试，逐项核对一次用户操作只产生一个最终语义动作。

## 6. 保存、撤销、完成事实与功能归因

- [x] 6.1 关联保存事件与本轮已修改对象，确定性维护 `saved_after_change`，避免重复保存通知重复计数。
- [x] 6.2 为撤销/重做建立动作关联，保留原动作并记录 undone/redone 事实及时间窗口。
- [x] 6.3 记录新建后删除、有效修改后删除、保存后再次编辑和对象返回等可审计事实。
- [x] 6.4 扩展 feature registry，为矩形精修、精确调整、AI、Inspector/质检、自动保存和输入模式定义唯一参与判定器。
- [x] 6.5 在动作中写入 participating_features，并通过状态重放派生 used，移除仅因 configured/active 自动置 used 的路径。
- [x] 6.6 验证功能开启但未参与、实际参与、同一动作多个功能参与和状态版本缺失四类场景。

## 7. 兼容读取、重放与测量质量诊断

- [x] 7.1 扩展读取器同时接受 v1/v2，并分别统计 schema 分布、legacy 事件数和字段覆盖率。
- [x] 7.2 为 v1 `shape_edited` 标记 legacy_low_granularity，确保可参与兼容次数但不进入 v2 精确耗时或重复率比较。
- [x] 7.3 扩展重放器以重建 ActionSpan、ObjectEpisode、ActivitySegment、保存事实、参与功能和终态完整性。
- [x] 7.4 实现动作耗时覆盖率、episode 闭合率、上下文覆盖率、功能状态覆盖率和低层重复事件率计算。
- [x] 7.5 实现异常长 episode 诊断，默认按事件数大于 100 或 active 时间大于 10 分钟标记，不自动删改或拆分数据。
- [x] 7.6 输出每项质量指标的分子、分母、阈值、状态、受影响事件类型和排除原因，并覆盖低于门槛的失败夹具。

## 8. 动作、对象、图片与返工统计

- [x] 8.1 扩展动作统计，按 action、edit_target、input_source、result、shape/context 分桶输出次数、结果率和耗时覆盖率。
- [x] 8.2 为有效耗时输出 total、mean、median、P75、P95，缺失值保持 null 并禁止以零补齐。
- [x] 8.3 实现 episode 的 wall、focused、active、动作耗时、结束原因、修改/保存事实和返工构成统计。
- [x] 8.4 实现对象级 episode 数、返回次数、累计 active、主要动作、完成状态、保存状态和返工次数汇总。
- [x] 8.5 实现 image visit 与 image identity 两层指标，包括对象工作量、有效动作、返工对象、时间和每活跃小时吞吐。
- [x] 8.6 实现撤销关联、反向调整、新建后删除、保存后再编辑、重复返回和 no_change 的版本化返工检测器。
- [x] 8.7 输出返工指标的规则版本、时间窗口、分子、分母、不适用数和返工活跃耗时，并增加边界测试。

## 9. 序列、功能比较与代表性轨迹

- [x] 9.1 构建归一化语义动作流，排除生命周期辅助事件和 legacy 重复回调，并按会话、图片、episode/segment 和长空闲切分。
- [x] 9.2 将纯同类自循环移出主要 transitions/common_sequences 排名，写入测量重复度诊断。
- [x] 9.3 升级 3 至 6 阶序列统计，输出次数、对象/episode 覆盖数、active 耗时和确定性排序。
- [x] 9.4 升级功能比较器，要求至少两个状态组、完整状态引用和每组默认 30 个有效 episode。
- [x] 9.5 为缺少对照、样本不足、状态缺失和维度不适用输出结构化 comparison_unavailable 原因，不再输出空白 difference。
- [x] 9.6 重写代表性轨迹选择，覆盖 common、median、P75、longest、rework、failure 和 measurement_anomaly，并排除只有 selection 的主轨迹。

## 10. 分析包、UI 与文档

- [x] 10.1 将 bundle schema 升级到 v2，保留首版九个文件并扩展现有 CSV/JSON 字段契约。
- [x] 10.2 新增 `image_metrics.csv`、`rework_metrics.csv` 和 `measurement_quality.json`，为所有表固定字段顺序和空值约定。
- [x] 10.3 扩展 manifest，记录事件版本分布、算法/分桶/返工规则版本、阈值、覆盖率、净化计数、文件大小和 SHA-256。
- [x] 10.4 保持临时目录写入和原子发布，验证失败、取消、目标已存在和旧分析包均不被覆盖。
- [x] 10.5 更新行为分析界面，展示测量质量状态、低可信度说明、功能不可比较原因和新增文件清单。
- [x] 10.6 更新用户文档，说明语义动作、四层时间口径、上下文隐私、返工定义、v1/v2 混合和观察性比较边界。

## 11. 端到端验收与发布保护

- [x] 11.1 为两个新能力规格的全部场景建立纯 Python 单测或最小 Qt offscreen 集成测试，并维护需求到测试映射。
- [x] 11.2 建立受控回放：整体移动、边/角调整、关键点、微调、标签/属性、创建/删除、撤销、保存、A→B→A、空闲和失焦。
- [x] 11.3 用受控回放验证支持动作耗时覆盖率 ≥95%、episode 闭合率 ≥99%、等价重复率 <5% 和缺失引用为 0。
- [x] 11.4 使用 v1、v2 和混合夹具验证动作次数、时间、返工、功能比较、序列、轨迹和 bundle 输出完全确定。
- [x] 11.5 对启用/关闭采集执行 UI 延迟、内存、队列和日志增长基准，修复超过首版约定阈值的回归。
- [x] 11.6 运行保存、撤销恢复、shape ID、格式转换、矩形精修和首版行为分析全套相关回归测试。
- [x] 11.7 运行 Black、flake8、相关 pytest、隐私扫描和 OpenSpec 严格校验，记录最终覆盖率与已知限制。

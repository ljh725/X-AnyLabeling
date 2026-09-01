## Context

参见 `proposal.md`。当前外观设置已经持有 `unrelated_opacity`，但纯 Python 聚焦控制器固定返回 `0.28`；Canvas 在进入 `Shape.paint()` 前没有最终渲染门控，普通标签又走独立绘制循环。Canvas 还保留 `_hide_backround` 旧状态，但它没有同组语义和完整 UI 契约。现有基础 Inspector 索引不保留原始 points，而 `quality/` 的 `QcShapeLoader`、bbox 和 IoU 工具能够支持几何重复检测。

本变更与进行中的 `optimize-annotation-visual-encoding-and-label-batch-operations` 有交叉。实施时以其已落地的外观类型、Focus 状态机和 Qt 适配器为基础，不复制第二套颜色或选择状态。

## Goals / Non-Goals

**Goals:**

- 让外观设置、Focus 强调、隔离成员关系和最终绘制结果形成单向、可测试的数据流。
- 用一个最终渲染决策统一约束矩形、文字和普通覆盖层，同时不污染 shape 数据。
- 在现有正式选择语义之上增加瞬态同组隔离，不复用持久可见性或筛选状态。
- 在纯 Python 质量层提供确定、可解释、只读且可扩展的重复矩形规则。

**Non-Goals:**

- 不改变 annotation JSON schema，不把外观、焦点、隔离或 QA 实体 ID 写入 shape。
- 不自动删除或合并重复矩形，不新增自动 NMS。
- 不改变不同 label 的 person/head/face 合法嵌套关系。
- 不重写现有标签筛选、虚拟复核或正式选择机制。
- 不在本变更中清理所有 `_hide_backround` 拼写和历史隐藏实现；只隔离新功能，待兼容入口迁移后再删除死路径。

## Decisions

### Decision 1: 由外观设置显式驱动 Focus 强调

将 `unrelated_opacity` 作为纯 Python 强调计算的显式输入或控制器配置，而不是在 Canvas 或 Qt 画笔中再次硬编码。控制器继续只返回 `0.0..1.0` 的语义透明度，Qt 适配器只负责转换。

**Rationale:** 单一数据源能让设置即时应用、边界钳制和纯 Python 测试保持一致。

**Alternative:** 仅在 Canvas 中把固定 `0.28` 替换为设置值。该方案会让纯控制器测试无法覆盖真实行为，并继续允许其他调用者绕过设置，因此不采用。

### Decision 2: 引入不可变的最终渲染决策

在基础可见性通过后，为每个 shape 解析一个不可变决策，至少包含 `draw_geometry`、`draw_text`、`draw_gid`、`draw_size_overlay` 和 `canvas_interactive`。解析顺序固定为：

1. 标签可见性、组合筛选、用户隐藏和虚拟复核；
2. 当前图片与正式选择快照；
3. Focus 强调和隔离成员关系；
4. 全局标签、Label on Selection、GID 与覆盖层偏好；
5. 视口裁剪后进入具体绘制器。

当 `object_opacity == 0` 或隔离排除对象时，在调用 `Shape.paint()` 之前跳过绘制。填充 Alpha 必须同时考虑对象透明度，避免轮廓隐藏但填充残留。普通标签循环、GID 和尺寸覆盖层消费同一个决策。

**Rationale:** 只让透明颜色进入绘制器仍有 CPU 成本，而且无法约束独立的文字和覆盖层通道。

**Alternative:** 在 `Shape.paint()` 内提前返回。该方案无法覆盖 Canvas 自己绘制的标签和覆盖层，因此不采用。

### Decision 3: 隔离状态独立于持久可见性与旧背景隐藏状态

新增瞬态隔离状态，保存 `enabled`、当前 image token 和由正式选择派生的目标语义，不修改 `shape.visible`、标签列表 checkbox 或过滤器。有效单组选择派生 group 目标；其他选择派生 shape token 集合。选择变化时重新计算，清空选择和图片生命周期事件清除。

隔离排除对象不参与 Canvas 命中测试，但标签列表和 Inspector 导航仍可以提交新的正式选择，从而转移隔离目标。菜单 action 显示明确 checked 状态，并分配经现有快捷键 schema 校验的快捷键。

**Rationale:** 复用 `hide_selected_polygons()` 会修改对象可见性且语义相反；复用 `_hide_backround` 会把同组对象遗漏并延续不完整生命周期。

### Decision 4: 统一标准标签路径而不重复绘制外观徽标

保留当前标准标签布局作为唯一文字排版来源，但在生成布局前查询最终渲染决策。`AppearanceSettings.show_labels`、全局 `show_labels`、`label_on_selection` 和 `show_gid` 在解析层合并，禁止同时绘制标准标签和未消费的 `VisualStyle.label_badge` 两套徽标。

**Rationale:** 两套标签渲染会产生位置冲突，也会让隔离规则出现一条路径隐藏、另一条路径残留的问题。

### Decision 5: 重复矩形规则放在纯 Python quality 层

新增独立 L2 runner，使用 `QcShapeLoader` 保留的原始 points、现有 bbox/IoU 函数和质量阈值 profile。规则先按文件和 label 分桶，再用扫线或均匀空间网格排除不可能相交的 bbox，最后对候选计算 IoU 和边坐标差。

每个无序对象对使用排序后的稳定实体标识构造 issue_id。问题主体保存一个导航主对象，并在 details 中保存另一对象的身份、索引和全部几何证据。复核队列继续按现有 feedback upsert 语义工作。

**Rationale:** `FlatIndex` 只有 points_count，无法可靠计算 bbox；扩展它会把基础 Inspector 与 L1/L2 几何质检重新耦合。

**Alternative:** 使用全量两两比较。实现简单但在密集检测结果中不可扩展，因此只作为测试 oracle 使用。

### Decision 6: 阈值进入版本化质量配置

在质量 profile 中增加同组 error IoU、跨组/未分组 warning IoU 和边坐标容差，沿用现有 schema 校验与 report profile_id。默认值分别为 `0.95`、`0.97` 和 `2px`。不同 label 永不进入该规则。

**Rationale:** 阈值需要可审计、可复现且能通过人工反馈后另行提出建议，不能藏在 UI 或规则实现常量里。

## Risks / Trade-offs

- **[Risk] 隔离后用户忘记存在隐藏对象** → 菜单、状态栏和画布角标持续显示隔离状态，清空选择与切图自动退出。
- **[Risk] 最终渲染决策与现有多条可见性路径重复判断** → 先增加契约测试和适配层，再逐条迁移消费者；不在同一步删除旧逻辑。
- **[Risk] 透明度为零时 QA 提示也可能造成认知分裂** → 普通画布输出统一隐藏，Inspector 中的问题计数与导航记录保留；导航选择目标后隔离随正式选择转移。
- **[Risk] 高 IoU 的真实双目标被误报** → 仅同 label 比较，跨组/未分组默认 warning，且坚持只读与人工决策。
- **[Risk] 空间索引边界导致漏检** → 用穷举 oracle 对随机小数据集做属性测试，并覆盖跨网格边界对象。
- **[Trade-off] 隐藏对象不参与 Canvas 命中** → 避免选择不可见对象的混乱；用户通过关闭隔离、标签列表或 Inspector 切换目标。
- **[Risk] 与现有外观大变更产生代码冲突** → 实施前对照其未完成任务 7.6、7.9、9.3、9.4、10.1，优先复用现有类型并在一个变更内完成冲突文件。

## Migration Plan

1. 先添加失败测试，证明配置透明度、零绘制、标签残留和重复规则缺口。
2. 接通纯策略与最终渲染决策，但保持隔离入口关闭；默认 `0.28` 保持现有可见效果。
3. 迁移矩形、标签、GID 和尺寸覆盖层消费统一决策，完成 offscreen/像素回归后开放零透明度。
4. 增加隔离 action、生命周期和本地化；默认关闭，避免改变现有交互。
5. 增加重复矩形规则和阈值；默认启用 warning/error 报告，但保持全程只读。
6. 若出现绘制回归，可关闭隔离并把无关对象透明度恢复为 `0.28`；质量规则可从 profile 禁用，无需迁移或恢复 JSON。

## Context

当前普通标签显示逻辑集中在 `anylabeling/views/labeling/widgets/canvas.py`，`label_on_selection` 同时参与标准标签绘制判断和点击释放阶段的选中处理。结果是一个本该只影响“看见什么”的开关，也会改变“点一下之后怎么选中/取消选中”。

相关文件：
- `canvas.py` — 普通标签绘制、hover/selected 状态、鼠标释放选中逻辑
- `label_widget.py` — 菜单 action、配置同步、保存用户配置
- `tests/test_canvas_interaction.py` — 交互级回归测试
- `tests/test_size_overlay.py` — 标签显示相关渲染测试

## Goals / Non-Goals

**Goals:**
- 将 `Label on Selection` 收敛为普通标签显示策略，不再改变选中语义
- 保留当前菜单项与配置项，避免引入额外 UI 成本
- 让单选、多选、hover 预览的显示规则可测试、可推理
- 为后续 Pose View 单独演进标签策略留出清晰边界

**Non-Goals:**
- 不修改 Pose View 的关键点标签策略
- 不新增“按缩放显示标签”等新模式
- 不改 annotation 文件格式或 shape 数据结构
- 不调整 `show_labels` 总开关的语义

## Decisions

### Decision 1: 将普通标签可见性抽成独立判定路径
**Rationale**: 让“显示哪些标签”由单一逻辑负责，比把条件散落在绘制循环和交互流程里更稳。这样可以直接表达 `show_labels`、`label_on_selection`、`selected`、`hovered` 四个因素的关系。

### Decision 2: 保留当前布尔配置，不扩展为多态显示模式
**Rationale**: 用户当前诉求是把已有功能边界理顺，不是扩大设置面。继续沿用现有菜单和配置键，修改成本更小，用户认知也更稳定。

### Decision 3: 开启 focused mode 时仅保留 selected 与 hovered 标签
**Rationale**: 这延续了当前“降低干扰”的核心目标，同时保留 hover 预览，避免用户在未点击前完全失去局部识别能力。相比引入延时 hover 或更多例外规则，这一版更容易验证。

### Decision 4: 删除显示开关对点击释放流程的特殊分支
**Rationale**: 选中生命周期应只由交互逻辑决定，不该由标签显示策略偷偷改写。把这层耦合去掉后，普通点击、重复点击、多选切换都会更可预测。

### Decision 5: 明确 Pose View 不属于本变更作用域
**Rationale**: Pose View 依赖 group 语义，普通 `shape.selected` 并不能准确表达“同一个人的全部关键点是否被聚焦”。把这部分留给独立任务，能避免普通模式规则误伤 Pose 渲染。

## Risks / Trade-offs

- **[Risk] hover 预览与 selected 规则叠加后出现漏显** → Mitigation: 为单选、多选、hover-only 三类场景补回归测试
- **[Risk] 去掉交互耦合后暴露已有点击边界问题** → Mitigation: 用现有 selection_changed 行为作为回归基线，不顺带改别的交互
- **[Trade-off] 继续保留布尔开关表达能力有限** → 先把行为边界收紧，后续若仍有更多显示模式需求，再单独升级配置模型

## Migration Plan

无需迁移。仅调整普通标签显示与交互解耦，不改历史标注数据，也不引入新的配置键。

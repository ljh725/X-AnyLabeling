## Context

当前 Pose View 存在三处边界混杂：

- `canvas.py` 中 Pose renderer 只在 `pose_filter_active` 为真时运行，而这个状态目前来源于“是否存在任何过滤”，并不等于“是否聚焦某个人体 group”。
- 标准标签绘制会抑制 COCO 关键点原生标签，但仍允许 `person` 矩形框标签继续显示，导致 Pose View 里仍有与关键点无关的文本干扰。
- Pose renderer 的接口虽然带有 `label_on_selection`、`hovered_group_id`、`zoom_reveals` 等参数，但当前实现并未真正消费这些语义，形成误导性的半接线状态。

相关文件：
- `canvas.py` — Pose View 入口、原生标签 suppression、渲染调用门控
- `pose_renderer.py` — Pose 几何与标签构建逻辑
- `label_widget.py` — Pose View 开关、过滤态与 group 聚焦状态流转
- `tests/test_canvas_interaction.py` / `tests/test_pose_renderer.py` — 行为回归测试

## Goals / Non-Goals

**Goals:**
- 让 Pose 几何渲染不依赖“是否存在任意过滤”
- 让关键点文本显示仅依赖 pose group 聚焦策略
- 在 Pose View 中默认去掉 `person` 矩形框标签文本干扰
- 把普通 `Label on Selection` 与 Pose View 的职责边界写清

**Non-Goals:**
- 不修改 Pose 标签左右布局规则
- 不改变骨架颜色、关键点样式或 pose 数据结构
- 不新增新的用户设置项
- 不改普通模式下 shape 级标签显示逻辑

## Decisions

### Decision 1: Pose 几何渲染与标签文本判定分层
**Rationale**: “能看到姿态结构”与“是否显示关键点文本”不是同一层需求。把几何常显、文本按策略显示拆开后，用户能稳定看到骨架，又不会因为默认全量标签而被干扰。

### Decision 2: Pose 聚焦以 group 语义为准，不复用普通 shape 级 selected 语义
**Rationale**: Pose 的工作对象是一个人的整组关键点。仅靠某个 point 或 person rectangle 的 `selected` 状态，无法准确代表整组是否应显示标签。group 级聚焦更符合用户心智模型。

### Decision 3: 只有 pose group 聚焦状态才能驱动关键点标签显示
**Rationale**: 当前“任何过滤都算 pose_filter_active”会把无关过滤误判成关键点标签触发条件。收紧为 pose group 聚焦后，状态来源更单一，行为也更可解释。

### Decision 4: Pose View 下主动 suppress `person` 矩形框原生标签
**Rationale**: Pose View 的核心任务是看关键点，不是看检测框标签。保留框线可以维持空间锚点，但默认隐藏框文本更符合“减少干扰”的目标。

### Decision 5: 将 `Label on Selection` 对 Pose 文本显示的无效性显式化
**Rationale**: 当前是“接口上传了，但渲染里没用”，这会让人误以为是漏实现。无论最终通过删参数还是显式 policy 隔离，都需要把“普通显示开关不控制 Pose 关键点文本”变成可读、可测的设计事实。

## Risks / Trade-offs

- **[Risk] 无聚焦时只显示几何，用户可能一开始看不到关键点文本** → Mitigation: 保持点击某个 pose group 后标签立即可见，并在文档与测试中固定该行为
- **[Risk] suppress `person` 标签可能影响依赖框文字识别的少数用户** → Mitigation: 保留 bbox 几何轮廓，不移除 person shape 本身
- **[Trade-off] 将 Pose 独立于普通 label 开关后，两个视图的标签规则不再统一** → 这是有意为之，因为普通 shape 聚焦与 pose group 聚焦属于两类不同问题

## Migration Plan

无需迁移。仅调整 Pose View 渲染策略与标签可见性，不影响历史标注数据和配置文件。

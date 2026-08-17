## Why

Pose View 的真实需求是“稳定显示姿态几何，并在需要时显示关键点标签”，但当前实现把 Pose 渲染是否启动绑定到过滤态，又保留了矩形框原生标签，导致功能语义混乱。现在需要把 Pose View 单独拆成一份任务文档，明确它是 group 级关键点可见性策略，而不是普通 `Label on Selection` 的延伸。

## What Changes

- 将 Pose View 的“姿态几何渲染”与“关键点文本标签显示”拆成两个独立层次：
  - Pose View 开启且存在 pose 数据时，骨架、关键点、人体框线稳定可见。
  - 关键点文本标签按 group 聚焦状态决定是否显示。
- 明确 Pose View 的聚焦语义基于 pose group，而不是普通 shape 级 `selected`。
- 在 Pose View 中默认隐藏人体矩形框标签文本，避免和关键点标签诉求混杂。
- 修正“任何过滤都触发 Pose 标签态”的边界，只有与 pose group 聚焦相关的状态才能影响关键点标签显示。
- 将 `Label on Selection` 与 Pose View 的关系写清：普通模式开关不再作为 Pose 关键点标签显示的控制面。

## Capabilities

### New Capabilities
- `pose-keypoint-label-visibility`: Pose View 下姿态几何常显、关键点标签按 group 聚焦显示的可见性策略。

### Modified Capabilities
- *(none - this change defines a dedicated Pose visibility contract rather than changing an existing main spec)*

## Impact

- **Files Affected**:
  - `anylabeling/views/labeling/widgets/canvas.py`
  - `anylabeling/views/labeling/widgets/pose_label/pose_renderer.py`
  - `anylabeling/views/labeling/label_widget.py`
  - `tests/test_canvas_interaction.py`
  - `tests/test_pose_renderer.py`
- **Risk**: 中，主要风险是 Pose View 开关、group 聚焦、普通标签 suppression 之间的回归。
- **Testing**: 需要新增“无过滤也渲染几何”“group 聚焦才显示关键点文本”“隐藏 person 矩形标签”的测试。
- **User Impact**: Pose View 行为更符合“看关键点”的使用目标，减少矩形框标签与过滤态带来的误解。

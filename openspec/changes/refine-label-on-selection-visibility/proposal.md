## Why

当前 `Label on Selection` 的目标是减少非选中对象标签干扰，这个方向是对的，但现有实现把“标签可见性”与“点击选中行为”耦合在一起，导致一个显示开关会意外影响交互语义。现在需要把它收敛成一个边界清晰、只负责普通模式标签显示的独立任务。

## What Changes

- 明确普通画布模式下 `Label on Selection` 的行为边界：
  - 开启时，仅显示当前选中 shape 的标签，并保留当前 hover shape 的即时预览能力。
  - 关闭时，恢复显示所有普通 shape 标签。
- 移除 `Label on Selection` 对选中/取消选中流程的副作用，使其成为纯显示策略。
- 保持现有菜单入口与配置项，不新增额外设置项。
- 明确该任务不处理 Pose View 的 group 级标签语义，避免和关键点标签策略耦合。

## Capabilities

### New Capabilities
- `label-on-selection-visibility`: 普通画布模式下基于选中态的标签显示策略与交互边界。

### Modified Capabilities
- *(none - this change introduces a new visibility contract rather than modifying an existing spec)*

## Impact

- **Files Affected**:
  - `anylabeling/views/labeling/label_widget.py`
  - `anylabeling/views/labeling/widgets/canvas.py`
  - `tests/test_canvas_interaction.py`
  - `tests/test_size_overlay.py`
- **Risk**: 中，主要风险是回归到普通 shape 的选中/hover 标签显示与点击行为。
- **Testing**: 需要补充 focused mode、multi-select、hover preview、点击回归测试。
- **User Impact**: 普通标注视图中非选中标签干扰减少，同时交互行为更稳定、更可预期。

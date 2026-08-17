## Purpose

定义普通画布模式下基于选中态的标签显示规则，使非选中对象的标签干扰可控，同时保证标签显示策略不会改变基础选中交互语义。

## ADDED Requirements

### Requirement: Focused mode SHALL 仅显示聚焦中的普通标签

当 `Label on Selection` 开启时，系统 SHALL 仅显示普通画布模式下当前聚焦中的标签；非聚焦 shape 的普通标签 SHALL 被隐藏。

#### Scenario: 单选时仅显示被选中标签

- **WHEN** 用户开启 `Label on Selection` 且当前只有一个普通 shape 处于选中状态
- **THEN** 该 shape 的标签 SHALL 可见
- **AND** 其他未选中普通 shape 的标签 SHALL 不可见

#### Scenario: 多选时显示全部被选中标签

- **WHEN** 用户开启 `Label on Selection` 且当前有多个普通 shape 处于选中状态
- **THEN** 所有被选中 shape 的标签 SHALL 可见
- **AND** 其他未选中普通 shape 的标签 SHALL 不可见

### Requirement: Hovered shape SHALL 保留即时标签预览

当 `Label on Selection` 开启且存在当前 hover 的普通 shape 时，系统 SHALL 允许该 hover shape 的标签作为即时预览显示，即使它尚未被选中。

#### Scenario: hover 未选中 shape 时显示预览标签

- **WHEN** 用户开启 `Label on Selection` 且鼠标悬停在一个未选中的普通 shape 上
- **THEN** 该 hover shape 的标签 SHALL 可见
- **AND** 其他未选中且未 hover 的普通 shape 标签 SHALL 保持隐藏

### Requirement: Disabled focused mode SHALL 恢复全部普通标签显示

当 `Label on Selection` 关闭时，系统 SHALL 恢复普通画布模式下全部普通标签的常规显示行为。

#### Scenario: 关闭 focused mode 后显示全部普通标签

- **WHEN** 用户关闭 `Label on Selection`
- **THEN** 所有满足普通标签显示条件的普通 shape 标签 SHALL 可见

### Requirement: 标签显示策略 SHALL NOT 改变选中交互语义

`Label on Selection` 作为显示策略，SHALL NOT 改变普通 shape 的选中、取消选中、多选切换等交互语义。

#### Scenario: 重复点击已选中 shape 的交互语义不受开关影响

- **WHEN** 用户在 `Label on Selection` 开启或关闭的任一状态下重复点击已选中的普通 shape
- **THEN** 系统的选中或取消选中结果 SHALL 与未引入该显示策略时保持一致

#### Scenario: 多选切换不受开关影响

- **WHEN** 用户执行普通 shape 的多选添加或移除操作
- **THEN** 选中集合的变化 SHALL 仅由交互动作决定
- **AND** SHALL NOT 因 `Label on Selection` 的状态不同而变化

### Requirement: Show Labels 总开关 SHALL 保持最高优先级

当全局标签显示总开关关闭时，系统 SHALL 隐藏普通标签，即使 `Label on Selection` 开启且存在选中或 hover shape。

#### Scenario: 总开关关闭时 focused mode 不再显示标签

- **WHEN** `show_labels` 关闭且 `Label on Selection` 开启
- **THEN** 普通 shape 标签 SHALL 全部不可见

## References

- `anylabeling/views/labeling/widgets/canvas.py`
- `anylabeling/views/labeling/label_widget.py`
- `tests/test_canvas_interaction.py`
- `tests/test_size_overlay.py`

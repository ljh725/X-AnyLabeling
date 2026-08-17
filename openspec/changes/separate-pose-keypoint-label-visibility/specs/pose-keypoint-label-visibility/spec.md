## Purpose

定义 Pose View 下姿态几何与关键点文本标签的可见性规则，使用户能稳定查看人体关键点结构，并只在 group 聚焦时看到需要的文本信息。

## ADDED Requirements

### Requirement: Pose 几何 SHALL 独立于过滤态稳定渲染

当 Pose View 开启且当前画布存在可渲染的 pose 数据时，系统 SHALL 渲染姿态几何元素，而不依赖任意过滤条件是否激活。

#### Scenario: 无过滤时仍显示 Pose 几何

- **WHEN** 用户开启 Pose View，当前图像存在 pose 数据，且没有激活任何过滤
- **THEN** 骨架、关键点和人体框线 SHALL 可见

#### Scenario: 非 pose 过滤存在时仍显示 Pose 几何

- **WHEN** 用户开启 Pose View，当前图像存在 pose 数据，且激活了与 pose group 无关的过滤条件
- **THEN** 骨架、关键点和人体框线 SHALL 继续可见

### Requirement: 关键点文本 SHALL 按 pose group 聚焦显示

Pose View 下的关键点文本标签 SHALL 由 pose group 聚焦状态驱动，而不是由普通 shape 级选中状态或任意过滤状态驱动。

#### Scenario: 无 group 聚焦时隐藏关键点文本

- **WHEN** 用户开启 Pose View 且当前没有聚焦任何 pose group
- **THEN** 关键点文本标签 SHALL 不可见

#### Scenario: 聚焦某个 group 时仅显示该组关键点文本

- **WHEN** 用户开启 Pose View 且当前聚焦某个 pose group
- **THEN** 该 group 的关键点文本标签 SHALL 可见
- **AND** 其他 group 的关键点文本标签 SHALL 不可见

### Requirement: Pose View SHALL 默认隐藏 person 矩形框标签文本

在 Pose View 中，系统 SHALL 隐藏 `person` 矩形框的原生标签文本，以减少与关键点阅读无关的文本干扰。

#### Scenario: Pose View 中 person 框线可见但文本隐藏

- **WHEN** 用户开启 Pose View 且当前存在 `person` 矩形框
- **THEN** `person` 框线 SHALL 继续可见
- **AND** `person` 标签文本 SHALL 不可见

### Requirement: 普通 Label on Selection 开关 SHALL NOT 控制 Pose 关键点文本

普通画布模式使用的 `Label on Selection` 开关 SHALL NOT 直接决定 Pose View 中关键点文本的可见性。

#### Scenario: 开关状态变化不改变未聚焦 Pose 文本结果

- **WHEN** 用户在 Pose View 中切换 `Label on Selection`，且当前没有聚焦任何 pose group
- **THEN** 关键点文本标签 SHALL 继续保持不可见

#### Scenario: 开关状态变化不改变已聚焦 Pose 文本结果

- **WHEN** 用户在 Pose View 中切换 `Label on Selection`，且当前已经聚焦某个 pose group
- **THEN** 当前 group 的关键点文本可见性 SHALL 保持不变

### Requirement: Pose 原生标签 suppression SHALL 覆盖普通标签路径

当 Pose View 生效时，系统 SHALL 避免通过普通标签绘制路径重复显示 Pose 相关文本。

#### Scenario: COCO 关键点不经普通标签路径重复显示

- **WHEN** 用户开启 Pose View 且当前存在 COCO 关键点 shape
- **THEN** 这些关键点的原生普通标签 SHALL 不可见
- **AND** 关键点文本仅可通过 Pose View 的 group 标签策略显示

## References

- `anylabeling/views/labeling/widgets/canvas.py`
- `anylabeling/views/labeling/widgets/pose_label/pose_renderer.py`
- `anylabeling/views/labeling/label_widget.py`
- `tests/test_canvas_interaction.py`
- `tests/test_pose_renderer.py`

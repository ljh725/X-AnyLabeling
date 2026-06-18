# pose-view-label-layout Specification

## Purpose

定义 Pose View 模式下人体关键点标签的摆放规则，使左右侧标签在视觉上一目了然，降低标注人员阅读标签前缀的认知负担。

## ADDED Requirements

### Requirement: 左右侧标签按身体轮廓方向分布

对于 Pose View 渲染的 COCO 关键点标签，若标签名以 `l_`、`r_`、`left_` 或 `right_` 开头（大小写不敏感），则标签必须分别放置在人形轮廓的左侧或右侧，而不是仅依赖字母前缀区分左右。

#### Scenario: 左臂/左腿标签位于身体左侧

- **GIVEN** 当前 group 中存在标签以 `l_` 或 `left_` 开头的关键点（如 `l_sho`、`left_elb`、`l_wri`、`l_hip`、`l_knee`、`l_ank`）
- **WHEN** PoseRenderer 计算标签摆放方向时
- **THEN** 这些标签的方向 SHALL 属于左侧族（`left` / `left-up` / `left-down`）
- **AND** 其实际矩形位置 SHALL 落在人体中线（midline）左侧

#### Scenario: 右臂/右腿标签位于身体右侧

- **GIVEN** 当前 group 中存在标签以 `r_` 或 `right_` 开头的关键点
- **WHEN** PoseRenderer 计算标签摆放方向时
- **THEN** 这些标签的方向 SHALL 属于右侧族（`right` / `right-up` / `right-down`）
- **AND** 其实际矩形位置 SHALL 落在人体中线右侧

#### Scenario: 无前缀标签保持默认方向

- **GIVEN** 标签为 `nose` 或无前缀自定义标签
- **WHEN** 前缀规则不适用时
- **THEN** 方向 SHALL 回退到现有 `compute_direction()` 基于 keypoint_index 和中线的默认方向

### Requirement: 躯干与下肢标签按部位和 Y 轴分层排列

躯干关键点标签与下肢关键点标签 SHALL 在身体左右侧分别排列，并按 Y 轴从上至下排序，避免相邻部位交叉显示。

#### Scenario: 躯干标签在左侧从上至下排列

- **GIVEN** 当前 group 的左侧躯干关键点包含 `l_sho`、`l_elb`、`l_wri`
- **WHEN** 应用 `anti` 或 `column` 布局时
- **THEN** 这三个标签 SHALL 全部位于中线左侧
- **AND** 按 Y 坐标从上至下依次排列为 `l_sho`、`l_elb`、`l_wri`

#### Scenario: 下肢标签在右侧从上至下排列

- **GIVEN** 当前 group 的右侧下肢关键点包含 `r_hip`、`r_knee`、`r_ank`
- **WHEN** 应用 `anti` 或 `column` 布局时
- **THEN** 这三个标签 SHALL 全部位于中线右侧
- **AND** 按 Y 坐标从上至下依次排列为 `r_hip`、`r_knee`、`r_ank`
- **AND** 位于躯干标签下方

### Requirement: 头部关键点在躯干上沿横向排列

头部关键点标签 SHALL 放置在躯干 bbox 上沿，按横向排列，`nose` 居中，左右眼/耳按前缀分居两侧，偏移量小于躯干标签。

#### Scenario: 头部标签横向居中排列

- **GIVEN** 当前 group 的头部关键点包含 `nose`、`l_eye`、`r_eye`、`l_ear`、`r_ear`
- **WHEN** PoseRenderer 渲染头部标签时
- **THEN** `nose` SHALL 位于躯干 bbox 上沿正中
- **AND** `l_eye`、`l_ear` SHALL 位于 `nose` 左侧，偏移量小于躯干标签的左右偏移量
- **AND** `r_eye`、`r_ear` SHALL 位于 `nose` 右侧，偏移量小于躯干标签的左右偏移量

### Requirement: 标签不得越过身体中线产生交叉

应用左右前缀规则后，标签矩形 SHALL 不跨越人体中线到对侧。若默认方向或防重叠搜索结果导致越界，SHALL 沿前缀方向继续外推直到不越界或达到最大搜索距离。

#### Scenario: 防重叠搜索结果越过中线时回正

- **GIVEN** 标签 `l_sho` 因防重叠搜索被推到中线右侧
- **WHEN** 应用前缀规则后
- **THEN** 该标签 SHALL 被重新定位到中线左侧
- **AND** 若左侧空间不足，SHALL 继续向左侧外推直到不越界或达到 `search_max`

### Requirement: 三种布局模式均支持前缀规则

左右前缀规则 SHALL 在 `direct`、`anti`、`column` 三种布局模式下均生效。

#### Scenario: direct 模式下左前缀标签在左侧

- **GIVEN** 布局模式为 `direct`
- **WHEN** 存在 `l_xxx` 标签
- **THEN** 该标签 SHALL 使用左侧方向族

#### Scenario: anti 模式下左前缀标签在左侧

- **GIVEN** 布局模式为 `anti`
- **WHEN** 存在 `l_xxx` 标签
- **THEN** 该标签 SHALL 经防重叠搜索后仍位于中线左侧

#### Scenario: column 模式下左前缀标签在左侧

- **GIVEN** 布局模式为 `column`
- **WHEN** 存在 `l_xxx` 标签
- **THEN** 该标签 SHALL 被分到左列

## References

- `anylabeling/views/labeling/widgets/pose_label/pose_layout.py`
- `anylabeling/views/labeling/widgets/pose_label/pose_renderer.py`
- `anylabeling/views/labeling/widgets/pose_label/pose_constants.py`

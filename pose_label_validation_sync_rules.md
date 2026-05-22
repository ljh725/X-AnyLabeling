# 姿态标注检查规则同步清单

## 同步目标

`scripts/validate_pose_labels.py` 与标注软件内置 `Data Inspector` 应共享同一套核心质检语义，避免出现脚本和软件检查结果不一致的问题。

建议定位如下：

| 模块 | 定位 |
|------|------|
| 共享核心规则 | 两边必须一致的姿态标注质量标准 |
| `validate_pose_labels.py` | 批量离线质检、生成报告、检查文件结构和坐标合法性 |
| `Data Inspector` | 软件内实时检查、辅助人工定位和修复问题 |

## 同步后的最终规则清单

| 规则 | 共享核心 | 脚本 | Data Inspector | 建议 |
|------|----------|------|----------------|------|
| 标签白名单检查 | 是 | 是 | 是 | 两边使用同一标签集，例如 `person/head/face/17 keypoints` |
| 标签与形状类型绑定 | 是 | 是 | 是 | `person/head/face` 必须是 `rectangle`，关键点必须是 `point` |
| 同一 `group_id` 内标签唯一 | 是 | 是 | 是 | 同一组内同一标签最多出现一次 |
| 关键点组必须包含 `person rectangle` | 是 | 是 | 是 | 有关键点的 `group_id` 必须存在对应 `person` 框 |
| `group_id` 类型合法性 | 是 | 是 | 建议补齐 | 统一为非负整数，排除 `null`、字符串、负数、布尔值 |
| `person rectangle` 必须有 `group_id` | 是 | 是 | 是 | 作为 `group_id` 类型合法性的子规则保留 |
| `head/face` 必须有 `group_id` | 是 | 是 | 建议补齐 | 脚本已有，Inspector 建议增加对应规则 |
| `head/face` 的 `group_id` 不应重复 | 是 | 是 | 建议补齐 | 脚本已有，Inspector 建议增加对应规则 |
| `label` 非空 | 是 | 间接检查 | 是 | 统一为明确错误 |
| `points` 非空 | 是 | 是 | 是 | Inspector 当前只检查点数量非空，建议语义与脚本对齐 |
| `points` 长度检查 | 否 | 是 | 可选补充 | `rectangle` 为 2 或 4 个点，`point` 为 1 个点 |
| 坐标格式检查 | 否 | 是 | 可选补充 | 每个坐标必须是 `[x, y]` |
| 坐标类型检查 | 否 | 是 | 可选补充 | `x/y` 必须是数字，不能是字符串或布尔值 |
| 坐标越界检查 | 否 | 是 | 可选补充 | 依赖 `imageWidth/imageHeight`，适合脚本批量检查 |
| `shapes` 字段结构检查 | 否 | 是 | 不建议同步 | 属于文件结构检查，Inspector 读取阶段处理即可 |
| JSON 读取/解析错误 | 否 | 是 | 不建议同步 | 属于文件加载错误，不属于 shape 规则 |
| 属性/flag 一致性 | 否 | 无 | 是 | 保留为 Inspector 扩展规则，如 `difficult`、`orphan_head` |
| 可配置 group 唯一类型 | 否 | 无 | 是 | 保留为 Inspector 扩展规则，适合项目自定义 |

## 建议统一后的规则分层

### 第一层：必须共享的核心规则

这些规则建议抽成共享定义，脚本和 Inspector 都使用同一语义：

| 规则名 | 说明 |
|--------|------|
| `LabelInAllowlist` | 标签必须在项目标签集内 |
| `LabelShapeTypeBinding` | 标签必须匹配指定 `shape_type` |
| `GroupLabelUniqueness` | 同一 `group_id` 内标签不可重复 |
| `GroupIdKeypointIntegrity` | 有关键点的组必须有 `person rectangle` |
| `GroupIdValid` | `group_id` 必须是非负整数 |
| `HeadFaceGroupIdRequired` | `head/face` 必须有合法 `group_id` |
| `HeadFaceGroupIdUnique` | `head/face` 的 `group_id` 不应重复 |
| `RequiredFieldNotEmpty` | `label` 和 `points` 不得为空 |

### 第二层：脚本专属批量检查

这些规则建议继续留在 `validate_pose_labels.py`，或作为脚本专属规则模块：

| 规则名 | 说明 |
|--------|------|
| `JsonReadable` | JSON 文件可读取、可解析 |
| `ShapesFieldValid` | `shapes` 存在且是列表 |
| `ShapeObjectValid` | 每个 shape 必须是对象 |
| `PointsLengthValid` | `rectangle`/`point` 的点数量正确 |
| `PointFormatValid` | 每个点必须是 `[x, y]` |
| `PointCoordinateTypeValid` | 坐标必须是数字 |
| `PointInsideImageBounds` | 坐标不能超出图片范围 |

### 第三层：Inspector 专属交互检查

这些规则建议继续作为 Data Inspector 的项目扩展能力：

| 规则名 | 说明 |
|--------|------|
| `AttributeConsistency` | 检查 `difficult`、`orphan_head` 等属性一致性 |
| `GroupIdUniqueness` | 用户自定义某些标签在组内唯一 |

## 推荐实施顺序

1. 统一标签集和形状类型映射。
2. 在 Data Inspector 中补齐 `GroupIdValid`、`HeadFaceGroupIdRequired`、`HeadFaceGroupIdUnique`。
3. 调整脚本和 Inspector 的同组重复、关键点完整性规则，使报错语义一致。
4. 评估是否将 `points` 长度、格式、越界检查加入 Inspector 的可选规则。
5. 后续如要彻底避免规则漂移，建议抽出共享规则定义，由脚本和 Inspector 同时复用。

## 结论

建议同步核心规则，不必强行同步所有规则。

必须同步的是标注语义规则：标签、形状类型、`group_id`、同组唯一性、关键点完整性。

可以保持差异的是运行环境相关规则：JSON 解析、文件结构、坐标越界、交互属性检查。

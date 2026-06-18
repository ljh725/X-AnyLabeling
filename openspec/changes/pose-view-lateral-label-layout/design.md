## Context

Pose View 的标签布局当前由 `anylabeling/views/labeling/widgets/pose_label/pose_layout.py` 中的 `compute_direction()` 决定方向，再由 `apply_layout()` 根据 `direct`/`anti`/`column` 三种模式放置标签。方向基于关键点索引和人体中线的相对位置，未显式利用标签名中的左右语义，导致左臂标签可能被推到右侧，降低可读性。

相关文件：
- `pose_layout.py` — 方向计算与布局算法
- `pose_renderer.py` — 构建 `PoseLabelItem` 并调用布局
- `pose_constants.py` — COCO 17 关键点顺序与身体部位分组（`head`、`la`、`ra`、`ll`、`rl`）

## Goals / Non-Goals

**Goals:**
- 对 `l_`/`r_`/`left_`/`right_` 前缀标签强制分配到身体左右侧
- 躯干标签按 Y 轴从上至下排列，左右不交叉
- 下肢标签按 Y 轴从上至下排列，接在躯干下方
- 头部关键点在躯干 bbox 上沿横向排列，偏移量小于躯干
- 三种布局模式全部生效
- 无前缀标签保持现有默认行为

**Non-Goals:**
- 不改关键点颜色、骨架绘制、圆形样式
- 不改原生 Canvas 标签显示逻辑
- 不改 PoseDisplayConfig 的公共 API
- 不引入新的布局模式

## Decisions

### Decision 1: 在 `compute_direction()` 后叠加前缀规则
**Rationale**: `compute_direction()` 仍负责基于解剖位置的默认方向。新增 `_apply_lateral_prefix_rule(direction, label, mid_x, anchor_x)` 函数，仅在前缀规则与默认方向冲突时修正方向，职责分离清晰。

### Decision 2: 三种布局模式统一生效
**Rationale**: 用户要求 `direct`、`anti`、`column` 都生效。`direct` 模式本身无防重叠，强制方向不会引入新的堆叠问题；`anti` 和 `column`  respectively 通过搜索和分栏保证位置约束。

### Decision 3: 头部标签放在躯干 bbox 上沿，偏移量较小
**Rationale**: 躯干 bbox 稳定易获取，避免计算人头轮廓。头部标签左右偏移量设为躯干标签的一半左右，既体现左右关系，又不至于 leader line 过长。

### Decision 4: 冲突时前缀规则优先，允许向同侧外推
**Rationale**: 当防重叠搜索把标签推到对侧时，前缀规则应覆盖该结果。若同侧空间不足，继续沿方向外推直到不越界或达到 `search_max`，保证左右语义不丢失。

### Decision 5: 使用大小写不敏感前缀匹配
**Rationale**: 兼容 `L_`、`Left_` 等历史或用户自定义标签，同时避免误匹配 `light_` 等非方向前缀（只匹配开头）。

## Risks / Trade-offs

- **[Risk] 强制方向可能导致 leader line 明显变长** → Mitigation: 受 `search_max` 限制；头部偏移量较小
- **[Risk] 自定义标签不遵循前缀约定时行为不变** → Mitigation: 无前缀时回退默认方向，文档说明支持的前缀
- **[Trade-off] 躯干/下肢分层需要额外排序** → 实现时按 `BODY_PARTS` 分组 + Y 轴排序，复杂度可控

## Migration Plan

无需迁移。仅渲染行为变化，不修改数据格式或配置文件。

## Open Questions

1. 是否需要在设置面板增加开关让用户关闭左右前缀规则？（当前按用户要求默认生效）
2. 对 `l_eye`/`r_eye` 等头部标签，横向偏移量具体取躯干偏移的 50% 是否合适，需视觉验证。

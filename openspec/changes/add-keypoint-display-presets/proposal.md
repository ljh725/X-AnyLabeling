## Why

密集图中的彩色圆点难以区分部位，长标签也会遮挡相邻点。用部位符号、按需名称和选中外环表达三种信息，让普通标注和密集复核共用一套显示方式。

## What Changes

- 所有关键点任务及普通标注画布都可以启用三层显示。明确选出唯一人物时弱化其他人物。
- 增加关键点显示管理器。用户可调整符号、名称、原始标签别名和两档尺寸，配置跨数据集使用。
- 用现有悬停提示和左下角状态栏解释点的身份。在数字键提示条下方提供当前图的部位对照。
- 复用现有选中和拖动流程。关键点在可见符号外保留少量命中余量，多个点同时命中时选最近者，当前矩形编辑手柄优先。

## Capabilities

### New Capabilities

- `keypoint-display-presets`：关键点的显示入口、跨数据集映射与尺寸、画布标记、按需释义和命中行为。

### Modified Capabilities

## Impact

- 涉及 PyQt6 画布、标注主界面、用户设置与翻译。密集复核接入复用 [CUSTOM-121 的有效显示与操作优先级](../redesign-dense-review-workspace/specs/dense-review-display-policy/spec.md)。
- 作用于显示和对象选择。标注标签、描述、分组、坐标、导出含义和审核状态沿用现有数据契约。
- 首版验收使用本地 `s1194` 和 `s54` 标注样本。决策来源见 [CUSTOM-122](../../../docs/custom_changes/2026-11-13-keypoint-three-layer-expression.md)。

## Why

单点拟合在框边内外使用突变的判断带，小框可能全落入无法判断区；按下后重新推断角点和 Alt 模式，可能导致松手结果与用户按下时确认的操作不同。

## What Changes

- 连续调整框外判断带，按屏幕宽高分别限制中心避让区。
- 按下后固定角点、原始几何和拟合模式；允许围绕固定点跨越，继续使用规范化矩形。
- 预览标记显示裁剪后的实际固定点和落点。
- 保留 Shift 取消、无效提案回退、单次撤销和导入越界框处理。

## Capabilities

### New Capabilities

- `rectangle-point-fit`: 稳定、可预期的矩形单点拟合交互。

### Modified Capabilities

无。当前主规格尚无对应能力。

## Impact

涉及 rect_edge_click.py、widgets/point_fit.py、Canvas 状态初始化和 test_shift_point_fit_*。不新增依赖，与矩形拖边变更分别验证。

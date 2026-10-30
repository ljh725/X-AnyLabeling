## Why

贴边例外可能选中更远的边并占用窄框内部的整体移动区域。扩大命中带后，边直接跳到鼠标坐标的问题更明显，极短边也容易被角点命中覆盖。

## What Changes

- 先比较所有相关边距离，再判断最近边是否可操作，禁止回退到更远边。
- 限制向框内延伸的感应带，保留中间移动区域。
- 按屏幕距离判断外侧空间不足，统一四边近边界处理。
- 给极小框提供边中点把手，并明确与角点的优先级。
- 使用原始边坐标加按下后的鼠标位移，避免跳变并保持边界限制和撤销。

## Capabilities

### New Capabilities

- `rectangle-edge-adjustment`: 兼顾准确拖边、角点和整体移动的矩形边编辑。

### Modified Capabilities

无。当前主规格尚无对应能力。

## Impact

涉及 widgets/rectangle_edge.py 和 test_rectangle_edge_migration.py；必要时在现有 Canvas 事件链增加把手命中。保持 Ctrl+Shift+E、原生对象遮挡顺序、坐标上限 width/height，不新增依赖。

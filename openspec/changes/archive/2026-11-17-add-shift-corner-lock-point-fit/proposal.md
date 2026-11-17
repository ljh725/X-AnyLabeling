## Why

实操日志显示，框内锁角后轻点左键会结束锁角，继续按住 Shift 移动鼠标却会出现固定对角的旧预览。用户需要用一套连续的操作预览、确认和取消。

## What Changes

- 普通 Shift 从框内开始时，四区只判断要移动的角，锁住该角的对角。锁角的同时生成预览，移动鼠标可跨区调整落点。
- 有效候选可用左键单击提交。先松开 Shift 就取消。框内手势结束后等待下一次 Shift 按下。
- 框外或边线起步继续使用原有单点拟合。Shift + Alt 仍提供同侧角单击入口。

## Capabilities

### New Capabilities

- `rectangle-point-fit` — 定义矩形单点拟合的入口、预览、提交和取消。

### Modified Capabilities

## Impact

- 画布单点拟合状态、Qt 键鼠事件与候选预览。
- 单点拟合回归及 CUSTOM-101 操作说明。

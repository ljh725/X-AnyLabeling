## Why

维护候选已完成整理。矩形预览主规格仍描述旧手势，部分历史证据链接在归档后失效，Windows 训练停止超时也需要实测退出路径。

## What Changes

- 对照当前实现和手册，修正矩形预览主规格的 Shift 入口和锁角标记描述。
- 在归档审计中为七处历史引用补充证据直达链接。
- 在两个固定提交的独立工作区复测训练停止，保留逐轮日志和进程、线程时间线。确认产品缺陷时另立修复变更。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `rectangle-preview-rendering`：校正主规格中拟合入口、Alt 和橙色实心点的规则，保留共边及预览恢复契约。

## Impact

起点为维护分支 `0e4a223e2b8f74f9c8a9e093643b3fa581d8c293`。工作分支为 `codex/4.2.1/stabilize-maintenance-baseline`，本地集成对照为 `codex/4.2.1-baseline-organization`。范围包括 OpenSpec、证据导航、诊断报告及台账。历史交付、运行源码和测试保持原样，提交仅在本地。

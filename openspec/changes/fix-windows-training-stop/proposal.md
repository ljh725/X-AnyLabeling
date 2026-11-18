## Why

Windows 无窗口训练进程在普通 taskkill 失败后仍要等待 5 秒才走强制终止，训练线程在此期间阻塞于输出读取。两个固定提交均复现了这一延迟。触发路径与实测证据见 [训练停止对照报告](../../../reports/stabilize_maintenance_baseline_20261118/REPORT.md)。

## What Changes

- 缩短 Windows 训练进程树在普通终止命令明确失败后的强制终止等待。
- 验证静默进程、输出管道、停止通知与清理的完整退出路径。

## Capabilities

### New Capabilities

- `windows-training-stop` 描述 Windows 停止训练的进程、通知及清理行为。

### Modified Capabilities

无现有训练停止主规格。

## Impact

优先限定在训练停止与 Windows 进程终止边界。若触及共用帮助函数，验证环境探测和导出调用方。此变更当前为后续修复方案。

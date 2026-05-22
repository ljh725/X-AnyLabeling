# 后台扫描手动化与索引安全功能总结

## 结论

后台扫描手动化与索引安全功能已经完成。

本次改造解决了打开大目录后首张图片已经显示、但 UI 仍持续卡顿数分钟的问题。根因不是单张图片或单个 JSON 的加载，而是目录打开后自动触发的全量 EXIF 扫描和 DatasetIndexWorker 索引构建抢占磁盘 IO，并通过进度信号持续影响主界面响应。

## 根因证据

- 关闭自动 EXIF 全量扫描和自动 DatasetIndexWorker 后，打开 3000+ 图片目录不再出现数分钟卡顿。
- 单张加载链路耗时约 `0.10s ~ 0.15s`，不是长时间卡顿来源。
- 长时间卡顿发生在 `load_file total` 之后，符合后台全量扫描抢 IO / 频繁进度信号拖慢 UI 的特征。

## 已完成改造

### 自动 EXIF 全量扫描关闭

- 打开目录时不再自动调用 `async_exif_scanner.start_scan(image_files)`。
- 拖放图片导入时也不再自动触发 EXIF 扫描。
- 已移除临时 `if False` 禁用写法。
- 配置项 `exif_scan_enabled` 不再导致目录打开时自动全量扫描。

### 手动 EXIF 扫描入口

- 新增 `Scan EXIF Orientation` 功能入口。
- 入口已加入 View 菜单和工具栏。
- 用户手动触发后扫描当前 `image_list`。
- 扫描期间通过状态栏提示当前扫描数量。
- 继续复用现有 `AsyncExifScanner` 和 `on_exif_detected()` 处理链路。

### 自动 DatasetIndexWorker 关闭

- 打开目录时不再自动调用 `_start_dataset_index_worker("refresh", ...)`。
- 不再通过 `_dataset_index_timer` 延迟自动构建索引。
- 切换目录时仍会取消 pending timer，避免旧目录任务残留。

### 手动 Dataset Index 入口保留

- 保留 `Refresh Dataset Index`。
- 保留 `Rebuild Dataset Index`。
- 保留 `Cancel Dataset Index Build`。
- 构建中、完成、失败、取消状态提示保持可用。

### 筛选导航索引安全

- `enable_filter_navigation()` 在 SQLite 索引未 ready 时只提示用户。
- 不再调用 `FilterNavigationEngine.collect_matched_files(...)` 做全目录 JSON 扫描。
- 用户需要先手动构建 Dataset Index，再启用筛选结果导航。

### 性能日志默认关闭

- 临时性能埋点已改为 `_perf_log(...)`。
- 默认启动时不输出翻页和加载阶段性能日志。
- 设置环境变量 `XANYLABELING_PERF_LOG=1` 后可以重新启用性能日志。
- 错误日志和正常业务日志不受影响。

## 关键代码位置

- `anylabeling/views/labeling/label_widget.py`
- `anylabeling/views/labeling/label_file.py`
- `anylabeling/views/labeling/widgets/canvas.py`
- `docs/background-scan-manualization-checklist.md`

## 使用方式

### 打开目录

直接打开图片目录即可。程序只加载当前需要显示的图片与标签，不会自动启动全目录 EXIF 扫描或 SQLite 索引构建。

### 手动扫描 EXIF

在 View 菜单或工具栏点击 `Scan EXIF Orientation`。程序会扫描当前文件列表中的图片，并沿用原有 EXIF 处理逻辑。

### 手动构建索引

在 View 菜单或工具栏点击 `Refresh Dataset Index` 或 `Rebuild Dataset Index`。构建期间可以使用 `Cancel Dataset Index Build` 取消。

### 启用性能日志

默认不输出性能埋点日志。如需调试加载性能，启动前设置：

```bash
XANYLABELING_PERF_LOG=1
```

## 验证情况

- 任务书 `docs/background-scan-manualization-checklist.md` 中 Task A 到 Task F 的 checklist 与验收项均已勾选完成。
- 已运行 `flake8 anylabeling/views/labeling/label_widget.py anylabeling/views/labeling/label_file.py anylabeling/views/labeling/widgets/canvas.py`。
- flake8 仍报告若干既有问题，包括复杂度、未使用 blocker 变量和一个缺少占位符的 f-string；本次新增修改点没有引入新的性能日志直出问题。

## 当前状态

该功能已完成，可以进入人工回归验证阶段。建议重点验证以下路径：

1. 打开 3000+ 图片目录后首张图片是否可立即翻页。
2. `Scan EXIF Orientation` 是否只在用户点击后启动。
3. 未构建 Dataset Index 时启用筛选导航是否只提示、不扫描 JSON。
4. 手动 `Refresh Dataset Index` / `Rebuild Dataset Index` 后筛选导航是否正常工作。
5. 未设置 `XANYLABELING_PERF_LOG=1` 时终端是否不再输出加载阶段性能日志。

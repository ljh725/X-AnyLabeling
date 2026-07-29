# 后台扫描手动化与索引安全任务书

## 0. 根因证据

- 测试结果：关闭自动 EXIF 全量扫描和自动 DatasetIndexWorker 后，打开目录后图片与标签显示完成不再出现数分钟卡顿。
- 单张加载链路耗时约 `0.10s ~ 0.15s`，不是长时间卡顿来源。
- 长时间卡顿发生在 `load_file total` 之后，符合后台全量扫描抢 IO / 频繁进度信号拖慢 UI 的特征。

---

## Task A：正式关闭自动 EXIF 全量扫描（P0）

### 目标

打开目录时不自动遍历所有图片读取 EXIF。

### Checklist

- [x] 移除临时 `if False` 写法。
- [x] 打开目录后不自动调用 `async_exif_scanner.start_scan(image_files)`。
- [x] 保留 EXIF 扫描能力，后续只由用户手动触发。
- [x] 配置项 `exif_scan_enabled` 不再导致目录打开时自动全量扫描。

### 验收

- [x] 打开 3000+ 图片目录后不触发 EXIF 扫描线程。
- [x] 首张图片显示后可立即翻页。

---

## Task B：正式关闭自动 DatasetIndexWorker（P0）

### 目标

打开目录时不自动构建 SQLite 索引。

### Checklist

- [x] 移除自动 `_dataset_index_timer` 启动逻辑。
- [x] 打开目录后不自动调用 `_start_dataset_index_worker("refresh", ...)`。
- [x] 保留手动 `Refresh Dataset Index` 和 `Rebuild Dataset Index`。
- [x] 切换目录时取消 pending timer / worker。

### 验收

- [x] 打开目录后不会出现后台索引进度。
- [x] 手动刷新/重建索引仍可用。

---

## Task C：新增/整理手动 EXIF 扫描入口（P1）

### 目标

提供用户主动触发的 `Scan EXIF Orientation` 功能。

### Checklist

- [x] 新增菜单或工具栏入口：`Scan EXIF Orientation`。
- [x] 手动触发时扫描当前 `image_list`。
- [x] 扫描期间显示状态或进度。
- [x] 支持取消更好，第一版可复用现有 `AsyncExifScanner`。

### 验收

- [x] 不打开目录自动扫描。
- [x] 用户点击后才开始 EXIF 扫描。
- [x] 扫描结果和原有逻辑一致。

---

## Task D：整理手动 Dataset Index 入口（P1）

### 目标

让 SQLite 索引构建变成用户明确触发的动作。

### Checklist

- [x] 保留 `Refresh Dataset Index`。
- [x] 保留 `Rebuild Dataset Index`。
- [x] 保留 `Cancel Dataset Index`。
- [x] 状态提示清晰：构建中 / 完成 / 失败 / 取消。

### 验收

- [x] 手动触发后索引能正常构建。
- [x] 构建期间可取消。
- [x] 构建完成后筛选导航可用。

---

## Task E：Task 8 禁止筛选导航回退全量 JSON 扫描（P0）

### 目标

SQLite 未就绪时，不允许筛选导航自动遍历全部 JSON。

### Checklist

- [x] `enable_filter_navigation()` 中 SQLite 未 ready 时只提示。
- [x] 不调用 `FilterNavigationEngine.collect_matched_files(...)` 做全目录扫描。
- [x] 提示用户先手动构建 Dataset Index。

### 验收

- [x] 未建索引时启用筛选导航不会卡顿。
- [x] 未建索引时只显示提示。
- [x] 手动构建索引后筛选导航正常工作。

---

## Task F：清理临时性能埋点（P0）

### 目标

确认根因后，性能日志默认不输出，避免污染终端和拖慢 UI。

### Checklist

- [x] 性能日志默认关闭。
- [x] 通过环境变量启用：`XANYLABELING_PERF_LOG=1`。
- [x] 保留关键慢日志阈值。
- [x] 不使用无条件 `logger.info` 打印每次翻页阶段。

### 验收

- [x] 默认启动时不输出性能埋点日志。
- [x] 设置 `XANYLABELING_PERF_LOG=1` 后输出性能埋点日志。
- [x] 错误和正常业务日志不受影响。

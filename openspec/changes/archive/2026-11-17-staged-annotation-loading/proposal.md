## Why

当前 4.2.1 在更改输出目录后，同步为整个目录检查标注文件并读取审核字段，当前图片显示必须等待这些工作。PRW 的 11,792 文件实测首图约 4.97 秒，其中目录状态读取约 3.4 秒；用户报告的 7–10 分钟发生在旧版本，不能当作当前版本基线。

## What Changes

- 在当前 4.2.1 实现拆分加载：当前图片优先，目录扫描及其他文件的标注存在性、审核状态在后台读取，界面分批更新。
- 更改输出目录时复用已知图片列表、保持当前图片，避免无必要地扫描同一图片目录。
- 区分待读取、读取失败、未审核、通过、不通过，防止尚未读取的数据被当成未审核。
- 保留文件搜索与审核导航的准确性；属性搜索后台执行，结果未完成时明确显示进度。
- 为目录切换、搜索切换、保存后的状态更新和关闭窗口建立取消与过期结果隔离机制。
- 增加针对竞态、导航及完整 GUI 加载链路的测试和可复现性能报告。
- 本阶段不加入 SQLite、重建索引、持久元数据缓存；不改变 JSON 格式、画框算法、几何缓存或 Undo 快照策略；不直接复制整个 beta.4 模块。

## Capabilities

### New Capabilities

- `staged-annotation-loading`: 分阶段加载、状态准确性、任务生命周期、搜索与审核导航以及性能验收。

### Modified Capabilities

无。当前项目尚无既有 OpenSpec 主规格。

## Impact

- 改造目标：`D:/X-AnyLabeling-4.2.1`；参考目录 `D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4` 只读。
- 主要入口：`anylabeling/views/labeling/label_widget.py` 中的目录导入、输出目录切换、文件状态、搜索、审核导航、保存回填和关闭处理；建议新增小型加载控制器/worker 模块，减少主窗口继续膨胀。
- 沿用现有 PyQt6 信号和线程能力，默认不引入新第三方依赖；单张图片仍由现有加载链读取真实 JSON。
- 数据集只读用于性能测试，写入及损坏数据用临时样本验证。真实图片与 JSON 不得被基准测试修改。
- 参考证据：`reports/label_loading_comparison_20261029/REPORT.md`、`benchmarks/canvas_drawing_20261029/REPORT.md`、`benchmarks/folder_loading_20261029/REPORT.md`。

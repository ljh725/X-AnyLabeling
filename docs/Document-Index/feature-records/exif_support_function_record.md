# EXIF Orientation Support 功能记录

```text
功能名称：
EXIF Orientation Support / AsyncExifScanner / ExifProcessingDialog

修改目的：
解决带有 EXIF Orientation 标签的图片在标注时显示方向错误的问题。
这类图片在查看器中可能自动旋转，但直接读取像素数据时却是未旋转的原图，
导致标注框位置与实际视觉内容不符，进而影响训练数据质量。
本功能提供自动检测和批量修正机制，在后台扫描并处理 EXIF 方向标签。

影响流程：
1. 用户打开数据集时，若配置项 exif_scan_enabled 为 True，自动启动 AsyncExifScanner 后台扫描。
2. ExifScannerWorker 逐张读取图片的 EXIF Orientation（0x0112）标签。
3. 发现非标准方向（orientation != 1）的图片后，通过信号通知主线程。
4. 主线程弹出确认对话框，询问用户是否批量处理。
5. 用户确认后，ExifProcessingDialog 显示进度条并逐张应用 PIL.ImageOps.exif_transpose() 修正。
6. 处理前自动将原图备份到 x-anylabeling-exif-backup/ 目录。
7. 用户也可通过菜单 "Scan EXIF Orientation" 手动触发扫描。

依赖锚点：
1. `anylabeling/views/labeling/utils/async_exif.py`（扫描器与处理对话框）
2. `anylabeling/views/labeling/utils/image.py`（辅助函数 check_img_exif / process_image_exif）
3. `anylabeling/views/labeling/label_widget.py`（AsyncExifScanner 集成与菜单项）
4. `anylabeling/views/labeling/settings/schema.py`（exif_scan_enabled 配置）
5. `anylabeling/views/labeling/settings/runtime_applier.py`（配置热更新）
6. `anylabeling/configs/xanylabeling_config.yaml`（默认配置）

改动文件：
1. `anylabeling/views/labeling/utils/async_exif.py`（新建）
2. `anylabeling/views/labeling/utils/image.py`（新增 EXIF 相关辅助函数）
3. `anylabeling/views/labeling/label_widget.py`（集成扫描器与菜单）
4. `anylabeling/views/labeling/settings/schema.py`（新增配置项）

验证步骤：
1. 准备一组包含 EXIF Orientation = 3/6/8 的测试图片，导入数据集。
2. 确认自动扫描检测到这些图片，并弹出确认对话框。
3. 执行批量处理，确认图片在标注界面显示方向正确。
4. 检查 x-anylabeling-exif-backup/ 目录，确认原图已备份。
5. 关闭 exif_scan_enabled，重新打开数据集，确认不再自动扫描。
6. 手动触发 "Scan EXIF Orientation"，确认功能正常工作。

已知副作用：
1. 自动扫描会增加数据集加载时间（与图片数量成正比）。
2. 处理后的图片会重写磁盘文件，虽已有备份但仍需谨慎。
3. 对于只读目录或网络路径，备份/写入可能失败。
4. 处理过程不可逆（除非从备份恢复）。

后续注意：
1. 若用户频繁切换数据集，可考虑缓存 EXIF 扫描结果避免重复扫描。
2. 支持更多 EXIF 字段（如 GPS、拍摄时间）的读取和展示。
3. 对于 WebP/HEIC 等格式的 EXIF 支持需验证 PIL 兼容性。
4. 处理失败时应更细粒度地记录日志，方便排查问题文件。
```

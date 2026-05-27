# Viewport Controller 功能记录

```text
功能名称：
Viewport Controller / ViewportState / ViewportController

修改目的：
解决切换图片时视图状态（缩放比例和滚动位置）丢失的问题。
在原始实现中，每次加载新图片都会重置为默认缩放，用户需要反复调整视图。
本功能将视图中心点以图像坐标（而非滚动条像素值）保存，使状态在窗口大小变化时仍然有效，
并支持跨图片继承视图（适用于批量处理同尺寸图片）。

影响流程：
1. 标注界面启动时创建 ViewportController 实例。
2. 用户离开当前图片时，LabelWidget.load_file() 调用 on_file_leaving() 保存当前视图状态。
3. 新图片加载后，调用 on_file_loaded() 尝试恢复历史视图。
4. 解析优先级：精确历史记录 → keep_prev_viewport 继承上一张图的视图 → 无记录则回退到默认缩放。
5. 关闭文件夹时调用 clear() 清除所有缓存状态。
6. 支持单张或批量清除指定图片的视图状态。

依赖锚点：
1. `anylabeling/views/labeling/widgets/viewport_controller.py`
2. `anylabeling/views/labeling/label_widget.py`（load_file 生命周期钩子）
3. `anylabeling/views/labeling/widgets/canvas.py`（scale / offset_to_center / pixmap）
4. `anylabeling/views/labeling/widgets/zoom_widget.py`（缩放值读取/设置）
5. `anylabeling/configs/xanylabeling_config.yaml`（keep_prev_viewport 配置项）

改动文件：
1. `anylabeling/views/labeling/widgets/viewport_controller.py`（新建）
2. `anylabeling/views/labeling/label_widget.py`（集成生命周期调用）
3. `anylabeling/views/labeling/widgets/__init__.py`（导出）

验证步骤：
1. 打开数据集，缩放并滚动到特定位置，切换到下一张图再切回，确认视图恢复。
2. 调整窗口大小后切换图片，确认视图中心仍然正确。
3. 启用 keep_prev_viewport，切换图片时确认继承上一张图的缩放和中心。
4. 关闭文件夹后重新打开，确认视图缓存已清空。
5. 验证 FIT_WINDOW / FIT_WIDTH / MANUAL_ZOOM 三种模式均正确保存和恢复。

已知副作用：
1. 继承视图模式（keep_prev_viewport）对不同尺寸图片可能导致中心点偏移出边界。
2. 如果图片从未被加载过（直接跳转），则没有历史记录可用，会回退到默认缩放。
3. 状态以图像坐标存储，理论上与窗口大小无关，但极端缩放比例下可能存在浮点精度误差。

后续注意：
1. 若新增“全局视图锁定”功能，需与 ViewportController 协调。
2. 若修改 Canvas 的坐标变换逻辑，需同步更新 _capture 和 _apply 中的换算公式。
3. 若未来支持多窗口/多标签页，需将状态与标签页 ID 关联而非仅文件名。
4. 可考虑持久化到配置文件，使视图在程序重启后仍可恢复。
```

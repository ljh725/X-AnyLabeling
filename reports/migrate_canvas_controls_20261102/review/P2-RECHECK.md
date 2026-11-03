# migrate-canvas-controls-from-v430 P2 复验

日期：2026-11-02（Asia/Shanghai）。针对当前未提交实现重新核对原两条复核意见、用户限定的五项迁移范围及对应修复；不改生产代码或任务勾选。

## 结论

本轮未发现仍需保留的未解决 P2。原“保持最新显示值”问题修复通过；原“四极值草稿切换模式”按已有功能兼容路径复验通过。后者原先只有延迟策略不一致的证据，不能据此声称发生了四极值功能回退，也不构成新增四极值迁移需求。

这只关闭本轮具体复核意见，不代表整个迁移已完成验收或可以自动归档。

## 1. 亮度/对比度最新值保持

- `label_widget.py::reset_state` 在清空原图片状态之前调用 `_flush_pending_brightness_contrast`。
- 刷新函数停止原图节流定时器，将滑块当前值保存到原图已有显示缓存，不为旧图额外执行像素渲染。
- 开启保持时，目标图从更新后的原图缓存读取最新值；未开启保持时，继续恢复目标图自己的缓存/中性值。
- 原两个反例（缓存 70，滑块 90，33ms 内切图）均通过。新增正式回归还验证原图缓存、目标图值及等待节流时间后不被旧事件覆盖。
- 结论：原 P2 已修复，本次相关路径未发现新增缺陷。

## 2. 既有四极值与导航模式的兼容

- `Canvas.interaction_in_progress` 已识别 `rectangle_creation.draft`。
- 主窗口复用 `drawing_polygon` / `new_shape` 结束通知，通过下一轮事件循环检查暂存模式；无需修改四极值几何或绘制算法。
- 原检测用例已通过；新增正式用例分别调用实际草稿取消、提交路径，经事件循环后验证新模式生效并清除 pending 状态，不依赖测试手动调用 pending 方法。
- `git diff --numstat` 对 `widgets/rectangle_creation.py` / `widgets/rectangle_extreme.py` 无输出：本轮工作区未改这两个既有功能文件。
- 结论：兼容处理复验通过；原 P2 评级不能作为新增范围的理由。本次仍仅迁移用户选定五项能力。

## 本次实际验证

运行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest reports/migrate_canvas_controls_20261102/review/test_review_gaps.py tests/test_labeling/test_canvas_display_retention.py tests/test_canvas/test_wheel_navigation.py -q -p no:cacheprovider --basetemp reports/migrate_canvas_controls_20261102/review-p2-recheck-pytest --junitxml=reports/migrate_canvas_controls_20261102/review/p2-recheck.xml
```

- 结果：**37 passed，47.16 秒**；包括原 7 项复核用例及保持值、模式切换相关回归。
- `openspec validate migrate-canvas-controls-from-v430 --strict`：通过。
- `git diff --check`：通过。
- 测试使用已有 Conda 环境，在获准的沙箱外离屏运行，测试图片/config/QSettings 与结果保存在项目复核目录。
- 未重新运行全历史测试、性能基准或可见窗口人工验收。原先未勾选的布局、视图边界、性能和人工任务仍不应因本次 P2 复验通过而自动完成。

## 复验源码指纹（SHA-256）

- `anylabeling/views/labeling/label_widget.py`: `eee4900575d76d5f6d669e9247367144ea16a91d061b745ae218f283d0ca909c`
- `anylabeling/views/labeling/widgets/canvas.py`: `e9880c23ace6f9e7c2ccde13eb1d16a5b2ae207b28efaa9f6b4786ad6126abf8`
- `tests/test_labeling/test_canvas_display_retention.py`: `d8069aba438620c009dbc331300fff508b6d56dae64c18f553ddcb22678a9428`

# 单点拟合实施与验证

2026-10-30，任务 5/5 完成，未归档。代码已实施；可见窗口人工体验未验收。

- 角点判断：框外判断带从 1px 连续增长到 8px，横纵分别不超过对应屏幕尺寸的 1/4。
- 按下捕获原始矩形、角点及 Alt 模式；移动、松手沿用捕获结果。跨固定点仍用 min/max 生成有效矩形。
- 预览固定点和目的点裁到 0..width/height，保持导入框裁剪、Shift 取消和单次撤销。
- 修改文件：rect_edge_click.py、widgets/point_fit.py、Canvas 初始化及两个 test_shift_point_fit_* 文件。

拟合专项命令：`python -m pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py -q --tb=short --color=no -p no:cacheprovider`，结果 **57 passed**。使用解释器 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，环境 `QT_QPA_PLATFORM=offscreen`。

联合画布回归 **543 passed / 1 failed / 83 subtests passed**，包含全部 57 项拟合测试。日志与 JUnit 见第二个变更中的 [canvas-regression.log](../improve-rectangle-edge-adjustment/canvas-regression.log) 和 [canvas-regression.xml](../improve-rectangle-edge-adjustment/canvas-regression.xml)。

唯一失败为 `test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`（179 != 139），此前 [基线日志](../../../reports/drag_fix_20261030/regression/core_baseline.log) 和 [边界修复回归](../../../reports/rect_boundary_20261030/canvas_regression.log) 已记录相同失败。未修改该标签缩放逻辑。

`openspec validate improve-point-fit-algorithm --strict` 通过。三个算法文件经 Black 格式化／检查，`git diff --check` 通过。

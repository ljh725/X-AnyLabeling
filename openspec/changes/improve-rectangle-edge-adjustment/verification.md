# 矩形边调整实施与验证

2026-10-30，任务 6/6 完成，未归档。五条优化均已实施；可见窗口人工体验未验收。

- 最近边：先比较几何距离；最近边不可操作时不回退到更远边；等距回退普通操作。
- 中心移动：内侧命中带上限为相对边间距的 1/4，中心保留整体移动空间。
- 近边界：统一按屏幕距离折算可用外侧空间，外侧空间不足时逐步开放内侧区域。
- 小框把手：四边中点可见、可命中，半径不超过 3 屏幕像素及宽高各 1/4；精确角点和中心可分别操作，保留遮挡对象优先级。
- 平稳拖边：保存图像空间按下点及原始四点，按原始位置加累计位移计算；到边界后返回起点不漂移。

修改文件：widgets/rectangle_edge.py、test_rectangle_edge_migration.py。此前边界测试中四项断言从“边跳到鼠标”改为“边跟随位移”；两项最后像素边界断言按新规则保留一图像像素的外侧空间。原小框近边中点断言改到把手之外，另有把手和中心实际移动测试。

联合专项运行先完成 **151 passed**；随后补充中央整体移动交互用例，最终完整画布回归中的三份专项文件合计 **152 项通过**，其中矩形边测试 95 项、单点拟合测试 57 项。

完整命令：`python -m pytest tests/test_canvas -q --tb=short --color=no -p no:cacheprovider --junitxml=openspec/changes/improve-rectangle-edge-adjustment/canvas-regression.xml`，解释器 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，环境 `QT_QPA_PLATFORM=offscreen`。

结果 **543 passed / 1 failed / 83 subtests passed**，见 [日志](canvas-regression.log) 和 [JUnit](canvas-regression.xml)。唯一失败是已知标签缩放测试 `test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`（179 != 139），此前 [基线](../../../reports/drag_fix_20261030/regression/core_baseline.log) 已失败；本次没有新增失败节点。

`openspec validate improve-rectangle-edge-adjustment --strict` 和 `git diff --check` 通过。算法文件 Black 格式化完成；未改变普通框菜单和快捷键。

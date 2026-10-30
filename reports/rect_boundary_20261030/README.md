# 矩形边界交互修复（2026-10-30）

修复 CUSTOM-101（Shift+左键单点拟合）和 CUSTOM-102（矩形边编辑）在图像边界附近失效的问题。原有三个 `probe_edge_boundary*.py` 保留在本目录。

## 改动

- 小框贴左、上边界，或右、下边到达最后一个像素／完整图像边界时，允许从框内的命中带启动拖边。仍保留角点优先、重叠对象选择优先和非贴边小框内部整体移动的规则。
- 拖边命中只检查有限坐标和至少 1×1 的尺寸；导入框部分越界时，仍可调整可见边。
- 单点拟合先裁剪提案，再检查剩余尺寸；预览和松手提交采用同一计算路径。裁剪后不足 1×1 的提案不捕获按下事件。
- 无效拟合回退至普通选择／移动后，按键拖动不会再次被拟合预览截断。
- 处理缩放换算在 10px 命中边缘产生的浮点误差。

与原诊断建议的一处调整：坐标上限使用 `width/height`。现有画框完成逻辑和 `test_shape_boundary.py`、`test_fit_preserves_opposite_edge_at_image_extent` 已将完整图像边界视为合法坐标；统一使用 `width-1/height-1` 会缩小已有框。拖边的右、下限也改为相同约定，命中兼容两种边界表示。

## 验证

环境：Windows，`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，`QT_QPA_PLATFORM=offscreen`。沙箱内加载 QtCore DLL 被拒绝，测试使用获准的沙箱外执行。

1. 先加入第一批回归用例、保留修复前源码运行：**30 failed / 64 passed**。失败覆盖四边内侧命中、越界拟合、无效拟合吞事件、越界导入框和右／下拖边上限。
2. 最终专项回归：**106 passed**。包含拟合几何、拟合交互、边编辑三个测试文件；结果见 [focused_regression.log](focused_regression.log)、[focused_regression.xml](focused_regression.xml)。
3. 最终完整画布回归：**497 passed / 1 failed，83 subtests passed**；结果见 [canvas_regression.log](canvas_regression.log)、[canvas_regression.xml](canvas_regression.xml)。唯一失败为 `test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`（179 != 139），此前的 [core_baseline.log](../drag_fix_20261030/regression/core_baseline.log) 和 [core_fixed.log](../drag_fix_20261030/regression/core_fixed.log) 已记录相同测试失败。本次未改动标签缩放代码。

专项用例覆盖四边、0.3/1/2 倍缩放、2/5/10 屏幕像素命中距离、四边薄框真实拖动及撤销、松手越界裁剪、导入越界框、无效拟合回退整体拖动、历史和变更信号。验证通过离屏鼠标事件完成；未进行可见窗口人工体验验收。

复跑命令（PowerShell）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_rectangle_edge_migration.py -q --tb=short --color=no -p no:cacheprovider
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest tests/test_canvas -q --tb=short --color=no -p no:cacheprovider
```

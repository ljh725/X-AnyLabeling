# 矩形预览共边显示实施与验证

2026-11-02，实施分支 `codex/refactor-data-inspector-workflow`，基线 `9a37c547`。源码接入与自动化验证已完成；任务清单中未勾选的 6.1（真实屏幕验收）仍视为未完成，本变更未归档。

## 实际文件

- 新增 `anylabeling/views/labeling/rectangle_preview.py`：矩形四边规范化、同线区间差集、屏幕线宽端点余量与开放路径构建；另有 `PointFitPreview` 单帧快照数据。
- `anylabeling/views/labeling/shape.py::Shape.paint`：新增仅本次调用有效的关键字参数 `outline_path`。`None` 保持原轮廓，空路径描边为空；填充、顶点和选中手柄继续使用完整几何。
- `anylabeling/views/labeling/widgets/point_fit.py`：新增 `_build_point_fit_preview()`；候选改为 RGBA `(220,130,0,255)`、cosmetic 2.0 的完整虚线路径；相同几何不叠画候选轮廓，无效候选保留红色指针反馈。
- `anylabeling/views/labeling/widgets/rectangle_crosshair.py`：提供当前草稿剩余轮廓；有效且不同的拟合预览期间常驻十字线让位，预览结束按原配置恢复。
- `anylabeling/views/labeling/widgets/canvas.py`：每帧只生成一次预览快照，普通 Shape 与 `show_masks` 额外轮廓共用该轮廓；创建十字线移到草稿预览之后、文字信息之前。
- 新增 `tests/test_canvas/test_rectangle_preview_overlap.py`：共边几何、缩放余量、四象限、遮罩、真实画布像素、取消恢复、提交后完整轮廓、数据独立与导出检查。

## 实际命令与结果

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_rectangle_preview_overlap.py -q --tb=short --color=no -p no:cacheprovider
```

结果：**35 passed**。覆盖 0.25/0.5/1/2/4 倍缩放的几何余量，四象限共边，相近但非共线、仅点相交、相同矩形、小框、遮罩开关、常驻线让位、创建引导开关，以及预览/取消/导出前后的像素和数据快照。

另用同一离屏平台生成了深色背景下的拟合与创建渲染图做目视核对：拟合时原框共边只剩橙色候选虚线，非共边白线完整；创建时草稿仅保留非共边两条实线，另两条由青色引导虚线表示。该核对仅用于辅助，不计入 6.1 的真实屏幕验收。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas -q --tb=line --color=no -p no:cacheprovider
```

结果：**578 passed / 1 failed**，失败项为既有 `test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`（`179 != 139`）。该失败在实施前的既有报告和本次改动前运行中均存在，与共边预览无关。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_labeling -q --tb=short --color=no -p no:cacheprovider
```

结果：**192 passed / 8 failed**，失败项均为既有环境/基线问题（Windows 临时文件权限、路径分隔符、既有 mock 契约），数量与 `reports/inspector_workflow_20261102/REPORT.md` 记录的基线一致，未出现与本次画布绘制接入相关的新增失败。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m flake8 anylabeling/views/labeling/rectangle_preview.py anylabeling/views/labeling/shape.py anylabeling/views/labeling/widgets/point_fit.py anylabeling/views/labeling/widgets/rectangle_crosshair.py anylabeling/views/labeling/widgets/canvas.py --max-line-length=79 --select=E9,F63,F7,F82,F401,F811,F841
```

结果：无输出（通过）。`black --check` 已用于新增模块和基线本已干净的 `point_fit.py`、`rectangle_crosshair.py`；`canvas.py` 在基线中即非 black-clean，未整体重排以避免混入无关格式差异。测试文件按项目惯例不纳入 black。

## 未验证

- 6.1 真实屏幕深浅背景验收未执行：本次为离屏渲染与像素采样，不能替代人工可见窗口验收。
- 未重跑 `pytest tests` 全量，未做性能重测；新增计算只遍历当前矩形四边，不读取标注文件。
- 未提交 Git；回退仅撤销上述新增模块、可选接口和接入点，不回退整个共享 `canvas.py`，不涉及用户标注数据。

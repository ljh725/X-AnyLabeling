**审核结论**

暂不建议合并。几何 helper 和测试结构看起来扎实，但 Canvas/UI 集成里有几个会影响真实交互的 bug，需要先修。

**Findings**

1. **P1：从绘制模式开启“矩形边对齐”会导致菜单状态和 Canvas 状态不一致**  
   [label_widget.py](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:7009) 中开启时如果正在绘制会先 `set_edit_mode()`；而 `set_edit_mode()` 调用 [toggle_draw_mode](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:4035)，里面又会在 action 已勾选时取消勾选并关闭 Canvas 边对齐。随后 `toggle_rect_edge_align()` 又把 Canvas 打开。结果是：Canvas 开启了，但菜单 action 显示未勾选。  
   建议：`toggle_draw_mode()` 只在 `edit == False` 进入创建模式时关闭边对齐；不要在切回 edit mode 时清掉 action。

2. **P1：拖动中 active/snap 边的状态色使用旧的 `RectEdgeRef`，视觉反馈会落在旧位置**  
   拖动时 [mouseMoveEvent](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/widgets/canvas.py:998) 会更新 `active.shape.points`，但 `rect_edge_active_edge` 的 `p1/p2/coord` 没有刷新。绘制时 [\_draw_rect_edge_alignment_overlay](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/widgets/canvas.py:4001) 仍用旧 edge 画橙色/绿色线。  
   这会让“实时吸附预览”状态色显示在原始边，而不是当前预览边。建议绘制前根据 `active.shape + active.edge_name` 重新派生当前 edge，或在每次 `apply_edge_coord` 后刷新 `rect_edge_active_edge`。

3. **P2：hover 到矩形边时没有清理既存 `h_hape/h_vertex`，可能残留旧高亮/旧顶点状态**  
   报告说 hover 分支会“清 `h_hape` 影响”，但代码在 [canvas.py](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/widgets/canvas.py:1016) 命中边后直接 `return`，没有清空旧的 `h_hape/h_vertex/h_edge`。如果上一帧 hover 过顶点或其他 shape，旧高亮可能继续影响绘制，甚至让 `selected_vertex()` 状态残留。  
   建议：边 hover 命中后显式清理普通 hover 状态，至少清 `h_hape/h_vertex/h_edge/h_cuboid_face` 并清除旧 shape highlight。

**测试情况**

我尝试复跑 `python -m pytest tests/test_rect_edge_alignment.py`，但当前 shell 默认使用 `C:\Python314`，没有 pytest；再尝试 `conda activate x-anylabeling-cu12` 也失败，提示当前 shell 未配置 conda activate。因此我这边没有复跑成功，报告中的测试结果需要在配置好的 conda 环境里再确认。

**补充观察**

`rect_edge_alignment.py` 的几何层实现整体符合任务文档：两点/四点归一化、同轴兼容、防反转 clamp、规范四点输出都比较清楚。主要问题集中在 UI 状态同步和 Canvas 实时交互显示。修完上面 3 点后，再做一次真实 GUI 手测会比较稳。
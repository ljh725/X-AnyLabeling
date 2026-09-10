## Why

矩形标注需要确定四条边，两点画框将四次判断压缩成两次二维落点，容易引起反复修正；已有框的修正则同时消耗在看清对象、选边、精确移动和重新确认上。需要把新建与修正组织成连续流程，让人表达边界判断，让系统承担坐标约束、固定步进和观察尺度管理。

## What Changes

- 新建框保留普通两点入口，增加专用四极值入口：按上、右、下、左确定边界，临时输入直接生成一个普通矩形，无需创建正式点或手动分组。
- 四极值框在第四次输入后自动提交并选中，允许直接进入单边修正；前置标签缺失时沿用现有标签确认流程。
- 修正框采用显式活动边、1px/5px 单边步进、粗细拖动、清晰反馈以及连续对象切换；复用现有精修组件，补齐行为差异。
- 为已知矩形提供可选的按对象观察尺度；新建前没有目标尺寸时提供以指针为中心的局部聚焦。手动缩放优先，修边期间保持视图稳定。
- 明确取消、撤销、快捷键焦点、无效几何、遮挡与边界不确定性处理；先验证质量和总耗时，再决定是否扩大默认启用范围。

## Capabilities

### New Capabilities

- `rectangle-extreme-creation`: 四极值临时输入、逐边预览、回退、提交及普通矩形兼容。
- `rectangle-refinement-workflow`: 新建后的修正与已有框修正的统一活动边、步进、撤销和切换契约。
- `rectangle-observation-workflow`: 新建定位与已有对象观察、稳定视图、上下文保留及不确定性边界。

### Modified Capabilities

无。上述能力尚无同名主规格；已有未归档变更的精修契约作为实现依赖，不重复创建底层算法。

## Impact

- 画布输入与绘制：`anylabeling/views/labeling/widgets/canvas.py`。
- 标签、动作、快捷键、视图与切图：`anylabeling/views/labeling/label_widget.py`。
- 复用 `rect_edge_alignment.py`、`rect_edge_interaction.py`、`review_refinement/` 及现有 viewport 生命周期组件。
- 新增独立的四极值草稿控制器；不新增持久化 shape_type，不把临时极值点或观察参数写入标注 JSON。
- 设置与翻译沿用现有机制；新增入口独立开关，普通两点画框维持默认行为。
- 依赖协调：`optimize-rectangle-review-refinement-workflow` 的单边步进、精修增益、反馈和撤销；`formalize-viewport-state-machine` 的视图状态契约。实施前建立未完成任务对照，避免重复交付和互相覆盖。
- 本次交付为设计与实施计划，不修改应用代码、不改变当前运行配置。

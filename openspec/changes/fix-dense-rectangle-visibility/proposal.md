## Why

密集检测结果中大量矩形轮廓、标签和 GID 同时绘制，仍会形成无法辨认的视觉网格。现有 Focus 外观已经提供弱化基础，但用户配置的无关对象透明度没有贯穿聚焦控制器和全部绘制通道，也缺少同组隔离与几何重复框识别，因此需要一次聚焦修复。

## What Changes

- 接通 `annotation_appearance.unrelated_opacity`，由用户配置决定 Focus 模式下无关对象的实际透明度，并保持显示设置不进入标注 JSON、dirty 或 undo。
- 建立统一的画布渲染门控；当无关对象透明度为零或临时隔离启用时，矩形、标签、GID 和普通尺寸覆盖层共同跳过绘制。
- 新增瞬态“隔离选中对象/同组对象”模式：有效单组选择显示同 GID 对象，混合组或无 GID 选择只显示正式选中对象，并定义清空选择、切图、删除和模式切换时的退出规则。
- 统一普通标签与外观标签/GID 的可见性语义，防止几何轮廓被隐藏后文字覆盖层仍残留。
- 新增只读的矩形几何重复质检，基于 label、group_id、坐标差和 IoU 产生 error/warning，并通过 Inspector 导航复核；不自动删除或写回标注。
- 补充纯 Python、Qt offscreen、像素/截图和密集场景性能测试，覆盖配置边界、绘制门控、隔离生命周期、覆盖层一致性和重复框误报边界。

## Capabilities

### New Capabilities

- `dense-rectangle-focus-isolation`: 定义密集矩形场景中的可配置弱化、零透明度跳过绘制、统一覆盖层门控及选中/同组瞬态隔离行为。
- `duplicate-rectangle-quality-check`: 定义基于几何重合度的只读重复矩形检测、严重度、排除条件、报告和人工复核契约。

### Modified Capabilities

- 无。

## Impact

- 聚焦与外观策略：`anylabeling/views/labeling/widgets/appearance/`、`widgets/appearance_qt.py`。
- 画布绘制与交互：`widgets/canvas.py`、`shape.py`、`label_widget.py`、设置 schema/runtime applier、快捷键与翻译资源。
- 质检：`widgets/inspector/quality/`、质量规则注册、报告输出、质检复核队列与阈值配置。
- 测试：外观策略、Canvas offscreen、隔离交互、标签/GID覆盖层、IoU规则、输出稳定性和密集场景性能。
- 本变更是 `optimize-annotation-visual-encoding-and-label-batch-operations` 的聚焦修复；实施前须核对其未完成的绘制优先级、像素测试和本地化任务，避免重复修改或产生冲突。
- 不新增运行时依赖，不改变标注 JSON 格式，不自动删除重复框。

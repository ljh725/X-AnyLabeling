# 小目标 Person 矩形实时尺寸显示需求修订 v1

> 状态：需求修订待实现  
> 基于文档：`docs/小目标Person矩形实时尺寸显示功能设计.md`  
> 实现：GLM-5.2  
> Review：Codex  
> 适用范围：仅修订“小目标 person 矩形实时尺寸显示”功能，不扩大到独立模式、
> 复核流程或 JSON 数据结构。

## 1. 修订目的

本修订用于解决三类需求问题：

1. 尺寸数据来源必须与项目现有矩形尺寸计算和唤醒方式保持一致，避免
   浮层另起一套不可复用、不可追踪的数据链路。
2. 浮层位置从“矩形右上角外侧优先”调整为“当前标签上方优先”，减少
   标注员视线跳转，并与现有标签视觉体系对齐。
3. 在 View 视图选项中增加独立功能开关，名称为“显示矩形框像素”，
   开关接线、配置持久化和即时刷新方式必须与项目已有“显示标签”
   功能保持同一模式。

同时，本修订吸收前两轮 Codex Review 发现的缺陷，明确必须修改：

- 直接拖动矩形边时浮层必须实时显示和刷新；
- 浮层位置必须受当前 Canvas 可见区域约束，而不是整张 pixmap；
- 缩放后浮层字体、内边距、间距必须屏幕稳定；
- 新增 UI 文案必须进入 Qt 翻译体系；
- UI 阈值读取不得依赖整份 L1/L2 质检 profile 的完整校验；
- 隐藏或被筛选掉的矩形不得显示浮层。

## 2. 修订优先级

如本修订与原设计文档存在冲突，以本修订为准。

必须按以下优先级实现：

| 优先级 | 内容 | 是否阻塞合入 |
| --- | --- | --- |
| P1 | 尺寸数据统一、直接拖边实时刷新、当前可见区域约束 | 是 |
| P1 | 浮层锚定到标签上方并可回退 | 是 |
| P1 | View 菜单增加“显示矩形框像素”独立开关 | 是 |
| P1 | 隐藏/筛选/多选/切图/取消时浮层消失 | 是 |
| P2 | 缩放下屏幕稳定 | 是 |
| P2 | i18n、窄阈值读取、测试补齐 | 是 |

本功能不接受“测试通过但关键交互缺失”的实现。

## 3. 数据来源修订

### 3.1 统一尺寸数据契约

必须在 `Canvas` 层收敛出一个统一的矩形尺寸解析契约，供以下两个消费方
共同使用：

- 左下角状态栏 `H/W` 显示；
- 小目标 person 尺寸浮层。

禁止状态栏和浮层各自散落实现一套独立 `W/H` 计算逻辑。

建议契约形态如下，具体命名可按仓库风格调整：

```text
RectangleMetrics:
  x_min: float
  y_min: float
  x_max: float
  y_max: float
  width: float
  height: float
  max_edge: float
  label: str | None
  shape: Shape | None
  source: creating | selected | rect_edge_active | vertex_drag | wheel_adjust
```

最低要求：

- 业务阈值判断使用 `max_edge` 的原始 float；
- UI 浮层显示默认保留一位小数；
- 状态栏可继续显示 int `H/W`，但必须来自同一份 metrics 结果；
- metrics 必须基于原图坐标，不得使用屏幕坐标、线宽、缩放倍率、
  QPainter 包围盒或抗锯齿后的视觉结果。

### 3.2 允许复用现有唤醒方式

项目已有尺寸反馈链路：

```text
Canvas.mouseMoveEvent / 几何变更路径
→ Canvas.show_shape(height, width, pos)
→ LabelingWidget.show_shape(...)
→ 状态栏显示 X/Y/H/W
```

本功能必须复用该链路的“唤醒时机”，但不得把状态栏字符串作为浮层数据源。

正确做法：

- 在原来会 `show_shape.emit(...)` 的路径上，改为先生成
  `RectangleMetrics`；
- 状态栏从 metrics 取 int `height/width` 后继续 `show_shape.emit(...)`；
- 浮层从同一 metrics 或同一解析函数取 float `width/height/max_edge`；
- 直接矩形边拖动 `_rect_edge_drag_update()` 也必须进入同一套 metrics
  刷新链路。

禁止做法：

- 禁止浮层解析状态栏文本；
- 禁止在 `LabelingWidget.show_shape()` 中反向驱动 Canvas 浮层；
- 禁止为浮层新增定时器轮询；
- 禁止将 metrics 写入 `Shape.other_data`、正式 JSON 或撤销栈。

### 3.3 创建阶段数据

创建 rectangle 时：

```text
start = self.current[0]
cursor = self.line.points[1] 或当前鼠标图像坐标
metrics = normalize(start, cursor)
```

要求：

- 正向、反向拖动均正确；
- 接近零尺寸时不得报错；
- 创建阶段 label 可为 `None`，因此不得提前显示 person 阈值警告；
- 创建取消后 metrics 清空，浮层消失。

### 3.4 编辑阶段数据

编辑阶段必须覆盖以下来源：

| 场景 | 数据来源 | 是否显示浮层 |
| --- | --- | --- |
| 单选 rectangle 静止 | `selected_shapes[0]` | 是 |
| 单选 rectangle 拖动整体 | 当前选中 shape 更新后 metrics | 是 |
| rectangle 顶点拖动 | 被编辑 shape 更新后 metrics | 是 |
| rectangle 滚轮/键盘尺寸调整 | 调整后的 shape metrics | 是 |
| 直接拖动 rectangle 边 | `rect_edge_active_edge.shape` | 是 |
| rectangle 边 pending 但未跨拖动阈值 | 可显示当前边对应 shape 的静态 metrics；若实现困难，至少不得影响拖动开始后的显示 | 可选 |
| 多选 | 无唯一目标 | 否 |
| 非 rectangle | 非目标类型 | 否 |
| 隐藏或筛选掉 | 不可交互 | 否 |

直接拖边场景是 P1。不得因为 `mousePressEvent` 中调用 `deselect_shape()`
导致浮层消失。

## 4. 可见性与交互约束

浮层目标必须满足：

```text
shape.shape_type == "rectangle"
and Canvas.is_shape_interactive(shape) == True
```

`Canvas.is_shape_interactive(shape)` 至少包含：

- `Canvas.visible[shape]`；
- `shape.visible`；
- `shape.hidden_by_filter`；
- 后续仓库扩展的不可交互状态。

禁止只检查 `shape.visible`。筛选引擎通过 `Canvas.visible[shape] = False`
隐藏对象时，浮层必须消失。

## 5. View 视图开关

### 5.1 功能名称

必须在 View 视图选项中增加一个独立开关。

用户可见名称必须为：

```text
显示矩形框像素
```

英文翻译建议：

```text
Show Rectangle Pixels
```

该名称指当前 rectangle 的原图像素尺寸显示，即本文档中的尺寸浮层。

### 5.2 接线模式

“显示矩形框像素”必须采用与项目已有“显示标签 / Show Labels”相同的
功能设定模式。

现有“显示标签”模式包含：

```text
配置项: show_labels
View 菜单 checkable action
action checked 状态来自 _config
切换时调用 set_canvas_params(...)
Canvas 上存在同名或等价 bool 状态
切换后立即 canvas.update()
配置写入用户配置并在下次启动恢复
```

新开关必须采用同类模式。建议命名：

```text
配置项: show_rectangle_pixels
Canvas 状态: canvas.show_rectangle_pixels
View action 文案: 显示矩形框像素
```

具体内部命名可按仓库风格调整，但必须满足：

- action 是 checkable；
- checked 初始值来自 `_config`；
- 切换后更新 `_config`；
- 切换后同步到 `Canvas`；
- 切换后立即刷新画布；
- 用户配置可持久化；
- 默认值与“显示标签”同级定义在 `xanylabeling_config.yaml`；
- 默认启用值为 `true`，与现有 `show_labels: true` 的默认启用策略一致；
- View 菜单位置应与“显示标签 / Show Labels”相邻，便于用户发现；
- 如增加快捷键配置，必须放入现有 shortcuts 配置体系，不得硬编码。

### 5.3 开关行为

当“显示矩形框像素”开启时：

- 按本文档规则显示 rectangle 像素尺寸浮层；
- person 小目标阈值警告正常生效；
- 状态栏 `X/Y/H/W` 继续保持原有行为。

当“显示矩形框像素”关闭时：

- 不绘制尺寸浮层；
- 不绘制 person 小目标警告文案、警告色或警告边框；
- 不影响状态栏 `X/Y/H/W`；
- 不影响矩形绘制、选择、拖边、保存、撤销、删除；
- 不影响 `show_labels` 的显示状态。

### 5.4 与显示标签的关系

“显示矩形框像素”和“显示标签”是两个独立开关。

必须禁止：

- 禁止复用 `show_labels` 布尔值作为尺寸浮层开关；
- 禁止关闭“显示标签”时强制关闭“显示矩形框像素”；
- 禁止开启“显示矩形框像素”时强制开启“显示标签”；
- 禁止把尺寸浮层状态写入 label 显示模式。

但两者必须采用同一类功能设定方式：View 菜单 action、配置项、Canvas
bool 状态、即时刷新、用户配置持久化。

当 `show_labels == False` 且 `show_rectangle_pixels == True` 时，标签框
不可作为锚点，浮层必须按“标签不可用时的回退顺序”定位。

### 5.5 i18n

新增 View 菜单文案必须进入 Qt 翻译体系。

禁止直接硬编码未包装中文：

```text
显示矩形框像素
```

应使用项目现有 action 文案翻译方式，例如 `self.tr(...)`。

## 6. 浮层位置修订

### 6.1 新默认锚点：标签上方

编辑阶段，浮层默认锚定到当前 shape 标签框的上方。

定义：

```text
label_rect = 现有标签绘制逻辑计算出的标签背景框
overlay.bottom = label_rect.top - gap
overlay.horizontal_anchor = label_rect.left
```

如左对齐导致越界，可尝试：

1. 与 `label_rect.left` 左对齐；
2. 与 `label_rect.center_x` 居中；
3. 与 `label_rect.right` 右对齐；
4. 限制到当前 Canvas 可见区域内。

标签上方位置不得遮盖标签文本本身。

### 6.2 标签不可用时的回退顺序

以下情况认为标签不可用：

- 创建阶段还没有正式 shape 标签框；
- `show_labels == False`；
- label 文本为空；
- 当前 label 显示模式不绘制该 shape 的标签；
- 该标签框被当前可见区域完全裁掉；
- label rect 计算失败。

标签不可用时，按以下顺序回退：

1. 矩形上方外侧；
2. 矩形上方内侧；
3. 矩形左上角外侧；
4. 矩形左上角内侧；
5. clamp 到当前 Canvas 可见区域内。

原设计中的“矩形右上角外侧优先”不再作为编辑阶段默认策略。

### 6.3 复用标签布局计算

实现必须尽量复用 `canvas.py` 中现有标签绘制 pass 的标签文本、字体、
padding、`bbox`、`rect` 和 `text_pos` 计算规则。

禁止复制一份与标签绘制逻辑不一致的“近似 label rect 算法”。

如需要抽取 helper，应保证：

- 标签绘制和浮层锚点使用同一 helper 输出的 `label_rect`；
- 不改变现有标签绘制视觉；
- 不改变 `label_display_mode`、`label_on_selection`、score、group_id、
  attributes 合并显示的既有语义。

## 7. 当前 Canvas 可见区域

浮层位置限制必须使用当前 Canvas 可见区域，不能使用整张 pixmap。

当前可见区域定义为 paint 坐标系下的图像可见矩形：

```text
offset = self.offset_to_center()
visible_x_min = -offset.x()
visible_y_min = -offset.y()
visible_width = self.width() / self.scale
visible_height = self.height() / self.scale
visible_rect = QRectF(visible_x_min, visible_y_min, visible_width, visible_height)
```

要求：

- `visible_rect` 应与 `paintEvent` 中已有 culling viewport 一致；
- `visible_rect` 应与 pixmap 范围取交集；
- 浮层 clamp 必须基于该交集；
- 缩放、平移、fit width、fit window 后均不得完全移出当前可见区域。

禁止使用：

```text
(0, 0, pixmap.width(), pixmap.height())
```

作为“当前可见区域”的替代。

## 8. 缩放稳定性

浮层字体、边距、圆角、边框宽度、与标签/矩形之间的 gap 必须保持屏幕
像素稳定。

允许两种实现路线：

### 路线 A：在控件坐标系绘制

1. 将图像坐标的 anchor 映射到 widget/screen 坐标；
2. `painter.save()`；
3. `painter.resetTransform()` 或使用不带画布 scale 的 painter 状态；
4. 使用固定屏幕像素绘制浮层；
5. `painter.restore()`。

### 路线 B：在图像坐标系绘制但严格反缩放

若继续在图像坐标系绘制，所有 screen px 常量必须除以当前 scale，且不得
再用会破坏稳定性的最小值钳制。

禁止出现如下效果：

```text
scale = 4
font_size 被 max(..., 6) 钳制为 6
实际屏幕字体约 24 px
```

此类实现不合格。

## 9. 文案与 i18n

新增 UI 文案必须走 Qt 翻译体系。

要求：

- 使用 `self.tr(...)` 或 `QCoreApplication.translate(...)`；
- 不得硬编码中文字符串直接进入 painter 文本；
- 文案格式中的动态数值通过 `%` 或 `.format()` 注入；
- 如项目要求更新 `.ts/.qm`，按项目语言资源流程处理。

建议文案：

```text
W %.1f px  H %.1f px
最大边 %.1f px < %g px
```

英文翻译建议：

```text
W %.1f px  H %.1f px
Max edge %.1f px < %g px
```

## 10. 阈值读取修订

`person_small_target.min_edge_px` 可以继续放在：

```text
anylabeling/configs/quality/l1_l2_threshold_profile_v0.yaml
```

但 UI 读取该值时不得依赖整份 L1/L2 `rules` 的完整校验。

必须满足：

- 读取 `person_small_target.min_edge_px` 只校验该配置块本身；
- 无关 QA 规则配置错误不得导致 UI 阈值静默回退；
- `min_edge_px` 缺失、非数字、非有限值、`<= 0` 时才回退到默认值；
- 回退时记录 warning 日志；
- 默认值仍为 `36.0`。

允许实现：

- 在纯 Python quality 配置模块中新增窄接口；
- 或在更靠近 UI/Canvas 配置的位置定义小目标阈值读取 helper。

禁止实现：

- `LabelingWidget` 为读一个 UI 阈值调用完整 `load_threshold_profile()`
  并校验所有 L1/L2 规则；
- 宽泛 `except Exception` 吞掉所有配置错误后无条件回退，且无可诊断信息。

## 11. 前两轮 Review 缺陷修复清单

GLM 必须逐项修复并补测试。

| 编号 | 缺陷 | 修改要求 | 验收 |
| --- | --- | --- | --- |
| R1 | 直接拖边时浮层消失 | resolver 支持 `rect_edge_active_edge.shape`，拖边更新后刷新 metrics | 拖动 left/right/top/bottom 任意边时浮层存在且 W/H 更新 |
| R2 | 使用整张 pixmap 当 viewport | 使用当前 Canvas 可见区域并与 pixmap 相交 | zoom/pan 后靠近视口边缘不出屏 |
| R3 | 隐藏状态遗漏 | 使用 `is_shape_interactive()` | `Canvas.visible=False`、`shape.visible=False`、`hidden_by_filter=True` 均不显示 |
| R4 | 缩放后浮层变大 | 控件坐标绘制或严格反缩放 | scale 0.25/1/4 下字体、padding、gap 屏幕尺寸稳定 |
| R5 | UI 文案未翻译 | 所有浮层文本走 Qt 翻译 | 搜索不到硬编码未包装中文 UI 文案 |
| R6 | 阈值读取耦合 QA profile | 提供窄读取接口 | 无关 QA rule 无效时，UI 阈值仍可读取 person block |
| R7 | 浮层位置不符合新需求 | 默认标签上方，失败后按修订 fallback | 标签可见时浮层在标签上方 |
| R8 | 缺少 View 功能开关 | 增加“显示矩形框像素”独立 checkable action，并按 Show Labels 同模式持久化 | 关闭后浮层完全不绘制，状态栏和标签显示不受影响 |

## 12. 测试要求

必须新增或调整测试覆盖以下内容。

### 12.1 纯函数测试

- 正向、反向两点 bbox；
- 四点 rectangle bbox；
- float 尺寸；
- `35.9/36.0/36.1` 阈值边界；
- 非 person 不触发小目标警告；
- label rect 上方锚点；
- 标签上方空间不足时 fallback；
- 当前可见区域 clamp。

### 12.2 Canvas 状态测试

- 无选择、创建中、单选、多选、非 rectangle；
- `Canvas.visible[shape] = False`；
- `shape.visible = False`；
- `shape.hidden_by_filter = True`；
- `rect_edge_active_edge.shape` 直接拖边；
- 创建取消、切图、清空 shapes 后浮层消失。

### 12.3 View 开关测试

必须覆盖：

- 默认配置能初始化 `canvas.show_rectangle_pixels`；
- View 菜单存在“显示矩形框像素” checkable action；
- 关闭开关后不绘制尺寸浮层；
- 关闭开关不影响 `show_labels`；
- 关闭 `show_labels` 不影响 `show_rectangle_pixels`；
- 配置持久化路径与“显示标签”同模式；
- 切换开关后立即刷新 Canvas。

### 12.4 缩放测试

至少验证：

```text
scale = 0.25
scale = 1.0
scale = 4.0
```

同一矩形下：

- 显示 W/H 数值一致；
- 业务阈值结果一致；
- 浮层字体/padding/gap 的屏幕像素尺寸保持稳定。

### 12.5 集成/回归测试

必须保留并通过：

```powershell
pytest tests/test_size_overlay.py -q
pytest tests/test_rect_edge_canvas_semantics.py -q
pytest tests/test_canvas_interaction.py -q
pytest tests/test_quality_thresholds.py -q
```

若 PyQt6 在沙箱内因 DLL 权限失败，按项目 AGENTS 规则在沙箱外使用
`QT_QPA_PLATFORM=offscreen` 重跑同一命令。

## 13. 非目标与禁止项

本修订仍禁止：

- 新增“小目标 Person 模式”；
- 弹出确认对话框；
- 阻止保存小于阈值的 person；
- 自动删除、自动撤销或自动修正标注；
- 修改数字快捷键、label、group_id 分配规则；
- 修改导航器；
- 修改保存 JSON schema；
- 将浮层状态写入 undo stack、dirty、Shape、JSON；
- 用 `show_labels` 代替“显示矩形框像素”独立开关；
- 大范围重构 Canvas 绘制顺序；
- 修改与本功能无关的筛选、质检、自动标注逻辑。

## 14. 实现交付要求

GLM 完成后必须提供：

1. 修改文件列表；
2. 每个 Review 缺陷编号 R1-R8 的修复说明；
3. 新增/修改测试列表；
4. 本地测试命令与结果；
5. 未完成项说明，未完成 P1/P2 项不得标记为可合入。

Codex Review 将按本文档逐项检查，不再只按原设计文档验收。

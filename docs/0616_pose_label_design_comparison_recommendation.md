# Pose 关键点标签显示设计文档对比与建议

> 对比文档：
> - `docs/0616_html_to_pyqt6_conversion_plan.md`
> - `docs/superpowers/specs/2026-06-16-pose-keypoint-label-display-design.md`
>
> 日期：2026-06-16

## 1. 结论摘要

两个文档目标一致，都是将 `html-case/0616_code.html` 中的 Pose 关键点标签防遮挡原型迁移到 X-AnyLabeling 的 PyQt6 画布体系中。

核心差异在于实施路径：

- `0616_html_to_pyqt6_conversion_plan.md` 更偏向“HTML 原型到 PyQt6 的迁移路线图”，强调先做独立 PyQt 原型，再逐步集成。
- `2026-06-16-pose-keypoint-label-display-design.md` 更偏向“产品化架构设计”，主张跳过独立原型窗口，直接以纯模块接入现有 `Canvas`。

建议采用第二个文档作为主实施蓝图，同时吸收第一个文档中的迁移映射、现有架构分析和风险清单。

## 2. 两个文档的相同点

两者都围绕同一个 HTML 原型展开，目标功能基本一致：

- 支持三种标签布局模式：`direct`、`anti`、`column`
- 支持两种着色模式：按人体部位、按 person/group
- 支持 bbox、骨骼连线、中线参考、关键点、标签、引线绘制
- 支持标签背景色、字体颜色、透明度、文字阴影、颜色预设
- 支持遮挡检测或遮挡高亮
- 最终都认为长期归宿应当是主 `Canvas` 的 Pose 渲染 pass，而不是停留在独立 HTML 或独立 demo 中

换句话说，两个文档在“要做什么”上基本一致，分歧主要在“怎么落地”。

## 3. 两个文档的主要不同点

### 3.1 文档定位不同

`0616_html_to_pyqt6_conversion_plan.md` 是迁移型文档。它关注：

- HTML 界面结构如何映射到 PyQt6 控件
- CSS 变量如何映射到项目主题 token
- JS 数据结构如何转换为 Python 数据结构
- HTML canvas 渲染流程如何转换为 QPainter 绘制流程
- HTML 交互如何复用现有 `Canvas` 交互

它更像一份“从原型到 Qt 的翻译说明书”。

`2026-06-16-pose-keypoint-label-display-design.md` 是架构型文档。它关注：

- 新模块如何划分：`pose_constants.py`、`pose_config.py`、`pose_layout.py`、`pose_renderer.py`
- `PoseDisplayConfig` 如何承载所有配置
- `PoseRenderer` 如何接入 `Canvas.paintEvent`
- Dock 面板如何读写同一个配置对象
- 配置如何持久化
- 单元测试和手动验收如何设计

它更像一份“可以直接开工的产品化设计”。

### 3.2 实施路径不同

`0616_html_to_pyqt6_conversion_plan.md` 推荐分阶段混合路线：

```text
HTML 原型
    ↓
Phase 0：独立 PyQt 原型窗口
    ↓
Phase 1：提取可复用渲染器
    ↓
Phase 2：接入主 Canvas
    ↓
Phase 3：持久化与打磨
```

优点是风险低，可以先验证 QPainter 视觉还原效果。

缺点是会产生第二套画布逻辑，后续还需要迁移到真实 `Canvas`，容易出现重复工作。

`2026-06-16-pose-keypoint-label-display-design.md` 推荐直接产品化路线：

```text
HTML 原型
    ↓
pose_label 纯模块
    ↓
PoseRenderer
    ↓
Canvas 直接集成
    ↓
Dock / 配置 / 测试
```

优点是架构干净，最终代码路径更短，也更容易测试。

缺点是初期就要触碰主画布，集成风险更集中。

### 3.3 模块边界不同

`0616_html_to_pyqt6_conversion_plan.md` 的 Phase 0 会新增：

```text
anylabeling/views/labeling/widgets/pose_label_prototype/
```

这个目录主要用于独立复刻 HTML 原型，包括独立窗口、独立画布、独立左右面板。

`2026-06-16-pose-keypoint-label-display-design.md` 则新增：

```text
anylabeling/views/labeling/widgets/pose_label/
```

该目录直接面向正式功能，内部模块按照数据、配置、布局、渲染、设置面板拆分。

从长期维护角度看，`pose_label/` 方向更清晰，因为它不会保留一套临时 demo 画布。

## 4. 设计方向差异

### 4.1 HTML 转换方案：原型保真优先

`0616_html_to_pyqt6_conversion_plan.md` 的核心思路是先确保 HTML 原型能被完整翻译到 PyQt6。

它更重视：

- 视觉 1:1 还原
- UI 结构还原
- 原型交互还原
- 风险隔离
- 渐进式迁移

这种路线适合需求仍不稳定、视觉效果还没有完全确认、或者团队需要先看一个 Qt demo 再决定是否集成的情况。

### 4.2 Pose 显示重构设计：产品集成优先

`2026-06-16-pose-keypoint-label-display-design.md` 的核心思路是直接把功能作为正式能力落到现有标注工作流中。

它更重视：

- 模块化
- 可测试性
- 配置持久化
- 主 `Canvas` 复用
- 与现有 `Shape`、缩放、拖拽、保存逻辑集成

这种路线适合视觉方案已经确认、目标是尽快进入真实标注流程的情况。

## 5. 我的建议

建议以 `2026-06-16-pose-keypoint-label-display-design.md` 作为主设计，不再完整实现 Phase 0 独立原型窗口。

原因如下：

1. 项目已经有真实 `Canvas`、真实 `Shape`、真实缩放/拖拽/选择/保存逻辑，独立原型窗口会重复这些能力。
2. 最终目标是主画布集成，先做独立原型会多一次迁移成本。
3. 第二个文档已经把模块边界、配置结构、渲染流程和测试策略定义得更清楚。
4. `pose_layout.py`、`pose_config.py`、`pose_renderer.py` 可以先独立测试，不一定需要完整 prototype window 才能验证。

但第一个文档不应废弃。建议把其中以下内容合并或引用到主设计中：

- HTML → PyQt6 控件映射
- CSS 变量 → 项目主题 token 映射
- JS 数据 → Python/Shape 数据映射
- 现有 PyQt6 架构分析
- 风险与挑战清单
- 交互映射说明

## 6. 推荐落地路径

建议采用一个折中但更直接的路径：

```text
M1：实现 pose_constants.py / pose_config.py
    ↓
M2：实现 pose_layout.py，并做单元测试
    ↓
M3：实现 pose_renderer.py，用最小绘制验证布局、颜色、遮挡计数
    ↓
M4：在 Canvas 中接入关闭默认的 pose_view 开关
    ↓
M5：增加菜单开关和配置持久化
    ↓
M6：实现设置面板和颜色面板
    ↓
M7：补齐 i18n、手动验收、代码质量检查
```

这里的关键点是：不做完整独立原型窗口，但可以为 `PoseRenderer` 做最小验证 harness 或单元测试，用来确认 QPainter 输出、布局和遮挡计数。

## 7. 开工前建议修正的设计点

### 7.1 Dock 集成方式需要确认

`2026-06-16-pose-keypoint-label-display-design.md` 中写到在 `LabelingWidget.__init__` 中调用 `addDockWidget()`。

但 `0616_html_to_pyqt6_conversion_plan.md` 中提到当前实际 UI 主要在 `LabelingWidget` 中构建，且可能没有使用 `QMainWindow` 的 dock 系统。

因此开工前需要确认：

- `LabelingWidget` 是否继承自 `QMainWindow`
- 如果不是，是否应该把 Dock 加到外层 `QMainWindow`
- 或者复用现有左右侧 `QFrame` 面板，而不是强行使用 `QDockWidget`

这个点不确认，后面 UI 集成可能会返工。

### 7.2 字号与缩放语义需要统一

当前设计里有一个潜在冲突：

- 验收清单希望“缩放时标签字号视觉恒定”
- 渲染流程草案中可能使用 `painter.scale(scale, scale)`，这会让字号随画布缩放变化

建议明确采用：

- 关键点坐标、bbox、骨骼、引线位置使用图像坐标
- 标签字号、标签 padding、边框宽度尽量使用屏幕像素恒定

这样标注员在缩放图片时，标签不会变得过大或过小，可读性更稳定。

### 7.3 旧标签渲染路径需要明确覆盖规则

Pose View 启用后，应明确跳过普通 point 标签渲染，否则会出现重复标签。

建议规则是：

- `pose_config.enabled == False`：完全走现有标签渲染路径
- `pose_config.enabled == True` 且存在 COCO keypoint：Pose keypoint 由 `PoseRenderer` 接管
- 非 pose 图形如 rectangle、polygon、line 是否仍绘制标签，需要单独明确

## 8. 最终推荐

最终建议：

```text
以第二个文档作为主实施蓝图；
以第一个文档作为迁移参考和风险补充；
跳过完整独立原型窗口；
保留小范围 renderer 验证；
优先把核心能力做成可测试的纯模块；
最后再做 UI 面板和持久化。
```

这样既避免 prototype 代码变成临时负担，也不会丢失 HTML 转 PyQt6 文档中对视觉、交互和主题映射的细节价值。

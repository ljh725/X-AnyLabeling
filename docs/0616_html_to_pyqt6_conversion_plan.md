# Pose 标签防遮挡原型 —— HTML 转 PyQt6 转换方案

> 源文件：`html-case/0616_code.html`
> 目标框架：PyQt6（X-AnyLabeling 项目）
> 创建时间：2026-06-16

## 一、HTML 原型功能清单

该 HTML 是一个 **Pose（人体姿态）关键点标签防遮挡** 原型工具，核心功能包括：

### 1.1 界面结构

| 区域 | 宽度/位置 | 内容 |
|------|----------|------|
| 顶部工具栏 | 全宽 | 品牌标题、工具切换（选择/加点）、提示文字 |
| 左侧面板 | 230px | 布局模式、着色模式、显示参数滑块、显示选项、遮挡统计 |
| 中央画布 | 自适应 | 基于 `<canvas>` 自定义渲染：背景、关键点、骨骼、标签、引线 |
| 右侧面板 | 240px | 标签文字颜色、部位颜色、目标颜色、颜色预设、属性面板 |
| 底部状态栏 | 全宽 | 翻转 P1、添加 Person3、重置、状态文字 |

### 1.2 数据模型

- **关键点定义（P17）**：COCO 风格 17 个关键点，分组为 `head`、`la`（左上肢）、`ra`（右上肢）、`ll`（左下肢）、`rl`（右下肢）
- **骨骼连线（SKEL）**：16 条骨骼边
- **颜色映射**：
  - 部位颜色 `BCOL`：head、la、ra、ll、rl
  - 目标颜色 `PCOLS`：每个 person 一个主色
  - 颜色预设 `PRESETS`：default、pastel、neon、earth
- **标注数据 `anns`**：混合 `rect`（目标框）和 `pt`（关键点），通过 `pi`（person index）分组

### 1.3 渲染逻辑

1. 合成背景（网格、天空、地面）
2. 按 person 分组绘制：
   - 目标框（bbox）
   - 中线参考（midline）
   - 骨骼连线（skeleton）
   - 关键点（keypoint）
   - 标签布局 + 引线 + 遮挡高亮
3. 叠加显示：缩放比例、实时参数

### 1.4 三种标签布局模式

| 模式 | 说明 |
|------|------|
| `direct`（方向引线） | 沿关键点方向直接放置标签 |
| `anti`（防遮挡） | 沿方向逐步外移，避免标签互相重叠 |
| `column`（侧栏列表） | 按关键点在人体左右/顶部位置分栏，垂直堆叠 |

### 1.5 交互

- 工具切换：选择/拖动 vs 添加关键点
- 鼠标拖拽关键点
- 中键平移画布
- 滚轮缩放
- 底部按钮：翻转 P1、添加 Person3、重置
- 滑块/颜色选择器实时更新渲染

---

## 二、项目现有 PyQt6 架构分析

### 2.1 主窗口

- `anylabeling/views/mainwindow.py`：仅将 `LabelingWrapper` 包装为 `QMainWindow`
- 实际 UI 在 `anylabeling/views/labeling/label_widget.py`（`LabelingWidget`）中构建
- 当前布局：左侧垂直 `ToolBar` + 中央 `QScrollArea`/`Canvas` + 右侧手写的 `QFrame` 面板
- **没有使用 `QMainWindow` 的 dock 系统**，但可以扩展

### 2.2 画布系统

- `anylabeling/views/labeling/widgets/canvas.py`
- 普通 `QWidget`，在 `paintEvent` 中用 `QPainter` 绘制所有内容
- 已支持：缩放（`scale`）、平移（通过外层 `QScrollArea`）、滚轮缩放、图形选择、顶点拖动
- 已有标签渲染逻辑，并且存在 `layout_keypoint_labels` 防遮挡标签布局

### 2.3 关键点相关模块

| 文件 | 作用 |
|------|------|
| `anylabeling/views/labeling/widgets/keypoint_label_layout.py` | 防遮挡标签布局算法 |
| `anylabeling/views/labeling/widgets/keypoint_fill_mode.py` | COCO 关键点顺序、填充模式 |
| `anylabeling/views/labeling/widgets/keypoint_tool_window.py` | 关键点补全浮动窗口 |
| `anylabeling/views/labeling/label_converter.py` | Pose 格式读写 |

### 2.4 主题与样式

- `anylabeling/views/labeling/utils/theme.py`：`get_theme()` / `get_mode()`
- `anylabeling/views/labeling/utils/style.py`：`get_panel_style()`、`get_dock_style()`、`get_checkbox_indicator_style()` 等
- 现有暗黑主题色板与原型的 CSS 变量高度匹配

---

## 三、HTML → PyQt6 元素映射

### 3.1 UI 组件映射

| HTML 元素 | PyQt6 对应 | 备注 |
|-----------|-----------|------|
| `.top-bar` | `QToolBar` 或 `QHBoxLayout` + `QFrame` | 集成到主程序时放在现有工具栏上方 |
| `.lp` / `.rp` 侧栏 | `QScrollArea` + `QVBoxLayout` + `QFrame` 卡片 | 复用 `get_panel_style()` |
| `.ps` 面板区块 | `QFrame` + `QVBoxLayout` + `QLabel` 标题 | 底部边框和标题样式 |
| `input[type="range"]` | `QSlider` + `QLabel` 数值显示 | `valueChanged` 触发重绘 |
| `input[type="radio"]` | `QButtonGroup` + `QRadioButton` | 每组建一组 |
| `input[type="checkbox"]` | `QCheckBox` | 复用 checkbox indicator QSS |
| `input[type="color"]` | `QPushButton` 颜色块 + `QColorDialog` | 点击弹出取色器 |
| `.collapsible` | `QGroupBox`（可折叠）或 `QToolButton` + 动画容器 | `QGroupBox` 最简单 |
| `.ca` canvas | 自定义 `QWidget` 子类 `paintEvent` | 原型阶段独立实现；集成阶段扩展现有 `Canvas` |
| `.zi` 缩放指示器 | `QLabel` 覆盖层 或 `paintEvent` 直接绘制 | |
| `.dp` 实时参数 | `QLabel` 覆盖层 或 `paintEvent` 直接绘制 | |
| `.bb` 底部栏 | `QStatusBar` + `QHBoxLayout` | 主窗口已有状态栏 |
| `.tbtn` 工具按钮 | `QToolButton`（`checkable=True`）或 `QAction` | 复用 toggle button 样式 |
| `.ab` 动作按钮 | `QPushButton` | 复用现有按钮样式 |

### 3.2 CSS 变量 → 项目主题 Token

| 原型 CSS 变量 | 值 | 项目 Token 建议 |
|--------------|-----|----------------|
| `--bg` | `#1e1e2e` | `theme["background"]` |
| `--panel` | `#252536` | `theme["background_secondary"]` |
| `--hover` | `#2e2e44` | `theme["background_hover"]` |
| `--bd` | `#3a3a52` | `theme["border"]` |
| `--tx` | `#cdd6f4` | `theme["text"]` |
| `--dm` | `#7f849c` | `theme["text_secondary"]` |
| `--ac` | `#89b4fa` | `theme["primary"]` |
| `--dg` | `#f38ba8` | `theme["error"]` |
| `--wn` | `#fab387` | `theme["warning"]` |
| `--ok` | `#a6e3a1` | `theme["success"]` |

### 3.3 JS 数据 → Python

| JS 结构 | Python 等价 |
|--------|-------------|
| `P17` 数组 | `list[KeypointDef]` dataclass 或 dict |
| `SKEL` | `list[tuple[int, int]]` |
| `BCOL` / `PCOLS` | `dict[str, QColor]` / `list[QColor]` |
| `PRESETS` | `dict[str, dict[str, QColor]]` |
| `anns` | 复用现有 `Shape`：一个 rectangle（label=person，group_id=pi）+ 多个 point（group_id=pi） |
| `selId` | `Shape.selected` 或单独 `selected_shape` |
| `zm`, `ppx`, `ppy` | 现有 `Canvas.scale`、偏移计算 |
| `tool` | 现有 `EDIT` 模式 / `create_mode="point"` |

### 3.4 渲染逻辑 → QPainter 绘制流程

1. `p.fillRect()` 绘制合成背景
2. 按 person 分组：
   - 计算中线 `mid`
   - 绘制目标框 `p.drawRect()`
   - 绘制中线虚线 `p.drawLine()` + `setDashPattern()`
   - 绘制骨骼 `p.drawLine()`
   - 绘制关键点 `p.drawEllipse()` / `p.drawRect()`，选中项加虚线光环
   - 标签布局计算后，绘制引线 `p.drawLine()`、圆角标签矩形、文字阴影、文字
3. 叠加层：缩放比例、实时参数

### 3.5 交互映射

| HTML 交互 | Qt 对应 |
|-----------|---------|
| `mousedown` / `mousemove` 拖拽 | `Canvas.mousePressEvent` / `mouseMoveEvent` + `bounded_move_vertex()` |
| 中键平移 | 现有 `prev_pan_point` 或 `QScrollArea` 平移 |
| 滚轮缩放 | `Canvas.wheelEvent` → `zoom_request` |
| 工具切换 | `LabelingWidget.toggle_draw_mode()` |
| 添加点 | `create_mode="point"` |
| 右键菜单 | 现有 `Canvas.menus` |
| 底部按钮 | 修改 `Canvas.shapes` 后调用 `update()` |
| 滑块/颜色实时更新 | `valueChanged` / `colorSelected` → 更新模型 → `update()` |

---

## 四、集成策略选项

| 方案 | 优点 | 缺点 |
|------|------|------|
| **A. 独立原型窗口** | 最快、无风险、1:1 复刻 HTML 行为 | 不编辑真实标注，会重复画布逻辑 |
| **B. 新 Dock + 现有 Canvas 渲染Pass** | 复用真实 Shape 数据、缩放、保存 | 需小心修改 `Canvas.paintEvent` |
| **C. 替换主画布模式** | 集成最深 | 风险最高，与现有编辑模式冲突 |
| **D. 新建独立模块** | 干净、可从菜单启动、易迭代 | 与 A 类似，后期再合并 |

### 推荐方案：分阶段混合

1. **Phase 0 — 独立原型模块**：在 `anylabeling/views/labeling/widgets/pose_label_prototype/` 下用 `QDialog`/`QWidget` 完整复刻，验证 QPainter 渲染、布局和样式。
2. **Phase 1 — 提取可复用渲染器**：将布局算法补充到 `keypoint_label_layout.py`，提取 `PoseRenderer`。
3. **Phase 2 — 接入主 Canvas**：在 `Canvas.paintEvent` 增加 Pose 渲染开关， suppressed 通用点标签，新增设置 Dock。
4. **Phase 3 — 持久化与打磨**：配置保存、i18n、颜色预设、测试。

---

## 五、推荐文件结构

### Phase 0（独立原型）

```
anylabeling/views/labeling/widgets/pose_label_prototype/
├── __init__.py
├── pose_window.py          # 组装窗口/对话框
├── pose_canvas.py          # 自定义 QWidget 画布
├── pose_toolbar.py         # 顶部工具栏
├── pose_settings_panel.py  # 左侧面板
├── pose_color_panel.py     # 右侧面板
├── pose_layout_engine.py   # 三种布局算法
├── pose_data.py            # P17、SKEL、颜色预设
└── utils.py                # 亮度、自动文字颜色等辅助
```

### Phase 1-2（集成到主程序）

```
anylabeling/views/labeling/widgets/
├── canvas.py                      # 增加 pose 渲染开关
├── keypoint_label_layout.py       # 增加 direct / column 布局
├── pose_settings_dock.py          # 设置面板 Dock
├── pose_color_dock.py             # 颜色面板 Dock
└── pose_label_prototype/          # 保留为沙盒
```

---

## 六、可复用资产

| 现有文件 | 复用点 |
|----------|--------|
| `canvas.py` | 缩放、平移、选择、拖拽、滚轮、QPainter 框架 |
| `shape.py` | rectangle / point 图形、group_id、label、selected |
| `keypoint_label_layout.py` | 防遮挡布局算法 |
| `keypoint_fill_mode.py` | COCO 关键点语义 |
| `theme.py` / `style.py` | 暗黑主题、卡片样式、checkbox 样式 |
| `toolbar.py` | 工具栏 |
| `utils/__init__.py` | `new_action()` 等工具 |

---

## 七、风险与挑战

1. **标签重复渲染**：现有 `Canvas` 已会绘制点标签。Pose 模式开启时应跳过通用点标签绘制。
2. **坐标系选择**：标签大小/引线长度是按图像坐标（随缩放变化）还是屏幕像素（恒定）？建议与现有项目一致：按图像坐标处理。
3. **布局算法性能**：防遮挡和侧栏布局是 O(N²)，密集人群场景需要缓存布局结果。
4. **模式冲突**：新增 select/point 工具不要与现有 `EDIT`/`CREATE` 模式冲突，优先复用 `toggle_draw_mode()`。
5. **关键点命名差异**：HTML 用 `left_eye`，项目里可能用 `l_eye`，内部统一用 COCO 索引，显示标签单独映射。
6. **序列化兼容**：新增视觉属性（颜色、布局模式）建议存到用户配置，不改动 label JSON 格式。
7. **i18n 与 docstrings**：所有 UI 字符串用 `self.tr()` 或 `QCoreApplication.translate()`；函数/类需 Google 风格 docstring 和类型提示。
8. **代码质量**：需通过 `black -l 79`、`flake8`（max complexity 18），复杂渲染逻辑应拆分为小函数/类。

---

## 八、实施计划

### Phase 0 — 独立原型（1-2 天）

1. 创建 `pose_label_prototype/` 包。
2. 实现 `PoseData`：P17、SKEL、颜色预设。
3. 实现 `PoseCanvas`：
   - 合成背景绘制
   - person/keypoint 数据模型
   - 完整渲染管线：skeleton、midline、bbox、keypoints、labels、leaders
   - 鼠标拖拽、中键平移、滚轮缩放
4. 实现三种标签布局算法（direct / anti / column）。
5. 实现 `PoseSettingsPanel`、`PoseColorPanel`、`PoseToolBar`。
6. 用 `PoseWindow` 组装，临时从菜单启动验证。

### Phase 1 — 可复用化（1-2 天）

1. 将布局函数移动到 `keypoint_label_layout.py`（或兄弟模块）。
2. 提取 `PoseRenderer` 类，输入 `list[Shape]` + 参数字典，只负责绘制。
3. 确保输出为图像坐标，返回 leader 线段和遮挡数量。

### Phase 2 — 接入主画布（2-3 天）

1. 给 `Canvas` 增加 pose 模式开关：
   - `pose_view_enabled`
   - `pose_layout_mode`
   - `pose_color_mode`
   - 显示开关和样式参数
2. 在 `Canvas.paintEvent` 中调用 `PoseRenderer`，开启时抑制通用点标签。
3. 增加 `occlusion_count_changed` 信号更新统计徽标。
4. 新增 `PoseSettingsDock` / `PoseColorDock` 到 `LabelingWidget` 侧边栏。
5. 增加菜单项/快捷键切换 pose view。

### Phase 3 — 打磨与持久化（1 天）

1. 通过 `QSettings` 或 `xanylabeling_config.yaml` 保存用户颜色、布局模式、显示开关。
2. 实现颜色预设和自定义颜色。
3. 添加状态栏消息和国际化字符串。
4. 运行 `black`、`flake8`、手动测试。
5. 决定是否保留独立原型模块。

---

## 九、结论

**建议先做 Phase 0 独立原型窗口**，完整验证 QPainter 对 HTML 原型的翻译；
**长期归宿是 Phase 2 的主 Canvas Pose 渲染 Pass + 新设置 Dock**，这样能复用现有的缩放、平移、选择、拖拽、序列化和主题系统，同时把原型的布局/颜色能力真正融入标注工作流。

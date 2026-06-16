# Pose 关键点标签显示功能 — 开发总结

> 分支：`feature/label-display-mode`  
> 时间：2026-06-16  
> 原型参考：`html-case/0616_code.html`  
> 设计文档：`docs/superpowers/specs/2026-06-16-pose-keypoint-label-display-design.md`

---

## 一、背景

骨架标注场景中，关键点（point）的标签存在遮挡、颜色单调、缩放后字号不合理等问题。基于 HTML 原型 `0616_code.html` 的理想效果，将完整的 Pose 标签防遮挡渲染系统以纯模块方式集成到 X-AnyLabeling 的 PyQt6 画布中。

---

## 二、最终交付功能

### 2.1 渲染管线

| 功能 | 说明 |
|------|------|
| 实心彩色矩形标签 | 每个关键点标签为填充色块 + 内嵌文字，底色跟随部位/目标 |
| 骨骼连线 | COCO 16 条骨骼边，按部位或目标着色，60% 透明度 |
| 中线参考 | 虚线垂直身体中线（肩部中点） |
| 目标框 | person 矩形 + 标签文字 |
| 关键点圆点 | 填充色 + 白色描边，选中时蓝色虚线光环 |
| 引线 | 标签与关键点之间的半透明白线 |
| 文字阴影 | 标签文字下偏移 1px 的黑色半透明阴影 |
| 遮挡高亮 | 发生重叠的标签叠加红色半透明 |
| 遮挡计数 | 实时统计标签重叠对数，通过信号上报 |

### 2.2 三种标签布局模式

| 模式 | 行为 |
|------|------|
| 方向引线（direct） | 沿关键点身体方向直接外放标签 |
| 防遮挡（anti） | direct + 优先级排序 + 沿方向外推消除重叠 |
| 侧栏列表（column） | 按身体左右/顶部分栏，垂直堆叠在 bbox 两侧 |

### 2.3 两种着色模式

| 模式 | 说明 |
|------|------|
| 按部位（bodypart） | head 红 / 左上肢蓝 / 右上肢紫 / 左下肢绿 / 右下肢橙 |
| 按目标（person） | 每个 group_id 分配一个循环颜色 |

### 2.4 字体颜色模式

白色 / 黑色 / 自动（按背景亮度切换）/ 黄色 / 自定义（QColorDialog）

### 2.5 参数调节（滑块）

标签字号（8-16）/ 透明度（0.3-1.0）/ 引线长度（15-80px）/ 描边宽度（0-4）/ 列间距（4-30px）

### 2.6 显示开关（复选框）

骨骼连线 / 中线参考 / 目标框 / 遮挡高亮 / 引线 / 文字阴影

### 2.7 颜色预设

默认 / 柔和 / 霓虹 / 大地 + 恢复默认颜色按钮

### 2.8 配置持久化

所有参数保存到 `~/.xanylabelingrc` 的 `pose_view` 配置节，跨会话生效。

---

## 三、架构设计

### 3.1 模块结构

```
anylabeling/views/labeling/widgets/pose_label/
├── __init__.py              # 包导出
├── pose_constants.py        # COCO 17 关键点、部位分组、骨骼边、颜色预设（零 Qt 依赖）
├── pose_config.py           # PoseDisplayConfig dataclass + 序列化（零 Qt 依赖）
├── pose_layout.py           # 3 种布局算法纯函数（仅依赖 QtCore 几何类型）
├── pose_renderer.py         # PoseRenderer：QPainter 绘制管线（依赖 QPainter + QtCore）
├── pose_settings_panel.py   # QFrame 面板：布局/着色模式、滑块、显示开关
├── pose_color_panel.py      # QFrame 面板：字体颜色、部位/目标颜色、预设
└── pose_view_panel.py       # QDockWidget：单页滚动容器，嵌入 right_sidebar_layout
```

### 3.2 设计原则

- **纯模块优先**：`pose_constants` / `pose_config` / `pose_layout` 零 QWidget 依赖，可独立单元测试。
- **Canvas 最小改动**：paintEvent 仅增加约 20 行（过滤 + 调用 renderer），全部渲染逻辑封装在 `PoseRenderer`。
- **缩放补偿**：painter 已由 Canvas 缩放，renderer 不做额外 `painter.scale()`；字号 / padding / 线宽逐项 `/ scale` 补偿，保证屏幕像素恒定。
- **QFrame 面板模式**：`LabelingWidget` 是 `QWidget` 不是 `QMainWindow`，沿用现有 `display_mode_panel` / `inspector_panel` 的 `QFrame` + `get_panel_style()` 模式。
- **配置同步**：面板变更 → `_on_pose_panel_changed()` → 重绘 + 同步到 `_config["pose_view"]` → closeEvent 保存。

### 3.3 数据流

```
用户操作侧栏面板控件
       ↓ 更新
PoseDisplayConfig（与 Canvas 共享的内存单例）
       ↓ 触发 _on_pose_panel_changed()
Canvas.update() → paintEvent
       ↓ 标签循环：pose view ON 时跳过 COCO keypoint point + person rect
       ↓ 循环之后：调用 PoseRenderer.render()
按 group_id 分组 → 计算 midline/bbox → 绘制 skeleton/keypoints/labels
       ↓ 返回 occlusion_count
pose_occlusion_count_changed 信号 → （未来可接统计徽标）
```

### 3.4 Canvas 集成要点

| 改动位置 | 内容 |
|----------|------|
| `canvas.py:17` | 导入 `COCO_KEYPOINT_SET`, `PoseDisplayConfig`, `PoseRenderer` |
| `canvas.py:89` | 新增 `pose_occlusion_count_changed` 信号 |
| `canvas.py:219` | 初始化 `self.pose_config` + `self._pose_renderer` |
| `canvas.py:2722` | 标签循环内：pose view ON 时跳过 COCO keypoint point + person rect |
| `canvas.py:3010` | 标签循环后：调用 `PoseRenderer.render()` |
| `canvas.py:3864` | `_has_pose_shapes()` 辅助方法 |
| `label_widget.py:114` | 导入 `PoseViewPanel` |
| `label_widget.py:2746` | 创建 `PoseViewPanel`（QDockWidget）+ QFrame 包装 + right_sidebar_layout |
| `label_widget.py:2496` | View 菜单新增 "Pose View" 复选框 |
| `label_widget.py:6961` | `toggle_pose_view()` / `_sync_pose_config()` / `_on_pose_panel_changed()` |

---

## 四、提交历史

| 提交 | 里程碑 | 内容 |
|------|--------|------|
| `5c54aa8` | M1+M2 | COCO 常量 + 配置 + 3 模式布局引擎 + 14 单元测试 |
| `53c8475` | M3 | QPainter 渲染管线 + 6 冒烟测试 |
| `125606a` | M4 | Canvas 接入 + View 菜单开关 |
| `3bac96b` | M5 | 设置面板 + 颜色面板 |
| `d59c15c` | M6 | 配置持久化（closeEvent 同步） |
| `d88f900` | 重构 | 合并为 QDockWidget + 全中文 UI |
| `fd93506` | 重构 | 单页滚动布局 + 字体对齐项目规范 |

---

## 五、代码统计

| 指标 | 数值 |
|------|------|
| 新增文件 | 9 个（8 模块 + 2 测试） |
| 修改文件 | 3 个（canvas.py, label_widget.py, schema.py, config.yaml） |
| 新增代码行 | ~2,631 行（含测试） |
| 单元测试 | 34 个（14 布局 + 6 渲染 + 14 原有 keypoint） |
| Lint | flake8 clean（max complexity 18） |
| 格式化 | black -l 79 全部通过 |

---

## 六、关键技术决策

### 6.1 为什么不用 QDockWidget 的浮动功能？

`LabelingWidget` 继承自 `LabelDialog`（`QWidget`），不是 `QMainWindow`。`QDockWidget` 的 `addDockWidget()` 只在 `QMainWindow` 上有效。因此沿用 Inspector 模式：`QDockWidget` 嵌入 `QFrame` + `right_sidebar_layout`，通过 `setVisible()` 切换。

### 6.2 为什么 renderer 不调 `painter.scale()`？

`Canvas.paintEvent` 在 `canvas.py:2176` 已执行 `p.scale(self.scale, self.scale)`。renderer 在已缩放的 painter 上工作，字号 / 线宽 / padding 逐项除以 scale 补偿，使屏幕显示大小恒定。这和现有标签渲染的 `font_size / Shape.scale` 策略一致。

### 6.3 为什么 pose view ON 时不完全 return？

Pose View 只接管 COCO keypoint point 标签和 person 矩形标签的渲染。非 pose 图形（polygon / line / circle / 普通 rectangle）仍走原有标签路径。因此在标签循环内过滤而非整体 return，PoseRenderer 在循环之后调用。

### 6.4 与昨日方案的关系

`docs/keypoint_label_display_optimization.md`（描边文字、无背景）**已作废**。最终采用 HTML 原型的实心彩色矩形标签风格。

---

## 七、测试覆盖

### 7.1 `test_pose_layout.py`（14 tests）

- 中线计算：双肩 / 鼻子回退 / 无关键点
- 方向计算：中线居中向 up / 左肩向 left / 右脚踝向 right-down
- direct 布局：标签沿方向外放
- anti 布局：重叠数 ≤ direct
- column 布局：左右分栏 / 空列表
- apply_layout 调度：direct / 未知模式回退 / 空列表

### 7.2 `test_pose_renderer.py`（6 tests）

- 单人渲染不崩溃
- 双人渲染不崩溃
- scale=2.0 下 /scale 补偿正确
- 三种布局模式均不崩溃
- person 着色模式不崩溃
- 空 shapes 返回 0

---

## 八、遗留与展望

| 项目 | 说明 |
|------|------|
| 遮挡统计徽标 | `pose_occlusion_count_changed` 信号已就绪，面板上暂未显示数字徽标 |
| 骨骼连线独立开关 | 目前骨骼完全绑定 pose view，未来可考虑在 pose view 关闭时也显示骨骼 |
| .ts 翻译文件 | 面板字符串使用 `self.tr()`，但 `.ts` 文件未更新（需要运行 `scripts/compile_languages.py`） |
| KEYPOINT_ORDER 去重 | `pose_constants.COCO_KEYPOINT_ORDER` 提供了权威定义，项目其他 5+ 处重复定义可逐步替换 |
| 性能优化 | 布局算法 O(N²)，密集人群场景可缓存布局结果帧间复用 |

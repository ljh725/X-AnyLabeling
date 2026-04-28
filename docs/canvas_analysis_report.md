# Canvas.py 详细分析报告

> 文件：`anylabeling/views/labeling/widgets/canvas.py`
> 分析日期：2026/04/25
> 总行数：3,684 行

---

## 1. 核心依赖与主控制器

### 1.1 外部依赖
| 模块 | 作用 |
|---|---|
| `PyQt6` (`QtCore`, `QtGui`, `QtWidgets`) | GUI 框架基座，所有事件、绘制、光标、定时器均来自此 |
| `math` | 旋转、三角函数、向量点乘等几何计算 |
| `anylabeling.services.auto_labeling.types.AutoLabelingMode` | 自动标注模式枚举（ADD / REMOVE / NONE 等） |
| `anylabeling.views.labeling.utils.colormap.label_colormap` | 分组颜色映射表 `LABEL_COLORMAP` |
| `anylabeling.views.labeling.utils.theme.get_theme` | 暗色/亮色主题背景色 |
| `..utils` | 通用几何工具（`distance`, `hex_to_rgb` 等） |
| `..shape.Shape` | **数据模型核心**。Shape 不仅存储点集，还自带 `paint()` 渲染逻辑 |

### 1.2 主控制器关系
- `Canvas` 本身**不是**顶层控制器，它通过构造函数接收 `parent`（通常为 `LabelWidget` 或 `MainWindow`）。
- 对 `parent` 的直接调用：
  - `self.parent.toggle_draw_mode(...)`（第 254、462 行）：切换全局绘图/编辑模式。
- 因此，`Canvas` 负责**局部状态与渲染**，而全局生命周期（文件 IO、模型推理、标签列表）由外部 `parent` 控制。

---

## 2. 直接交互模块

### 2.1 输入事件矩阵
| 事件 | 方法 | 职责 |
|---|---|---|
| `mouseMoveEvent` | 第 532 行 | **最复杂的状态路由器**。区分 drawing / copy-moving / vertex-moving / shape-moving / cuboid-face-moving / panning / hovering 七条分支 |
| `mousePressEvent` | 第 1070 行 | 左键：创建形状首点、追加顶点、触发 auto-decode、进入移动编辑态；右键：预选对象供后续菜单/复制 |
| `mouseReleaseEvent` | 第 1287 行 | 右键弹出 `self.menus`（0=无选中菜单，1=拖拽菜单）；左键完成选择切换逻辑 |
| `mouseDoubleClickEvent` | 第 1351 行 | 结束 auto-decode、编辑标签请求、闭合 polygon/linestrip |
| `wheelEvent` | 第 3227 行 | Ctrl+滚轮→`zoom_request`；Shift+滚轮→调整对比视图 split；普通滚轮→`scroll_request`；矩形编辑模式下滚轮直接调整边长/缩放 |
| `keyPressEvent` / `keyReleaseEvent` | 第 3435、3479 行 | 方向键移动选中形状；Z/X/C/V 旋转；Esc/Backspace/Return 控制绘制流程；Alt 临时关闭 snapping |

### 2.2 菜单系统
- `self.menus = (QtWidgets.QMenu(), QtWidgets.QMenu())`
  - `menus[0]`：无选中且未拖拽时的右键菜单。
  - `menus[1]`：有选中或拖拽复制时的右键菜单。
- 菜单内容未在 `canvas.py` 内填充，由外部 `LabelWidget` 注入（`self.canvas.menus[0].addAction(...)` 模式）。

---

## 3. 工具与辅助模块

### 3.1 几何与约束工具
| 方法群 | 说明 |
|---|---|
| `transform_pos` / `offset_to_center` | 坐标系转换核心（详见第 7 节） |
| `intersection_point` / `intersecting_edges` | 计算线段与图像边界的交点，用于 polygon 画到图外时自动吸附到边缘 |
| `rotate_point` / `bounded_rotate_shapes` | 旋转形状并处理 2 点→4 点的矩形补全 |
| `close_enough` | 基于 `epsilon / self.scale` 的动态距离阈值，实现"吸附闭合" |
| `make_rectangle_points` | 两点生成轴对齐矩形四点 |
| `get_adjoint_points` / `get_cross_point` | 旋转矩形（rotation）拖拽顶点时的对顶点几何求解 |

### 3.2 Cuboid（立方体）专用工具链（约 20+ 方法）
这是本文件最复杂的几何子系统，包含：
- **深度向量**：`normalize_cuboid_depth`, `get_cuboid_depth_vector`, `sync_cuboid_depth_vector`
- **控制点索引**：`cuboid_control_point`, `cuboid_visible_control_indices`, `nearest_cuboid_control`
- **面命中测试**：`cuboid_face_path`, `cuboid_face_hit_test`
- **约束调整**：`adjust_cuboid_front_vertex`（保持矩形性）、`adjust_cuboid_front_edge`（边中点拖拽）、`adjust_cuboid_visible_back_vertex`（后边缘防越界）、`move_cuboid_face_by`（左/右/后面整体平移）

### 3.3 自动解码（Auto Decode）辅助
- `auto_decode_timer`：`QTimer` 单发定时器，延迟 `AUTO_DECODE_DELAY_MS`（100ms）。
- `auto_decode_tracklet`：记录鼠标轨迹点，上限 `MAX_AUTO_DECODE_MARKS`（42）。
- `on_auto_decode_timeout`：聚合轨迹并发射 `auto_decode_requested` 给外部推理线程。

### 3.4 渲染辅助
- `render_visualization`（第 2975 行）：**离屏渲染工厂**。构造临时 `Canvas` 实例，绘制到 `QImage`，用于导出带标签的可视化结果，不影响主画布状态。

---

## 4. 信号/槽契约

`Canvas` 通过 **18 个信号** 与外部解耦。以下按功能域分类：

### 4.1 视口导航
- `zoom_request(int, QPoint)` — Ctrl+滚轮触发，请求外部缩放。参数：滚轮 delta、鼠标位置。
- `scroll_request(float, object, int)` — 滚轮/中键拖拽平移。参数：滚动量、方向、模式标志。

### 4.2 形状生命周期
- `new_shape()` — `finalise()` 中调用，通知外部新形状已加入 `self.shapes`。
- `drawing_polygon(bool)` — 进入/退出绘制中状态，外部据此更新 UI（如禁用某些按钮）。
- `edit_label_requested()` — 双击已有形状，或右键菜单触发，请求弹出标签编辑器。

### 4.3 选择与变换
- `selection_changed(list)` — 选中集合变更。这是**单向权威通知**，外部应以此为准刷新标签列表。
- `shape_moved()` / `shape_rotated()` — 键盘或鼠标释放后，若坐标确实改变，通知外部保存/备份。
- `vertex_selected(bool)` — 悬停顶点状态变化，用于控制属性面板或删除顶点按钮的可用性。
- `shape_hover_changed()` — 鼠标滑过不同形状时触发，外部可据此高亮侧边栏对应行。

### 4.4 自动标注
- `auto_labeling_marks_updated(list)` — 自动标注模式下，将 ADD/REMOVE 的 point/rectangle 转为标记列表。
- `auto_decode_requested(list)` — 向外部 AI 模型发送轨迹，请求解码。
- `auto_decode_finish_requested()` — 双击结束连续解码。

### 4.5 其他
- `mode_changed()` — 在 CREATE 模式下悬停到已有对象时，请求自动切换到 EDIT 模式。
- `show_shape(int, int, QPointF)` — 实时报告当前绘制/调整的形状高宽及鼠标位置（通常显示在底部状态栏）。
- `split_position_changed(float)` — 对比视图（compare view）分割线比例改变。

---

## 5. 绘制流程分离

`paintEvent`（第 2125 行）是一个**严格按层级堆叠**的渲染管线，共 14 层。每层使用独立的 `QPainter` 状态（pen/brush/font），避免状态污染。

```
Layer 0:  基础图像层
          ├── drawPixmap(0,0, self.pixmap)          // 原图
          └── 若 compare_pixmap 存在，左半部绘制对比图（受 split_position 控制）

Layer 1:  加载遮罩层（is_loading）
          ├── 半透明黑底
          ├── 旋转的加载指示器（手动旋转角度 + 自触发 update）
          └── 加载文字（Arial 20pt，居中）

Layer 2:  分组框层（show_groups）
          ├── 同 group_id 形状计算包围盒
          ├── 虚线外框
          └── 每个形状中心绘制彩色小三角

Layer 3:  KIE 关联层（show_linking）
          ├── 按 group_id 找中心点
          ├── 绘制带箭头指向的连线（三角箭头，抗锯齿）

Layer 4:  形状遮罩层（show_masks）
          ├── 对 polygon/rectangle/rotation/quadrilateral/circle 生成 QPainterPath
          ├── 半透明填充（alpha = mask_opacity，默认 80）
          └── 轮廓线（选中色/普通色，difficult 时为虚线）

Layer 5:  旋转角度层（show_degrees）
          ├── rotation 形状绘制中心小方块
          └── 若启用，绘制角度文本（橘底白字）

Layer 6:  当前绘制层
          ├── self.current.paint(p)                 // 正在创建的形状
          └── self.line.paint(p)                    // 跟随鼠标的预览线/点

Layer 7:  四边形闭合预览层
          └── quadrilateral 第三点时，绘制 preview 闭合线

Layer 8:  复制预览层
          └── selected_shapes_copy.paint(p)         // 右键拖拽的虚影

Layer 9:  实时填充预览层（fill_drawing）
          ├── polygon：将 current + line[1] 构成临时形状并填充
          └── quadrilateral：同理填充预览

Layer 10: 文本描述层（show_texts）
          └── 绘制 shape.description（蓝底白字，位于包围盒上方）

Layer 11: 标签层（show_labels）
          ├── 过滤 AUTOLABEL_* 占位符
          ├── 组合文本：id + label + score
          └── 橘色背景条 + 黑色文字

Layer 12: 十字准星层（cross_line_show）
          └── 以 prev_move_point 为中心画绿色虚线十字

Layer 13: 属性面板层（show_attributes）
          ├── 深灰背景框（attr_background_color）
          ├── 边框（attr_border_color）
          └── 蓝色属性文字（attr_text_color，位于形状下方）

Layer 14: 对比视图分割线层
          ├── 白色竖线 + 发光 handle
          └── 左右箭头指示器
```

**关键设计**：`Shape.scale = self.scale`（第 2164 行）被设为类级/模块级变量，供所有 `Shape.paint()` 内部使用，以统一控制顶点绘制大小、线宽的反缩放（保证视觉上不随 zoom 改变粗细）。

---

## 6. 交互状态机

Canvas 的交互状态可用一个**五维状态向量**描述：

```
(MODE, CREATE_SUBMODE, HOVER_TARGET, EDIT_ACTION, SELECTION_STATE)
```

### 6.1 状态维度详解

| 维度 | 取值 | 说明 |
|---|---|---|
| **MODE** | `CREATE` (0) / `EDIT` (1) | 由 `set_editing()` 切换；CREATE 下不可选择已有形状 |
| **CREATE_SUBMODE** | `_create_mode` | polygon, rectangle, rotation, circle, line, point, cuboid, quadrilateral, linestrip |
| **HOVER_TARGET** | `h_hape` / `h_vertex` / `h_edge` / `h_cuboid_face` | 当前鼠标悬停的目标；影响光标形状与可执行操作 |
| **EDIT_ACTION** | idle / move_editing / moving_shape / rotating_shape | `is_move_editing`：顶点编辑的"粘滞"模式（点击锁定，再点击释放） |
| **SELECTION_STATE** | `selected_shapes[]` / `selected_shapes_copy[]` | 正常选中 vs 右键拖拽时的幽灵副本 |

### 6.2 关键状态转换

```
[CREATE 模式]
  左键按下(outside pixmap) && linestrip
    → 创建 current，点被 clip 到边界
  左键按下(inside pixmap) && 无 current
    → current = Shape(create_mode); add_point(pos)
  移动鼠标 && current 存在
    → 更新 self.line（预览线），发射 show_shape
  左键按下 && current 存在
    → polygon: add_point | rectangle/cuboid/rotation: 补全点并 finalise()
    → point/circle/line: 直接 finalise()
  双击 / Return / 闭合点吸附
    → finalise() → new_shape.emit() → 进入 EDIT（由外部槽处理）

[EDIT 模式 - 悬停探测]
  移动鼠标
    → 按优先级命中：cuboid 控制点 > cuboid 前面 > cuboid 其他面
      > 普通顶点 > 边（可插入点）> 形状内部
    → 设置 h_hape / h_vertex / h_edge / h_cuboid_face
    → 更新光标（POINT / GRAB / DEFAULT）

[EDIT 模式 - 左键交互]
  点击顶点 && Shift
    → remove_selected_point()（quadrilateral/rectangle 等受保护不可删）
  点击顶点 && 无 Shift
    → is_move_editing = toggle；进入粘滞移动状态
  点击边
    → add_point_to_edge()；插入新点并选中
  点击形状内部
    → select_shape_point()；单选 / Ctrl 多选
  拖拽
    → 根据悬停类型分支：move vertex / move face / move shapes / pan canvas

[EDIT 模式 - 右键交互]
  按下
    → 若已有选中形状，生成 selected_shapes_copy
    → 拖拽时 bounded_move_shapes() 移动副本
  释放
    → 弹出 context menu；若取消则丢弃副本
```

### 6.3 自动标注状态叠加
- `is_auto_labeling=True` 时，CREATE 模式的行为被重写：
  - 所有新建形状的 `label` 被强制设为 `auto_labeling_mode.edit_mode`（第 3058 行）。
  - `auto_decode_mode=True` 时，移动鼠标积累轨迹，定时发射 `auto_decode_requested`。

---

## 7. 坐标系与视口

### 7.1 双坐标系定义

| 坐标系 | 原点 | 单位 | 用途 |
|---|---|---|---|
| **Widget 物理坐标** | QWidget 左上角 | 屏幕像素 | 鼠标事件 `ev.position()` |
| **图像逻辑坐标** | `pixmap` 左上角 | 原图像素 | `Shape.points` 存储、`transform_pos` 输出 |

### 7.2 变换公式

**Widget → Logical**（第 3027 行）：
```python
logical_pos = widget_pos / self.scale - self.offset_to_center()
```

**Logical → Widget**（由 `QPainter` 在 `paintEvent` 中隐式完成）：
```python
p.scale(self.scale, self.scale)
p.translate(self.offset_to_center())
```
即 QPainter 的当前变换矩阵为 `M = Scale(scale) · Translate(offset)`。

### 7.3 居中偏移计算（第 3031 行）
```python
offset.x = (area_width  - pixmap_width  * scale) / (2 * scale)   # 若窗口更大，否则 0
offset.y = (area_height - pixmap_height * scale) / (2 * scale)
```
- 当画布大于图像时，`offset > 0`，图像被居中，四周留白。
- 当画布小于图像时，`offset = 0`，图像左上角与 Widget 左上角对齐（通过滚动条浏览）。

### 7.4 缩放与视口一致性
- `self.scale` 是单一浮点值，外部通过槽（未在本文件定义，通常在 `LabelWidget` 中）修改。
- `minimumSizeHint()`（第 3220 行）返回 `scale * pixmap.size()`，确保 `QScrollArea` 的滚动范围随缩放自动扩展。
- **反缩放渲染**：所有视觉元素（顶点大小、线宽、字体、十字线宽）在绘制时均除以 `Shape.scale`，保证无论 zoom 到多少，UI 控件在屏幕上保持恒定像素尺寸。

### 7.5 边界约束
| 方法 | 约束对象 | 行为 |
|---|---|---|
| `out_off_pixmap(p)` | 通用 | 判断逻辑坐标是否超出图像矩形 |
| `clip_rectangle_to_pixmap` | rectangle | 最终化时裁剪到图像内，若退化则丢弃 |
| `clip_rotation_to_pixmap` | rotation | 仅对 direction=0（未旋转）的矩形做裁剪 |
| `intersection_point` | polygon | 画到图外时，将预览线吸附到图像边缘交点 |
| `bounded_move_shapes` | 批量移动 | 根据 `offsets` 限制整体平移不越界 |

---

## 总结

`canvas.py` 是一个**高度内聚但职责繁重**的控件。其核心设计特点为：

1. **信号驱动解耦**：通过 18 个信号将"用户意图"上报给 `LabelWidget`，自身不处理文件、模型或标签数据库。
2. **状态机显式化**：用 `mode` + `create_mode` + 多个 `h_*` 变量实现了细粒度的交互状态判别，支撑了从简单多边形到复杂 Cuboid 的多种标注范式。
3. **Painter 管线分层**：`paintEvent` 按语义分层绘制，避免了复杂 Z-Order 冲突，且便于独立开关（masks、labels、attributes 等）。
4. **坐标系单一入口**：所有鼠标坐标必须经过 `transform_pos` 进入逻辑域，所有绘制必须经过 `paintEvent` 的 `scale+translate` 变换，保证了两端的一致性。

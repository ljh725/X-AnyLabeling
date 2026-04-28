# Canvas.py 架构深度分析报告

> 分析对象: `anylabeling/views/labeling/widgets/canvas.py` (3684 行)
> 分析工具: opencode-kimi
> 生成时间: 2026-04-27

---

## 一、核心依赖与主控制器

### 1.1 核心依赖层
```text
PyQt6 (QtCore, QtGui, QtWidgets)        # GUI 框架底座
    ├── QPainter / QPixmap / QWheelEvent  # 绘制与输入基础设施
    └── QTimer                            # 自动解码延时触发器

anylabeling.services.auto_labeling.types  # AutoLabelingMode 枚举
anylabeling.views.labeling.utils.*        # colormap, theme, distance 等
..shape (Shape)                           # 标注图形的数据模型与自绘制能力
..utils                                   # 通用几何/颜色工具
```

### 1.2 主控制器定位
`Canvas` 是一个 **纯视图控制器（View Controller）**，继承自 `QWidget`。它不构成完整的 MVC，而是典型的 **"胖视图"（God Widget）** 模式：

- **数据持有者**：`self.shapes`（全部标注）、`self.current`（正在绘制）、`self.selected_shapes`（当前选中）
- **父级回调**：通过 `self.parent`（通常为 `LabelWidget`）调用 `toggle_draw_mode`、`update_auto_labeling_marks` 等高层逻辑
- **不直接处理文件 IO 或模型推理**，但通过信号将事件上报给父级完成

---

## 二、直接交互模块

### 2.1 输入事件处理矩阵

| 事件 | 处理函数 | 核心职责 |
|------|---------|---------|
| `mouseMoveEvent` | `mouseMoveEvent` (532) | 悬停检测、顶点/边/面高亮、拖拽移动、绘制预览线、自动解码触发 |
| `mousePressEvent` | `mousePressEvent` (1070) | 创建新形状、添加点、选择形状、切换编辑状态、边加点 |
| `mouseReleaseEvent` | `mouseReleaseEvent` (1287) | 结束移动、存储备份、右键菜单、取消选中 |
| `mouseDoubleClickEvent` | `mouseDoubleClickEvent` (1351) | 编辑标签、闭合多边形、自动解码完成 |
| `wheelEvent` | `wheelEvent` (3227) | 缩放、滚动、矩形边缘微调、对比视图分割 |
| `keyPressEvent` / `keyReleaseEvent` | (3435 / 3479) | 键盘移动/旋转、撤销点、ESC 取消绘制、Alt 吸附切换 |

### 2.2 交互优先级（mouseMoveEvent 中的决策链）
```text
1. is_loading? -> 直接返回
2. auto_decode_mode + auto_labeling? -> 触发延时解码
3. self.drawing()? -> 处理预览线 (self.line) 与 光标形状
4. RightButton + selected_shapes_copy? -> 复制体拖拽
5. LeftButton + selected_vertex? -> 顶点移动 (bounded_move_vertex)
6. LeftButton + selected_cuboid_face? -> 立方面移动
7. LeftButton + selected_shapes? -> 形状整体移动 (bounded_move_shapes)
8. LeftButton + 空白处? -> 视口平移 (scroll_request)
9. editing() + is_move_editing? -> 持续移动/面调整
10. 纯 Hover? -> 顶点/边/形状/立方面 高亮检测循环
```

---

## 三、工具与辅助模块

### 3.1 几何与约束工具
| 方法 | 功能 |
|------|------|
| `intersection_point` / `intersecting_edges` | 线段与图像边界的相交计算，用于越界裁剪 |
| `clip_rectangle_to_pixmap` / `clip_rotation_to_pixmap` | 矩形/旋转框限制在图像内 |
| `rotate_point` / `bounded_rotate_shapes` | 绕中心点旋转变换 |
| `get_adjoint_points` | 旋转框顶点联动几何（通过斜率求对顶点） |
| `close_enough` | 基于 epsilon 与当前 scale 的吸附判定 |

### 3.2 Cuboid（立方体）专用工具集（约 500 行）
```text
cuboid_face_path           # 构造面的 QPainterPath
cuboid_face_hit_test       # 面碰撞检测（按深度排序）
nearest_cuboid_control     # 最近控制点检测（含边中心虚拟点）
adjust_cuboid_front_vertex # 前面顶点拖拽（保持矩形约束）
adjust_cuboid_front_edge   # 前边中心拖拽
adjust_cuboid_back_edge_center # 后边中心拖拽（控制深度）
move_cuboid_face_by        # 面整体平移（left/right/back）
set_cuboid_points / make_cuboid_points # 前后面对齐生成
```

### 3.3 状态备份与撤销
- `store_shapes()`：深拷贝 `shapes` 到 `shapes_backups`（最大保留 `num_backups` 份）
- `restore_shape()`：从备份栈恢复状态
- `store_moving_shape()`：移动结束后自动检测变化并备份

### 3.4 渲染辅助
- `render_visualization()`：创建临时 Canvas 实例，离屏渲染到 `QImage`，用于导出可视化结果

---

## 四、信号/槽契约（Signal/Slot Contract）

### 4.1 Canvas 对外发射的信号

| 信号 | 参数 | 触发场景 | 消费者（推测） |
|------|------|---------|--------------|
| `zoom_request` | `(int delta, QPoint pos)` | Ctrl+滚轮 | `LabelWidget` -> 调整 `scale` |
| `scroll_request` | `(float delta, object orientation, int type)` | 滚轮/拖拽平移 | `LabelWidget` -> `QScrollBar` |
| `mode_changed` | `()` | 在创建模式下点击已有对象自动切编辑 | `LabelWidget` |
| `new_shape` | `()` | `finalise()` 完成新形状 | `LabelWidget` -> 弹出标签对话框 |
| `show_shape` | `(int h, int w, QPointF pos)` | 绘制/移动时实时尺寸 | `LabelWidget` -> 状态栏显示 |
| `selection_changed` | `(list shapes)` | 选中/取消选中 | `LabelWidget` -> 更新属性面板 |
| `shape_moved` | `()` | 移动/旋转后备份完成 | `LabelWidget` -> 标记文件为修改 |
| `shape_rotated` | `()` | 键盘旋转完成 | `LabelWidget` |
| `drawing_polygon` | `(bool)` | 开始/结束绘制 | `LabelWidget` -> 启用/禁用动作 |
| `vertex_selected` | `(bool)` | 悬停顶点状态变化 | `LabelWidget` |
| `auto_labeling_marks_updated` | `(list marks)` | 自动标注标记变化 | `ModelManager` |
| `auto_decode_requested` | `(list tracklet)` | 鼠标停止移动延时后 | `SAM/分割模型推理` |
| `auto_decode_finish_requested` | `()` | 双击结束自动解码 | `ModelManager` |
| `shape_hover_changed` | `()` | 悬停对象变化 | `LabelWidget` |
| `split_position_changed` | `(float)` | 对比视图分割线调整 | `LabelWidget` |
| `edit_label_requested` | `()` | 双击对象请求编辑标签 | `LabelWidget` -> 标签对话框 |

### 4.2 信号流向图
```text
用户输入 -> Canvas 处理 -> 发射信号 -> LabelWidget/MainWindow 接收 -> 修改数据/状态 -> 回调 Canvas 方法 (如 load_shapes, set_scale)
```

---

## 五、绘制流程分离（Paint Pipeline）

### 5.1 paintEvent 分层绘制顺序（自底向上）

```python
def paintEvent(self, event):
    # 1. 坐标系建立
    p.scale(self.scale, self.scale)
    p.translate(self.offset_to_center())
    
    # 2. 底图
    p.drawPixmap(0, 0, self.pixmap)
    
    # 3. 对比视图（左半部分覆盖 compare_pixmap）
    if self.compare_pixmap: ...
    
    # 4. Group 分组视觉（虚线包围框 + 三角标记）
    if self.show_groups: ...
    
    # 5. KIE Linking（关键信息提取连线与箭头）
    if self.show_linking: ...
    
    # 6. 形状蒙版填充（半透明遮罩 + 轮廓线）
    if self.show_masks:
        for shape in shapes:
            # polygon/rectangle/rotation/quadrilateral/circle
            # 构建 QPainterPath -> fill -> stroke
            ...
    
    # 7. 形状本体绘制（委托 Shape.paint）
    for shape in self.shapes:
        shape.paint(p)   # 内部处理顶点、线条、选中态、高亮态
    
    # 8. 旋转角度指示
    if shape.shape_type == "rotation": ...
    
    # 9. 当前绘制预览
    if self.current:
        self.current.paint(p)
        self.line.paint(p)
    
    # 10. 复制体（拖拽阴影）
    if self.selected_shapes_copy:
        for s in self.selected_shapes_copy: s.paint(p)
    
    # 11. 实时填充预览
    if self.fill_drawing(): ...
    
    # 12. 文本层（description / label / scores）
    if self.show_texts: ...
    if self.show_labels: ...
    
    # 13. 十字准星
    if self.cross_line_show: ...
    
    # 14. 属性文本
    if self.show_attributes: ...
    
    # 15. 对比视图分割线 UI
    if self.compare_pixmap: ...
```

### 5.2 绘制架构特点
- ** imperative 绘制**：直接在 `paintEvent` 中按图层顺序调用 QPainter API，无场景图（Scene Graph）
- **Shape 自绘制**：每个 `Shape` 负责自己的几何路径与画笔，Canvas 只决定**是否绘制**与**全局状态**（scale、hide_background）
- **离屏渲染支持**：`render_visualization()` 通过临时实例实现无头渲染

---

## 六、交互状态机（Interaction State Machine）

### 6.1 主模式（Mode）
```text
CREATE (0)  --set_editing(False)-->  EDIT (1)
  ^                                  |
  |-- toggle_draw_mode -------------|
```

### 6.2 创建模式子状态（Create Mode）
通过 `_create_mode` 区分：
```text
polygon, rectangle, rotation, circle, line, point, linestrip, quadrilateral, cuboid
```

### 6.3 运行时状态标志矩阵

| 标志 | 类型 | 语义 |
|------|------|------|
| `self.mode` | `CREATE/EDIT` | 顶层交互模式 |
| `self.is_auto_labeling` | `bool` | 是否处于 AI 自动标注模式 |
| `self.auto_labeling_mode` | `AutoLabelingMode` | 自动标注的具体配置（ADD/REMOVE/...） |
| `self.current` | `Shape/None` | 正在绘制中的形状（中间态） |
| `self.moving_shape` | `bool` | 正在执行形状移动（用于释放时备份） |
| `self.rotating_shape` | `bool` | 正在执行形状旋转 |
| `self.is_move_editing` | `bool` | 编辑模式下顶点的持续移动锁定态 |
| `self._brush_drawing` | `bool` | 画笔模式连续绘制多边形 |
| `self.auto_decode_mode` | `bool` | 自动解码（如 SAM）触发模式 |
| `self.snapping` | `bool` | 顶点吸附使能（Alt 键切换） |

### 6.4 高亮对象状态（Hover State）
```text
h_hape          -> 当前悬停的 Shape
h_vertex        -> 当前悬停的顶点索引
h_edge          -> 当前悬停的边索引（可插入点）
h_cuboid_face   -> 当前悬停的立方体面名称
prev_*          -> 上一帧状态（用于清除高亮）
```

### 6.5 状态转换示例（矩形绘制）
```text
[EDIT] --点击绘制工具--> [CREATE, rectangle]
  --mousePress(空白处)--> current = Shape(rectangle), 记录首点
  --mouseMove--> line = [首点, 当前鼠标], 实时显示尺寸
  --mousePress(第二点)--> 补全 4 个点, finalise()
       --> shapes.append(current), store_shapes(), emit new_shape
       --> 回到 [EDIT] 或保持 [CREATE]（取决于配置）
```

---

## 七、坐标系与视口（Coordinate & Viewport）

### 7.1 三级坐标系

| 坐标系 | 表示 | 转换关系 |
|--------|------|---------|
| **Widget 坐标** | `ev.position()` (Qt 事件原始坐标) | 最外层，含滚动条偏移 |
| **Painter 逻辑坐标** | `transform_pos()` 结果 | `= widget_pos / scale - offset_to_center()` |
| **图像像素坐标** | `pixmap` 的 `(0,0)` 到 `(W-1,H-1)` | 与 Painter 逻辑坐标 1:1 映射（在 scale 之后） |

### 7.2 核心变换函数
```python
def transform_pos(self, point):
    """widget -> painter(image)"""
    return point / self.scale - self.offset_to_center()

def offset_to_center(self):
    """计算画布居中偏移（当图像小于视口时两侧留白）"""
    s = self.scale
    area = super().size()
    w, h = self.pixmap.width() * s, self.pixmap.height() * s
    x = (area_width - w) / (2 * s) if area_width > w else 0
    y = (area_height - h) / (2 * s) if area_height > h else 0
    return QPointF(x, y)
```

### 7.3 视口与滚动
- `sizeHint()` / `minimumSizeHint()` 返回 `scale * pixmap.size()`，使 `QScrollArea` 自动产生滚动条
- 滚轮事件通过 `scroll_request` 信号通知父级滚动条移动，或 Ctrl+滚轮触发 `zoom_request`
- 平移操作：在 `mouseMoveEvent` 中计算 `delta = ev.position() - prev_pan_point`，转换为滚动比例发射 `scroll_request`

### 7.4 边界约束（Boundary Clamping）
所有形状移动/创建最终通过以下逻辑限制在图像内：
- `out_off_pixmap(pos)`：判定是否越界
- `bounded_move_vertex`：顶点移动时调用 `intersection_point` 限制在边界交点
- `bounded_move_shapes`：整体移动时利用 `offsets`（选区到图像四边的距离）进行 clamp

---

## 八、总结：架构特征与风险点

### 8.1 架构特征
1. **事件驱动 + 状态机**：通过 `mode` + 多个布尔标志构成扁平状态机
2. **信号解耦**：Canvas 不直接操作滚动条或对话框，全部通过信号委托给父级
3. **Shape 自治**：图形数据与自绘制逻辑下沉到 `Shape` 类，Canvas 专注交互编排
4. **指令式绘制**：无场景图，直接在 `paintEvent` 中分层绘制，简单高效但扩展性受限

### 8.2 关键风险点（God Class 症状）
- **3684 行单文件**：`paintEvent` 约 800 行，`mouseMoveEvent` 约 470 行，单一函数过长
- **Cuboid 逻辑侵入**：立方体特殊处理散布在 mouseMove、mousePress、paintEvent 中，未完全抽象
- **状态标志过多**：`moving_shape`, `is_move_editing`, `rotating_shape`, `snapping`, `_brush_drawing` 等 10+ 标志相互耦合，维护困难
- **绘制与状态混合**：`paintEvent` 中直接修改 `self.loading_angle`（副作用），违反纯函数原则

---

**文件定位**：`anylabeling/views/labeling/widgets/canvas.py:1-3684`

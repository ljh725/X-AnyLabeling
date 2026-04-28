# Canvas.py 完整分析报告

**文件**: `anylabeling/views/labeling/widgets/canvas.py` (3684行)
**类型**: PyQt6 QWidget — 标注图像的核心绘制与交互组件

---

## 一、核心依赖与主控制器

### 1.1 外部框架依赖

| 模块 | 用途 |
|------|------|
| `PyQt6.QtCore` | Qt 核心类型：`Qt`, `QTimer`, `QPointF`, `QRect`, `QRectF`, 信号机制, `pyqtSignal` |
| `PyQt6.QtGui` | 绘图基础设施：`QPainter`, `QPixmap`, `QPainterPath`, `QWheelEvent`, `QColor`, `QFont` 等 |
| `PyQt6.QtWidgets` | QWidget 基类、`QMenu`、`QApplication`(光标覆盖) |
| `math` | 旋转计算、距离计算 |

### 1.2 项目内部依赖

```
Canvas (QWidget)
├── Shape                    ← ..shape.Shape          (标注图形核心数据结构)
├── utils                    ← ..utils                (距离、颜色转换等工具函数)
├── AutoLabelingMode         ← services.auto_labeling.types
├── label_colormap()         ← .utils.colormap
├── get_theme()              ← .utils.theme
└── self.parent              ← LabelWidget (label_widget.py)
```

### 1.3 主控制器：LabelWidget (`label_widget.py`)

Canvas 的 `parent` 是 **LabelWidget**，它是真正的控制器——创建 Canvas 实例后连接其所有信号并实现业务逻辑：

```
┌─────────────────────────────────────────────┐
│               LabelWidget (Controller)        │
│  - 创建 Canvas                               │
│  - 连接 Canvas 所有信号到自己的槽             │
│  - 管理 label_list / file_list / toolbar     │
│  - 处理文件I/O、标注导入导出                  │
│  - 管理 CompareViewManager                   │
│  - 通过 self.canvas.xxx 调用 Canvas 公共方法 │
└──────────┬──────────────────────────────────┘
           │  父子关系 (self.parent)
           │  信号上行 (Signal → Slot)
           │  Canvas 也接收外部信号 (双向)
           ▼
┌─────────────────────────────────────────────┐
│               Canvas (QWidget)               │
│  标注渲染、交互、坐标变换                     │
└─────────────────────────────────────────────┘
```

关键创建代码（`label_widget.py:377-393`）:
```python
self.canvas = Canvas(
    parent=self,
    epsilon=...,
    double_click=...,
    num_backups=...,
    wheel_rectangle_editing=...,
    attributes=...,
    rotation=...,
    mask=...,
    brush=...,
    cuboid=...,
    double_click_edit_label=...,
)
```

Canvas 通过 `self.parent.toggle_draw_mode(...)` 等直接调用父控制器方法——形成**双向依赖**。

---

## 二、直接交互模块

### 2.1 Shape —— 数据核心

**`Shape`（`..shape.py`）** 是 Canvas 操作的核心数据对象。每个标注实体都是一个 Shape 实例。

```
Canvas.shapes[]          ← 所有已确认的 Shape 对象列表
Canvas.current           ← 正在绘制中的 Shape (可能是 None)
Canvas.line              ← 绘制时的辅助线 Shape
Canvas.selected_shapes[] ← 当前选中的 Shape 列表
Canvas.h_hape            ← 当前悬停 / 激活的 Shape
Canvas.selected_shapes_copy[] ← 右键拖拽时的影子副本
```

Shape 提供的关键能力:
- `points` (list[QPointF]) — 顶点坐标
- `shape_type` — polygon/rectangle/rotation/circle/line/linestrip/point/quadrilateral/cuboid
- `highlight_vertex(index, action)` / `highlight_clear()` — 顶点高亮
- `nearest_vertex(pos, epsilon)` / `nearest_edge(pos, epsilon)` — 邻近检测
- `contains_point(pos)` — 点击命中测试
- `bounding_rect()` — 包围盒
- `move_by(dp)` / `move_vertex_by(index, offset)` — 移动
- `copy()` — 深拷贝(undo/redo)
- `cuboid_*` 系列方法 — 立方体控制点/深度向量

### 2.2 utils —— 工具函数模块

```python
utils.distance(p)           # 计算两点距离
utils.hex_to_rgb(hex_str)   # 颜色转换
```

---

## 三、工具与辅助模块

### 3.1 颜色/主题系统

| 工具 | 来源 | 作用 |
|------|------|------|
| `label_colormap()` | `.utils.colormap` | 生成标注类别 → 颜色映射表 |
| `get_theme()` | `.utils.theme` | 获取背景主题色 |
| `LABEL_COLORMAP` | 模块级变量 | 颜色查找表, 用于 group 渲染 |

### 3.2 光标管理系统

定义 5 种光标常量 + 3 个方法形成光标子系统:

```python
CURSOR_DEFAULT = ArrowCursor       # 默认
CURSOR_POINT  = PointingHandCursor # 顶点命中/可点击
CURSOR_DRAW   = CrossCursor        # 绘制模式
CURSOR_MOVE   = ClosedHandCursor   # 拖拽移动中
CURSOR_GRAB   = OpenHandCursor     # 可抓取(悬停在shape上)

override_cursor(cursor)   # 设置光标(保持优先级)
restore_cursor()           # 恢复上层光标
current_cursor()           # 查看当前全局光标状态
```

光标选择决策表:
| 上下文 | 光标 |
|--------|------|
| 空画布悬停 | DEFAULT |
| Shape 内部悬停 | GRAB |
| 顶点命中 | POINT |
| 边命中(可加点) | POINT |
| 立方体面命中 | POINT |
| 正在绘制 | DRAW |
| 拖拽移动中 | MOVE |
| 绘制时闭合起点 | POINT (磁吸提示) |

### 3.3 撤消/恢复系统

```python
shapes_backups[]   # 状态快照堆栈 (最大 num_backups 层)
store_shapes()       # 保存当前快照(每次修改后调用)
restore_shape()      # 弹出一层恢复
is_shape_restorable  # 判断是否可撤销

# 快照存储规则:
# - 每次修改后保存, 最少需要 2 层快照才能 undo
# - LabelWidget 可以外部 pop/push backups
```

### 3.4 自动标注子系统

| 方法 | 功能 |
|------|------|
| `set_auto_labeling(mode)` | 设置自动标注模式 |
| `set_auto_labeling_mode(mode)` | 设置自动标注 Shape 类型 |
| `set_auto_decode_mode(enabled)` | 开启/关闭 SAM 自动解码 |
| `on_auto_decode_timeout()` | 100ms 定时器触发, 发送解码请求 |
| `update_auto_labeling_marks()` | 将 shapes 转换为 auto_labeling_marks |
| `reset_auto_decode_state()` | 清空解码跟踪状态 |

### 3.5 CompareView 比较视图

```python
compare_pixmap      # 对比图像
split_position      # 分割线位置 (0.0 - 1.0)
split_position_changed 信号  # 通知外部
```

### 3.6 立方体(Cuboid)子系统

27 个专用常量/方法，组成独立子系统:
- `cuboid_face_vertex_indices()` — 6 个面的顶点索引映射
- `cuboid_face_path()` — 构造面的 QPainterPath
- `cuboid_face_hit_test()` — 面命中测试(排除 front face)
- `move_cuboid_control()` — 控制点路由(前台顶点/边/后台边)
- `move_cuboid_face_by()` — 面拖拽(LEFT/RIGHT/BACK)
- `adjust_cuboid_front_vertex()` — 前顶点约束调整
- `adjust_cuboid_front_edge()` — 前边约束调整
- `adjust_cuboid_back_edge_center()` — 后边中心拖拽调整深度
- `adjust_cuboid_visible_back_vertex()` — 后可见顶点拖拽
- `normalize_cuboid_depth()` — 深度向量约束(最小深度)
- 向量运算工具: `_vector_dot`, `_vector_length`, `_vector_scale`, `_solve_vector_basis`

### 3.7 键盘交互模块

```python
keyPressEvent:
  Drawing模式: Escape(取消), Backspace(删点), Enter(完成), Alt(禁用吸附)
  Editing模式: 方向键(移动), Z/X/C/V(旋转±1° / ±0.1°)

keyReleaseEvent:
  恢复 snapping, 保存移动/旋转变更
```

### 3.8 分组/链接系统

```python
group_selected_shapes()     # 合并 group_id
ungroup_selected_shapes()   # 取消分组
gen_new_group_id()          # 生成新 group_id
merge_group_ids()           # 合并多个 group_id
show_groups / show_linking  # 渲染开关
```

### 3.9 渲染可视化导出

```python
render_visualization(pixmap, shapes, ...)  # 离屏渲染到 QImage, 用于导出可视化
```

此方法创建一个临时 Canvas 实例，在 QImage 上离屏渲染，然后销毁。

### 3.10 菜单系统

Canvas 持有两个 QMenu 对象，由 LabelWidget 外部填充：

```
Canvas.menus[0]  ← 无选区右键菜单
  ├─ 标签/Group ID 过滤子菜单 (prepend)
  ├─ self.actions.menu (编辑/删除/复制等)
  └─ aboutToShow → refresh_filter_menus (动态更新过滤项)

Canvas.menus[1]  ← 有选区副本右键菜单
  └─ "Copy here"(copy_shape) / "Move here"(move_shape)
```

`mouseReleaseEvent` 中右键释放时触发菜单；若菜单未选择任何项且存在副本，则**取消移动**。

### 3.11 Wheel Rectangle Editing —— 矩形滚轮编辑

```
触发条件: editing() + enable_wheel_rectangle_editing +
          not auto_highlight_shape + len(selected_shapes)==1 +
          shape_type=="rectangle" + no Ctrl

滚轮行为:
  ├─ 鼠标在矩形内 → _scale_rectangle(shape, wheel_up)
  │    以4点中心为原点, scale_factor = 1±0.05
  └─ 鼠标在矩形外 → _adjust_rectangle_edge(shape, cursor_pos, move_outward)
       检测最近的边(top/bottom/left/right), 按 rect_adjust_step 调整
```

### 3.12 Brush Drawing —— 多边形自动描点

Polygon 专用的连续描点模式：

```
启用: _brush_drawing = True
触发: mouseMoveEvent 中 _brush_drawing=True + create_mode=="polygon"
逻辑: 当前点与上一个点距离 * scale >= brush_point_distance(默认25px)
      → current.add_point(pos) 自动添加顶点
终止: 吸附到起点时自动 finalise, 或 ESC/Backspace 取消
```

### 3.13 Visibility 可见性系统

```python
self.visible = {}         # {Shape: bool} 字典
set_shape_visible(shape, value)   # 设置单个 shape 可见性
is_visible(shape)                  # 查询可见性
```

### 3.14 Loading 状态

```python
set_loading(is_loading, loading_text)  # 设置加载状态
is_loading = True → 阻断所有鼠标交互, paintEvent 绘制旋转动画
```

### 3.15 内部几何工具库

Canvas 包含一组完整的几何计算静态方法/普通方法：

| 方法 | 用途 |
|------|------|
| `make_rectangle_points(pt1, pt2)` | 对角两点 → 四点矩形 |
| `get_mid_point(p1, p2)` | 线段中点 |
| `get_cross_point(a1,b1,a2,b2)` | 两直线交点(斜截式) |
| `get_adjoint_points(theta, p3, p1, idx)` | 旋转框的邻接顶点计算 |
| `rotate_point(p, center, theta)` | 点绕中心旋转 |
| `_vector_dot / _vector_length / _vector_scale` | 向量运算 |
| `_solve_vector_basis(target, u, v)` | 克莱姆法则解基向量系数 |
| `intersecting_edges(p1, p2, points)` | 线段与矩形四边的交点枚举+排序 |
| `intersection_point(p1, p2)` | 选择最近边界交点 |

---

## 四、信号/槽契约

### 4.1 信号清单（16 个自发射信号 + 连接映射）

| # | 信号 | 签名 | 发送时机 | 外部接收方 |
|---|------|------|----------|------------|
| 1 | `zoom_request` | `(int, QPoint)` | wheelEvent + Ctrl | `LabelWidget.zoom_request` → ScrollArea |
| 2 | `scroll_request` | `(float, Orientation, int)` | wheelEvent / 左键拖拽空白区 | `LabelWidget.scroll_request` → ScrollArea scrollbar |
| 3 | `mode_changed` | `()` | 一键形状(矩形等)绘制完成后自动切回编辑 | LabelWidget |
| 4 | `new_shape` | `()` | finalise() 完成后 | `LabelWidget.new_shape` → 标注流程 |
| 5 | `show_shape` | `(int, int, QPointF)` | 鼠标移动/拖拽时, 显示当前矩形尺寸 | `LabelWidget.show_shape` → 状态栏显示 |
| 6 | `selection_changed` | `(list)` | select_shapes/deselect_shape/点击形状 | `LabelWidget.shape_selection_changed` |
| 7 | `shape_moved` | `()` | 形状移动/缩放完成 | `LabelWidget.set_dirty()` |
| 8 | `shape_rotated` | `()` | 旋转完成 | `LabelWidget.set_dirty()` |
| 9 | `drawing_polygon` | `(bool)` | 开始/结束/取消多边形绘制 | `LabelWidget.toggle_drawing_sensitive` |
| 10 | `vertex_selected` | `(bool)` | mouseMoveEvent 悬停检测结束 | `self.actions.remove_point.setEnabled` (控制删除顶点按钮) |
| 11 | `auto_labeling_marks_updated` | `(list)` | finalise() 自动标注时 | `auto_labeling_widget.on_new_marks` |
| 12 | `auto_decode_requested` | `(list)` | QTimer 超时(on_auto_decode_timeout) | `LabelWidget.on_auto_decode_requested` → SAM 服务 |
| 13 | `auto_decode_finish_requested` | `()` | 双击结束 SAM decode | `auto_labeling_widget.on_finish_clicked` |
| 14 | `shape_hover_changed` | `()` | leaveEvent / mouseMoveEvent 悬停变化 | lambda → `update_navigator_shapes()` (navigator高亮) |
| 15 | `split_position_changed` | `(float)` | Shift+滚轮 调整比较视图分割 | `compare_view_slider.set_position` |
| 16 | `edit_label_requested` | `()` | 双击已选 shape(编辑模式) | `LabelWidget.edit_label()` |

### 4.2 内部信号连接（__init__ 中）

```python
auto_decode_timer.timeout.connect(self.on_auto_decode_timeout)  # QTimer 回调
```

### 4.3 Canvas 接收的外部 Qt 信号（方向注入）

Canvas 不仅发出信号，也通过外部 Qt 连接接收指令：

```python
auto_labeling_widget.auto_labeling_mode_changed.connect(
    self.canvas.set_auto_labeling_mode        # Slot
)
auto_labeling_widget.auto_decode_mode_changed.connect(
    self.canvas.set_auto_decode_mode          # Slot
)
auto_labeling_widget.clear_auto_decode_requested.connect(
    self.canvas.reset_auto_decode_state       # Slot
)
```

### 4.4 契约说明

- **上行**: Canvas 通过 signal 发出，LabelWidget 通过 slot 接收
- **下行**: LabelWidget 通过公共方法调用 Canvas（如 `canvas.load_shapes`, `canvas.set_editing` 等）
- **侧行**: auto_labeling_widget 通过 signal 直接连接到 Canvas 的 setter 方法
- **反向**: Canvas 通过 `self.parent.toggle_draw_mode(...)` 直接调用父对象，打破了纯信号/槽架构

---

## 五、绘制流程分离 (Paint Pipeline)

### 5.1 整体绘制管线

```
paintEvent(event)
│
├─ 1. 有效性检查 ─ pixmap 为空则短路, 调用 super().paintEvent()
├─ 2. QPainter 初始化 ─ begin + AntiAliasing + SmoothPixmapTransform
├─ 3. 坐标变换 ─ scale(self.scale) + translate(offset_to_center())
├─ 4. 背景层 ─ drawPixmap(0, 0, self.pixmap)
│
├─ 5. CompareView 左半图 ─ 条件绘制 compare_pixmap 左侧部分
├─ 6. Shape.scale 同步 ─ 更新类变量
│
├─ 7. Loading 状态 ─ 半透明遮罩 + 旋转动画 + 文字 (绘制后调用 self.update() 形成动画循环, 短路返回)
│
├─ 8. Groups 层 ─ 虚线包围盒 + 三角形标记
├─ 9. KIE Linking 层 ─ 连线 + 箭头
│
├─ 10. Masks 层 ─ QPainterPath 填充 + 边框 (多边形/矩形/旋转/四边形/圆)
│     ├─ fill: fill_color + mask_opacity
│     └─ outline: select_line_color + 虚线(difficult)
│
├─ 11. Shape 主体 ─ 遍历 shapes, 调用 shape.paint(p)
│     └─ 设置 hovered / fill 状态
│
├─ 12. 旋转角度标注 ─ 中心点 + 角度文本/圆点
│
├─ 13. 当前绘制中 ─ current.paint(p) + line.paint(p)
│     └─ 四边形第三条虚线辅助线
│
├─ 14. 移动副本 ─ selected_shapes_copy.paint(p)
│
├─ 15. 填充预览 ─ polygon/quadrilateral 绘制中填充预览
│
├─ 16. Texts 层 ─ description 文字
├─ 17. Labels 层 ─ label + score + group_id 标签背景+文本
│     └─ label_on_selection 模式下仅渲染选中的 label
│
├─ 18. 十字准线 ─ cross_line (虚线)
├─ 19. Attributes 层 ─ 属性背景+边框+文本
│
├─ 20. CompareView 分割线 ─ 分割竖线 + 拖拽手柄 + 渐变背景 + 双向箭头
│
└─ 21. p.end() ─ 结束绘制
```

### 5.2 分层设计原则

| 层级 | 绘制内容 | Z 序 | 可见性控制 |
|------|---------|------|------------|
| BG | pixmap + compare_pixmap | 最底 | — |
| Group | group 包围盒 | ↑ | `show_groups` |
| Linking | KIE 连线 | ↑ | `show_linking` |
| Mask | 半透明填充+描边 | ↑ | `show_masks` + `_hide_backround` |
| Shape | 主体图形+顶点 | ↑ | `visible[shape]` |
| Rotation | 角度标注 | ↑ | `show_degrees` |
| Current | 正在绘制的形状 | ↑ | `current is not None` |
| Shadow | 右键拖拽副本 | ↑ | `selected_shapes_copy` |
| Fill Preview | 绘制中填充预览 | ↑ | `fill_drawing()` |
| Text | 描述文本 | ↑ | `show_texts` |
| Label | 类别标签 | ↑ | `show_labels` + `label_on_selection` |
| Crosshair | 十字准线 | ↑ | `cross_line_show` |
| Attributes | 属性列表 | ↑ | `show_attributes` |
| Splitline | CompareView 分割 | 最顶 | `compare_pixmap` |

### 5.3 绘制与交互完全分离

- **绘制** (`paintEvent`): 只读访问 shapes/pixmap，不修改任何状态（除 loading_angle 动画）
- **交互** (mouse/keyboard events): 只修改数据和状态，通过调用 `update()/repaint()` 触发重绘
- 例外: loading 状态的 `self.update()` 自触发形成动画循环

### 5.4 Scale 全局变量同步

```python
Shape.scale = self.scale  # paintEvent 中将 scale 同步到 Shape 类变量
```

这是一个**隐式的全局状态传递**——Shape 在 paint 时通过 `Shape.scale` 获取当前缩放比来计算顶点半径和线宽。`render_visualization` 中通过 `old_shape_scale` 保存/恢复来避免竞态。

---

## 六、交互状态机

### 6.1 顶层模态

```
                 ┌──────────┐
                 │   EDIT   │ ◄── 默认模态
                 └────┬─────┘
                      │ set_editing(False) / 工具栏切换绘制
                      ▼
                 ┌──────────┐
                 │  CREATE  │
                 └──────────┘
                      │ mode_changed 信号 (一键形状完成自动切回)
                      │ set_editing(True)
                      └──────► EDIT
```

### 6.2 CREATE 模式的子状态机

```
                    ┌──────────────┐
                    │  IDLE (无当前) │
                    └──┬───────────┘
                       │ LeftClick on pixmap
                       ▼
                    ┌──────────────┐
                    │  DRAWING     │ current = Shape() + add_point(pos)
                    └──┬───────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
    polygon:      一键形状:     point:
    逐点添加      rectangle/    直接 finalise
    点击添加       rotation/
    Enter=完成    circle/line/
    Backspace=    cuboid/quad.
    删点          点击=完成
    DoubleClick
    =完成
          │            │
          └────────────┘
                       │ finalise()
                       ▼
              ┌──────────────┐
              │ shapes.append│ → new_shape 信号
              │ current=None │
              └──────────────┘
```

关键绘制变量 `self.line` 在不同 create_mode 下的语义:
| create_mode | line 语义 |
|-------------|----------|
| polygon | 最后一点 → 当前鼠标 |
| rectangle | 对角线的两点 |
| circle | 圆心 → 当前鼠标 |
| line | 起点 → 当前鼠标 |
| point | 仅当前点 |
| rotation | 起点 → 当前鼠标 (对角线) |
| quadrilateral | 最后一点 → 当前鼠标 |
| cuboid | 起点 → 当前鼠标 |
| linestrip | 最后一点 → 当前鼠标 |

### 6.3 EDIT 模式的子状态机

```
                         ┌──────────┐
                         │  IDLE    │ 空画布悬停
                         └──┬───────┘
                            │ mouseMove → 命中检测
           ┌────────────────┼──────────────────┐
           ▼                ▼                  ▼
    ┌──────────────┐ ┌─────────────┐ ┌────────────────┐
    │ VERTEX HIT   │ │ SHAPE HIT   │ │ CUBOID_FACE HIT│
    │ h_vertex=idx │ │ h_hape=s    │ │ h_cuboid_face=n│
    │ cursor=POINT │ │ cursor=GRAB │ │ cursor=POINT   │
    └──┬───────────┘ └──┬──────────┘ └──┬─────────────┘
       │ LeftClick       │ LeftClick     │ LeftClick
       ▼                 ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ MOVE VERTEX  │ │ SELECT + MOVE│ │ MOVE CUBOID FACE │
│ is_move_edit │ │ selected_    │ │ prev_point = pos │
│ ing 切换      │ │ shapes       │ │ offset 计算       │
└──────────────┘ └──────────────┘ └──────────────────┘
       │                 │               │
       │ Ctrl+click      │ Ctrl+click    │
       ▼                 ▼               ▼
  multiselect       multiselect      multiselect
  (追加选中)         (追加选中)       (追加选中)

特殊操作:
  - 单点/线/折线: epsilon*3 放大命中容差
  - Shift+点击顶点: 删除该顶点 (remove_selected_point)
  - 右键拖拽: 复制移动 (selected_shapes_copy)
  - 重复点击已选shape: 取消选中 (h_shape_is_selected)
  - leaveEvent: 自动清高亮 + shape_hover_changed
  - auto_highlight_shape: 悬停自动选中
```

### 6.4 `is_move_editing` — 免按拖拽子模态

```
点击顶点 → is_move_editing = not is_move_editing
   ├─ True: 移动鼠标即可移动顶点（无需按住鼠标）
   │    mouseMoveEvent 中检测 editing() and self.is_move_editing
   │    → bounded_move_vertex(pos)
   └─ False: 恢复 IDLE 悬停检测

例外：点击立方体面后直接进入移动，自动设置 is_move_editing = False
```

### 6.5 `h_shape_is_selected` — 重复点击取消选中逻辑

```
select_shape_point 中:
  - shape 尚未选中 → selection_changed.emit([shape]) → h_shape_is_selected = False
  - shape 已选中:
      label_on_selection=True  → h_shape_is_selected = False (不取消)
      label_on_selection=False → h_shape_is_selected = True

mouseReleaseEvent (LeftButton):
  if h_shape_is_selected and not moving_shape:
      → 从 selected_shapes 中移除该 shape (取消选中)
```

### 6.6 `auto_highlight_shape` — 悬停自动选中

当 `h_shape_is_hovered=True` 时，在 `mouseMoveEvent` 的悬停检测分支中：

```python
if self.h_shape_is_hovered:
    group_mode = (ev.modifiers() == ControlModifier)
    self.select_shape_point(pos, multiple_selection_mode=group_mode)
```

即**鼠标滑入 shape 内部时自动选中**。

### 6.7 右键拖拽复制/移动完整流程

```
RightButton Press (EDIT)
  → 若 h_hape 不在 selected_shapes 中: select_shape_point (先单选)
  → prev_point = pos

RightButton Move (在 mouseMoveEvent 中高优先级)
  → 首次移动: selected_shapes_copy = [s.copy() for s in selected_shapes]
  → 后续移动: bounded_move_shapes(selected_shapes_copy, pos)
  → cursor = CURSOR_MOVE

RightButton Release
  → 弹出 menus[1] (含 "Copy here" / "Move here")
  → 若菜单未被选中 + 副本存在 → 取消（丢弃副本，refresh）
  → 若选中 Copy → end_move(copy=True) → 追加新 shapes
  → 若选中 Move → end_move(copy=False) → 更新原 shapes 坐标
```

### 6.8 拖拽扩散的交互优先级（mouseMoveEvent 完整决策树）

```
mouseMoveEvent
├─ [ESC] loading → return
├─ 坐标变换 transform_pos()
│
├─ auto_decode 模式触达检测
│
├─ DRAWING 分支 (最高优先级)
│   ├─ 无 current → 设置 CURSOR_DRAW
│   ├─ rectangle/cuboid → show_shape 信号
│   ├─ 越界裁剪 (intersection_point)
│   ├─ 吸附起点 (close_enough)
│   ├─ Shift 正交约束
│   ├─ brush 模式自动加点 → 可能 finalise
│   └─ 更新 line 坐标
│
├─ 右键+已选副本 → 移动副本
├─ 右键+已选 → 创建副本 → return
│
├─ 左键+顶点选中 → bounded_move_vertex
│    ├─ cuboid → move_cuboid_control (4类控制点路由)
│    ├─ rotation → get_adjoint_points
│    ├─ rectangle → 对角联动
│    └─ 其他 → move_vertex_by
│
├─ 左键+cuboid_face选中 → move_cuboid_face_by
├─ 左键+shape选中 → bounded_move_shapes
├─ 左键+空白 → scroll_request (平移)
│
├─ 编辑+移动中(is_move_editing) → 同上顶点/面移动 → return
│
├─ 悬停检测 (降序遍历 shapes)
│   ├─ cuboid(8点) → nearest_cuboid_control → 顶点高亮
│   ├─ cuboid front face 命中 → CURSOR_GRAB
│   ├─ cuboid 侧面/背面 命中 → CURSOR_POINT
│   ├─ nearest_vertex → 顶点高亮
│   ├─ nearest_edge (且 can_add_point) → 边高亮
│   ├─ point/line/linestrip 特殊命中 (epsilon*3)
│   ├─ cuboid front path 命中
│   ├─ contains_point → shape 命中
│   ├─ auto_highlight_shape → select_shape_point (自动选中)
│   └─ rectangle/cuboid → show_shape 信号
│
├─ 未命中 → un_highlight + CURSOR_DEFAULT
└─ vertex_selected 信号 + shape_hover_changed 信号
```

### 6.9 mouseDoubleClickEvent 三路分支

```
双击 → 优先级:
  1. auto_decode_mode + is_auto_labeling + tracklet 非空
     → auto_decode_finish_requested (SAM 解码完成)

  2. editing() + double_click_edit_label + shape 命中
     → 单选该 shape + edit_label_requested (编辑标签)

  3. double_click=="close" + can_close_shape
     → linestrip: 直接 finalise
     → 其他: 先 pop 重复点 再 finalise (polygon/quadrilateral 等)
```

### 6.10 事件处理器总览

| 事件处理器 | 功能 |
|-----------|------|
| `enterEvent` | 恢复 Canvas 内部光标 |
| `leaveEvent` | 保存移动、清高亮、恢复光标、发射 shape_hover_changed |
| `focusOutEvent` | 恢复光标（防止光标漂移） |
| `mouseMoveEvent` | 绘制辅助线/移动/拖拽/悬停检测（核心交互入口）|
| `mousePressEvent` | 创建形状/选择/开始拖拽/自动标注 |
| `mouseReleaseEvent` | 菜单弹出/取消选中/保存移动 |
| `mouseDoubleClickEvent` | 完成 SAM 解码/编辑标签/闭合形状 |
| `wheelEvent` | 缩放/滚动/矩形编辑/CompareView 分割 |
| `keyPressEvent` | Drawing: Esc/Backspace/Enter/Alt; Editing: 方向键/Z/X/C/V |
| `keyReleaseEvent` | 恢复 snapping, 保存移动/旋转变更 |

---

## 七、坐标系与视口

### 7.1 三层坐标空间

```
┌──────────────────────────────────────────────┐
│  WIDGET 坐标 (Widget Coordinates)             │
│  - 来源: ev.position() / ev.position().toPoint()│
│  - 用途: 滚轮缩放中心、右键菜单弹出位置       │
│  - 单位: 物理像素 (受 widget 尺寸影响)        │
└───────────────┬──────────────────────────────┘
                │ transform_pos()
                │ point / self.scale - offset_to_center()
                ▼
┌──────────────────────────────────────────────┐
│  PAINTER 坐标 (Image/Painter Coordinates)    │
│  - 即 pixmap 内的逻辑坐标                     │
│  - 形状坐标、绘制坐标 都以此为准              │
│  - 来源: 大多数内部操作 (移动、创建、命中)    │
│  - 单位: pixmap 像素                          │
└───────────────┬──────────────────────────────┘
                │ self.scale (paintEvent 中 p.scale())
                │ + self.offset_to_center() (p.translate())
                ▼
┌──────────────────────────────────────────────┐
│  SCREEN 坐标 (实际渲染)                       │
│  - paintEvent 内部                            │
│  - scale * pixmap_coord + center_offset      │
└──────────────────────────────────────────────┘
```

### 7.2 关键坐标变换函数

```python
def transform_pos(self, point):
    """QPointF: Widget坐标 → Painter(图像)坐标"""
    return point / self.scale - self.offset_to_center()

def offset_to_center(self):
    """计算居中偏移量 (Painter坐标空间)"""
    # 当 pixmap*scale < widget_size 时，居中放置
    s = self.scale
    w, h = self.pixmap.width() * s, self.pixmap.height() * s
    area_w, area_h = super().size().width(), super().size().height()
    x = (area_w - w) / (2 * s) if area_w > w else 0
    y = (area_h - h) / (2 * s) if area_h > h else 0
    return QPointF(x, y)
```

在 `paintEvent` 中建立相反变换:
```python
p.scale(self.scale, self.scale)           # 放大
p.translate(self.offset_to_center())       # 居中偏移
p.drawPixmap(0, 0, self.pixmap)           # 在 Painter 坐标原点绘制
```

### 7.3 视口状态属性

| 属性 | 类型 | 含义 |
|------|------|------|
| `self.scale` | float | 缩放因子 (1.0 = 原始大小) |
| `self.pixmap` | QPixmap | 当前显示的图像 |
| `self.compare_pixmap` | QPixmap | CompareView 的对比图像 |
| `self.split_position` | float | CompareView 分割线位置 (0.0~1.0) |

### 7.4 sizeHint / 最小尺寸 —— 控制 ScrollArea

```python
def sizeHint(self):
    return self.minimumSizeHint()

def minimumSizeHint(self):
    if self.pixmap:
        return self.scale * self.pixmap.size()  # 核心: 缩放后的图像尺寸
    return super().minimumSizeHint()
```

QScrollArea 依赖这两个方法判断是否需要滚动条。Canvas 通过**放大/缩小后 pixmap 的物理显示尺寸**驱动 ScrollArea 的滚动行为。

### 7.5 视口操作（wheelEvent）

| 操作 | 条件 | 行为 |
|------|------|------|
| Ctrl+滚轮 | `mods & Ctrl` | `zoom_request` → 缩放 |
| 普通滚轮 | 无修饰键 | `scroll_request` → 滚动 |
| Shift+滚轮 | CompareView 激活 | 调整 `split_position` |
| 滚轮+矩形编辑 | 特殊配置 | 缩放/调整矩形边 |

### 7.6 平移/滚动的完整管道

```
用户鼠标拖拽空白区
    │
    ▼
mouseMoveEvent (左键 + 无选中)
    │
    ▼
delta = ev.position() - self.prev_pan_point
scroll_request.emit(delta.x / (pixmap.width * scale), Horizontal, 1)
scroll_request.emit(delta.y / (pixmap.height * scale), Vertical, 1)
    │
    ▼
LabelWidget.scroll_request(ratio, orientation, mode=1)
    │
    ▼
QScrollArea scrollbar.setValue(...)
```

### 7.7 越界约束（out_off_pixmap）

```python
def out_off_pixmap(self, p):
    """检查 Painter 坐标是否在 pixmap 边界内"""
    w, h = self.pixmap.width(), self.pixmap.height()
    return not (0 <= p.x() <= w - 1 and 0 <= p.y() <= h - 1)
```

绘制时越界策略:
- **polygon**: 调用 `intersection_point()` 将点裁剪到边界交点
- **rectangle/rotation/quadrilateral/cuboid**: **允许越界** (`allowed_oop_shape_types`)
- 移动时: `bounded_move_shapes()` 限制偏移不越界

```
allowed_oop_shape_types = ["rotation", "quadrilateral", "cuboid"]
```

### 7.8 Clip-to-Pixmap 约束系统

Canvas 有两套裁剪：

| 时机 | 方法 | 说明 |
|------|------|------|
| 绘制完成 | `clip_rectangle_to_pixmap(shape)` | 矩形超出边界时钳制到边界, 无效则返回 False |
| 绘制完成 | `clip_rotation_to_pixmap(shape)` | 旋转框(仅 direction==0)钳制, 同时更新 center |
| 移动中 | `bounded_move_shapes(shapes, pos)` | 根据 allowed_oop_shape_types 决定是否允许越界 |
| 移动中 | `bounded_move_vertex(pos)` | 顶点级边界约束 |

### 7.9 精度管理（epsilon / scale）

Canvas 的命中容差随缩放自适应:
```python
self.epsilon / self.scale       # 通用顶点/边检测容差
self.epsilon * 3 / self.scale  # point/line/linestrip 放大3倍
```

缩放越大(scale↑)，容差越小——在高倍率下需要更精确的点击。

---

## 八、完整依赖图谱 (总结)

```
                        ┌───────────┐
                        │  PyQt6    │
                        └─────┬─────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        QtCore.QTimer   QtGui.QPainter   QtWidgets.QWidget
                              │               │
                              ▼               ▼
                         Shape.scale    self.parent
                              │          (LabelWidget)
                              ▼               │
              ┌────────────────────┐         │
              │     Canvas (本文件) │◄────────┘
              └───────┬────────────┘
                      │
     ┌────────────────┼────────────────┐
     ▼                ▼                ▼
  Shape          utils           AutoLabelingMode
 (..shape)    (distance,     (auto_labeling.types)
               hex_to_rgb)
     │
     ├─── colormap → label_colormap()
     └─── theme    → get_theme()
```

---

**总结**: Canvas 是一个含有 ~3700 行代码的复杂 QWidget 组件。其架构核心是通过 **信号上行 + 方法下行 + 外部信号注入** 三种模式与 LabelWidget 及 auto_labeling_widget 进行双向通信。交互系统以 EDIT/CREATE 两大状态机为基础，内含 `is_move_editing` 免按拖拽、右键拖拽复制、`auto_highlight_shape` 悬停自动选中、`brush_drawing` 自动描点等多个子模态，通过 mouseMoveEvent 的优先级链路处理不同上下文。绘制管线将 15 层内容自底向上分层渲染，完全与交互逻辑解耦。坐标系采用 Widget→Painter→Screen 三层变换，并通过规模自适应容差保证不同缩放级别下的一致性操作体验。立方体(Cuboid)子系统是一个功能完整的独立编辑模块，涵盖 6 面识别、4 类控制点拖拽、深度约束和基底向量求解。

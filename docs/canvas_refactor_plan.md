# Canvas.py 拆分重构方案

> 目标：将 `anylabeling/views/labeling/widgets/canvas.py` 从 God Object 拆分为职责单一、可独立演进、AI/人可维护的模块化架构。

---

## 1. 现状诊断

### 1.1 规模与复杂度
- **总行数**：3,684 行
- **总 Token 数**：~30,328 tokens（已超出常见模型单次加载上限 25K）
- **类数**：1 个（`Canvas`）
- **信号数**：18 个
- **方法数**：约 90+ 个公有/私有方法
- **状态变量**：40+ 个实例属性

### 1.2 耦合的职责域
当前 `Canvas` 同时承担了以下 5 个正交职责：

1. **QWidget 壳子**：事件接收、信号定义、对外数据接口。
2. **交互状态机**：鼠标/键盘/滚轮的事件路由、悬停探测、选择逻辑、粘滞编辑态。
3. **2D 渲染引擎**：14 层 `paintEvent` 绘制管线、离屏渲染工厂、加载动画。
4. **几何约束引擎**：矩形/旋转框/多边形的边界裁剪、Cuboid 的 3D-2D 投影与约束求解、顶点拖拽的伴随点计算。
5. **自动标注控制器**：Auto-decode 定时器、轨迹收集、Brush 模式、AI 标记序列化。

### 1.3 对 AI 辅助开发的影响
| 维度 | 现状影响 |
|---|---|
| **上下文长度** | 必须分段加载（4 次 Read 才能覆盖完整文件），AI 无法在单轮内看到全局约束。 |
| **变更爆炸半径** | 新增一种 `create_mode` 需同时修改事件路由、绘制管线、几何约束三块代码。 |
| **Token 消耗** | 修改 Cuboid 交互需携带 ~12K tokens 上下文；拆分后预计降至 ~3K。 |
| **回归风险** | `mouseMoveEvent` 单方法 468 行，内含 7 条分支，修改任意分支都需人工/AI 验证对其他分支的副作用。 |

---

## 2. 拆分原则

1. **按变更原因分离（Single Reason to Change）**
   - 视觉需求 → 只改 Renderer
   - 交互需求 → 只改 InteractionManager
   - 数学需求 → 只改 GeometryEngine

2. **保持 Qt 事件链完整**
   - `Canvas` 仍作为 `QWidget` 接收原始事件，但**只做转发**，不做决策。
   - 避免将 `QWidget` 依赖渗透到几何引擎中，使几何逻辑可单元测试。

3. **零行为变更迁移（Behavior-Preserving Refactoring）**
   - 第一阶段仅搬移代码，不修改算法逻辑。
   - 所有现有信号、槽、外部调用点（`LabelWidget` 等）保持不变。

4. **显式依赖注入**
   - `Renderer` 通过方法参数接收状态快照，不直接持有 `Canvas` 引用。
   - `GeometryEngine` 设计为纯函数/静态方法集合，脱离 Qt 环境可独立运行。

---

## 3. 目标架构

```
anylabeling/views/labeling/widgets/canvas/
├── __init__.py                    # 导出 Canvas，保持外部导入路径不变
├── canvas.py                      # QWidget 壳子 + 信号定义 + 数据容器（目标 < 600 行）
├── interaction_manager.py         # 交互状态机 + 所有事件处理器（原 mouse*/key*/wheel*）
├── renderer.py                    # paintEvent 14 层绘制管线 + 离屏渲染工厂
├── geometry_engine.py             # 形状变换、边界约束、Cuboid 专用几何、滚轮矩形编辑
└── auto_labeling_controller.py    # 自动标注、auto decode、brush 模式
```

---

## 4. 各模块职责与迁移映射

### 4.1 `canvas.py` —— 事件壳子与数据容器

**保留职责**：
- 18 个 `pyqtSignal` 定义。
- `__init__` 中的配置参数读取（`epsilon`, `double_click`, `wheel_rectangle_editing`, `attributes_config` 等）。
- 基础状态存储：`shapes`, `pixmap`, `scale`, `mode`, `current`, `line`, `visible`。
- 坐标系核心方法：`transform_pos`, `offset_to_center`, `out_off_pixmap`。
- `QWidget` 尺寸提示：`sizeHint`, `minimumSizeHint`。
- 公共数据接口：`load_pixmap`, `load_shapes`, `set_shape_visible`, `reset_state`。
- 纯转发的事件存根：
  ```python
  def mouseMoveEvent(self, ev):
      self._interaction_manager.on_mouse_move(ev)

  def mousePressEvent(self, ev):
      self._interaction_manager.on_mouse_press(ev)

  def paintEvent(self, event):
      self._renderer.render(self, event)
  ```

**剥离内容**：
- 所有事件分支判断逻辑 → `interaction_manager.py`
- 所有绘制逻辑 → `renderer.py`
- 所有几何计算 → `geometry_engine.py`
- 所有自动标注逻辑 → `auto_labeling_controller.py`

---

### 4.2 `interaction_manager.py` —— 交互状态机

**迁入范围**（原文件行号）：
- `mouseMoveEvent`（532–999 行）完整逻辑。
- `mousePressEvent`（1070–1270 行）。
- `mouseReleaseEvent`（1287–1314 行）。
- `mouseDoubleClickEvent`（1351–1399 行）。
- `keyPressEvent` / `keyReleaseEvent`（3435–3507 行）。
- `wheelEvent` 中矩形编辑分支（3227–3257 行）。

**管理的状态变量**：
- 悬停状态：`h_hape`, `h_vertex`, `h_edge`, `h_cuboid_face` 及其 `prev_*` 版本。
- 编辑动作态：`is_move_editing`, `moving_shape`, `rotating_shape`。
- 选择态：`selected_shapes`, `selected_shapes_copy`。
- 光标栈：`override_cursor`, `restore_cursor`。
- 历史点：`prev_point`, `prev_pan_point`, `prev_move_point`。

**核心方法**：
- `select_shape_point(pos, multiple_selection_mode)`：命中测试与选择切换。
- `deselect_shape()`：清空选择并发射信号。
- `end_move(copy)`：结束移动/复制操作。
- `calculate_offsets(point)`：计算选中集相对边界的偏移量。

**对外依赖**：
- 通过 `self.canvas` 访问 `shapes`, `pixmap`, `scale`, `mode`, `create_mode`。
- 通过 `self.canvas` 发射信号（`zoom_request`, `scroll_request`, `selection_changed` 等）。
- 调用 `self.geometry_engine` 执行实际坐标变换（见 4.4）。

---

### 4.3 `renderer.py` —— 绘制管线

**迁入范围**：
- 完整 `paintEvent`（2125–2973 行）。
- `render_visualization` 离屏渲染工厂（2975–3025 行）。
- `set_loading` 及加载动画逻辑（238–243 行）。

**内部子层（保持现有 14 层结构）**：
1. `BaseImageLayer`：原图 + 对比视图左半部
2. `LoadingLayer`：半透明遮罩 + 旋转指示器
3. `GroupLayer`：分组虚线框 + 三角标记
4. `KIELayer`：关联连线与箭头
5. `MaskLayer`：形状半透明填充与轮廓
6. `RotationDegreeLayer`：角度指示
7. `CurrentShapeLayer`：`self.current` + `self.line`
8. `QuadrilateralPreviewLayer`：第四点闭合预览
9. `CopyPreviewLayer`：`selected_shapes_copy`
10. `FillPreviewLayer`：`fill_drawing` 实时填充
11. `TextDescriptionLayer`：`shape.description`
12. `LabelLayer`：标签 + 分数 + ID
13. `CrossHairLayer`：鼠标十字准星
14. `AttributeLayer`：属性键值对
15. `SplitHandleLayer`：对比视图分割线手柄

> **注**：第一阶段可将所有子层作为 `Renderer` 的私有方法，无需立即拆分为独立类，以降低重构风险。

**接口设计**：
```python
class Renderer:
    def render(self, canvas: Canvas, event: QPaintEvent):
        """主入口，按层绘制到 canvas 的 QPainter 上。"""
        ...

    def render_visualization(self, pixmap, shapes, **flags) -> QImage:
        """离屏渲染工厂。"""
        ...
```

---

### 4.4 `geometry_engine.py` —— 几何约束引擎

**迁入范围**：
- 顶点/形状移动：`bounded_move_vertex`, `bounded_move_shapes`, `bounded_shift_shapes`。
- 旋转：`rotate_point`, `bounded_rotate_shapes`。
- 边界裁剪：`clip_rectangle_to_pixmap`, `clip_rotation_to_pixmap`, `intersection_point`, `intersecting_edges`。
- 矩形生成：`make_rectangle_points`, `get_adjoint_points`, `get_cross_point`。
- **全部 Cuboid 几何方法**（约 20+ 个）：
  - 深度向量：`normalize_cuboid_depth`, `get_cuboid_depth_vector`
  - 控制点：`cuboid_control_point`, `cuboid_visible_control_indices`, `nearest_cuboid_control`
  - 面几何：`cuboid_face_path`, `cuboid_face_hit_test`, `cuboid_face_vertex_indices`
  - 约束调整：`adjust_cuboid_front_vertex`, `adjust_cuboid_front_edge`, `adjust_cuboid_visible_back_vertex`, `adjust_cuboid_back_edge_center`
  - 整体变换：`move_cuboid_face_by`, `move_cuboid_control`, `set_cuboid_points`, `set_cuboid_raw_points`
- 矩形滚轮编辑：`_scale_rectangle`, `_adjust_rectangle_edge`。

**设计约束**：
- 不导入 `QtWidgets`，仅使用 `QtCore.QPointF` 和 `QtGui.QPainterPath`（若需要路径计算）。
- 不持有 `Canvas` 引用；方法签名显式接收 `shape`, `pos`, `pixmap_size` 等参数。
- 便于脱离 Qt 环境进行单元测试。

---

### 4.5 `auto_labeling_controller.py` —— 自动标注控制器

**迁入范围**：
- `set_auto_labeling_mode`, `set_auto_labeling`。
- `set_auto_decode_mode`, `reset_auto_decode_state`, `on_auto_decode_timeout`。
- `update_auto_labeling_marks`。
- `auto_decode_timer`, `auto_decode_tracklet`, `last_mouse_pos`。
- `brush_point_distance` 及 `_brush_drawing` 相关逻辑。

**职责边界**：
- 管理自动标注的生命周期（进入/退出）。
- 收集轨迹并定时发射 `auto_decode_requested` / `auto_decode_finish_requested`。
- 将 `Canvas.shapes` 转换为 AI 模型所需的标记格式（point/rectangle + label 0/1）。

---

## 5. 迁移路线图

### Phase 0：准备与防护（0.5 天）
- [ ] 建立 `canvas/` 包目录与 `__init__.py`。
- [ ] 确保现有测试/手工测试矩阵可运行（创建、编辑、选择、删除、复制、分组、Cuboid、自动标注）。
- [ ] 冻结 `canvas.py` 上的其他功能开发，避免迁移冲突。

### Phase 1：提取 Renderer（0.5 天）
- [ ] 新建 `renderer.py`，将 `paintEvent` 整体搬入 `Renderer.render()`。
- [ ] `Canvas.paintEvent` 简化为 `self._renderer.render(self, event)`。
- [ ] 将 `render_visualization` 搬入 `Renderer`。
- **验证标准**：
  - 目视检查所有 14 层绘制正常。
  - `show_labels`, `show_masks`, `show_attributes` 开关生效。
  - 对比视图分割线与手柄交互正常。

### Phase 2：提取 GeometryEngine（1 天）
- [ ] 新建 `geometry_engine.py`。
- [ ] 将 `bounded_*`, `clip_*`, `rotate_*`, `intersection_*`, `make_rectangle_points`, `get_adjoint_points` 搬入。
- [ ] 将全部 `cuboid_*` 方法搬入。
- [ ] 将 `_scale_rectangle`, `_adjust_rectangle_edge` 搬入。
- [ ] 在 `Canvas` 中实例化 `self._geometry_engine = GeometryEngine()`。
- [ ] `InteractionManager`（下一步）和 `Canvas` 通过 `self._geometry_engine.method(...)` 调用。
- **验证标准**：
  - 所有形状拖拽、旋转、顶点编辑行为不变。
  - Cuboid 的前顶点、边中点、后面、面的拖拽与约束正常。
  - 矩形滚轮放大/缩小及边调整正常。

### Phase 3：提取 InteractionManager（1–1.5 天）
- [ ] 新建 `interaction_manager.py`。
- [ ] 将 5 个鼠标/键盘事件处理器完整搬入。
- [ ] 将 `select_shape_point`, `deselect_shape`, `calculate_offsets`, `end_move` 搬入。
- [ ] 将光标管理（`override_cursor`, `restore_cursor`, `current_cursor`）搬入。
- [ ] `Canvas` 中实例化 `self._interaction_manager = InteractionManager(self, self._geometry_engine)`。
- [ ] `Canvas` 的事件方法改为 1–3 行的转发存根。
- **验证标准**：
  - 完整跑通交互测试矩阵：
    - 创建：polygon, rectangle, rotation, circle, line, point, cuboid, quadrilateral, linestrip
    - 编辑：顶点移动、边插入点、整体移动、旋转、复制、删除
    - 选择：单选、Ctrl 多选、框选（若支持）、自动高亮
    - 模式切换：CREATE ↔ EDIT

### Phase 4：提取 AutoLabelingController（0.5 天）
- [ ] 新建 `auto_labeling_controller.py`。
- [ ] 将 auto-decode 与 brush 相关逻辑搬入。
- [ ] `InteractionManager` 在自动标注模式下通过 `AutoLabelingController` 代理轨迹收集。
- **验证标准**：
  - SAM / EdgeSAM 等自动标注插件的 point/rectangle 提示正常。
  - Auto-decode 模式下的轨迹收集与推理请求序列正常。

### Phase 5：清理与收尾（0.5 天）
- [ ] 删除 `canvas.py` 中已搬移的代码块。
- [ ] 检查并删除遗留的未使用私有方法。
- [ ] 统一文档字符串与类型注解。
- [ ] 最终行数目标检查：
  - `canvas.py` < 600 行
  - `interaction_manager.py` ~900 行
  - `renderer.py` ~800 行
  - `geometry_engine.py` ~600 行
  - `auto_labeling_controller.py` ~200 行

---

## 6. 拆分后的收益

### 6.1 对 AI 辅助开发的收益
| 指标 | 拆分前 | 拆分后 |
|---|---|---|
| 单文件最大 Token | ~30K | ~9K（renderer.py 最大） |
| AI 单轮完整加载 | 需 4 次分段 | 1 次完整加载 |
| 修改绘制层所需上下文 | ~15K tokens | ~4K tokens（仅 renderer.py） |
| 新增 `create_mode` 影响范围 | 事件+绘制+几何 3 个文件 | 主要是 interaction_manager + renderer |
| 新增形状类型（如 ellipse） | 需阅读 3,684 行 | 只需阅读 geometry_engine + renderer |

### 6.2 对工程质量的收益
| 指标 | 拆分前 | 拆分后 |
|---|---|---|
| 单元测试可行性 | 极难（强依赖 QWidget 初始化） | `GeometryEngine` 可脱离 Qt 测试；`Renderer` 可用离屏 QImage 测试 |
| 复用性 | 无法复用绘制逻辑 | `Renderer.render_visualization` 可直接用于批量导出 |
| 并发安全性 | 所有状态在一个对象内，竞态风险高 | 状态分散，职责边界清晰 |
| 新人 onboarding | 需理解 3,684 行 God Object | 只需阅读对应职责的单一模块 |

### 6.3 对未来扩展的预留
- **视频标注**：只需替换 `renderer.py` 中的 `BaseImageLayer` 为帧缓存层；交互层无需改动。
- **3D 点云**：`GeometryEngine` 可扩展 3D 投影方法；`InteractionManager` 可增加 3D 旋转状态。
- **Web 远程协作**：`InteractionManager` 的网络化只需序列化状态向量，无需携带整个 QWidget。

---

## 7. 风险与回滚策略

| 风险 | 缓解措施 |
|---|---|
| 回归缺陷 | Phase 0 建立完整的手工测试矩阵；每 Phase 完成后执行全量测试。 |
| 性能下降（多一层转发） | 事件转发为 Python 属性访问，耗时 < 1μs，可忽略。Renderer 仍使用同一 `QPainter` 实例。 |
| 外部代码导入路径变更 | 通过 `canvas/__init__.py` 保持 `from anylabeling.views.labeling.widgets.canvas import Canvas` 不变。 |
| 重构过程中需求变更 | 冻结 canvas.py 功能开发，重构分支独立运行，完成后合并。 |

---

## 附录：当前 `canvas.py` 方法归类速查

```
[坐标系与视口]
transform_pos, offset_to_center, out_off_pixmap, sizeHint, minimumSizeHint

[事件入口]
mouseMoveEvent, mousePressEvent, mouseReleaseEvent, mouseDoubleClickEvent
wheelEvent, keyPressEvent, keyReleaseEvent, enterEvent, leaveEvent, focusOutEvent

[交互状态]
select_shape_point, deselect_shape, calculate_offsets, end_move
hide_background_shapes, set_hiding, can_close_shape
add_point_to_edge, remove_selected_point, undo_pending_edge_point

[绘制]
paintEvent, render_visualization, set_loading

[几何约束]
bounded_move_vertex, bounded_move_shapes, bounded_shift_shapes
bounded_rotate_shapes, rotate_point, clip_rectangle_to_pixmap
clip_rotation_to_pixmap, intersection_point, intersecting_edges
close_enough, make_rectangle_points, get_adjoint_points, get_cross_point
_scale_rectangle, _adjust_rectangle_edge

[Cuboid 几何]
get_cuboid_depth_vector, cuboid_constraint_margin, normalize_cuboid_depth
make_cuboid_points, set_cuboid_points, set_cuboid_raw_points
get_cuboid_back_offsets, set_cuboid_front_with_offsets
cuboid_control_point, cuboid_visible_control_indices, nearest_cuboid_control
cuboid_face_vertex_indices, cuboid_face_path, cuboid_face_hit_test
adjust_cuboid_visible_back_vertex, adjust_cuboid_front_vertex
adjust_cuboid_front_edge, adjust_cuboid_back_edge_center
move_cuboid_control, move_cuboid_face_by

[自动标注]
set_auto_labeling_mode, set_auto_labeling, set_auto_decode_mode
reset_auto_decode_state, on_auto_decode_timeout, update_auto_labeling_marks

[数据管理]
load_pixmap, load_shapes, set_shape_visible, store_shapes, restore_shape
set_last_label, undo_last_line, undo_last_point, reset_state

[UI 辅助]
override_cursor, restore_cursor, current_cursor, set_cross_line
set_fill_drawing, fill_drawing, get_mode, set_editing

[分组]
gen_new_group_id, merge_group_ids, group_selected_shapes, ungroup_selected_shapes

[其他]
finalise, drawing, editing, is_visible, is_shape_restorable
```

# 矩形边级编辑功能说明

## 1. 功能定位

矩形边级编辑用于扩展 `rectangle` 标注框的边级调整能力。

该功能的主语不是“让目标边拟合某条参考边”，而是：

```text
选中某条矩形边 -> 拖动给出目标坐标 -> 鼠标释放后提交修改
```

它属于对矩形框编辑方式的增强，和已有的滚轮调整、顶点拖拽共同构成矩形框编辑能力。

## 2. 设计语义

旧版“矩形边对齐”采用参考边优先语义：

```text
先选择参考边 -> 再选择目标边 -> 目标边拟合参考边坐标
```

新版“矩形边级编辑”采用目标边优先语义：

```text
先选中目标边 -> 鼠标拖动产生目标坐标 -> 目标边移动到合法坐标
```

因此，鼠标释放点重新成为本次编辑的提交节点，符合项目原生绘制/编辑的交互方向：

```text
用户动作 -> 坐标意图 -> 几何变化 -> mouseRelease 提交
```

## 3. 用户交互流程

1. 开启“矩形边编辑”模式。
2. 鼠标悬停到矩形框某条边。
3. 可编辑边以白色高亮显示。
4. 按下鼠标左键选中该边。
5. 按住左键拖动鼠标。
6. 目标边沿自身法向方向实时移动：
   - 左边 / 右边读取鼠标 `x` 坐标。
   - 上边 / 下边读取鼠标 `y` 坐标。
7. 松开鼠标左键后提交本次修改。
8. 边高亮状态清除，恢复原本显示颜色。

## 4. 状态机

```text
Idle
  -> HoverEdge
      条件：鼠标靠近合法 rectangle 边
      效果：边显示白色 hover 高亮

HoverEdge
  -> EdgeDragging
      条件：鼠标左键按下
      效果：记录 active_edge 与拖动前 points

EdgeDragging
  -> EdgeDragging
      条件：鼠标移动
      效果：按 active_edge 方向读取坐标并实时更新矩形边

EdgeDragging
  -> Commit
      条件：鼠标左键释放
      效果：如 points 发生变化，则 store_shapes + shape_moved

EdgeDragging
  -> Cancel
      条件：按 Esc
      效果：恢复拖动前 points，清理临时状态

Commit / Cancel
  -> Idle
      效果：清理 hover / active / dragging 状态
```

## 5. 坐标规则

矩形边更新由目标边类型决定：

```text
left   -> x_min = mouse.x
right  -> x_max = mouse.x
top    -> y_min = mouse.y
bottom -> y_max = mouse.y
```

更新时保持对侧边不动：

```text
移动 left   时保持 right 不动
移动 right  时保持 left 不动
移动 top    时保持 bottom 不动
移动 bottom 时保持 top 不动
```

## 6. 几何约束

当前实现复用 `rect_edge_alignment.py` 中的几何 helper，保留以下约束：

1. 只作用于 `shape_type == "rectangle"` 的 shape。
2. 支持 2 点矩形和 4 点矩形输入。
3. 内部统一归一化为 `x_min / y_min / x_max / y_max`。
4. 写回时使用规范四点顺序：

```text
top-left -> top-right -> bottom-right -> bottom-left
```

5. 防止矩形翻转。
6. 保证最小宽高，默认 `min_size = 1.0`。
7. 只修改矩形点坐标，不修改 label、group_id、attributes、flags 等标注语义字段。
8. 临时交互状态不写入 JSON。

对应的核心约束可表达为：

```text
left   <= right  - min_width
right  >= left   + min_width
top    <= bottom - min_height
bottom >= top    + min_height
```

当用户拖动越过合法范围时，坐标会被 clamp 到合法边界，而不是产生翻转矩形。

## 7. 提交与撤销

提交粒度与项目原生编辑保持一致：

```text
按下拖动 -> 实时预览/编辑 -> mouseRelease 形成一次提交
```

释放鼠标时：

```text
如果 points 有变化：
    store_shapes()
    shape_moved.emit()
清理临时状态
```

按 Esc 时：

```text
恢复拖动开始前的 points
清理临时状态
不提交 undo / dirty 变化
```

## 8. 视觉反馈

视觉反馈复用项目现有画布叠加绘制方式：

```text
hover edge  -> 白色细线
active edge -> 白色中等线宽
release     -> 清理叠加层，恢复原 shape 颜色
```

不再使用旧版本中的：

```text
reference edge 蓝色虚线
snap edge 绿色粗线
invalid edge 红色提示
```

## 9. 与旧“矩形边对齐”的差异

旧功能关注“边与边之间的拟合关系”：

```text
参考边坐标是目标值
目标边服从参考边
```

新功能关注“用户对某条边的直接编辑”：

```text
鼠标坐标是目标值
目标边服从用户拖动
```

因此新版不再保留以下逻辑：

1. 先选 reference edge。
2. reference / target 兼容性判断。
3. 同轴边吸附。
4. 吸附阈值。
5. release 后保留 reference edge 继续对齐。

## 10. 相关代码

主要涉及文件：

```text
anylabeling/views/labeling/widgets/canvas.py
anylabeling/views/labeling/rect_edge_alignment.py
anylabeling/views/labeling/label_widget.py
tests/test_rect_edge_alignment.py
```

核心职责划分：

```text
canvas.py
  管理 hover / press / drag / release / Esc 状态机和视觉反馈。

rect_edge_alignment.py
  提供矩形边枚举、命中测试、坐标更新、防翻转 clamp、四点写回。

label_widget.py
  提供菜单入口“矩形边编辑”，并处理与绘制模式的互斥。

tests/test_rect_edge_alignment.py
  覆盖几何归一化、边命中、边坐标更新、防翻转和四点写回。
```

## 11. 验证结果

已完成的验证：

```text
python -m py_compile canvas.py rect_edge_alignment.py label_widget.py test_rect_edge_alignment.py
pytest -q tests/test_rect_edge_alignment.py
git diff --check
```

关键测试结果：

```text
21 passed
```

测试中的 NumPy deprecation warning 来自既有距离计算逻辑，不影响本功能结果。

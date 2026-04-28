# X-AnyLabeling 4.0.0 - Label on Selection 功能开发记录

## 功能概述

**Label on Selection**（选中即显）是一个视图功能，启用时仅显示当前选中形状的标签，隐藏所有未选中形状的标签。

**原名称**: Show Selected Label Only  
**新名称**: Label on Selection  
**中文**: 选中即显

---

## 开发历程

### 1. 初始状态（4.0.0-beta.4）

- 保留了 `show_selected_label_only` 属性
- 但移除了与 LabelDisplayManager 的集成
- 简化了 paintEvent 处理逻辑
- **遗漏了关键检查**：mouseReleaseEvent 和 select_shape_point

### 2. 问题发现

**问题 1**: Point 类型无法选中  
**原因**: `selected_vertex()` 分支只处理 `cuboid` 和 `rotation`，遗漏 `point`  
**影响**: Point 类型对象无法显示标签

**问题 2**: 其他形状类型也无法选中  
**原因**: `select_shape_point` 方法逻辑不完整  
**影响**: rectangle、polygon 等类型无法通过点击选中

**问题 3**: 立方体面选择缺失  
**原因**: 没有处理 `selected_cuboid_face()` 分支  
**影响**: Cuboid 面无法点击选中

### 3. 修复过程

#### 修复 1: 统一顶点选择处理
- 移除 point 类型的特殊分支
- 统一处理所有类型的顶点选择
- 保持 label_on_selection 模式行为一致性

#### 修复 2: 添加缺失分支
- 添加 `selected_cuboid_face()` 分支
- 添加普通形状选择逻辑（else 分支）
- 支持 point、line、linestrip、cuboid、rectangle、polygon 等

#### 修复 3: 移除粘滞选中
- 原设计: 点击空白区域保持选中（粘滞选中）
- 新设计: 点击空白区域取消选中（快速检查模式）
- 修改 `deselect_shape()` 移除保护逻辑
- 修改 `mouseReleaseEvent` 和 `select_shape_point` 中的重复点击处理

---

## 最终代码结构

### select_shape_point 方法

```python
def select_shape_point(self, point, multiple_selection_mode):
    """Select the first shape created which contains this point."""
    if self.selected_vertex():  # 顶点选择
        index, shape = self.h_vertex, self.h_hape
        if shape.shape_type == "cuboid":
            # cuboid 特殊处理
            ...
            return
        # 统一处理所有其他类型的顶点选择
        shape.highlight_vertex(index, shape.MOVE_VERTEX)
        self.set_hiding()
        if shape not in self.selected_shapes:
            self.selection_changed.emit([shape])
            self.h_shape_is_selected = False
        else:
            # 重复点击取消选中
            self.h_shape_is_selected = True
        self.calculate_offsets(point)
        return
    elif self.selected_cuboid_face():  # 立方体面选择
        shape = self.h_hape
        self.set_hiding()
        if shape not in self.selected_shapes:
            self.selection_changed.emit([shape])
            self.h_shape_is_selected = False
        else:
            self.h_shape_is_selected = True
        self.calculate_offsets(point)
        return
    else:  # 普通形状选择
        for shape in reversed(self.shapes):
            # 检测各种形状类型
            if shape_selectable:
                self.set_hiding()
                if shape not in self.selected_shapes:
                    self.selection_changed.emit([shape])
                    self.h_shape_is_selected = False
                else:
                    self.h_shape_is_selected = True
                self.calculate_offsets(point)
                return
    self.deselect_shape()  # 点击空白区域取消选中
```

### 三层保护机制（已移除粘滞选中）

1. **mouseReleaseEvent**: 点击已选中对象取消选中
2. **select_shape_point**: 重复点击取消选中
3. **deselect_shape**: 点击空白区域取消选中（无保护）

---

## 关键文件和行号

| 文件 | 行号 | 功能 |
|------|------|------|
| `anylabeling/views/labeling/widgets/canvas.py` | 186 | 属性初始化 `label_on_selection` |
| `anylabeling/views/labeling/widgets/canvas.py` | 1308-1314 | mouseReleaseEvent 点击处理 |
| `anylabeling/views/labeling/widgets/canvas.py` | 1408-1510 | select_shape_point 完整方法 |
| `anylabeling/views/labeling/widgets/canvas.py` | 2076-2087 | deselect_shape（无保护） |
| `anylabeling/views/labeling/widgets/canvas.py` | 2578-2591 | paintEvent 标签过滤 |
| `anylabeling/views/labeling/label_widget.py` | 1289-1298 | 菜单 Action 定义 |
| `anylabeling/views/labeling/label_widget.py` | 4533-4578 | shape_selection_changed |
| `anylabeling/views/labeling/label_widget.py` | 5461-5465 | set_canvas_params |
| `anylabeling/configs/xanylabeling_config.yaml` | 27 | 默认配置 `label_on_selection: false` |

---

## 行为规则

### 状态转换

| 用户操作 | 行为 |
|---------|------|
| 点击未选中形状 | 选中该形状，显示标签 |
| 点击已选中形状 | **取消选中**，标签消失 |
| 点击空白区域 | **取消选中**，标签消失 |
| Ctrl+点击多选 | 添加选中 |
| 切换编辑/绘制模式 | 取消选中 |

### 与 show_labels 的关系

| show_labels | label_on_selection | 行为 |
|-------------|-------------------|------|
| False | 任意 | 不显示任何标签 |
| True | False | 显示所有标签 |
| True | True | **只显示选中形状的标签** |

---

## 技术文档

**文档位置**: `docs/Label on Selection.md`  
**版本**: 4.0  
**更新日期**: 2026-04-23

文档包含：
- 功能概述
- 状态管理机制
- 核心实现代码
- 行为控制逻辑
- 绘制过滤逻辑
- 选择处理修复（顶点/面/普通形状）
- 完整调用链
- 验证清单

---

## 与 3.3.0 版本的差异

| 维度 | 3.3.0 | 4.0.0 |
|------|-------|-------|
| **状态载体** | `DisplayMode.SELECTED_ONLY` (枚举) + `show_selected_label_only` (布尔) | `label_on_selection` (布尔) |
| **Manager** | LabelDisplayManager | 直接 Canvas 属性 |
| **绘制路径** | 双路径（原始 + 智能标签） | 单路径（原始标签过滤） |
| **选择行为** | 粘滞选中（点击空白保持） | 快速检查（点击空白取消） |
| **代码复杂度** | 高（6个模块） | 低（属性 + 过滤逻辑） |

---

## 已知问题

1. **快捷键冲突**: `edit_polygon: B` 和 `delete_polygon: Delete` 可能没有反应
   - 原因: action 的 enabled 状态控制
   - 位置: `label_widget.py` 第 861-889 行

2. **初始化不一致**: Canvas `__init__` 硬编码 `label_on_selection = False`
   - 但配置可能为 True
   - 需要确认启动时是否同步

---

## 未来扩展

### Focus 模式（预留）
- 显示选中形状 + 同组形状的标签
- 需要引入轻量级模式枚举或 LabelDisplayManager 基座

### 可配置行为
- 粘滞选中 vs 快速检查
- 通过配置开关切换

---

## 调试技巧

### 添加日志位置
```python
# mousePressEvent
print(f"mousePressEvent: pos={pos}, scale={self.scale}")

# select_shape_point
print(f"select_shape_point: total shapes={len(self.shapes)}")

# paintEvent
print(f"paintEvent: label_on_selection={self.label_on_selection}")
```

### 验证清单
1. 启用功能时只显示选中标签
2. 点击空白区域取消选中
3. 重复点击已选中对象取消选中
4. 所有形状类型（point、rectangle、polygon、cuboid）可正常选中
5. 禁用功能后恢复正常行为

---

## 开发注意事项

1. **不要恢复粘滞选中逻辑** - 当前设计是快速检查模式
2. **保持三层保护机制** - 但都是"取消选中"而非"保持选中"
3. **统一处理所有形状类型** - 避免特殊分支导致遗漏
4. **更新文档同步** - 代码变更时同步更新 `docs/Label on Selection.md`

---

*记录创建: 2026-04-23*  
*适用版本: X-AnyLabeling 4.0.0-beta.4*

# 功能12：shapes与selected_shapes状态同步 — 迁移分析报告

- **难度**: ⭐⭐ | **影响级别**: 🟡 需在ShapeManager中适配
- **源文件**: 无独立文件，嵌入 `canvas.py` (~40行)
- **性质**: 防御性修复，确保shapes与selected_shapes列表一致性

---

## 1. 依赖与导入调整

### 独立模块文件
无。属于ShapeManager内部防御性增强。

### 导入变更
- 无新增导入

### 外部依赖
- 无

---

## 2. 集成点分析

### 原始修改点（旧canvas.py中）

**修改点1**: `load_shapes()` 中重置 `selected_shapes = []`
- **3.3.8现状**: `canvas_adapter.load_shapes()` (L796-805) 调用 `ShapeManager.load_shapes(replace=True)`
- **需验证**: ShapeManager.load_shapes(replace=True) 是否清空 `_selected_shapes`
- **ShapeManager.load_shapes()** 内部调用 `self.clear()` → 需确认clear()是否清空_selected_shapes

**修改点2**: `delete_selected()` 中防御性检查 `if shape in self.shapes`
- **3.3.8现状**: `canvas_adapter.delete_selected()` (L949-958) 使用列表推导 `[s for s in self.shapes if s not in deleted_shapes]`
- **已含防御性**: ✅ 不会出现shape不在shapes中的问题

**修改点3**: 新增 `_check_selection_consistency()` 方法
- **3.3.8现状**: ShapeManager通过信号机制维护一致性，但缺少显式的一致性检查
- **需新增**: 在ShapeManager中添加防御性一致性检查

### 目标文件: `graphics/managers/shape_manager.py`

新增方法:
```python
def _check_selection_consistency(self):
    """检查selected_shapes是否与shapes列表一致"""
    # 移除已不在shapes中的selected_shapes
    self._selected_shapes = [s for s in self._selected_shapes if s in self._shapes]
```

调用时机:
- `remove_shape()` 后
- `clear()` 后
- `load_shapes()` 后

---

## 3. Canvas API 兼容性

| 旧API调用 | 3.3.8适配方式 | 状态 |
|-----------|-------------|------|
| `self.selected_shapes = []` | ShapeManager._selected_shapes 清空 | 需验证clear()行为 |
| `if shape in self.shapes` 检查 | 列表推导已含防御性 | ✅ 已解决 |
| `_check_selection_consistency()` | 需在ShapeManager新增 | ❌ 待添加 |

### 3.3.8 ShapeManager 现有一致性保证分析
- `remove_shape(shape)`: 从 `_shapes` 移除shape，但**未检查**是否也在 `_selected_shapes` 中
- `clear()`: 清空 `_shapes`，但需确认是否也清空 `_selected_shapes`
- **风险**: 如果shape被remove但仍在selected_shapes中，后续操作可能导致ValueError

### 建议的防御性增强
1. `remove_shape()` 中添加: `if shape in self._selected_shapes: self._selected_shapes.remove(shape)`
2. `clear()` 中添加: `self._selected_shapes.clear()`
3. 新增 `_check_selection_consistency()` 方法

---

## 4. 独立文件拆解建议

| 文件 | 状态 | 操作 |
|------|------|------|
| 无需独立文件 | — | 直接修改 `graphics/managers/shape_manager.py` |

**不建议独立**: 属于ShapeManager内部数据一致性保证，不应暴露为外部模块。

### 迁移工作量估算
- 复制文件：0个
- 修改文件：1个（shape_manager.py）
- 新增代码：~20行（防御性检查方法 + 调用点）
- 预计耗时：0.5-1小时
- **优先级**: 高 — 应在其他功能迁移之前完成，防止后续操作触发一致性问题

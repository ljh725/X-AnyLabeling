# 功能8：循环选择重叠Shapes — 迁移分析报告

- **难度**: ⭐⭐⭐ | **影响级别**: 🟡 适配（修改adapter已有方法）
- **源文件**: 无独立文件，嵌入 `canvas.py` (~85行)
- **核心变更**: `select_shape_point()` 方法重写

---

## 1. 依赖与导入调整

### 独立模块文件
无现有独立文件。

### 新增状态变量（canvas_adapter.py `__init__`）
```python
self._cycle_select_point = None       # 上次点击位置
self._cycle_select_candidates = []    # 当前位置的候选shapes（按面积排序）
self._cycle_select_index = 0          # 当前循环索引
```

### 外部依赖
- 无

---

## 2. 集成点分析

### canvas_adapter.py — `select_shape_point()` 方法替换
- **当前实现** (L865-922): "后来者优先"策略 — `for shape in reversed(self.shapes)` 找到第一个包含点的shape
- **新实现**: "面积小优先 + 连续点击循环"策略:
  1. 收集所有包含该点的可见shapes
  2. 按面积从小到大排序
  3. 如果点击位置与上次相同（阈值内），循环切换到下一个候选
  4. 如果点击位置变化，重置候选列表，选择面积最小的

### 核心逻辑
```
def select_shape_point(self, point, multiple_selection_mode):
    # 1. 收集候选
    candidates = [s for s in self.shapes 
                  if self.is_visible(s) and s.contains_point(point)]
    
    # 2. 按面积排序（小→大）
    candidates.sort(key=lambda s: s.bounding_rect().width() * s.bounding_rect().height())
    
    # 3. 判断是否与上次同一位置
    if self._is_same_point(point, self._cycle_select_point):
        # 循环切换
        self._cycle_select_index = (self._cycle_select_index + 1) % len(candidates)
    else:
        # 新位置，重置
        self._cycle_select_candidates = candidates
        self._cycle_select_index = 0
    
    # 4. 选中当前索引的shape
    ...
```

### canvas_adapter.py — `__init__`
- 新增3个状态变量（见上方）

---

## 3. Canvas API 兼容性

| 旧API调用 | 3.3.8适配方式 | 状态 |
|-----------|-------------|------|
| `shape.contains_point(point)` | Shape数据对象方法，通用 | ✅ 兼容 |
| `shape.bounding_rect()` | Shape数据对象方法，通用 | ✅ 兼容 |
| `self.is_visible(shape)` | adapter方法 → `ShapeManager.is_shape_visible()` | ✅ 兼容 |
| `self.selection_changed.emit()` | adapter信号 | ✅ 兼容 |
| `self.calculate_offsets(point)` | adapter已有方法 | ✅ 兼容 |
| `self.set_hiding()` | adapter已有方法 | ✅ 兼容 |

**此功能修改adapter层的已有方法，不涉及QGraphicsView底层，API全部兼容。**

### 需保持的兼容行为
- 顶点悬停优先（`self.selected_vertex()` 分支保持不变）
- `multiple_selection_mode` 的Ctrl多选逻辑保持不变
- rotation类型的特殊处理保持不变

---

## 4. 独立文件拆解建议

| 方案 | 说明 | 推荐 |
|------|------|------|
| 方案A: 独立文件 | 新建 `widgets/cycle_select_manager.py` | ⭐ 推荐 |
| 方案B: 内联修改 | 直接修改 `canvas_adapter.select_shape_point()` | 简单但不够干净 |

### 方案A详细设计
新建 `widgets/cycle_select_manager.py` (~60行):
```python
class CycleSelectManager:
    """循环选择管理器 — 管理重叠shapes的循环选择状态"""
    
    def __init__(self, distance_threshold=5.0):
        self._last_point = None
        self._candidates = []
        self._index = 0
        self._threshold = distance_threshold
    
    def select(self, point, shapes, visible_checker, scale=1.0):
        """返回应选中的shape，支持循环"""
        ...
    
    def reset(self):
        """重置状态"""
        ...
```

**优点**: 可独立测试，不污染adapter，状态管理清晰

### 迁移工作量估算
- 新建文件：1个（建议）或 0个（内联）
- 修改文件：1个（canvas_adapter.py）
- 修改代码：~85行（替换select_shape_point + 新增状态变量）
- 预计耗时：1-2小时

# 03 · 优先级排序拾取模式
#### Priority-Sorted Shape Hit Candidates

> 用「决策转排序（Decision → Sort）」范式取代旧的 `reversed + 首次命中` 策略：对每个候选 shape 计算 4 维优先级元组，按字典序排序，让"抓顶点 > 抓边 > 抓小对象 > 抓栈顶"在排序中自然生效。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

密集/嵌套标注场景下，旧的选择策略经常**选错或选不到想要的对象**：

```
场景1：大背景框套小目标框
  ┌─────────────────────────┐
  │  ┌───┐                  │   点击小框 → 旧策略选到大框（大框后创建？不，
  │  │ A │      B           │   实际是先创建大框，所以旧策略 reversed 会选
  │  └───┘                  │   到后创建的小框——但如果小框先创建呢？）
  └─────────────────────────┘

场景2：关键点压在矩形框上
  ┌──────────────┐
  │  •(关键点)   │   点击关键点 → 想抓关键点的顶点编辑，
  │              │   旧策略可能选到整个矩形框
  └──────────────┘

场景3：多个重叠框
  ┌────┐
  │ ┌──┼──┐    想选中间那个，旧策略只能选到最后创建的
  └─┼──┘  │
    └─────┘
```

旧策略 `reversed(shapes) + 首次 contains 命中即返回` 只能选到"最后创建且整体命中"的对象，**无法表达"顶点优先于边、边优先于整体、小对象优先于大对象"这些交互语义**。

---

## 方案：决策转排序

核心思想来自我沉淀的 [PATTERN_CARD_001](../meth-050_note_模式卡片001_决策转排序.md)——**把多重 if-elif 决策转成可比较的元组排序**。

对每个候选 shape 计算一个 **4 元组优先级**，最后按元组字典序升序排序（越小越优先），返回排好序的 `[shape, ...]` 列表：

```python
# anylabeling/views/labeling/widgets/canvas.py:515-523
# 优先级元组 priority = (级别, 距离, 面积, -stack_index)，全部升序(越小越优先)：
#   - 级别 0: 附近顶点(可抓取编辑点)——最高优先
#   - 级别 1: 附近可编辑边(可双击加点)
#   - 级别 2: 整体命中(contains_point)——兜底
#   - 同级别下: 距离更近者优先；仍相同时面积更小者优先
#     (嵌套场景下小对象优先于大对象)；最后后创建者(栈顶)优先。
```

### 优先级元组的四条设计准则

| 准则 | 体现 | 代码 |
|------|------|------|
| **① 语义层级** | 级别（离散）放第一维：抓顶点 > 抓边 > 抓整体 | `priority = (0/1/2, ...)` |
| **② 语义失效** | 级别 2 整体命中时"距离"无意义，填 `area`；第三维填 `0.0` | `(2, area, 0.0, -stack_index)` |
| **③ 代理变量** | 用"面积"代理"具体性"——嵌套场景小对象面积小自然排前 | `area = rect.width() * rect.height()` |
| **④ 兜底兼容** | 最后一维 `-stack_index`，等价于旧的 `reversed` 行为 | `-stack_index` |

### 核心算法

```python
# anylabeling/views/labeling/widgets/canvas.py:507-596
def _shape_hit_candidates(self, point):
    """Return shapes under a point in interaction priority order."""
    candidates = []
    epsilon = self.epsilon / self.scale
    for stack_index, shape in enumerate(self.shapes):
        if not self.is_shape_interactive(shape):
            continue
        rect = shape.bounding_rect()
        area = max(0.0, rect.width()) * max(0.0, rect.height())

        # 级别 0：顶点命中（最高优先）
        vertex_distance = ...  # nearest_vertex / nearest_cuboid_control
        if vertex_distance is not None:
            priority = (0, vertex_distance, area, -stack_index)
            candidates.append((priority, shape))
            continue

        # 级别 1：边命中（可双击加点）
        if not shape.locked and shape.can_add_point() ...:
            edge_index = shape.nearest_edge(point, epsilon)
            if edge_index is not None:
                edge_distance = utils.distance_to_line(point, line)
                priority = (1, edge_distance, area, -stack_index)
                candidates.append((priority, shape))
                continue

        # 级别 2：整体命中（兜底）
        if hit:
            priority = (2, area, 0.0, -stack_index)
            candidates.append((priority, shape))

    candidates.sort(key=lambda item: item[0])  # 字典序排序
    return [shape for _, shape in candidates]
```

**关键**：整个算法**零 if-elif 决策链**来决定"选谁"——决策被编码进元组，由排序统一裁决。新增一种交互语义只需加一个元组维度，不需要改控制流。

---

## 技术亮点

### 1. 面积作为"具体性"代理变量

嵌套场景下（大框套小框），用户几乎总是想选**内层的小对象**。直接用 `area` 作为第三维度：

```python
# 小对象 area 小 → 元组第三维小 → 排序靠前
priority = (2, area_small, 0.0, -stack_index)  # 内层小框
priority = (2, area_large, 0.0, -stack_index)  # 外层大框
# 小框自然胜出
```

### 2. 三入口统一复用

三个消费者都**取排序后的首个候选**，行为一致：

| 入口 | 代码位置 | 行为 |
|------|---------|------|
| 悬停高亮 | `canvas.py:1021` `for shape in self._shape_hit_candidates(pos)` | 遍历候选设高亮与光标 |
| 点击选择 | `canvas.py:1708` `select_shape_point` 的 else 分支 | 取首个候选 emit `selection_changed` |
| 双击编辑 | `canvas.py:1628` `mouseDoubleClickEvent` | 取首个候选 emit `edit_label_requested` |

**额外复用**：矩形边对齐功能的 `_rect_edge_hit_candidate`（`canvas.py:3911`）docstring 明确写"Candidates are ranked like `_shape_hit_candidates`"，复用了同样的排序语义。

### 3. 兜底维度保证向后兼容

最后一维 `-stack_index` 等价于旧的 `reversed(shapes)` 行为。当所有其他维度都相同时（同级别、同距离、同面积），后创建的对象（stack_index 大，`-stack_index` 小）排前面——与旧行为完全一致，保证不破坏现有用户体验。

---

## 代码定位

| 位置 | 行数 | 说明 |
|------|------|------|
| [`canvas.py:507-596`](../../anylabeling/views/labeling/widgets/canvas.py) | ~90 | `_shape_hit_candidates` 核心算法 |
| [`canvas.py:1021`](../../anylabeling/views/labeling/widgets/canvas.py) | — | 悬停高亮调用点 |
| [`canvas.py:1628`](../../anylabeling/views/labeling/widgets/canvas.py) | — | 双击编辑调用点 |
| [`canvas.py:1708`](../../anylabeling/views/labeling/widgets/canvas.py) | — | 点击选择调用点 |
| [`canvas.py:3911`](../../anylabeling/views/labeling/widgets/canvas.py) | — | 矩形边对齐复用点 |
| [`shape.py:96`](../../anylabeling/views/labeling/shape.py) | — | `locked` 默认值（False，守卫为 no-op） |

---

## 测试覆盖

[`tests/test_shape_hit_candidates.py`](../../tests/test_shape_hit_candidates.py)（321 行，**不依赖 PyQt6**，纯 Python 复刻算法验证）：

| 测试场景 | 验证点 |
|---------|--------|
| `test_nested_small_over_big` | 嵌套大框套小框，选小框 |
| `test_nested_stack_order_fair` | 即便大框栈顶仍选小框（证明靠面积非栈序） |
| `test_vertex_beats_contains` | 顶点(级别0)优先于整体命中(级别2) |
| `test_nearest_vertex_wins` | 两对象顶点都在附近，选距离近的 |
| `test_empty_point` | 空白点击返回空列表 |
| `test_priority_tuple_ordering` | 直接验证 4 元组字典序 |

---

## 设计方法论沉淀

这个功能的设计思路被我抽象成了一张可复用的「模式卡片」：

- 📇 [**PATTERN_CARD_001 决策转排序**](../meth-050_note_模式卡片001_决策转排序.md) — 把多重 if-elif 决策转成可比较的元组排序的通用模板，含多目标选择实例

---

## 截图

> `[截图待补]` — 计划补充：嵌套框选择对比（旧策略 vs 新策略）、顶点优先于整体命中的演示

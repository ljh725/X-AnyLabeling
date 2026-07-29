# 问题重表征：当前多目标选择

> 把“用户点了一个位置，我该选哪个 shape？”从流程判断问题，改写成候选记录排序问题。

---

## 1. 原始问题

```text
用户点了一个位置，我该选哪个 shape？
```

直觉上很容易写成流程式判断：

```text
如果点到顶点，选顶点所属 shape；
否则如果点到边，选边所属 shape；
否则如果点到多个框，选某个框；
否则按栈序选。
```

这种问法会把规则藏进 `if-elif-else` 的执行顺序里。规则越多，控制流越长，后续扩展也越容易互相影响。

---

## 2. 重表征

```text
一次点击会产生一组候选 shape。
每个候选 shape 都可以被描述为一条可排序记录。
选择问题 = 对候选记录排序，取第一名。
```

也就是：

```text
点击选择问题
→ 多候选竞争问题
→ 候选记录排序问题
→ priority tuple 设计问题
```

---

## 3. 候选表

```text
候选 shape | 命中类型 | 距离 | 面积 | 栈序 | 是否可交互 | priority
A          | 顶点     | 1.4  | 400  | 0    | 是         | (0, 1.4, 400, 0)
B          | 整体     | -    | 6400 | 1    | 是         | (2, 6400, 0, -1)
C          | 边       | 0.8  | 900  | 2    | 是         | (1, 0.8, 900, -2)
```

表格里的列，就是原本隐含在判断流程里的规则。

---

## 4. 决策键

当前 X-AnyLabeling 的选择优化可以表达为：

```python
priority = (级别, 主排序值, 次排序值, -stack_index)
```

具体取值：

| 命中类型 | priority |
|---------|----------|
| 顶点 | `(0, vertex_distance, area, -stack_index)` |
| 可编辑边 | `(1, edge_distance, area, -stack_index)` |
| point / line / linestrip 近邻 | `(1, distance, area, -stack_index)` |
| 整体命中 | `(2, area, 0.0, -stack_index)` |

排序后取第一名：

```python
candidates.sort(key=lambda item: item.priority)
winner = candidates[0]
```

---

## 5. 思维转换

不要先问：

```text
我该写几个 if？
```

而是先问：

```text
候选是谁？
每个候选有哪些可比较字段？
哪些字段优先级最高？
平手时用什么兜底？
```

这就是本案例里的核心转换：

```text
隐式控制流
→ 显式候选表
→ 显式 priority
→ 通用 sort 消费
```


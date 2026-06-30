# 问题重表征：通用模板

> 把“我该先判断什么？”改写成“有哪些候选？每个候选有哪些字段？字段如何决定结果？”

---

## 1. 原始问题形态

很多问题表面上长这样：

```text
面对多个可能对象 / 动作 / 规则 / 任务，我该选哪个？先处理哪个？显示哪个？
```

直觉写法通常是：

```text
如果满足 A，做这个；
否则如果满足 B，做那个；
否则如果满足 C，再做另一个。
```

这会让决策逻辑依附在控制流顺序上。顺序本身变成了隐式知识。

---

## 2. 通用重表征

```text
一个决策点会产生一组候选项。
每个候选项都可以被描述成结构化记录。
决策逻辑 = 根据记录字段构造 decision_key。
最终动作 = sort / filter / group / max / min 后消费。
```

通用表格：

```text
候选 | 类型 | 关键度量 | 约束状态 | 业务优先级 | 稳定兜底 | decision_key
```

---

## 3. 通用代码骨架

```python
records = collect_candidates(context)

for record in records:
    record.decision_key = (
        type_rank(record),
        constraint_rank(record),
        metric_value(record),
        business_rank(record),
        tie_breaker(record),
    )

records.sort(key=lambda r: r.decision_key)
result = consume(records)
```

这里的关键不是 `sort`，而是把规则变成字段，把字段顺序变成优先级。

---

## 4. 应用示例

### 校验问题

```text
问题：先显示哪个 issue？

issue 候选 | 严重级别 | 是否当前文件 | 规则优先级 | 文件顺序 | shape序号 | decision_key
```

```python
decision_key = (
    0 if issue.severity == "error" else 1,
    0 if issue.file_path == current_file else 1,
    rule_priority[issue.rule_name],
    file_index[issue.file_path],
    issue.shape_index,
)
```

### 任务调度

```text
问题：先执行哪个任务？

task 候选 | 是否阻塞 | 截止时间 | 用户优先级 | 创建时间 | id | decision_key
```

```python
decision_key = (
    0 if task.is_blocking else 1,
    task.deadline,
    task.user_priority,
    task.created_at,
    task.id,
)
```

### 导出策略

```text
问题：哪些文件先导出？

file 候选 | 是否有错误 | 是否被筛选命中 | 图片是否存在 | 文件大小 | 原始顺序 | decision_key
```

```python
decision_key = (
    0 if file.has_error else 1,
    0 if file.in_filtered_set else 1,
    0 if file.image_exists else 1,
    file.size,
    file.original_index,
)
```

### UI 状态选择

```text
问题：当前显示哪个面板？

panel 候选 | 用户是否显式选择 | 是否有数据 | 是否有错误 | 最近使用时间 | decision_key
```

```python
decision_key = (
    0 if panel.user_selected else 1,
    0 if panel.has_data else 1,
    0 if panel.has_error else 1,
    -panel.last_used_time,
)
```

---

## 5. 迁移口诀

```text
流程判断 → 候选建模
规则先后 → 字段顺序
特殊情况 → 字段取值
最终选择 → sort / filter / group / max / min
```

更压缩的版本：

```text
if-else 链
→ 候选表
→ 决策键
→ 通用消费
```

---

## 6. 自检问题

遇到复杂判断时，先问：

```text
这件事里的候选是谁？
我要选一个、排个序、过滤一批，还是分组展示？
每个候选能不能表示成一条记录？
原来的判断顺序能不能变成字段优先级？
最终动作能不能用通用操作消费？
```

能回答这些问题，就说明这个问题很可能可以从“隐式控制流”重表征为“显式数据结构”。


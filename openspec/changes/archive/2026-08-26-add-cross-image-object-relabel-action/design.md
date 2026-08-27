## Context

参见 [proposal.md](proposal.md) 的动机和
[cross-image-object-relabel spec](specs/cross-image-object-relabel/spec.md)
的行为契约。

项目已有两个相关基础：Shape 顶层持久 `xanylabeling_shape_id`；
`widgets/label_batch.py` 已实现纯 Python 的标签变更计划、预检、暂存、备份、
源文件指纹检查、原子提交和恢复清单。现有 `BatchMigrationEngine` 的转换入口
仍与全局 `rename_map/delete_labels` 耦合，结果以文件计数为主，不能直接表达
对象级成功、删除、冲突和失败。跨图对象标记仓库、Canvas 标记模式和标记
视觉目前均不存在，需要作为本 change 的前半段实现。

实现需要跨越标记状态、纯 Python 批量内核和 PyQt UI，但不能把写盘逻辑
放进 Canvas，也不能在 `label_widget.py` 中重新实现事务。该文件和
`canvas.py` 都是高成本文件，接入时必须先精确定位并批量完成窄范围修改。

## Goals / Non-Goals

**Goals:**

- 建立不可变、可序列化、无 Qt 依赖的对象引用和对象改标计划。
- 建立独立于 Canvas 普通选中的会话级跨图标记仓库和明确交互状态。
- 让标记状态只承担目标收集，由独立命令承担修改副作用。
- 在不复制事务实现的前提下复用标签批量迁移的安全写盘能力。
- 同时返回文件级和对象级结果，使标记清理与失败重试准确可测。
- 保持全局标签重命名现有 API 和行为兼容。

**Non-Goals:**

- 不把跨图标记状态持久化到 JSON、SQLite 或 sidecar。
- 不改变、补齐或迁移 `xanylabeling_shape_id`。
- 不实现按 group 自动扩展、模糊匹配、多目标标签或其他字段批量修改。
- 不把 Dataset Index 变成数据真相或对象写入目标。
- 不在第一版增加多个独立 UI 流程。

## Decisions

### Decision 1: 使用独立的对象级纯 Python 领域模型

新增 `widgets/object_relabel.py`，放置不依赖 PyQt 的数据模型和转换逻辑：

```text
MarkedObjectRef
├── project_id
├── image_id
├── shape_id
└── display_summary（不参与定位）

ObjectRelabelPlan
├── project_id
├── target_label
└── targets_by_annotation_path

ObjectPreflightSummary
ObjectMutationResult
ObjectRelabelResult
```

所有计划和引用使用 frozen dataclass 或等价不可变结构。`shape_id` 字段映射
JSON 顶层的 `xanylabeling_shape_id`；运行时 `Shape` 地址和 Canvas 下标不
进入领域模型。

对象转换函数接收一个 JSON 映射、目标 Shape ID 集合和目标标签，返回新
数据及逐对象结果。函数必须深复制输入并验证 `shapes` 结构，不原地修改
调用者数据。

**Alternatives considered:** 把目标 ID 塞进 `LabelChangePlan.rename_map`。
两者一个按标签集合匹配，一个按对象身份匹配，混用会重新引入“改到所有
同标签对象”的风险，因此采用独立计划。

### Decision 2: 新建唯一的会话级标记仓库

在 `widgets/object_relabel.py` 中新增纯 Python `MarkedObjectStore`，作为跨图
活动标记的唯一所有者。它保存 `MarkedObjectRef`，提供：

```text
toggle(ref)
contains(key)
snapshot()
refs_for_image(project_id, image_id)
remove(key) / remove_many(keys)
clear()
counts()
```

仓库只存在于当前 LabelingWidget 会话，不写 JSON、SQLite 或 sidecar。UI
集成层在启动请求时取得 `tuple[MarkedObjectRef, ...]` 不可变快照。

改标完成后，集成层按结构化对象结果调用现有标记模块的精确移除能力：

```text
succeeded / deleted → remove(object_key)
conflict / failed   → keep(object_key)
cancelled           → keep all
```

仓库发出变化结果由 Qt 适配层更新 action 计数、状态栏和当前 Canvas 标记
集合。改标功能和 Canvas 均不维护第二份跨图集合。

**Alternatives considered:** 复用 `canvas.selected_shapes`。它只包含当前图片
对象，且移动、删除、复制和分组都把它当成编辑选择，无法承担跨图意图，
因此采用独立会话仓库。

### Decision 3: Canvas 只识别标记手势并绘制当前图片 overlay

Canvas 增加 `batch_mark_mode`、当前图片 `marked_shape_ids` 和一个
`batch_mark_toggle_requested(Shape)` 信号。它不保存跨图引用，也不写文件。

鼠标按下时记录候选 Shape、位置以及是否命中顶点/活动边；释放时只有候选
一致、移动未超过现有拖动阈值、且未开始顶点/边编辑，才发出 toggle 请求。
普通选择仍按现有逻辑执行。空白单击、拖动、缩放和边/顶点编辑不发信号。

Canvas 在 Shape 正常绘制之后按 `xanylabeling_shape_id` 绘制橙色角标或外层
描边。overlay 不修改 Shape 的 QColor、selected、visible 或序列化字段，且
绘制层级与活动边、QA overlay 分离。`Shape.bounding_rect()` 可能返回几何缓存，
因此 overlay 必须用其副本或 `adjusted()` 返回值计算外扩矩形，禁止原地调用
`adjust()` 造成每次重绘累积放大。

**Alternatives considered:** 给 Shape 增加持久或瞬态 `marked` 字段。持久字段
会污染 JSON，瞬态字段会在 reload/copy 路径产生继承歧义，因此由 Canvas
根据当前图片 ID 集合绘制。

### Decision 4: 在 UI 边界解析文件路径，领域计划只接受项目内目标

标记条目的 `image_id` 先通过项目现有路径解析规则映射到 JSON。计划构建器
必须规范化路径、验证条目属于当前 `project_id`，并拒绝解析到当前标注根
目录之外的路径。

跨图批处理、标签迁移和恢复操作共用同一个规范化写入根：优先使用项目
`output_dir`，否则使用导入目录，最后才从图片目录计算公共父目录。递归目录
因此会落在同一把项目级写入锁下，不会因为当前图片所在的子目录不同而产生
两套互斥状态。

同一文件的 Shape ID 去重后进入 `targets_by_annotation_path`。显示摘要不
影响路径或身份解析。

**Alternatives considered:** 让后台 worker 自行猜测图片和 JSON 的对应关系。
这会在 `output_dir`、图片/JSON 分目录及同名文件场景产生歧义，因此在拥有
完整项目上下文的 UI/计划构建边界完成解析。

### Decision 5: 对象预检直接读取快照指定文件

对象快照已经精确给出目标文件，预检不执行按标签的全数据集扫描，也不依赖
Dataset Index 选择候选。每个文件重新读取 JSON，并构建一次
`shape_id → shape` 映射：

```text
唯一命中且标签不同 → changeable
唯一命中且标签相同 → unchanged
没有命中           → deleted
目标身份冲突       → conflict（整文件不暂存）
读取或结构异常     → failed（整文件不暂存）
```

一个文件出现目标身份冲突时整文件失败，以免同一次文件替换混合可靠与不可靠
定位。非目标对象不参与改标，但转换后验证会保证它们没有被改变。

**Alternatives considered:** 信任 Dataset Index 或内存 Shape。两者都可能比
磁盘旧，不能作为破坏性写入的正确性来源。

### Decision 6: 抽取通用 JSON 事务层，保留现有标签迁移外观

从 `BatchMigrationEngine` 中抽取或增加一个向后兼容的通用暂存入口，输入为：

```text
明确的源文件列表
按文件转换回调或转换请求
可写入 manifest 的领域结果元数据
```

通用事务层继续唯一负责：

- 事务目录和同卷临时文件；
- JSON 写入与重新解析；
- 原文件备份；
- 原始指纹记录和提交前复核；
- 数据集写锁；
- 原子替换；
- manifest 和恢复。

现有 `BatchMigrationEngine.preflight/stage/commit/restore` API 保留，原有标签
迁移通过适配器调用通用事务层，避免影响尚在进行的
`optimize-annotation-visual-encoding-and-label-batch-operations` change。
对象级引擎提供自己的 `preflight/stage/commit` 外观，并把逐对象状态写入
事务元数据，从实际提交结果生成 `ObjectRelabelResult`。

**Alternatives considered:** 复制一份对象专用备份和 `os.replace` 实现。
重复实现会让恢复、安全修复和并发策略发生漂移，因此不采用。

### Decision 7: 预检与暂存可取消，提交不可取消

后台 worker 只负责纯 Python 预检、暂存和提交。取消标志在逐文件预检和
暂存边界检查；一旦进入持有数据集写锁的提交阶段，就忽略取消并完成既定
文件替换。UI 必须显示当前阶段。

当前文件 dirty 处理在 worker 启动前完成。保存失败或用户取消时，不创建
事务目录，也不改变标记。

**Alternatives considered:** 提交期间响应取消。逐文件替换无法提供跨文件
原子性，中途取消只会制造语义不清的半完成状态，因此只允许提交前取消。

### Decision 8: 对象结果是标记同步的唯一依据

文件提交成功不等于快照中每个对象都需要清除。结果聚合按完整对象键返回：

```text
succeeded | unchanged | deleted | conflict | failed | cancelled
```

`unchanged` 表示对象已是目标标签，视为本次意图已经满足并从标记集合移除；
`deleted` 也从活动集合移除；只有真正提交成功的对象标记为 `succeeded`。
文件未提交时，文件中原本标记为 changeable 的对象最终必须转换为
`failed`，不能沿用预检的成功预期。

完成后 UI 仅按磁盘实态重新加载当前受影响文件、刷新标签摘要和失效或增量
更新受影响索引。

**Alternatives considered:** 按成功文件清空全部标记。这无法处理同文件内
无变化、删除或计划异常对象，并会破坏精确重试，因此采用逐对象结果。

### Decision 9: 第一版使用两个状态动作和一个改标入口

新增轻量 Qt 对话框/worker 适配层，例如
`widgets/object_relabel_dialog.py`，负责目标标签选择、预检确认、阶段进度和
结果展示。`label_widget.py` 只负责创建 action、处理 dirty 文件、取得标记
快照、启动协调器及刷新结果。

进度框在预检确认期间隐藏，进入暂存后恢复显示，并使用实际 `index/total`
更新确定进度；成功、取消和失败都经过同一个幂等终态清理，先停止线程并
关闭/销毁进度框，再显示至多一次结果或错误提示。

UI 增加“跨图对象标记”checkable action、“清空跨图标记”和“修改已标记
对象的标签……”三个动作。标记开关只启停新的标记手势，关闭不清空集合；
改标入口在无标记对象时禁用或给出明确提示，并显示对象数和文件数。未来
数字键、标签列表或 Canvas 右键只调用同一改标请求入口。

**Alternatives considered:** 把每个入口直接连接到 worker。这样会重复 dirty
处理、确认和标记清理，难以保持一致，因此所有入口必须经过同一协调器。

### Decision 10: 新 UI 文案进入现有翻译流程

所有用户可见字符串使用现有 `translate`/`tr` 机制，更新 `.ts` 后通过
`scripts/compile_languages.py` 重建 `.qm` 和生成资源。不得手工修改
`anylabeling/resources/resources.py`。

## Risks / Trade-offs

- **[Risk] 标记模式与普通选择/边编辑手势冲突** → Canvas 只在明确 click
  手势结束后发请求，并用单击、拖动、顶点和活动边组合测试固定优先级。
- **[Risk] 抽取通用事务层破坏全局标签迁移** → 保留现有公开 API，并先用
  `tests/test_label_batch.py` 建立回归门禁，再接入对象转换。
- **[Risk] 同一文件部分对象可靠、部分对象身份冲突** → 冲突文件整文件不
  暂存，牺牲局部成功以换取可解释性。
- **[Risk] 预检后外部修改导致结果过期** → 提交前比较源文件指纹，变化则
  失败并保留标记。
- **[Risk] 大批次结果对象占用内存** → 计划只保存紧凑完整键和必要摘要，
  按文件处理，不保留完整 JSON 副本。
- **[Risk] 当前文件重载影响用户视图状态** → 只在当前文件实际提交成功时
  重载，并沿用现有视图状态恢复路径。
- **[Risk] 进行中的安全标签批量 change 与本变更同时触碰同一内核** → 实施
  前检查其工作区状态，保持修改可叠加且不覆盖未完成改动。

## Migration Plan

1. 为现有标签批量事务 API 补充回归测试，并抽取向后兼容的通用 JSON
   暂存/提交接口。
2. 增加对象引用、计划、严格定位、纯转换和逐对象结果聚合，先完成无 Qt
   单元测试。
3. 实现会话级标记仓库、Canvas 标记手势和独立 overlay，并补齐交互测试。
4. 接入后台 worker、目标标签选择、预检和结果对话框。
5. 在 `label_widget.py` 增加标记开关、清空、改标入口、dirty 协调和提交后
   有界刷新。
6. 更新翻译资源，运行相关纯 Python、PyQt offscreen、格式和 lint 验证。

回滚时可以移除主入口和对象级适配器；现有全局标签迁移继续通过兼容 API
工作。对象改标不新增 JSON 字段，未完成或失败事务可以使用现有 manifest
恢复，不需要数据迁移脚本。

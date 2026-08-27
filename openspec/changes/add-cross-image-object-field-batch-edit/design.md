## Context

参见 [proposal.md](proposal.md) 的动机和 [cross-image-object-field-edit spec](specs/cross-image-object-field-edit/spec.md) 的行为契约。第一阶段已经建立会话级 `MarkedObjectStore`、不可变对象快照、严格 Shape ID 定位、对象级预检结果，以及复用 `JsonTransactionEngine` 的安全写盘闭环。

现有 `transform_objects_by_id()` 接收单个 `target_label`，通过 `shape.get("label")` 判断变化，只能表达标签的 changed/unchanged。第二阶段需要区分“字段不存在”和“字段存在且等于运行时默认值”；例如缺少 `difficult` 与显式 `difficult: false` 在运行时效果接近，但对用户要求的字段创建操作不是同一结果。

`Shape.load_from_dict()` / `Shape.to_dict()` 依赖 PyQt 并会把运行时默认值物化；`LabelFile.save()` 还会重建根 JSON 和规范化矩形点。跨图批处理必须继续直接转换原始 JSON，避免把对象字段编辑扩大为整文件格式迁移。

## Goals / Non-Goals

**Goals:**

- 用纯 Python、不可变计划表达一个或多个类型安全字段设置。
- 在不丢失“缺失”信息的前提下完成预检、转换和逐字段结果统计。
- 只修改标记目标和用户明确选择的字段路径，保留未知字段、非目标对象和根对象内容。
- 继续复用第一阶段的对象快照、事务、恢复、取消、并发和标记同步边界。
- 让现有标签专用入口保持兼容，并可在内核稳定后适配到通用字段设置。

**Non-Goals:**

- 不实现 Shape 标准字段补全，也不要求用户先运行字段补全。
- 不支持任意 JSONPath、数组路径、字段递增、切换、追加或条件表达式。
- 不修改对象身份、几何、`shape_type`、旋转方向或 KIE 关系。
- 不自动迁移或删除 `flags.difficult`。
- 不把标记集合持久化，也不改变第一阶段标记交互。

## Decisions

### Decision 1: 新增独立纯 Python 字段编辑领域模块

新增 `widgets/object_field_edit.py`，复用 `object_relabel.py` 中的对象引用、标记仓库和公共状态，但不把字段规则继续堆进标签专用转换函数。核心模型建议为：

```text
FieldAssignment
├── path: tuple[str, ...]
├── value: JSON scalar
└── field_kind

ObjectFieldEditPlan
├── project_id
├── assignments: tuple[FieldAssignment, ...]
└── targets_by_annotation_path

FieldMutation
├── path
├── status: created | updated | unchanged | conflict
├── old_value / old_value_missing
└── new_value

ObjectFieldEditResult
├── object results
├── field counts
├── file counts
└── committed_annotation_paths
```

计划构造时拒绝重复路径，并冻结 assignments 与目标映射。一个批次允许多个字段设置，使用户可以在一次快照和一次事务中完成相关修改，避免每修改一个字段都重新标记对象。

**Alternatives considered:** 直接扩展 `ObjectRelabelPlan.target_label` 为任意字典。裸字典不能表达字段类型、路径合法性、缺失状态和稳定顺序，容易绕过验证，因此采用显式不可变模型。

### Decision 2: 使用字段注册表限制路径与类型

建立纯 Python 字段定义注册表，负责 UI 选项、输入解析、计划验证和转换前复核的共同语义：

```text
label              non-empty str
difficult          bool
group_id           int | None（bool 不作为 int）
description        str
score              int | float | None（排除 NaN/Infinity 和 bool）
flags.<key>         bool
attributes.<key>    JSON scalar
```

嵌套键必须为非空安全字符串，不允许点号继续扩展层级，也不允许覆盖整个 `flags` 或 `attributes` 对象。受保护字段在计划构造边界直接拒绝。

**Alternatives considered:** 允许任意 JSONPath。它会把首版变成通用 JSON 编辑器，并引入数组、结构替换和未知字段类型风险，因此只支持已知顶层字段和一层字典子键。

### Decision 3: 以显式 MISSING 哨兵保留字段缺失语义

读取旧值时使用模块私有 `MISSING` 哨兵，而不是 `dict.get(path, default)`：

```text
old is MISSING       → created
old == target        → unchanged
old != target        → updated
parent wrong type    → conflict
```

比较使用 JSON 类型感知规则，避免 Python 中 `True == 1` 把不同字段类型误判为相同。转换函数深复制输入，逐个目标 Shape 应用 assignments，并返回逐字段状态；只有至少一个 `created` 或 `updated` 才把文件标为 changed。

**Alternatives considered:** 先通过 `Shape.load_from_dict()` 补默认值再比较。这样会丢失缺失信息，并会让 `difficult=false` 的补字段意图被误判为无变化，因此不采用。

### Decision 4: 嵌套父容器缺失可创建，错误类型使整文件冲突

对 `flags.<key>` 和 `attributes.<key>`：父字段缺失时创建新字典；父字段为字典时只设置目标子键；父字段存在但不是字典时记录字段冲突。只要文件中任一快照目标存在字段冲突，该文件就不暂存，文件内其他目标最终也按失败/冲突保守处理。

**Alternatives considered:** 同文件跳过冲突对象但提交其他对象。虽然成功率更高，但一次文件替换会混合用户可理解与不可理解的结果，恢复和标记清理更复杂，因此沿用第一阶段“文件内不可靠则整文件不提交”的保守策略。

### Decision 5: 普通字段编辑与字段补全没有调用关系

字段编辑计划只携带用户选择的 assignments。转换器不得遍历标准字段清单调用 `setdefault`，也不得调用 Shape/LabelFile 往返；创建嵌套父字典只是完成所选路径的必要步骤，不视为字段补全。

独立字段补全未来可以共享字段定义常量、JSON 事务和验证函数，但必须拥有独立入口、计划、预检和文档。字段编辑不检测其是否执行过，也不把它作为前置门禁。

**Alternatives considered:** 提交前自动补全所有标准字段。它会修改用户未选择的内容、扩大差异与恢复范围，并改变 LabelMe 精简格式，因此明确排除。

### Decision 6: difficult 顶层字段与旧别名只提示、不联动

字段注册表把 `difficult` 映射到 Shape 顶层。预检额外检查 `flags.difficult`：存在时生成 warning；与顶层值冲突时生成 stronger warning。普通设置仍只操作顶层，不删除或同步别名。

这样可以保证“只修改所选字段”的承诺。未来独立格式规范化功能负责让用户显式选择迁移策略。

**Alternatives considered:** 设置顶层值时自动删除 `flags.difficult`。这会产生未在 assignment 中声明的第二处修改，且可能破坏依赖旧 flags 的外部工具，因此不采用。

### Decision 7: 预检同时聚合对象级和字段级状态

预检仍以文件为处理边界，并为每个目标对象保存紧凑的逐字段状态。摘要至少包括：

```text
对象/文件：snapshot、changeable、unchanged、deleted、conflict、failed
字段：created、updated、unchanged、conflict
提示：legacy difficult alias、alias value mismatch
```

UI 首屏显示聚合计数，提供可展开的字段明细或有限示例，避免大批次把全部旧值加载进 Qt 表格。确认文本明确说明缺失字段会被创建、未选字段不会补全。

### Decision 8: 新对话框复用协调流程，不复制写盘逻辑

新增字段设置编辑/预检 UI，例如 `object_field_edit_dialog.py`。字段行由注册表生成适当编辑器；worker 只调用纯 Python引擎。`label_widget.py` 继续负责 dirty 文件处理、取得冻结快照、启动协调、终态幂等清理和有界刷新。

事务阶段复用 `JsonTransactionEngine.stage_files()`、`commit()` 和 manifest。manifest 领域元数据记录 assignments、字段计数和逐对象结果，恢复继续使用通用恢复入口。

现有改标签 action 首先保持原路径和测试门禁；通用引擎稳定后可将其适配成单个 `label` assignment，但 UI 行为和文案不变。

### Decision 9: 标记清理以对象最终意图是否满足为准

对象所有 assignments 成功提交时结果为 succeeded；所有字段本来相同为 unchanged；对象已不存在为 deleted。三者从活动标记移除。文件冲突、读取/暂存/提交失败和取消均保留标记。

对于同时包含 created、updated、unchanged 的对象，只要文件成功提交，就视为该对象全部字段意图已满足并移除标记。批次外的新标记继续由冻结快照边界保护。

## Risks / Trade-offs

- **[Risk] 多字段 UI 增加输入和预检复杂度** → 首版只支持 SET，字段行按注册表生成，拒绝重复路径并提供聚合摘要。
- **[Risk] Python bool 与 int 相等导致误判** → 验证和相等比较同时检查 JSON 类型，不使用裸 `==` 作为唯一标准。
- **[Risk] 大批次逐字段结果占用内存** → 保存紧凑 path/status 与必要旧值摘要，UI 只展示有限明细。
- **[Risk] 旧 `flags.difficult` 造成应用内视图不一致** → 预检显式警告，但迁移留给独立规范化功能，避免隐式副作用。
- **[Risk] 新模块与标签专用引擎重复协调代码** → 共享对象引用、状态聚合和通用事务，标签入口适配在兼容测试通过后再做。
- **[Risk] 当前文件内存态覆盖后台结果** → 沿用第一阶段 dirty 处理、项目写门和成功后按磁盘重载边界。

## Migration Plan

1. 先增加纯 Python 字段注册表、计划、预检和转换测试，不接 UI。
2. 接入通用 JSON 事务和逐对象结果，验证取消、指纹变化、部分失败与 manifest 恢复。
3. 增加字段编辑对话框、worker 和统一入口，保持原标签入口不变。
4. 补齐当前文件刷新、Dataset Index/Inspector 更新、翻译和用户文档。
5. 通过标签专用回归后，再决定是否让旧入口内部适配通用引擎；适配不是上线前置条件。

回滚时移除新 action、对话框和字段编辑适配器即可；第一阶段标签改标与标记仓库继续独立工作。已提交事务仍可通过现有 manifest 恢复。

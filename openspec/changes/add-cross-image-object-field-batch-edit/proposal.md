## Why

现有跨图对象标记流程只能把已标记对象统一修改为一个目标标签，无法安全地批量修改 `difficult`、`group_id`、`description` 等对象字段。部分 LabelMe 来源 Shape 缺少这些可选字段，因此第二阶段必须明确“字段不存在时如何修改”，同时避免把独立的数据格式补全工作隐式混入对象级修改。

## What Changes

- 新增“批量编辑已标记对象”能力，继续使用冻结标记快照和持久 `xanylabeling_shape_id` 严格定位具体对象。
- 首版支持类型安全的顶层字段设置，以及 `flags.<key>`、`attributes.<key>` 单键设置；结构性身份和几何字段不开放通用修改。
- 明确区分字段缺失、已有相同值和已有不同值：执行 `SET` 时缺失字段直接创建，并在预检与结果中单独计为 `created`。
- 对缺失或类型非法的嵌套父容器给出确定规则：父容器缺失时可创建字典，父容器类型错误时报告冲突且不写文件。
- 保留现有“修改已标记对象的标签”快捷流程，并让新增字段编辑复用同一安全事务、并发控制和逐对象标记同步机制。
- 明确排除自动字段补全：字段补全是独立的数据规范化功能，不与本流程融合，也不作为执行前置条件；普通修改只触碰用户明确选择的字段。

## Capabilities

### New Capabilities

- `cross-image-object-field-edit`: 定义对跨图已标记对象执行类型安全字段设置、缺失字段创建、预检、安全提交、结果统计和失败重试的行为契约。

### Modified Capabilities

无。现有 `cross-image-object-relabel` 的标签专用行为保持兼容，新增能力在其标记快照和事务基础上扩展，不改变第一阶段契约。

## Impact

- 主要影响 `anylabeling/views/labeling/widgets/object_relabel.py`、对象操作 Qt 对话框/worker、`label_widget.py` 的统一入口，以及相关纯 Python 与 offscreen 测试。
- 复用 `widgets/label_batch.py` 的通用 JSON 事务、备份、指纹校验、原子提交和恢复清单，不增加第二套写盘实现。
- 需要新增字段路径、字段类型、缺失状态和逐对象结果模型，并补充 UI 文案、翻译资源和用户文档。
- 不自动调用 `Shape.load_from_dict()` / `Shape.to_dict()` / `LabelFile.save()` 规范化整文件，不修改未标记对象或未选字段。

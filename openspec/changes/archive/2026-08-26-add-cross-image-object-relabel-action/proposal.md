## Why

项目已经具备持久 `xanylabeling_shape_id` 和安全批量事务基础设施，但尚未
实现跨图对象标记和对象级批量改标。当前需要从零补齐“跨图收集具体对象、
冻结标记快照、对象级预检、安全提交”的闭环，同时避免把对象实例改标误
实现成全局标签重命名。

## What Changes

- 新增会话级跨图对象标记仓库，使用完整对象键维护活动标记集合。
- 新增独立的跨图标记模式：单击对象切换标记，拖动、边/顶点编辑不改变
  标记；切图恢复标记视觉，暂停模式不清空集合。
- 新增对象级批量改标命令，消费标记仓库提供的不可变跨图对象快照。
- 使用 `(project_id, image_id, xanylabeling_shape_id)` 严格定位目标对象，
  只修改唯一命中 Shape 的 `label` 字段。
- 新增对象级预检、目标标签确认、dirty 文件处理和结构化结果报告。
- 复用现有批量迁移的暂存、备份、源文件变化检查、原子替换和恢复清单，
  但保持对象 ID 匹配与全局 `rename_map` 匹配语义分离。
- 成功或确认已删除的对象从标记集合移除；冲突、读取或写入失败的对象
  保留标记以便重试；取消操作不清空标记。
- 新增一个明确的“修改已标记对象的标签……”主入口；未来其他入口只能
  转发到同一个命令。
- 不迁移或修复 Shape ID，不把标记状态写入 JSON，不扩展到其他 Shape 字段。

## Capabilities

### New Capabilities

- `cross-image-object-relabel`: 定义从已有跨图标记快照选择目标标签、严格
  预检、对象级安全提交、结果同步及剩余标记重试的完整行为。

### Modified Capabilities

无。

## Impact

- 标记内核：新增纯 Python 会话仓库，提供 toggle、snapshot、按图片查询、
  精确移除、清空、计数通知和结果同步。
- Canvas 集成：`anylabeling/views/labeling/widgets/canvas.py` 增加标记模式的
  单击意图信号和独立标记 overlay，同时保持普通选中、拖动与边编辑行为。
- 批量内核：`anylabeling/views/labeling/widgets/label_batch.py` 需要增加
  对象级变更计划和按 Shape ID 转换能力，或抽取可供对象级操作复用的事务
  基础设施。
- UI 集成：`anylabeling/views/labeling/label_widget.py` 增加统一入口、目标
  标签选择、预检、进度和结果同步；实现时遵守大文件窄读窄改约束。
- 数据契约：X-AnyLabeling JSON schema 不变，只修改明确目标 Shape 的
  `label`，保留 `xanylabeling_shape_id` 和所有非目标字段。
- 测试：新增纯 Python 对象级计划/转换/事务测试，以及最小范围的 PyQt
  入口与标记结果同步测试。

## Why

X-AnyLabeling 已能为 Shape 生成并保存 `xanylabeling_shape_id`，但当前加载链路不会识别同一标注文件中的重复 ID，也缺少覆盖文件往返、损坏输入和所有“创建新对象”入口的完整契约。需要把现有实现从“高概率唯一的字段”完善为可验证、可迁移、边界明确的持久身份能力，避免行为分析、复核队列和未来跨模块引用错误地关联到另一个 Shape。

## What Changes

- 明确 Shape ID 的作用域、格式和完整对象键：JSON 内持久 ID 使用随机 UUID，跨项目消费使用 `(project_id, image_id, shape_id)`。
- 在标注文件加载和合并边界校验空值、非法类型与重复 ID，并以确定性策略修复或报告冲突。
- 固化身份生命周期：编辑、保存、重载、撤销和删除撤销保留 ID；新建、复制、粘贴、导入为新对象和 AI 生成必须获得新 ID。
- 保持旧 JSON 兼容：缺少 ID 时仅在内存惰性补齐，不单独将文件标记为已修改；后续真实保存时持久化。
- 明确私有字段边界：`xanylabeling_shape_id` 不占用 `group_id`、`flags`、`attributes` 或 `kie_linking`，且不进入 VOC、YOLO、COCO 等交换格式。
- 增加 Shape 模型、LabelFile 文件往返、撤销/复制/粘贴、重复输入治理和转换器边界的定向测试。
- 为下游模块提供稳定身份读取契约，逐步淘汰需要跨保存周期追踪对象时使用 shape 下标或 Python 对象地址的做法。

## Capabilities

### New Capabilities

- `persistent-shape-identity`: 定义 Shape 持久身份的生成、保存、恢复、冲突治理、生命周期和外部格式边界。

### Modified Capabilities

无。

## Impact

- 数据模型与序列化：`anylabeling/views/labeling/shape.py`、`label_file.py`。
- UI 对象创建与历史操作：`label_widget.py`、`widgets/canvas.py` 以及 AI/导入入口。
- 数据消费：行为分析、Inspector、虚拟复核和其他需要稳定 Shape 引用的模块。
- 转换边界：内置 COCO 转换器与 `tools/label_converter.py` 中的 VOC/YOLO 等转换路径。
- 测试：Shape 身份单测、LabelFile 往返测试、UI 生命周期测试和转换器边界测试。
- JSON 向后兼容；不改变 VOC、YOLO、COCO 等公共交换格式。

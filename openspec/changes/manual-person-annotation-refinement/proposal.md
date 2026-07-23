## Why

手动人物标注当前有两类主要摩擦：一类是 `person`、`head`、`face` 之间的 `group_id` 绑定仍依赖人工输入或事后修正；另一类是矩形框精修时，用户需要在看清边界和稳定拖动之间反复 zoom in / pan，几像素级调整容易受鼠标控制增益影响。

项目已有数字快捷键、数字快捷重命名、`group_id` 生成/组合、矩形边编辑和稳定精修预览等基础能力，但它们尚未形成面向人物实例的工作流。该变更将这些基础能力组织为四个可独立实现、协同工作的功能：新建 `person` 自动创建人物实例、数字快捷绑定绘制、精修控制模式、局部边缘吸附。

## What Changes

- 新增“新建 person 自动创建人物实例”开关：
  - 当新建 `label == "person"` 且 `shape_type == "rectangle"` 时，若无绑定绘制上下文，自动生成新的 `group_id`。
  - v0 只作用于手动新建标注流程，不作用于 auto-labeling 结果落地流程。
  - 该功能不与“自动使用上一个标签”互斥；当上一个标签为 `person` 时，连续绘制将自动生成连续的新 `group_id`。
  - 该功能优先于“自动使用上一个 group_id”，新建 `person` 不沿用上一组 ID。
- 新增数字快捷绑定绘制模式：
  - 与现有数字快捷重命名模式互斥。
  - 选中 `person` / `head` / `face` 来源对象后，按数字快捷键进入新建标注，新标注继承来源 `group_id`。
  - 来源无 `group_id` 时，允许继续并拟分配新 `group_id`；来源回填和新建对象写入在绘制完成时作为一次事务提交，取消绘制不改来源。
  - v0 只支持数字快捷目标为 `rectangle + person/head/face`。
  - 同一 `group_id` 下已存在目标 label 时提示并拒绝，进入绘制前和创建提交前均需校验，避免重复 `person` / `head` / `face`。
- 新增“数字快捷操作提示”：
  - 在模式切换、选中对象变化、数字键触发和拒绝执行时提示当前模式、来源对象、来源 `group_id`、数字键、目标 label、目标 shape_type 和执行结果。
- 新增精修控制模式：
  - 基于已确认的坐标模型 `image_delta = screen_delta / canvas.scale`，提供鼠标拖动降速，默认 `precision_factor = 4`。
  - 精修降速只缩放拖动 delta，不改变 `transform_pos()`、hit-test 或 epsilon；连续拖动使用虚拟光标避免 `prev_point` 漂移。
  - 增加像素级键盘微调、粗调和矩形单边微调能力。
- 新增局部边缘吸附：
  - 对当前选中矩形边，在当前边坐标附近默认 `±4` image pixels 搜索图像强边缘。
  - 按键触发吸附，不做实时吸附；吸附前先 validate，候选若会触发 clamp 则视为失败，成功或失败均给出提示，并支持撤销。

## Capabilities

### New Capabilities

- `manual-person-instance-binding`: 手动人物标注中的 `person` / `head` / `face` 实例绑定协议、数字快捷绑定绘制和操作提示。
- `manual-rectangle-refinement`: 手动矩形框精修中的控制增益管理、键盘像素微调和局部边缘吸附。
- `labeling-digit-shortcuts`: 数字快捷键从单一绘制/重命名入口扩展为互斥的重命名模式与绑定绘制模式。

## Impact

- **Files Affected**:
  - `anylabeling/views/labeling/label_widget.py`
  - `anylabeling/views/labeling/widgets/canvas.py`
  - `anylabeling/views/labeling/widgets/digit_rename_manager.py`
  - `anylabeling/views/labeling/rect_edge_alignment.py`
  - Potential new helpers under `anylabeling/views/labeling/` or `anylabeling/views/labeling/widgets/`
  - `anylabeling/configs/xanylabeling_config.yaml`
  - `anylabeling/views/labeling/settings/schema.py`
  - Tests under `tests/`
- **Risk**: 中等。数字快捷键和矩形编辑是高频交互，必须保持旧默认行为可预测，并通过互斥模式、状态提示和测试降低误操作风险。
- **Testing**: 需要覆盖 `group_id` 自动生成/继承/拒绝重复、数字快捷模式互斥、pending context 取消与 undo 原子性、提示上下文、鼠标精修降速连续拖动、键盘微调、边缘吸附成功/失败。
- **User Impact**: 标注员可以更快补齐同一人物实例的 `person` / `head` / `face` 框，并在不频繁 zoom in 的情况下完成几像素级精修。

# Shape 持久身份契约

完整设计背景、JSON 结构、项目迁移和下游对象管理说明见
[Shape 持久唯一身份项目说明](persistent_shape_identity_project_design.md)。

## 目标和作用域

每个保存到 X-AnyLabeling JSON `shapes` 数组的正式 Shape 都拥有顶层
`xanylabeling_shape_id`。身份属于通用 Shape，而不是矩形专用能力，因此点、
关键点、线、多边形、矩形、旋转框、圆、四边形和 cuboid 均使用相同规则。

新身份是 32 位小写 UUID4 hex。同一标注文件内必须非空且唯一；需要跨文件
引用时使用 `(project_id, image_id, shape_id)`，不把 Shape ID 单独当成可由本地
应用验证的全球主键。`group_id` 继续只表达 person/head/face 等业务分组关系。
序列化时 `xanylabeling_shape_id` 固定为每个 Shape 对象的第一个键；这个顺序要求
只影响 JSON 可读性和不同写入入口的一致性，不改变 JSON 对象的键值语义。

## 生命周期

| 操作 | 身份行为 |
|---|---|
| 手工绘制、AI 生成 | 生成新 ID |
| 修改标签、点、属性、描述 | 保留 ID |
| 保存、重载 | 保留 ID |
| 撤销、重做、删除后撤销 | 保留 ID |
| Duplicate、右键复制、剪贴板粘贴 | 生成新 ID |
| 合并形状、跨图片批量复制、导入为新对象 | 生成新 ID |
| 仅用于绘制预览、几何比较的临时副本 | 可保留来源 ID，但不得持久化为新对象 |

`Shape.copy()` 表示状态快照并保留身份；`Shape.copy_for_new_object()` 表示创建
独立对象并生成新身份。调用者必须按语义选择，不能用普通 `deepcopy` 猜测意图。

## 加载、迁移和保存

`LabelFile` 加载整个 Shape 集合时执行 O(n) 规范化：

- 保留每个首次出现的非空字符串历史 ID，包括旧版本写入的非 UUID 字符串；
- 为缺失、非字符串、空字符串和后续重复项生成不冲突的 UUID；
- 在 `LabelFile.shape_identity_diagnostics` 中暴露 `missing`、`invalid`、
  `duplicate` 结构化诊断，并写入警告日志；
- 仅因惰性补 ID 或冲突修复不修改源 JSON，也不单独触发 dirty。

用户发生真实标注变化并正常保存后，内存身份随 Shape 写回 JSON。保存入口只读
验证所有 ID；若运行时扩展绕过标准入口制造空值或重复值，保存明确失败并报告
Shape 数组位置，不会在生命周期末端静默换 ID。现有临时文件、`fsync`、原子替换
和失败清理语义保持不变。

工具菜单中的“Assign Shape IDs to Project”可以手动递归扫描当前项目及标注输出
目录下的 JSON。它只写入确实需要修复的文件，逐文件报告新增 ID 数量和失败文件；
已有合法 ID 不会被重置。这个操作用于把旧项目一次性迁移到下游功能所需的完整
身份状态，扫描和写入在后台线程执行，界面显示节流后的进度，写入过程使用临时
文件和原子替换。

已有项目也可以执行：

```powershell
python scripts\ensure_shape_identity_order.py --input <项目或JSON路径>
```

脚本只分配/修复 `xanylabeling_shape_id` 并将其移动到 Shape 的第一个键，不补齐
`group_id`、`description`、`difficult`、`attributes` 或其他标准字段。

## 创建和恢复入口审计

| 入口 | 分类 | 处理 |
|---|---|---|
| `Shape(...)` 及 auto-labeling 模型输出 | 新对象 | 构造器生成 UUID，Canvas 再声明文件内唯一性 |
| `LabelFile.load()` | 恢复对象 | 集合规范化后保留有效历史 ID |
| Canvas undo/redo backups、编辑预览 | 状态快照 | `copy()` 保留 ID |
| Duplicate、右键 Copy、内部/系统剪贴板 | 新对象 | `copy_for_new_object()` 或反序列化时 `preserve_shape_id=False` |
| Union 合并结果 | 新对象 | 使用新 ID，来源 Shape 随后删除 |
| Shape Manager 跨图片批量复制 | 新对象 | 生成新 ID并避开目标 JSON 已有 ID |
| Canvas `load_shapes(..., replace=False)` | 合并/AI 入口 | 以现有 Canvas ID 为保留集合，修复来件冲突 |
| visualization、批处理 skip 检测、Shape Manager 几何比较 | 临时读取 | 可保留 ID，不把临时对象作为新 Shape 写出 |

## 下游引用审计

| 模块 | 生命周期 | 身份策略 |
|---|---|---|
| behavior analytics | 跨编辑、保存和会话 | 使用 `(project_id, image_id, shape_id)`；对象 episode 另有独立 ID |
| L1/L2 质检报告与复核反馈 | 跨复扫和人工反馈 | `report.json`、`review.tsv`、`review_feedback.tsv` 保存 `shape_id`；`shape_index` 仅用于当前文件导航 |
| 本地虚拟复核页面 | 当前图片会话 | 优先使用持久 Shape ID；仅对无 ID 的测试/临时对象使用 `_virtual_review_id` 回退 |
| 数据集虚拟复核 sidecar | 跨文件变化 | 持久 task locator 使用成员序号、标签、类型和几何指纹做保守重绑定；运行时 Shape map 使用持久 ID |
| Inspector 基础规则和 QA matching | 当前扫描/导航 | `shape_index`、`qa_entity_id` 是明确的扫描期身份，不作为 Shape 主键写回标注 JSON |
| Canvas 命中测试、布局和渲染 | 单次内存计算 | 可使用对象地址或下标，但不得输出为持久 Shape 引用 |

## 外部格式边界

`xanylabeling_shape_id` 是项目私有字段。VOC、YOLO、COCO 等没有对应扩展契约的
格式采用公共字段白名单，既不输出该 ID，也不修改源 JSON。经过这些格式往返后，
系统不承诺恢复原 Shape 身份；重新导入为新对象时会生成新 ID。

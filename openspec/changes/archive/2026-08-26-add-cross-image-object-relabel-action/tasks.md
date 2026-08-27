## 1. 既有能力确认与回归基线

- [x] 1.1 精确定位 Canvas 单击/拖动/边编辑、Shape 绘制、切图加载、对象删除和 action 创建钩子，记录跨图标记仓库与 UI 的最小接入点
- [x] 1.2 核对 `project_id`、`image_id` 到目标 JSON 的现有解析规则，覆盖 `output_dir`、图片与 JSON 分目录、相对路径规范化和项目根目录边界
- [x] 1.3 为 `BatchMigrationEngine` 当前公开的 preflight、stage、commit、restore、取消、部分失败和恢复行为补齐回归测试
- [x] 1.4 运行 `tests/test_label_batch.py -q` 建立改造前基线，并记录当前进行中的 `optimize-annotation-visual-encoding-and-label-batch-operations` 对同文件的未完成修改，避免覆盖

## 2. 对象级不可变计划与路径边界

- [x] 2.1 新增无 PyQt 依赖的 `widgets/object_relabel.py`，定义 frozen `MarkedObjectRef`、`ObjectRelabelPlan` 和规范化完整对象键
- [x] 2.2 实现从标记快照构建对象改标计划，校验目标标签、当前项目、完整对象键并按目标 JSON 分组和去重
- [x] 2.3 实现项目内 JSON 路径解析与边界校验，拒绝无法解析、跨项目或逃逸标注根目录的目标
- [x] 2.4 确保计划只保存完整对象键和必要显示摘要，不保存运行时 `Shape` 地址、Canvas 下标或完整 JSON 副本
- [x] 2.5 新增计划单元测试，覆盖空快照、空标签、重复引用、跨项目条目、分目录数据集、路径逃逸和快照不可变性

## 3. 严格对象预检与纯 JSON 转换

- [x] 3.1 定义逐对象 `changeable`、`unchanged`、`deleted`、`conflict`、`failed`、`cancelled` 状态和文件级预检汇总模型
- [x] 3.2 实现按文件读取 JSON 并一次构建 `xanylabeling_shape_id → Shape` 映射的严格预检，不读取 Canvas 内存对象且不依赖 Dataset Index 决定正确性
- [x] 3.3 实现目标 Shape ID 唯一命中、已删除、非法和重复冲突判定，并让目标身份冲突或 JSON 结构异常的文件整文件退出暂存
- [x] 3.4 实现纯 `transform_objects_by_id` 转换，只修改唯一目标 Shape 的 `label`，将已是目标标签的对象报告为 `unchanged`
- [x] 3.5 验证转换保留 `xanylabeling_shape_id`、points、shape_type、group_id、flags、attributes、description、未知扩展字段、非目标 Shape 内容及 Shape 顺序
- [x] 3.6 新增严格定位测试，覆盖数组重排、原标签/坐标/属性/group_id 变化、对象删除、重复 ID、非法 ID 和禁止模糊匹配
- [x] 3.7 新增转换隔离测试，证明同文件内相同原标签的未标记对象不变、无变化对象不触发无效写入且输入映射不被原地修改

## 4. 复用并泛化安全批量事务

- [x] 4.1 从现有标签迁移引擎抽取或增加向后兼容的通用 JSON 暂存入口，接受明确源文件、按文件转换请求和可序列化领域元数据
- [x] 4.2 保留 `BatchMigrationEngine` 现有公开 API 和全局 rename/delete 行为，通过兼容适配调用通用事务层
- [x] 4.3 让通用暂存层统一完成临时文件写入、JSON 重解析、备份、源文件指纹、manifest 写入和无实际变化跳过
- [x] 4.4 扩展事务 manifest 以保存对象计划和逐对象阶段结果，同时保持旧 manifest 的 restore 兼容读取
- [x] 4.5 实现对象级 stage/commit 外观，复用 `DatasetWriteCoordinator`，并从实际文件提交结果生成最终逐对象结果
- [x] 4.6 保持预检和暂存可取消、提交不可取消；源文件指纹变化时拒绝覆盖并将对应 changeable 对象转为失败
- [x] 4.7 确保部分提交失败时成功文件可通过 manifest 恢复，失败文件保持原样且对象标记结果可精确重试
- [x] 4.8 扩展纯 Python 事务测试，覆盖取消边界、外部修改、验证失败、替换失败、部分成功、旧 API 回归、旧 manifest 恢复和对象元数据往返

## 5. 会话级跨图标记仓库

- [x] 5.1 实现纯 Python `MarkedObjectStore`，提供 toggle、contains、snapshot、按图片查询、精确移除、批量移除、clear 和对象/文件计数
- [x] 5.2 保证仓库只保存 `MarkedObjectRef` 且不写 JSON、SQLite 或 sidecar；快照创建后仓库变化不改变冻结批次
- [x] 5.3 实现按最终结果更新仓库：移除 `succeeded`、`unchanged` 和 `deleted`，保留 `conflict`、`failed` 和 `cancelled`
- [x] 5.4 保证结果同步不会清空批次外新标记，并返回结构化变化供 UI 更新计数和当前图片 overlay
- [x] 5.5 新增仓库测试，覆盖 toggle、跨图计数、冻结快照、全部成功、全部取消、同文件部分失败、跨文件部分成功和已删除对象清理

## 6. 后台协调器与用户界面

- [x] 6.1 在 Canvas 增加标记模式、当前图片标记 ID 集合和明确 click 后的 toggle 请求信号，不保存跨图引用
- [x] 6.2 实现标记手势优先级：对象单击切换，空白单击、拖动、缩放、顶点和矩形边编辑不切换
- [x] 6.3 在 Canvas 正常 Shape 绘制后增加独立标记 overlay，不修改 Shape 序列化、普通 selected、hover、活动边或 QA 状态
- [x] 6.4 在 LabelingWidget 创建唯一 `MarkedObjectStore`，接收 Canvas toggle 请求，并在切图、删除、清空和仓库变化后同步当前图片标记 ID
- [x] 6.5 新增“跨图对象标记”checkable action、“清空跨图标记”和“修改已标记对象的标签……”主 action，显示对象数和文件数且关闭模式不清空集合
- [x] 6.6 新增对象改标 Qt worker/协调器，在线程边界传递不可变计划、进度、预检和最终结构化结果，不在 worker 中访问 QWidget 或 Canvas
- [x] 6.7 复用项目标签来源实现单目标标签选择；用户取消选择时不创建事务、不写文件且不改变标记
- [x] 6.8 在 worker 启动前接入当前图片 dirty 处理，覆盖保存成功、保存失败和用户取消三个分支
- [x] 6.9 实现预检对话框，显示目标标签、快照对象、涉及文件、可修改、无变化、已删除、身份冲突和读取失败数量
- [x] 6.10 实现预检/暂存阶段取消和提交阶段不可取消的阶段提示，防止同一数据集同时启动另一批量写事务
- [x] 6.11 实现结果对话框，分别显示对象与文件的成功、无变化、跳过、冲突、失败、取消数量和恢复清单位置
- [x] 6.12 按最终对象结果更新标记仓库；仅在当前文件实际提交成功时重新加载，并有界刷新标签摘要、过滤器和受影响 Dataset Index
- [x] 6.13 将未来菜单、右键或数字键接入点统一收口到同一请求方法，数字键不得无提示直接写盘
- [x] 6.14 新增 PyQt offscreen 测试，覆盖标记 toggle、拖动/边编辑隔离、切图恢复、空标记、取消标签、dirty 中止、预检取消、部分失败清标记和当前文件刷新

## 7. 国际化、文档与恢复入口

- [x] 7.1 为主入口、目标标签选择、预检、进度、不可取消提交、结果分类和恢复提示补齐可翻译 UI 字符串
- [x] 7.2 更新 `.ts` 文件并运行 `scripts/compile_languages.py` 重建 `.qm` 与资源，确认未手工编辑 `anylabeling/resources/resources.py`
- [x] 7.3 在用户文档中说明“先标记、后改标、再确认”的流程，以及它与全局标签重命名的区别
- [x] 7.4 复用或接入现有 manifest 恢复入口，确保对象改标结果能够定位恢复清单并刷新恢复后的当前文件和索引

## 8. 验收与质量门禁

- [x] 8.1 运行对象计划、严格定位、纯转换、事务和标记适配的新增纯 Python 测试文件
- [x] 8.2 使用 `QT_QPA_PLATFORM=offscreen` 运行对象改标 UI 测试，并重跑 `tests/test_label_batch.py -q` 和现有标记模块相关测试
- [x] 8.3 对新增和修改的 Python 文件运行 Black 79 列格式化、`py_compile` 和窄范围 flake8，修复类型、Google-style docstring 和复杂度问题
- [x] 8.4 手工验收跨三张图片标记、快照后继续标记、对象编辑及数组重排、对象删除、冲突文件、dirty 文件、取消、部分失败和 manifest 恢复流程
- [x] 8.5 确认只修改目标 Shape 的 `label`、非目标内容逐字段不变、失败标记可直接重试，并记录最终测试命令与结果

## 9. 第三视角审核修复记录

- [x] 9.1 P0 修复：提交后按对象 image_id 调用 `label_saved` 刷新 Dataset Index；`union_selection` 合并删除时清理标记；预检对冲突文件整文件计冲突；提交失败文件内 `unchanged` 转为 `failed` 保留标记（`skipped` 仍视为已验证成功）；badge 计数/入口快照限定当前 `project_id`
- [x] 9.2 P1 修复：`BatchWriteGate` 双向互斥（对象改标 ↔ Label Manager 迁移）；`run_object_relabel_flow` 返回 False 时恢复入口 action；非法类型（如 int）目标 Shape ID 判冲突；Tool 菜单新增"从恢复清单还原对象改标…"入口；`closeEvent` 中止并等待 worker 线程
- [x] 9.3 已知偏差（记录不修）：ShapeManager 区间删除仍是历史无事务直写，不参与 BatchWriteGate（但已补标记清理）；模态进度对话框使"预检期间继续标记"场景实际不可达（spec 空真满足）；事务目录在数据集根累积（与标签迁移既有模式一致）
- [x] 9.4 回归测试：索引刷新仅限提交文件、union 钩子、flow 拒绝恢复、项目限定计数、非法 id 冲突、整文件冲突计数、失败文件 unchanged→failed、BatchWriteGate 互斥、恢复入口与关闭保护接线

## 10. Review 修复

- [x] 10.1 统一缺失、非法和重复 Shape ID 的文件级冲突判定，并让 preflight、stage、纯转换使用同一身份规则
- [x] 10.2 以导入目录或全体图片共同根作为 project/annotation/transaction 根，统一对象改标与 Label Manager 的互斥键
- [x] 10.3 加固窗口关闭边界：提交未完成时拒绝关闭，避免销毁仍运行的 QThread
- [x] 10.4 加固 manifest 恢复：校验当前数据集、处理 dirty、获取 BatchWriteGate/写锁并刷新恢复文件的 Dataset Index
- [x] 10.5 Shape Manager、标注文件删除和图片删除后清理不存在的跨图对象标记
- [x] 10.6 增加非法身份端到端、多目录根、恢复安全、关闭保护和删除清理回归测试

## 11. 实际 GUI 验收修复

- [x] 11.1 修复橙色虚线 overlay 原地扩大 Shape 缓存边界的问题，保证重复预选和重绘时外框尺寸稳定
- [x] 11.2 收敛对象改标进度/结果弹框生命周期：确认期间隐藏、确定进度、终态只关闭和提示一次
- [x] 11.3 增加 overlay 重复绘制不改变几何，以及改标流程终态幂等关闭的 PyQt 回归测试

## 12. 实际恢复入口验收修复

- [x] 12.1 修正恢复清单文件过滤器为 `*.json`，并从统一批处理根目录打开选择框
- [x] 12.2 增加恢复入口默认目录与 JSON 文件过滤器回归测试，保持 manifest 内容校验和索引刷新流程不变

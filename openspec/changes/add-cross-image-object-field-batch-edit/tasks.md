## 1. 基线与测试骨架

- [x] 1.1 核对第一阶段对象改标、通用 JSON 事务和 Qt worker 的现有公开接口，记录可直接复用与需要适配的边界
- [x] 1.2 新建纯 Python `tests/test_object_field_edit.py` 测试骨架和最小合法标注 fixture
- [x] 1.3 新建 offscreen `tests/test_object_field_edit_widget.py` 测试骨架，并复用现有对象标记/对话框测试辅助函数
- [x] 1.4 运行 `tests/test_object_relabel.py`、`tests/test_object_relabel_widget.py` 和 `tests/test_label_batch.py` 建立变更前基线

## 2. 字段定义与不可变计划

- [x] 2.1 新增纯 Python `widgets/object_field_edit.py`，定义 created/updated/unchanged/conflict 字段状态常量
- [x] 2.2 实现 `FieldAssignment` 不可变模型，规范化顶层路径和一层嵌套路径并拒绝重复路径
- [x] 2.3 实现字段注册表，覆盖 label、difficult、group_id、description、score、flags 子键和 attributes 子键
- [x] 2.4 实现各字段目标值验证，确保 bool 不冒充 int/number，score 拒绝 NaN/Infinity，attributes 仅接受 JSON 标量
- [x] 2.5 实现嵌套键名验证，拒绝空键、继续嵌套的点号路径和整个 flags/attributes 对象覆盖
- [x] 2.6 实现受保护字段拒绝规则，覆盖 Shape ID、points、shape_type、direction 和 kie_linking
- [x] 2.7 实现 `ObjectFieldEditPlan`，冻结项目 ID、assignments 和按标注路径分组的目标 Shape ID
- [x] 2.8 测试合法/非法字段、目标类型、重复路径、mutable 输入隔离和计划不可变性

## 3. 缺失字段感知的纯转换

- [x] 3.1 增加模块私有 MISSING 哨兵和 JSON 类型感知相等比较，区分缺失、false、0、null 和空字符串
- [x] 3.2 实现顶层字段读取与 SET：缺失返回 created、相同返回 unchanged、不同返回 updated
- [x] 3.3 实现嵌套字段读取与 SET：父对象缺失时创建字典，子键缺失时新增且保留其他键
- [x] 3.4 实现父容器错误类型冲突，确保冲突转换不修改调用者输入
- [x] 3.5 实现按唯一 Shape ID 应用多个 assignments 的纯转换，并返回逐对象、逐字段状态
- [x] 3.6 保持第一阶段严格身份规则：缺失/非法/重复 Shape ID 冲突，对象不存在报告 deleted，不使用下标或内容回退匹配
- [x] 3.7 确保只有 created/updated 才令文件 changed；全 unchanged 不产生无效写入
- [x] 3.8 测试缺少 difficult 时设置 false 会真实新增，而已有 false 为 unchanged、已有 true 为 updated
- [x] 3.9 测试只修改所选路径：其他缺失标准字段、未知字段、非目标 Shape 和根对象保持不变
- [x] 3.10 测试多字段同批次、嵌套父对象创建、父对象类型冲突、输入深复制和字段顺序稳定性

## 4. 预检、警告与结果模型

- [x] 4.1 定义文件级/对象级/字段级预检数据模型和 created/updated/unchanged/conflict 聚合计数
- [x] 4.2 实现逐文件原始 JSON 预检，复用第一阶段路径边界、读取校验和严格 Shape ID 分类
- [x] 4.3 实现文件保守策略：任一目标字段类型冲突时整文件不进入暂存，并为同文件目标生成可解释结果
- [x] 4.4 检测 `flags.difficult` 旧格式别名和顶层/flags 值不一致，生成 warning 但不修改别名
- [x] 4.5 实现多个 assignments 下对象最终 changeable/unchanged/conflict 分类和有限预览明细
- [x] 4.6 测试新增/修改/无变化混合计数、多个字段混合状态、旧别名提示和冲突文件整文件跳过

## 5. 安全事务与恢复

- [x] 5.1 实现 `ObjectFieldEditEngine.preflight/stage/commit/cancelled_result` 外观并复用 `JsonTransactionEngine`
- [x] 5.2 在 stage 转换回调中接入纯字段转换，验证暂存 JSON 并保留非目标内容
- [x] 5.3 在 manifest 领域元数据中记录字段 assignments、字段计数、逐对象状态和实际提交文件
- [x] 5.4 实现提交结果聚合：成功文件中的 created/updated 对象为 succeeded，全 unchanged 为 unchanged，未提交文件保守转 failed/conflict
- [x] 5.5 复用源文件指纹检查、数据集写锁、原子替换、部分失败和通用 manifest 恢复
- [x] 5.6 测试预检后源文件变化、暂存取消、提交部分失败、manifest 往返、恢复和无变化不写盘
- [x] 5.7 测试字段编辑与现有标签迁移、对象改标以及当前文件保存之间的项目级写互斥

## 6. 字段编辑 Qt 界面

- [x] 6.1 新增 `widgets/object_field_edit_dialog.py`，提供字段设置行、增加/移除行、对象数和文件数摘要
- [x] 6.2 按字段注册表提供布尔、整数/空值、数值/空值、文本、flags 键和 attributes 标量编辑器
- [x] 6.3 在 UI 边界拒绝重复路径、无效嵌套键、空 label 和错误类型，错误时不创建后台任务
- [x] 6.4 实现预检确认界面，显示 created/updated/unchanged/conflict、deleted/failed 和 difficult 别名提示
- [x] 6.5 在确认文案中明确“缺失的所选字段将新增；未选字段不会补全；字段补全不是前置条件”
- [x] 6.6 实现字段编辑 worker 的预检、暂存、提交阶段进度和第一阶段一致的取消边界
- [x] 6.7 复用或抽取幂等终态清理，确保成功、取消、失败只关闭进度框和显示结果一次
- [x] 6.8 测试字段行编辑器、类型错误、重复字段、取消、预检统计、旧别名 warning 和终态幂等

## 7. LabelingWidget 集成与状态同步

- [x] 7.1 在 Tool 菜单增加“批量编辑已标记对象……”入口并显示/使用当前活动标记数量
- [x] 7.2 入口启动时沿用第一阶段 dirty 文件保存/放弃/取消协调并冻结当前标记快照
- [x] 7.3 构建字段编辑计划时复用项目路径解析和标注路径边界检查，不依赖 Dataset Index 定位写入目标
- [x] 7.4 按最终对象结果清理标记：succeeded/unchanged/deleted 移除，conflict/failed/cancelled 保留，批次外标记不受影响
- [x] 7.5 提交成功后只重载实际提交的当前文件，并刷新标签摘要、Dataset Index 和 Inspector 表格
- [x] 7.6 保持现有“修改已标记对象的标签”入口、文案、确认和测试行为兼容，不要求用户经过通用字段界面
- [x] 7.7 测试跨多图标记、多字段提交、当前文件 dirty、部分失败精确保留标记、批次外标记保护和成功刷新
- [x] 7.8 测试仅设置 difficult 不会补 score/description/attributes，且从未运行字段补全仍可成功提交

## 8. 文档、翻译与验证门禁

- [x] 8.1 更新用户文档，说明字段白名单、缺失字段创建、嵌套冲突、旧 difficult 别名和恢复方式
- [x] 8.2 在文档中明确字段补全是独立后续功能，不属于本 change、不是前置条件且不会被隐式调用
- [x] 8.3 为所有新增 UI 文案使用翻译机制，更新 `.ts` 并运行 `scripts/compile_languages.py` 重建资源
- [x] 8.4 运行纯 Python 目标测试：对象字段编辑、对象改标和通用事务
- [x] 8.5 设置 `QT_QPA_PLATFORM=offscreen` 运行字段编辑 widget、对象改标 widget 和相关 Canvas/LabelingWidget 回归
- [x] 8.6 对触碰的生产文件运行 Black 79、py_compile 和窄范围 flake8，确认未手改生成的 `resources.py`
- [x] 8.7 运行 `openspec validate add-cross-image-object-field-batch-edit --strict` 并修复全部规格问题
- [x] 8.8 完成 GUI 等价验收：offscreen Qt 测试覆盖跨图标记、字段新增、多字段修改、冲突预检、取消、部分失败和 manifest 恢复

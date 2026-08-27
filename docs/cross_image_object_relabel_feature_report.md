# 跨图对象标记与对象级改标 — 功能实现与审核报告

- **变更（OpenSpec）**: `add-cross-image-object-relabel-action`（schema: spec-driven）
- **分支**: `feature/selection-optimization`
- **规格**: `openspec/changes/add-cross-image-object-relabel-action/specs/cross-image-object-relabel/spec.md`
- **任务清单**: 归档目录 `openspec/changes/archive/2026-08-26-add-cross-image-object-relabel-action/tasks.md`（67/67 项已完成，包含完整人工 GUI 验收）
- **用户文档**: `docs/cross_image_object_relabel.md`

## 一、功能概述

为 X-AnyLabeling 增加"跨图片收集具体对象 → 冻结标记快照 → 严格预检 →
对象级安全提交"的完整闭环。核心语义：以
`(project_id, image_id, xanylabeling_shape_id)` 完整对象键严格定位目标，
**只修改唯一命中 Shape 的 `label` 字段**，与全局标签重命名（按标签字符串
匹配所有对象）彻底分离。

入口位于 **Tool 菜单**：

| 动作 | 行为 |
|------|------|
| 跨图对象标记（checkable） | 开启/暂停标记手势，关闭不清空集合 |
| 清空跨图标记 | 清除全部活动标记，不写文件 |
| 修改已标记对象的标签…… | 唯一改标入口（所有未来入口必须收口到此方法） |
| 从恢复清单还原对象改标…… | 选择 manifest.json 回滚一次已提交事务 |

## 二、初始实现的代码修改

### 2.1 新增文件

#### `anylabeling/views/labeling/widgets/object_relabel.py`（纯 Python，无 PyQt）

| 位置 | 内容 |
|------|------|
| `:46-52` | 异常：`ObjectRelabelPlanError`（计划拒绝）、`ObjectIdentityConflict`（重复/非法身份） |
| `:54-93` | `normalize_object_key` + frozen `MarkedObjectRef`（project_id / image_id / shape_id / display_summary，构造即校验） |
| `:96-131` | frozen `ObjectRelabelPlan`（`targets_by_annotation_path` 为 MappingProxy）+ `_is_within` 路径边界 |
| `:133-196` | `build_object_relabel_plan`：从快照构建计划；拒绝空快照、空标签、跨项目、无法解析、逃逸标注根目录；按 JSON 路径分组并按完整键去重 |
| `:198-230` | `FileObjectPreflight` / `ObjectPreflightSummary`（七类计数 + 逐文件明细） |
| `:232-282` | `read_annotation_data`（结构校验）、`_shape_id_counts`、`_has_invalid_shape_id`（缺失/非法身份检测） |
| `:284-324` | `classify_file_objects`：唯一命中→changeable/unchanged，缺失、非法或重复身份→conflict（整文件） |
| `:326-369` | `transform_objects_by_id`：纯转换，深复制输入，只改唯一目标 `label`，保留全部其他字段与顺序 |
| `:371-432` | `ObjectMutationResult` / `ObjectRelabelResult`（逐对象 + 逐文件计数、`committed_annotation_paths`）/ `ObjectStagedBatch` |
| `:434-645` | `ObjectRelabelEngine`：`preflight`（读盘分类，可取消）、`stage`（经通用事务层，逐文件对象状态）、`commit`（原子替换后按 `_final_status` 汇总最终逐对象结果）、`cancelled_result`、`_plan_metadata`（写入 manifest 的领域元数据） |
| `:647-676` | `_ids_for_path`、`_final_status`（changeable+成功→succeeded；文件失败→failed；unchanged 在 failed 文件保守转 failed，skipped 仍视为已验证） |
| `:679-790` | `MarkSyncReport` + `MarkedObjectStore`：toggle / contains / snapshot / snapshot_for_project / refs_for_image / remove / remove_many / clear / counts / counts_for_project / `apply_relabel_result`（succeeded·unchanged·deleted 移除标记，conflict·failed·cancelled 保留，绝不动批次外新标记） |

#### `anylabeling/views/labeling/widgets/object_relabel_dialog.py`（Qt 适配层）

| 位置 | 内容 |
|------|------|
| `:26-105` | `ObjectRelabelThread(QThread)`：后台 preflight→等确认→stage→commit；线程内只接触纯领域对象，不访问 QWidget/Canvas；`confirm_commit`/`request_abort` 控制推进与取消 |
| `:107-165` | `_preflight_message` / `_result_message`：确认与结果文案（`QCoreApplication.translate("LabelingWidget", …)` 静态可提取） |
| `:163-316` | `run_object_relabel_flow`：信号驱动的完整流程——`BatchWriteGate` 申请数据集根、QProgressDialog 进度、预检 QMessageBox 确认（默认 No）、`committing_started` 后移除取消按钮（提交不可取消）、结果对话框显示逐对象/逐文件计数与 manifest 路径、worker 异常经 `on_worker_failed` 回调（不递归） |

#### `tests/test_object_relabel.py`（35 用例）

计划构建/路径边界/不可变性、严格定位（重排·字段变化·删除·重复·非法·禁止模糊匹配）、转换隔离（字段保全·顺序·输入不被原地修改·同标签邻居不变·无变化不写盘）、事务（提交/取消/指纹变化/部分失败/manifest 往返/旧 v1 manifest 恢复）、预检汇总与可取消、仓库（toggle/跨图/冻结/全成功/全取消/部分失败/批次外保护/项目限定）。

#### `tests/test_object_relabel_widget.py`（25 用例，offscreen）

Canvas 真实鼠标事件级：单击 toggle、拖动/顶点/边/空白不 toggle、移动后释放不 toggle、暂停模式保留标记、overlay 跟随身份且重复绘制不改变缓存边界；Widget 旁路：切图恢复、删除清标记、空标记提示、取消标签选择不建事务、dirty 三分支中止、部分失败不清标记/成功才重载、worker 取消与异常回调、终态弹框幂等关闭；审核修复回归（见 4.2）。

#### `docs/cross_image_object_relabel.md`

用户文档：流程说明、与全局重命名对照表、结果与重试、并发边界、已知局限。

### 2.2 修改文件

#### `anylabeling/views/labeling/widgets/label_batch.py`（事务层泛化）

| 位置 | 内容 |
|------|------|
| `:276-288` | 新增 `StagedTransform`：每文件纯转换结果（data/changed/matched_shapes/metadata/skip_reason），metadata 进入 manifest |
| `:334-581` | **新增 `JsonTransactionEngine`**：从原 `BatchMigrationEngine.stage/commit/restore` 抽取的通用事务层——`stage_files(sources, transform, cancel, progress, domain)`、`commit`（`DatasetWriteCoordinator` 锁 + 指纹复核 + `os.replace` 原子替换 + manifest 状态回写，保留 domain）、`restore`（备份回滚）、manifest v2（可选 `domain` 顶层 + 条目 `domain_metadata`），读取兼容旧 v1 |
| `:583-657` | `BatchMigrationEngine` 改为兼容门面：公开 API 与全局 rename/delete 语义不变，`stage` 经适配闭包委托 `stage_files` |

#### `anylabeling/views/labeling/widgets/canvas.py`（标记手势与 overlay）

| 位置 | 内容 |
|------|------|
| `:266` | 信号 `batch_mark_toggle_requested(object)` |
| `:345-349` | 状态：`batch_mark_mode` / `marked_shape_ids` / `_batch_mark_press` |
| `:2270-2275` | `mousePressEvent` 编辑分支：按下时记录候选（顶点/活动边/空白不合格） |
| `:2408-2409` | `mouseReleaseEvent` 编辑分支：仅"候选一致 + 未发生几何移动 + 位移低于拖动阈值"才 emit toggle |
| `:3950` | `paintEvent`：正常绘制与既有 overlay 之后调用 `_draw_batch_mark_overlay` |
| `:6505` | `load_shapes` 重置 `_batch_mark_press`（切图防串扰） |
| `:6614-6700` | 新方法：`set_batch_mark_mode`、`set_marked_shape_ids`、`_batch_mark_capture_press`、`_emit_batch_mark_toggle_if_click`、`_draw_batch_mark_overlay`（橙色虚线外框，屏幕恒定线宽，不改 Shape 任何状态） |

#### `anylabeling/views/labeling/label_widget.py`（会话所有权与入口）

| 位置 | 内容 |
|------|------|
| `:166-175` | 导入领域模块与 `run_object_relabel_flow`、`JsonTransactionEngine` |
| `:412-415` | `__init__`：唯一 `MarkedObjectStore`、`_object_relabel_thread`、`_object_relabel_running` |
| `:738-740` | 连接 `batch_mark_toggle_requested` → `toggle_marked_object` |
| `:1407-1457` | 四个 action（标记开关/清空/改标/恢复清单）+ `object_mark_actions` Struct |
| `:2706-2708` | Tool 菜单条目 |
| `:4244` | **union_selection**：合并删除旧 shape 前清标记（审核修复） |
| `:4312-4330` | `toggle_batch_mark_mode` / `toggle_marked_object` / `clear_marked_objects` |
| `:4338-4427` | `relabel_marked_objects`：唯一入口——项目限定计数与快照 → dirty 三分支 → 目标标签选择 → 计划构建（失败给结构化错误）→ 启动 flow；flow 拒绝时恢复 action（审核修复） |
| `:4429-4454` | `_candidate_target_labels` / `_marked_project_id`（output_dir 或数据集根，normcase）/ `_annotation_path_for_image`（与 load_file 同规则：output_dir 拼接或同目录 .json） |
| `:4456-4475` | `_sync_marked_object_ui`：按当前项目/图片刷新 overlay + badge（项目限定计数） |
| `:4477-4493` | `_remove_marks_for_shapes`：删除钩子共用逻辑 |
| `:4495-4517` | `_apply_object_relabel_result`：按逐对象结果同步仓库 → 对提交成功文件的 image_id 调 `_dataset_index_controller.label_saved`（审核修复）→ 仅当前文件提交成功才 `load_file`，否则仅同步 UI |
| `:4519-4567` | `restore_object_relabel_from_manifest`（文件选择入口）+ `restore_object_relabel_manifest`（备份回滚 + 当前文件刷新） |
| `:7485` | `load_shapes` 尾部 `_sync_marked_object_ui()`（切图/加载恢复标记视觉） |
| `:9528-9536` | `closeEvent`：运行中 worker `request_abort` + `wait(2000)`（审核修复） |
| `:10429, :10438` | `remove_selected_point` / `delete_selected_shape` 删除钩子 |

#### `anylabeling/views/labeling/widgets/label_dialog.py`

| 位置 | 内容 |
|------|------|
| `:37, :1739-1752` | `LabelModifyDialog._start_batch` 启动前 `BatchWriteGate.try_acquire(transaction_root, "label-batch")`，失败提示并放弃（审核修复） |
| `:1840-1843` | `on_batch_thread_finished` 终止信号释放 gate（审核修复） |

#### 资源与翻译

- `zh_CN.ts` / `zh_CN.qm` / `resources.py`：补充恢复、关闭保护等 review 文案，
  并运行 `scripts/compile_languages.py` 重建资源；翻译经编译检查。

## 三、第三视角审核（实现完成后）

**方法**：独立 QA 探索代理对照 spec 全部 Requirement/Scenario 逐条核查
实现（不共享实现者上下文），随后实现对每项 MAJOR 结论做代码级复核。
结果：22 个场景中 19 个直接验证通过；发现 **3 MAJOR / 5 MINOR / 5 INFO**
共 13 项。

| # | 级别 | 发现 | 判定 |
|---|------|------|------|
| 1 | MAJOR | 提交后从不刷新 Dataset Index，非当前文件的标签→文件索引过期 | 成立（代码级复核确认） |
| 2 | MAJOR | `union_selection` 合并删除 shape 不清标记，悬空标记污染计数 | 成立（全库第三处删除路径漏钩） |
| 3 | MAJOR | 并发互斥仅靠模态性"碰巧"成立：gate 只拦对象改标自身；Label Manager 不参与；无 output_dir 时锁 key 可能不同 | 成立（部分结构性） |
| 4 | MINOR | `run_object_relabel_flow` 返回 False 时入口 action 永久禁用 | 成立（当时不可达，契约错配） |
| 5 | MINOR | 非法类型 id（如 int）被判 deleted 并静默移除标记，spec 要求 conflict | 成立（按 spec 字面） |
| 6 | MINOR | 混合冲突文件预检虚报 changeable，与 stage 整文件冲突不一致 | 成立 |
| 7 | MINOR | 提交失败文件内 unchanged 对象仍移除标记，磁盘状态未知违背重试语义 | 成立 |
| 8 | MINOR | `restore_object_relabel_manifest` 无任何调用者（死代码） | 成立 |
| 9 | MINOR | 跨项目标记泄漏：计数含异项目、快照含异项目导致整体报错 | 成立 |
| 10-13 | INFO | 关闭不等待线程 / 事务目录累积 / commit 前取消竞态（无害）/ 无文件静默 no-op | 记录 |

另实现者自检阶段已发现并修复 1 项未列入上表：`on_failed` 闭包遮蔽参数
导致 worker 异常路径无限递归（更名 `on_flow_failed` + 回归测试）。

## 四、审核后修复

### 4.1 修复明细

| 修复 | 位置 | 内容 |
|------|------|------|
| 索引刷新（#1） | `label_widget.py:4495-4517` | 提交成功文件的 image_id 去重调用 `label_saved`，沿用保存路径的 defer/STALE 容错；测试证明仅 committed 触发 |
| union 钩子（#2） | `label_widget.py:4244` | `delete_selected()` 结果先 `_remove_marks_for_shapes` 再 `remove_labels` |
| 预检一致性（#6） | `object_relabel.py:466-475` | `file_status == conflict` 时聚合计数整文件计 conflict，明细保留 |
| 失败文件保守化（#7） | `object_relabel.py:654-676` | `_final_status`：unchanged 在 failed 文件→failed（保留标记）；skipped 仍为已验证成功（docstring 固化边界） |
| 项目限定（#9） | `object_relabel.py:719-726, 765-770`；`label_widget.py:4338-4362, 4465` | 新增 `snapshot_for_project`/`counts_for_project`；入口与 badge 全部改用项目限定视图 |
| BatchWriteGate（#3 部分） | `label_batch.py:304-332`；两处接入 | 进程级按根互斥注册表；对象改标与标签迁移启动前申请、终止信号释放 |
| flow 返回值（#4） | `label_widget.py:4415-4427` | 拒绝启动时立即恢复 `_object_relabel_running` 与 action |
| 身份校验一致性（#5 + review） | `object_relabel.py` | 缺失、非法或重复 ID 均按文件级 conflict 处理，preflight、stage 和纯转换共用同一规则 |
| 恢复入口（#8） | `label_widget.py:4519-4533`；菜单 `:2708` | "从恢复清单还原对象改标…"（QFileDialog → restore） |
| 关闭保护（#10 + review） | `label_widget.py` | `closeEvent` 中止可取消阶段；提交未结束时拒绝关闭，避免销毁运行中的 worker |
| 恢复安全（review） | `label_widget.py` / `label_batch.py` | 恢复前处理 dirty、校验当前数据集、获取互斥与写锁，并刷新恢复文件索引 |
| 多目录根（review） | `label_widget.py` / `label_dialog.py` | 导入目录或图片共同根作为统一 project/annotation/transaction 根 |
| overlay 累积放大（实际 GUI 验收） | `canvas.py:_draw_batch_mark_overlay` | 使用 `QRectF.adjusted()` 生成外扩副本，不再原地修改 `Shape.bounding_rect()` 缓存 |
| 弹框持续刷新（实际 GUI 验收） | `object_relabel_dialog.py` | 预检确认时隐藏进度框；按 `index/total` 更新；终态等待线程、关闭进度框并只提示一次 |
| manifest 无可选 JSON（实际 GUI 验收） | `label_widget.py:restore_object_relabel_from_manifest` | 从统一批处理根目录打开，过滤器使用 `*.json`，内容仍由恢复流程校验 |

### 4.2 新增回归测试（对应上述修复）

- `test_apply_result_refreshes_index_only_for_committed_files`（索引）
- `test_union_selection_cleans_marks_of_merged_shapes`（union 钩子静态契约）
- `test_preflight_counts_whole_conflict_file_as_conflict`（预检一致性）
- `test_failed_file_turns_unchanged_objects_into_failures`（保守化，含 skipped 对照）
- `test_store_project_scoped_snapshot_and_counts` + `test_entry_uses_project_scoped_counts`（项目限定）
- `test_batch_write_gate_blocks_overlapping_owners`（互斥）
- `test_entry_recovers_when_flow_refuses_to_start`（flow 返回值）
- `test_classification_treats_illegal_ids_as_conflict` / `test_classification_missing_field_is_file_conflict`（非法/缺失 id）
- `test_object_stage_preserves_illegal_identity_conflict_from_preflight`（预检与暂存一致）
- `test_restore_entry_and_close_guard_are_wired`（恢复入口与关闭保护接线）
- `test_dataset_root_uses_import_root_for_nested_images` + `test_prune_missing_marked_objects_cleans_shape_manager_deletions`
- `test_mark_overlay_repaint_does_not_expand_cached_bounds`（重复绘制不改变 Shape 缓存边界）
- `test_relabel_flow_closes_progress_and_reports_result_once`（终态关闭和结果提示幂等）
- `test_restore_picker_accepts_json_from_batch_root`（恢复入口目录与 JSON 过滤器）

## 五、记录在案的偏差（不修）

记录于 `tasks.md` 第 9.3 节与 `docs/cross_image_object_relabel.md`「已知局限」：

1. ShapeManager 区间删除仍是历史无事务直写，不参与 BatchWriteGate；但操作
   完成后会清理已经不存在的跨图标记。
2. 模态进度对话框使"预检期间继续标记"场景实际不可达（spec 空真满足）。
3. 事务目录在数据集根累积不清理（与标签迁移既有模式一致）。

## 六、验证与门禁汇总

| 命令 | 结果 |
|------|------|
| `pytest tests/test_object_relabel.py tests/test_label_batch.py -q` | **49 passed**（35 对象改标 + 14 事务） |
| `pytest tests/test_object_relabel_widget.py -q`（offscreen） | **25 passed** |
| 加 canvas 回归（multiselect/interaction/rect_edge 等 6 文件） | **122 passed** |
| 全量套件 `pytest -q`（offscreen） | 1286 passed / 5 failed——失败全部位于 `test_settings/test_schema.py`，由并行进行中的 behavior analytics 变更的配置字段数漂移引起（本变更未触碰任何配置/settings 文件） |
| `black -l 79`（本次触碰的 3 个生产文件） | 通过 |
| `flake8`（新增/窄改文件与测试） | 通过；`label_widget.py` 仍有 9 条历史 F841/C901/F541，未新增 |
| `compile_languages.py` | `.qm` 与 `resources.py` 已重建 |
| `openspec validate add-cross-image-object-relabel-action` | valid |

## 七、收口状态

- **8.4 手工 GUI 验收**已完成：跨三图标记、快照后继续标记、对象编辑与数组
  重排、冲突文件、dirty 文件、取消、部分失败、manifest 恢复均已通过。
- 本 change 已达到归档条件；主规格已同步。

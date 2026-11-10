# 任务 1.2 矩形修改入口矩阵

> 变更：`openspec/changes/add-annotation-correction-cost-statistics` 任务 1.2
> 仓库：`D:\X-AnyLabeling-4.2.1`（只读测绘，未修改任何仓库文件）
> 生成：entry-mapper / 2026-11-10

## 0. 先决事实（影响整张表的读法）

### 0.1 路径勘误（任务描述中的位置与实际不符）

| 任务描述给的路径 | 实际路径 | 说明 |
| --- | --- | --- |
| `anylabeling/views/labeling/canvas.py` | `anylabeling/views/labeling/widgets/canvas.py`（6569 行） | 不存在前者 |
| `anylabeling/utils/batch.py` | `anylabeling/views/labeling/utils/batch.py` | `anylabeling/utils/` 不存在 |
| `anylabeling/views/labeling/inspector/controller.py` | 存在，但它是**检查运行**的 `InspectionController`（线程/进度/Qt 信号） | 标注编辑的 Inspector 入口在 `label_widget.py` 的 `inspection_*` 方法，不在 controller 里 |

### 0.2 关键前提：记录点已预埋，但统计运行时尚未接线

- `views/labeling/correction_metrics/` 目录下只有 `clock_adapter.py`、`hooks.py`、`i18n.py`；
  `hooks.metrics_available()` 期望的 `controller.py`、`panel.py`、`report_dialog.py` **全部缺失**（目录实测）。
- 因此 `metrics_available()` 恒为 False：`open_correction_metrics`（label_widget.py:4375）只弹"开发中"提示；菜单项在 1385-1393 就已禁用。
- `hooks.notify_metrics()` 对 `host.correction_metrics` 取 `getattr`，该属性在 303 行初始化为 `None`，全仓库无赋值点（`start_metrics` 只存在于不可达分支 4384）。
- **结论**：下表"已采集"的准确含义是"**已预留记录点（记录了 kind/source/changed），运行时不会落库**"；真正接入要到 tasks 4.4–4.7。

### 0.3 数据契约侧已具备的能力（决定哪些记录点算合格）

`services/correction_metrics/core.py`：`CorrectionRound.patch(shapes, removed_ids, kind, source, transaction_id, undo_of)`（344）、`sync()`（334）、`_event(..., tx, undo_of)`（313，含 `tx` 幂等去重）、`review_event()`（412）、`taxonomy()`（423）、`prepare_save()/saved()/save_failed()/discard()`（456-516）。
即：**契约要求每次事务给出唯一 `transaction_id` 与受影响对象集合**，并能关联 `undo_of`。现有记录点多数只传 `changed=`，撤销完全不传 `undo_of` → 见 C 类风险。

---

## 1. 入口矩阵总表

保存路径缩写：
- **A** = `set_dirty()`（label_widget.py:3621）→ 若 `auto_save` 开则立即 `save_labels()`（3631-3636）→ `LabelFile.save`（7679-7690）；`auto_save` 关则仅置 dirty，等 Save（`save_file` 9619）/切图 `may_continue`（9887）。
- **B** = 显式 `save_file` → `save_labels` → `LabelFile.save`。
- **C** = **绕过** `save_labels`，直接 `atomic_write_json` 写已存在的图片 JSON。

| # | 入口 | 触发 / 关键函数（文件:行） | 一次操作的事务完成边界 | 实际保存路径 | 现有 correction_metrics 采集 | 缺口判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **创建矩形**（画框） | 画布拖拽：`canvas.add_point_to_shape` 收尾 `shapes.append` + `store_shapes()` + `new_shape.emit()`（canvas.py:5641-5646）→ `label_widget.new_shape()`（7842） | 用户确认标签、`shape.label` 落地那一行：`notify_metrics(self,"edit","create",changed=[shape])`（7933）+ `set_dirty()`（7934）。注意 canvas 侧 5642 已先 push undo 快照 | A | ✅ `edit/create`，`changed=[shape]` | 事务被切成两段（undo 在 5642、metrics 在 7933）；标签为空/非法时直接 return（7906-7914、7919 `if text:`）→ **产生无记录的新框**（B5 同类） |
| 2 | **数字键创建**（无选中） | Action `digit_shortcut_0..9` → `create_digit_mode()`（5734；判定 5752-5778）→ `digit_to_label` + `toggle_draw_mode(edit=False)` → 画框 → `new_shape`（7863-7868 直取 digit 绑定） | 同 #1：7933 | A | ✅ `edit/create`（同一处） | 与 #1 同一记录点，无法区分"手选类"与"数字键类" |
| 3 | **删除（Delete / 右键删除）** | `delete_selected_shape`（9947）→ `canvas.delete_selected`（4587，内部 `store_shapes()` 4596）→ `remove_labels`（7432） | `notify_metrics(self,"edit","delete",removed=removed)`（9967）+ `set_dirty()` | A | ✅ `edit/delete`，`removed=` | — |
| 4 | **删点导致形状消失** | `remove_selected_point`（9936）→ `canvas.remove_selected_point`（2175 起）：点数低于下限时 `shapes.remove` + `store_shapes()` + `shapes_deleted.emit([shape])`（2185-2193） | 走 emit 分支时：`on_canvas_shapes_deleted`（7432）→ 7434 `edit/delete` | A | ⚠️ 仅 emit 分支有（7434） | **B5**：若 `h_shape.points` 为空走 label_widget 9939-9942（`canvas.delete_shape` + `remove_labels` + `set_dirty`），**无任何 notify**；`canvas.delete_shape`（4603）本身不发 `shapes_deleted` |
| 5 | **复制（原地副本 Ctrl+D）** | `duplicate_selected_shape`（7732）→ `canvas.duplicate_selected_shapes`（4614）→ `end_move(copy=True)`（3661，3678 `store_shapes()`） | `notify_metrics(self,"edit","duplicate",changed=added_shapes)`（7743） | A | ✅ `edit/duplicate` | 与 #6、#7 共用 kind，三者不可区分 |
| 6 | **移动复制（拖拽+Ctrl）** | `copy_shape`（9973）→ `canvas.end_move(copy=True)` | `notify_metrics(self,"edit","duplicate",changed=self.canvas.selected_shapes)`（9984） | A | ⚠️ 已采集但对象集合取的是 `canvas.selected_shapes`（**当前选中**），不一定等于本次新增集合 | A4：selection 变化即错位 |
| 7 | **粘贴** | `paste_selected_shape`（7746）：系统剪贴板 JSON（7750-7766）或内部 `_copied_shapes` → `canvas.prepare_pasted_shapes`（4641，仅换新 id/解锁/换 group，**不 store_shapes**）→ `load_shapes(replace=False)`（7440） | `notify_metrics(self,"edit","paste",changed=shapes)`（7771）+ `set_dirty()` | A | ✅ `edit/paste` | undo 快照由 `load_shapes(record_history=True)` 内部产生，与 metrics 不同函数，边界可接受 |
| 8 | **拖动（整框平移）** | `canvas.mouseReleaseEvent` → `store_moving_shape()`（519）：仅当点真的变化才 `store_shapes()` + `shape_moved.emit()`（536-537） | `shape_moved` → `_on_geometry_committed`（4371）→ `notify_metrics(self,"geometry")`（4372）+ `set_dirty()`（4373） | A | ⚠️ 已采集**但无对象 id**（`notify_metrics(self,"geometry")` 不传 `changed`） | **C1**：无法计算对象触达/去重对象数；无法定位是哪些框动了 |
| 9 | **拖边/拖角（矩形边手柄）** | `widgets/rectangle_edge.py`：`_rectangle_edge_press`（185）→ `_rectangle_edge_drag_move`（205，中途 243 会 `store_shapes()`）→ `_rectangle_edge_release_event`（254） | 释放时 265 `store_shapes()` + 266 `shape_moved.emit()` → 4372 `"geometry"` | A | ⚠️ 已采集，无 id | A3：拖拽中 243 已 push 多个 undo 快照（撤销粒度 vs 事务粒度不一致）；metrics 只在释放记一条（粒度正确） |
| 10 | **滚轮 Alt 改框（缩放/调边）** | `canvas.wheelEvent`（5847-5873）：命中单矩形+Alt → `_scale_rectangle` / `_adjust_rectangle_edge`（5865-5867） | 每一格滚轮：5869 `store_shapes()` + 5870 `shape_moved.emit()` → 4372 `"geometry"` | A | ⚠️ 已采集，无 id | **A1**：一次"调框"按滚轮格数产生 N 条 geometry → 事务数虚高 |
| 11 | **Shift 单点拟合** | `widgets/point_fit.py`：`_point_fit_press`（255）→ `_point_fit_release`（278） | 成功提交分支 315 `store_shapes()` + 316 `shape_moved.emit()` → 4372 `"geometry"` | A | ⚠️ 已采集，无 id | 与拖动/拖边共用无参 geometry，**两种单点拟合无法区分** |
| 12 | **Shift+Alt 单点拟合** | 同一 `_point_fit_release`（278），角点/内缩由 `_point_fit_cursor`/`_point_fit_inward` 决定；修饰键预览走 `_point_fit_refresh_from_cursor`（228，canvas.py:6084-6092） | 同 #11（315-316） | A | ⚠️ 同上 | Shift 与 Shift+Alt 只能从 before/after 几何反推 |
| 13 | **键盘微调（方向键）** | `canvas.keyPressEvent` 6117-6144 → `move_by_keyboard`（6037，`moving_shape=True`）；`keyReleaseEvent` 6187-6203 比对备份 | 6188-6201：点变化 → `store_shapes()` + 6201 `shape_moved.emit()` → 4372 `"geometry"` | A | ⚠️ 已采集，无 id | **A2**：长按自动重复 → 每次松开记一条（事务数虚高）；单次微调也无 id |
| 14 | **数字键改类（有选中）** | Action digit → `create_digit_mode()`（5734）→ 有选中走 `_relabel_selection`（5780）→ `_apply_field_patch(shapes,{"label":label},{"label"})`（5790）→ `editing_commands.apply_field_changes`（29）+ `store_undo_step`（97） | `_apply_field_patch` 内 `store_undo_step(self.canvas)`（6549）之后 → `notify_metrics(self,"edit","relabel"/"attributes",source,changed=changed)`（6571-6574）+ `set_dirty()`（6575） | A | ✅ `edit/relabel`，`changed=` | source 缺省 `"manual"`，与 #15/#18 的改类不可区分（C3） |
| 15 | **字段对话框改字段（多选批量）** | `edit_label`（6586）→ `len(selected)>1` → `batch_edit_labels`（6489）→ `_apply_field_patch(...)`（6531） | 同 #14（6549 → 6571） | A | ✅ `edit/relabel` / `edit/attributes`（按 `touched` 里是否有 `label`） | 只 patch 用户显式改的字段（`editing_commands.BATCH_FIELDS`），语义正确 |
| 16 | **字段对话框改字段（单选）** | `edit_label`（6586）：单对象 → `label_dialog.pop_up(...)`（6617-6631）→ **直接赋值** `shape.label/flags/group_id/description/difficult/kie_linking/review_status`（6636-6643）→ `set_dirty()`（6672） | **没有任何事务完成点**：无 `_apply_field_patch`、无 `store_undo_step`、无 `notify_metrics` | A | ❌ **完全未采集** | **B1（最高风险）**：最高频的单框改类/改属性 0 记录，且**连 undo 快照都没有**（4.2.1 原生行为） |
| 17 | **全局类别管理（重命名/合并/删除类）** | `widgets/label_dialog.py::LabelModifyDialog.modify_label`（1248-1315）；由"修改标签"对话框确认触发（`confirm_changes`/`update_range` 1302-1365 区段） | 每个图片 JSON 的 `atomic_write_json(label_file, data)`（1305）即完成；随后尝试 `metrics.taxonomy_saved(image_file, label_file, dst_shapes, renames, comparable)`（1308） | **C**（直写 JSON，不经 `save_labels`/`LabelFile.save`；不改画布、不 `set_dirty`） | ❌ 预埋了调用但**永不生效**：`self.parent.correction_metrics` 恒 `None`；且 `taxonomy_saved` 在 core.py 中不存在（core 是 `CorrectionRound.taxonomy()`） | **B2**：跨图批量改类完全未采集；**绕过保存管线**，`prepare_save/save_result` 的 revision 语义对它不成立（tasks 4.6 明确点名） |
| 18 | **分组 / 取消分组** | `group_selected_shapes`（10612）/`ungroup_selected_shapes`（10615）→ `_apply_field_patch(targets,{"group_id":...},{"group_id"})`（10641） | 同 #14 | A | ⚠️ 记为 `edit/attributes`（"label" 不在 touched 里） | 与"改属性"混同（C3） |
| 19 | **Inspector：删除对象** | `inspection_delete_shapes`（5312）：逐框 `canvas.delete_shape`（5338，每个都 `store_shapes`），随后重建批量 undo（5342-5348） | `notify_metrics(self,"edit","delete","inspection_edit",removed=deletable)`（5346） | A | ✅ `edit/delete`，source=`inspection_edit` | **A5**：undo 侧被折叠成一条（5345-5348），但 `canvas.delete_shape` 每次 push（4611）→ 撤销粒度与事务粒度不一致；metrics 一条（正确） |
| 20 | **Inspector：改类** | `inspection_relabel_shapes`（5364）→ `_apply_field_patch(..., source="inspection_edit")`（5375-5377） | 同 #14（6549→6571），source=`inspection_edit` | A | ✅ `edit/relabel`，source 可区分 | — |
| 21 | **Inspector：接受候选（新建矩形）** | `inspection_accept_candidate`（5380）→ `load_shapes([shape], replace=False)`（5446） | `notify_metrics(self,"edit","create","inspection_edit",changed=[shape])`（5457） | A | ✅ `edit/create`，source=`inspection_edit` | 外部候选 → 人工确认的"新增"语义正确 |
| 22 | **撤销（画布）** | `undo_shape_edit`（3970）→ `canvas.restore_shape`（713，pop `shapes_backups`）→ `load_shapes(record_history=False)`（3986） | `notify_metrics(self,"edit","undo")`（3996）+ `set_dirty()` | A | ⚠️ 已采集但**不传 `undo_of`/`transaction_id`** | **C2**：无法与上一事务配对；`core._event` 支持 `undo_of` 但无人使用；也无 affected ids |
| 23 | **重做（画布）** | `redo_shape_edit`（4000）→ `canvas.redo_shape` | `notify_metrics(self,"edit","redo")`（4039） | A | ⚠️ 同上 | 同上 |
| 24 | **密集复核：撤销进度** | `undo_shape_edit` 前置分支（3976-3983）：`session.next_undo_kind()=="progress"` → `session.undo_progress()` | `notify_metrics(self,"review_event","undo-review")`（3980） | 进度存 `other_data[DENSE_REVIEW_FIELD]`，随 `save_labels` 落盘 | ⚠️ 用 `review_event`，与框修改区分开（方向正确） | 与 #22 共用同一快捷键，靠 `next_undo_kind` 分流；分流判断有偏差会把审核进度记成框修改（tasks 4.7 明确禁止） |
| 25 | **密集复核：重做进度** | 4006-4024 | `review_event`/`redo-review`（4010、4023） | 同上 | ⚠️ 已采集 | 同上 |
| 26 | **密集复核：确认对象 / 批量确认** | `dense_review/workspace.py:2160` `session.confirm_batch(...)`；`:2196` `session.confirm_object(shape_id, dimensions)`；会话 `DenseReviewSession`（`services/dense_review/session.py:70`，`confirm_batch` 522、`confirm_object` 580） | `confirm_object/confirm_batch` 返回 True 即完成；进度写入 payload → `other_data[DENSE_REVIEW_FIELD]` | 随 `save_labels` | ❌ **完全未采集**：`workspace.py` 全文无 `notify_metrics`/`correction_metrics`（grep 0 命中）；label_widget 侧只有 undo/redo-review | **B4**：确认"这张图/这个对象已复核"是核心成本信号，现在 0 记录；tasks 4.7 明确要求接入 |
| 27 | **AI 单张：应用预测结果** | `new_shapes_from_auto_labeling`（10250）；迟到/错图 → `notify_metrics(self,"prediction_unapplied",...)`（10260-10264） | 应用完成、`annotations_changed` 判定后：`notify_metrics(self,"prediction_applied",auto_labeling_result)`（10349）+ `set_dirty()`（10350） | A | ✅ `prediction_applied` / `prediction_unapplied` | replace（替换）vs additive（追加）需 core 侧从 before/after 推断；`provenance` 有白名单过滤（`safe_provenance` core.py:52） |
| 28 | **AI 批量预标注（run_all_images）** | `utils/batch.py::run_all_images`（803）→ `BatchProcessingThread`（468/487）→ `process_next_image`（552）→ `save_auto_labeling_result`（362） | 每图 `atomic_write_json(label_file, data)`（445）成功即完成；随后 `manager.batch_prediction_saved.emit(image, label_file, shapes, source, predicted_ids, replace)`（456-457） | **C**（直写 JSON；不经 `save_labels`/`LabelFile.save`；不动画布） | ❌ 信号 `batch_prediction_saved`（`model_manager.py:499`）**无接收方**（controller 缺失）；失败仅 `prediction_unapplied`（batch.py:449-453） | **B3**：批量结果完全未采集；且"部分失败"只能靠逐图 emit 判断，tasks 4.3 要求"部分失败不报整批成功" |
| 29 | **保存 / 丢弃 / 切图 / 关闭** | `save_labels`（7636）：`prepare_save`（7679）→ `LabelFile.save` → `save_result True`（7690）/失败 `False`（7726）；`discard`（9905）；`leave_image`（3833）；`enter_image`（9107）；`stop`（9331） | `save_result` 即保存事务完成；`prepare_save` 返回 `metrics_token` 供配对 | B（显式）/ A（auto_save 触发） | ✅ `prepare_save`/`save_result`/`discard`/`leave_image`/`enter_image`/`stop` | 保存与编辑的关联依赖 `CorrectionRound.prepare_save→saved` 配对，目前记录点是裸 token，无 controller 串接 |
| 30 | **外部文件改动 / 画布与磁盘不一致** | `reconcile_dirty`（3623，`set_dirty` 内）与 #17 直写 | — | C | ⚠️ 仅 `reconcile_dirty` 提示 | 全局改类直写磁盘后无 reconcile，当前画布与磁盘可能不一致（归属 #17） |

> 说明：`copy_selected_shape`（7786，Ctrl+C）只写 `_copied_shapes`/系统剪贴板，**不修改标注**，无需记录，不算缺口。
> 说明：右侧 attributes 面板直接改属性的提交函数本次未逐行核实，列入待确认（B6），不臆断为缺口。

---

## 2. 统计口径速查

- **已枚举入口 30 条**（含保存/生命周期 2 条、外部改动 1 条；其中 Ctrl+C 为只读已单列排除）。
- **已有记录点**：`notify_metrics` 全仓库 22 处（label_widget.py 21 处 + hooks 定义），覆盖 13 个入口类别：
  create（含数字键/Inspector）、delete（主路径）、duplicate×2、paste、geometry（拖动/拖边/滚轮/两种单点拟合/键盘微调 → 合并为 1 个无参事件）、relabel/attributes（数字键/批量对话框/Inspector 改类/分组）、undo、redo、review_event（仅 undo/redo-review）、prediction_applied/unapplied、prepare_save/save_result/discard/leave_image/enter_image/stop。
- **类别覆盖**：✅ 可用 11 条；⚠️ 有记录但口径不足 12 条（其中 6 条是无 id 的 geometry）；❌ 完全未覆盖 5 条 + 1 条待确认（#16、#17、#26、#28、#4 分支、B6）。

---

## 3. 高风险漏采集清单

### A 类：一次操作会产生**多次**记录（事务数虚高 / 粒度错）

| 编号 | 入口 | 机制（证据） | 后果 |
| --- | --- | --- | --- |
| A1 | 滚轮 Alt 改框 | 每格滚轮都 `store_shapes()` + `shape_moved.emit()`（canvas.py:5869-5870）→ 每条一条 `geometry` | 一次"微调一下边"可能记 10+ 次事务，tasks 2.4 的"累计事务数"失真；拖滚轮调框 = 成本被高估 |
| A2 | 键盘微调 | `keyReleaseEvent` 6187-6201 每次松开都 emit；长按自动重复 | 同上；10px 微调可能算 10 次修正 |
| A3 | 拖边中途 push undo | `rectangle_edge._rectangle_edge_drag_move` 243 内 `store_shapes()` | metrics 只在释放记 1 条（✅），但 undo 栈每条都是独立步 → 撤销一次拖边要按 N 次 Ctrl+Z，与"一事务一撤销"矛盾，间接影响 undo 计数口径 |
| A4 | 移动复制对象集合错位 | `copy_shape`（9984）用 `self.canvas.selected_shapes` 当 `changed=` | 记录对象与实际新增对象可能不一致 → 对象触达/去重对象数错误 |
| A5 | Inspector 批量删除的 undo 折叠 | `inspection_delete_shapes` 5338 每个 `delete_shape` 都 push，5345-5348 事后重建 | 将来若按 undo 栈推算事务，会与 5346 的单条 metrics 打架 |

### B 类：**完全未覆盖**（0 记录）

| 编号 | 入口 | 证据 | 后果 |
| --- | --- | --- | --- |
| **B1** | **单对象字段对话框修改**（改类/难度/描述/分组/审核状态） | `edit_label` 6636-6643 直接赋值 → 6672 `set_dirty()`；无 `_apply_field_patch`、无 `store_undo_step`、无 `notify_metrics`（对比多选路径 #15 有全套） | 最高频的"改一个框的类"完全不计成本；且**连撤销都没有**，误改无法回退 → 修正成本被系统性低估，tasks 4.6 核心场景失败 |
| **B2** | **全局类别管理（重命名/合并/删类）** | `label_dialog.py::modify_label` 1305 `atomic_write_json` 直写；1308 `metrics.taxonomy_saved` 因 `correction_metrics is None` 永不执行，且该方法在 core.py 中不存在（core 是 `CorrectionRound.taxonomy`） | 跨图批量改类 0 记录；tasks 2.5/4.6 要求的"类别版本 + 一对一重命名映射、合并/拆分导致 C 未知"完全无数据来源；直写绕过 `save_labels`，不做 reconcile，当前打开图内存/磁盘会分叉 |
| **B3** | **AI 批量预标注结果** | `utils/batch.py:362-458`：`atomic_write_json`（445）+ `batch_prediction_saved.emit`（456），无接收方 | tasks 4.3 无法实现"逐图保存结果与一致起点、部分失败不报整批成功"；批量 AI 产物会被算成"未知来源旧标注" |
| **B4** | **密集复核确认（对象/批量）** | `workspace.py:2160/2196`；workspace.py 无任何 metrics 引用 | "哪张图被确认为复核完成"0 记录 → 无法算复核效率、无法区分"审图时间"与"改框时间"（tasks 4.7、6.x 依赖它） |
| **B5** | **删点致形状消失（空点分支）** | `label_widget.py:9939-9942`：`canvas.delete_shape` + `remove_labels` + `set_dirty`，无 notify；`delete_shape` 本身不发 `shapes_deleted` | 少量但真实的删除丢失；且 undo 由 `canvas.delete_shape` 内部 push → 出现"能撤销但没记录"的孤记录 |
| **B6** | 右侧属性面板直接改属性（**待确认**） | 本次未逐行核实提交函数（时间盒限制） | 若存在直接 `setattr` 路径，与 B1 同类；建议 4.6 实施前补一次定位 |

### C 类：有记录，但**口径不足以支撑指标**（会算错而不是算漏）

| 编号 | 问题 | 证据 | 后果 |
| --- | --- | --- | --- |
| **C1** | `geometry` 事件**不带受影响对象 id** | 4372 `notify_metrics(self,"geometry")`；6 个不同交互（拖动/拖边/滚轮/Shift 拟合/Shift+Alt 拟合/键盘）共用同一调用 | tasks 2.4"对象触达次数与去重对象数"、2.3"B/F/G/C 净差异"无法归因；也无法按入口分类成本 |
| **C2** | 撤销/重做**不传 `undo_of`/`transaction_id`** | 3996 `"edit","undo"`、4039 `"redo"`；而 `core._event`（313）已支持 `tx`/`undo_of` | "新增再删及多次修改再撤销的过程/净结果分离"（2.4）无法实现；幂等去重（`_seen`）永不生效 |
| **C3** | `relabel` 与 `attributes` 靠 `"label" in touched` 二分，source 缺省 manual | 6571-6574；`_apply_field_patch` 默认 `source="manual"` | 数字键改类、批量对话框改类、分组、Inspector 改类四类入口**无法区分**；tasks 4.6 要求区分"个别对象改类"与"体系更名" |
| **C4** | 记录点全部空转（前提问题） | `correction_metrics/` 缺 `controller.py`/`panel.py`/`report_dialog.py`（§0.2） | 现在跑任何操作都**不会有统计**；上表"已采集"必须理解为"记录点已就位"。若 4.x 只补记录点而不补 controller，指标依旧为空 |

---

## 4. 对后续任务的直接输入

| 任务 | 本表的结论 |
| --- | --- |
| 4.4 创建/删除/复制粘贴/批量 | #1-#7 记录点已就位；需统一 `transaction_id`，并把 #6 的 `changed` 改为本次真正新增集合 |
| 4.5 拖动/拖边/两种拟合/键盘微调 | **6 个交互共用一个无参 `geometry`**：必须改为携带 `changed=[...]` + `source=`（区分 6 类），并把"滚轮一格格 / 键盘自动重复"合并为一次事务（A1/A2） |
| 4.6 单点/批量改类、字段对话框、全局类别管理 | 补 **B1（单选字段对话框）** 与 **B2（全局类别管理）**；B2 还要解决直写 JSON 与 `save_labels` 的 revision 语义冲突；`taxonomy_saved` 名字需对齐 core 的 `taxonomy()` |
| 4.7 撤销/Inspector/密集复核 | 撤销补 `undo_of`（C2），Inspector 已齐全（#19-#21），**密集复核确认需从 0 补建（B4）**，并保证 review 事件不被当成框修改 |
| 5.1/5.2 保存/丢弃 | `prepare_save`/`save_result` token 已就位；B2/B3 两条直写路径不经过它们 → 需为"非 save_labels 写盘"定义单独的完成点 |

## 5. 方法与限制

- 采用 grep 定位 + 定向读片段（`canvas.py` 6569 行、`label_widget.py` 10702 行，均未整读；未做任何 git 操作，仓库文件未改动）。
- 证据均为函数名 + 行号，行号对应当前工作区版本。
- 未覆盖：`pointcloud/`、`classifier/`、`vqa/`、`ppocr/` 等非矩形标注域；`video_classifier` 的 `label_panel.rename_label` 与本变更矩形范围无关，未展开。
- B6（属性面板）与 `label_list` 其他右键入口（如"复制坐标"4067，只读不修改）留待 4.6 实施前确认。

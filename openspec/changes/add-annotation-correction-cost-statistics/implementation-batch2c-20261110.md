# 第 2 批 C 段实施记录（2026-11-10）：预标注来源、批量与复核

范围：tasks.md **4.1、4.2、4.3、4.7**（本批确认完成）。
依据：[批次 2 需求规格](../../../.local/stage/batch2-doublecheck-spec.md) 与本轮补充约定（只提交统计相关改动）。

## 1. 4.1 预标注来源字段

- `model_manager.py` 已有 `_prediction_source()`（白名单字段 + 凭据剔除）与 `collect_prediction_provenance` 开关；本次补齐三处缺口：
  - 新增 `_finalise_source()`：成功分支写入 `mode`（由适配器自身的 `replace` 标志推导 `additive` / `replacement`），并补 `status/ended_at/inference_seconds/elapsed_s`；
  - 新增 `enable_prediction_provenance(manager, enabled)`：采集开关此前**没有任何启用点**，现由统计控制器在启用数据集范围时打开、停止时关闭；
  - `core.ORIGIN_FIELDS` 增加 `mode` / `replace`：否则白名单会把模式字段过滤掉，加法预测永远被当成 replacement。
- `controller.prediction_applied()` 的 AI 对象集合改用 `result.shapes`（此前用整块画布，会把保留的人工框算成预测对象，"5 人工 + 3 AI" 得 8 而非 3）。

验证：`tests/test_correction_metrics/test_prediction_provenance.py` 13 用例——旧式构造兼容、mode 推导、白名单剔除 `api_key/authorization/token/带凭据 URL`、缺失字段为 None、controller 侧 origin/run_id/model/ai_count。

## 2. 4.2 单张预测应用

- 应用成功：`prediction_applied(result)` 开新轮次、`predicted_ids` 仅取本次预测对象、`record_prediction("applied")`；
- 迟到/未应用：`prediction_unapplied` 记 `unapplied` 状态，不替换起点；
- 失败：`_finalise_source` 只在成功分支赋值，异常分支保持 `status=failed`。

## 3. 4.3 批量预标注

`views/labeling/utils/batch.py` 的 `save_auto_labeling_result()` 是 UI 循环与后台线程共用的**唯一写盘边界**，新增 3 处观察点：

| 位置 | 状态 | shapes |
| --- | --- | --- |
| `atomic_write_json` 成功之后 | `applied` | 实际落盘的合并后 shapes |
| 写盘异常分支 | `failed` | `()`（保留原有 logger 与 `prediction_unapplied("save-failed")`） |
| 结果为空 | `skipped` | `()` |

`controller.prediction_saved(image, label, provenance, shapes, status)` 按图片独立开 `saved=True` 轮次并记预测状态：**不触碰当前打开的轮次、不启动计时、不自动完成图片**；写入走 `MetricsStore` 队列（调用来自后台 QThread，且不在每张图 flush），按 `(image, label, run_id)` 去重；失败只返回 False，不抛异常。

验证：`tests/test_correction_metrics/test_batch_prediction.py` 5 用例——3 图成功=3 次调用且路径/来源/shapes 精确、单图失败只记 failed、空结果记 skipped、部分失败不声明整批成功、controller 缺失或抛异常时保存仍成功并记 degrade。

## 4. 4.7 撤销关联与复核来源

- **撤销关联无需新增逻辑**：`core._replace()` 已维护 `undo_stack`，`kind=="undo"` 时自动取栈顶并出栈（实测：两次 geometry 后撤销 → `undo_of=="tx-2"`）。局限：画布快照与事务非一一对应（点拟合双推快照、Inspector 批量删 N 快照/1 事务），连续多步撤销会漂移，栈空则 `undo_of=None`——按 best-effort LIFO 记录，不猜测。
- **修复一个真 bug**：`label_widget` 原来用的是反写的 `"undo-review"/"redo-review"`，不在 `report_row` 的排除表里，会被当成一次框修改事务；已改为 `review-undo` / `review-confirm`。
- **密集复核接入**：`dense_review/workspace.py` 的 `_complete_batch` 与 `_complete_current_object` 在 `session.confirm_*` 成功后旁观记录 `review-confirm`，不改写复核业务状态。
- **redo 不再计入修正事务**：`report_row` 的排除表加入 `redo`，并新增 `redo_count`（CSV 指标字典同步）。

验证：`tests/test_correction_metrics/test_review_wiring.py` 8 用例（确认不增 `transactions/touches/unique_objects`、撤销复核用独立 kind、反写旧名会被计为事务的防回退用例、`undo_of` 指向上一事务、无 controller 时空转、redo 不计事务）。

## 5. 验证汇总

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **188 passed / 0 failed**（3.4 s） |
| 批量相邻回归 | `pytest tests/test_auto_labeling/test_batch_range.py -q` | 2 passed + 6 subtests |
| OpenSpec 校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | valid |

新增用例：provenance 13 + batch 5 + review 8 + controller 3（批量入口与 undo_of 关联）= 29。

## 6. 仍然未完成

| 任务 | 缺口 |
| --- | --- |
| 4.4 | 创建/删除/复制/粘贴 hooks 已带对象，但缺逐入口 GUI 回归 |
| 2.2 / 2.5 / 3.3 | 图片内容摘要计算、显式类别版本对象、存储重试入口（批次 1 遗留） |
| 5.2–5.6 | 取消导航未验证；批量完成、完成失效、质量状态展示 |
| 6.2 / 6.4–6.6 | 标注弹窗与可交互状态、空闲提示 UI、模型运行单列、崩溃尾段 |
| 7.x / 8.x / 9.x / 10.x | 界面打磨、CSV 逐项核对、GUI 回归与性能、交付文档 |

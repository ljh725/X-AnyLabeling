# 密集复核评审问题修复记录（F1–F4）

日期：2026-11-02（Asia/Shanghai）
来源：`reports/dense_review_audit_20261102/REPORT.md`
状态：三项已修复，新增探针通过；人工屏幕验收与性能测试仍未完成。

## F1 — 调框后对象卡片复用旧裁图

- 根因：`ThumbnailProvider.cached_image(shape_id)` 只按 shape_id 和代际查询，忽略边界、上下文和源图版本；同 ID 的旧请求结果也没有被拒绝。工作区卡片签名只看批次和成员列表。
- 修复：
  - 缓存键改为 `形状 ID + 代际 + 规范化边界 + 上下文比例 + 目标尺寸 + 源图版本`。
  - 工作区为每个形状记录当前请求键；边界/上下文/源版本变化时 `invalidate_shape()` 清除旧缓存、失败状态和待处理标记，再发起新请求。
  - Provider 记录每个形状的最新请求键；旧请求结果即使同 ID 也直接丢弃，不写缓存、不清新请求的 pending、不发出 ready/failed。
  - 上下文变化、刷新按钮和图像/输出目录切换都会推进代际并清除旧失败状态。
- 探针：
  - `tests/test_dense_review/test_workspace.py::test_changed_bounds_request_fresh_card`
  - `tests/test_dense_review/test_thumbnails.py::test_cache_is_keyed_by_bounds_and_source_version`
  - `tests/test_dense_review/test_thumbnails.py::test_stale_same_id_result_is_ignored`

## F2 — 连续审核撤销只生效一次

- 根因：`undo_progress()` 把 `_last_action` 清空，`can_undo_progress()` 依赖该一次性标记；更早的进度快照仍在栈中却无法继续撤销。
- 修复：撤销入口改为查看进度栈顶的内容哈希是否等于当前内容版本；每次撤销后重新按栈顶判断。审核与画布编辑交错时，内容哈希不匹配的进度事务仍让位于画布撤销。
- 探针：
  - `tests/test_dense_review/test_session.py::test_two_progress_commands_can_be_undone_consecutively`
  - 既有的 `test_undo_progress_and_content_edit` 继续覆盖编辑与确认交错。

## F3 — 全图返回覆盖用户局部倍率

- 根因：工作区从全图返回时先由主窗口恢复保存倍率/滚动，随后又调用 `_focus_current()`，按目标重新计算稳定倍率。
- 修复：返回局部时只恢复显示策略，不再重新聚焦缩放；全图/返回路径保留用户手动倍率、滚动和中心，同时取消未完成草稿。
- 探针：
  - `tests/test_dense_review/test_workspace.py::test_full_image_roundtrip_restores_user_zoom`

## F4 — 相同内容不能证明相同历史位置

- 根因：`can_undo_progress()` 只比较进度栈顶内容哈希与当前内容哈希。框右移再左移后内容哈希回到旧值，但最新操作实际是第二次画布编辑，主窗口误入审核撤销分支。
- 修复：
  - 引入统一动作历史：审核动作与内容变更按真实发生顺序记录；内容变更保存变更前后内容版本。
  - `next_undo_kind()` 仅在最新动作是审核且其内容版本等于当前版本时返回 `progress`；否则先走画布撤销。
  - 画布撤销后按当前恢复的内容版本恢复审核状态，并清理已被同一次画布撤销覆盖的内容记录；连续审核撤销仍按剩余栈顶继续。
  - 主窗口撤销入口与按钮可用状态都通过 `next_undo_kind()` 决定，不再用内容哈希单独推断顺序。
- 探针：
  - `tests/test_dense_review/test_session.py::test_manual_edit_back_to_same_content_keeps_canvas_undo_first`
  - `tests/test_dense_review/test_workspace.py::test_main_window_undo_reverts_latest_move_after_manual_roundtrip`
  - 既有 `test_two_progress_commands_can_be_undone_consecutively`、`test_undo_progress_and_content_edit`、`test_batch_confirmation_is_one_undo_without_touching_labels` 继续覆盖连续审核与交错序列。

## 验证

- `python -m pytest tests/test_dense_review -q`：**70 passed**。
- 未新增性能或人工试用结论；原有未验证项保持不变。

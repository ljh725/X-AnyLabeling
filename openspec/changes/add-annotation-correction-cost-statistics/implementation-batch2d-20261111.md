# 第 2 批 D 段实施记录（2026-11-11）：完成状态、质量、导航与空闲计时

范围：tasks.md **5.2、5.4、5.6、6.2、6.4**（本批确认完成）；**5.3、5.5 部分完成**（数据与面板已就绪，缺批量完成/开始复核的界面入口）。
依据：[批次 2 需求规格](../../../.local/stage/batch2-doublecheck-spec.md)。

## 1. 5.2 保存/丢弃/取消导航与关闭生命周期

- 取消切图路径逐条核对（`may_continue` 的 7 个调用方：文件列表切换、关闭、拖放、Inspector 两条路径）：取消即 `return False`，调用方各自回滚；`leave_image` 只在 `reset_state()` 中发出，而它的调用点全在"已决定换图/关闭之后"，**取消时不会 leave、不会 enter，时间不会分给目标图片**（真实 SQLite 断言 round_id / image_path / time 三项前后一致）。
- 取消动作此前在统计侧完全不可见；新增 `notify_metrics("navigation_cancelled")` → `controller.navigation_cancelled()`（强制一次时间检查点，不改轮次）。
- 关闭链路核对完整：`closeEvent` 先 `may_continue`（保存/丢弃）→ 各子窗口 → `notify_metrics("stop")` → 工作区 shutdown；`stop()` 自身 `set_time(closed=True)` + flush + close 且幂等。

## 2. 5.4 完成本轮与完成失效

- 完成只绑定成功保存版本：脏草稿 `finish()` 返回 False（不抛异常）；保存后成功；重复完成幂等（同一 completion id、记录数 1）；完成后任何真实内容变化（几何/改类/全局重命名/非矩形新增）立即失效而旧完成记录保留；只读查询与"同内容重存"不失效；`finish → resume → finish` 产生新 id；丢弃不冒充新完成。
- 13 个用例覆盖（`tests/test_correction_metrics/test_completion.py`），无缺陷。

## 3. 5.6 质量状态

- 默认 `not-assessed`；`core.set_quality` 现在**要求明确来源**，无来源的非默认结论被拒绝（返回 False）。
- 质量结论绑定当前保存版本：任何真实内容变化会把质量重置为 `not-assessed` 并清除来源（与完成失效同步）。
- 面板把质量作为独立一行显示，文案明确"完成本轮不等于质量通过"，既有 `checked` 标记另起一行，不参与完成/质量判定。

## 4. 6.2 可交互状态与弹窗计时

- **修复真实计时缺陷**：Qt 静态对话框（保存提示、`error_message`、文件选择）是独立顶层窗口，`activeWindow()` 判据会把标注中途弹出的对话框误判为"离开应用"而停表，低估工作时长。`clock_adapter._sync_foreground` 现在把属于本窗口的模态对话框视为作业（design D6「本应用中的标注相关对话框仍视为作业」）。
- 取消切图时间归属已验证；关闭后新会话仍能读回该轮次。

## 5. 6.4 空闲确认

- 120 秒无输入后只产生 `pending_idle`，**不自动扣时**；面板显示非模态提示条「这段时间是否在审图？」+「是，计入作业」/「排除空闲」，对应 `confirm_idle(False)` / `confirm_idle(True)`；确认后提示消失，同一段不重复提示；新片段才会再次询问。
- 面板时间行改为优先显示 `adjusted_working`（排除后从 130 s 正确降到 0 s），tooltip 披露已排除秒数。
- 顺带修复原面板缺陷：事务/触达/去重三个计数行此前创建但从未渲染。

## 6. 5.3 / 5.5 已完成与未完成部分

| 任务 | 已完成 | 仍缺 |
| --- | --- | --- |
| 5.3 | 明确"完成本轮"绑定成功保存版本；`controller.complete_scope()` 批量完成：逐轮返回 completed 与 skipped 原因（unsaved / unsaved-draft / not-ready / unavailable），有 5 个用例 | **界面入口**（汇总对话框按钮）未做 |
| 5.5 | 完成时冻结成本并关闭计时；已完成图片重开挂空时钟（仅浏览、不计时）；「继续修正」回同轮恢复计时且不回填浏览时间；`start_review()` 建立独立 review 阶段轮次（有测试） | **"开始复核"的界面入口**未做 |

## 7. 验证汇总

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **227 passed / 0 failed**（5.0 s） |
| 新增用例 | — | completion 13 + navigation 10 + panel_completion 10 + completion_extra 5 = 38 |
| OpenSpec 校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | valid |

## 8. 遗留

- `.ts/.qm` 未重新编译（新文案走 `i18n.TRANSLATIONS` 四语回落，界面语言正确；分发前需 lupdate + lrelease + pyrcc6）。
- 面板完整数据时 sizeHint 约 650 px 高；右侧栏若高度紧张，宿主宜外套 `QScrollArea`。
- 空闲提示只在逐秒心跳的 working 状态下产生；休眠恢复造成的大间隔按既有语义记为 `timing_gap_seconds`，不提示。

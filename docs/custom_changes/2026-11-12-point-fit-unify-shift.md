# CUSTOM-101：Shift 单点拟合统一手势（框外进框锁角、移除 Shift+Alt）

- 状态：已验证（独立规格 87 项通过，用户确认人工验收通过）
- 功能分类：原功能修改
- 创建日期：2026-11-12，最后更新日期：2026-11-13（Asia/Shanghai）
- 原始版本与基线提交：X-AnyLabeling 4.2.1，基线 `f87fdfa8`
- 实现提交 / PR：无（工作区改动）
- 工作区已有修改、前置依赖：`add-shift-corner-lock-point-fit`、`improve-point-fit-algorithm` 两份未归档增量的既有实现；对应 OpenSpec 变更 `openspec/changes/unify-shift-rectangle-point-fit/`

## 问题与目标

原行为：`Shift` 在框外起手时只有「框外预览 + 单击」一条路，进框后仍随鼠标方向重选固定点；框内起手才锁角。用户需要从要调整的一侧就近进框、锁住对角，并让锁角、确认、取消、无效重试共用同一套规则。

另有一段 `Shift + Alt` 同侧角拟合（固定鼠标所在象限的原角，取象限内更小的框）。它引入第二套选角规则，本次统一移除。

目标：
- 框外或边线起手先沿用框外预览，左键松开时首次移入框内明确区域即锁该区对角。
- 按下左键时捕获固定端，松开时按释放位置计算并提交。
- 已锁角时无效或未变化的落点只结束这次点击，保留锁角供重试。
- 只有真正锁定的原角显示橙色实心点。

## 修改位置与方法

| 文件 / 函数 | 原行为 | 改后行为 | 迁移注意事项 |
| --- | --- | --- | --- |
| `widgets/point_fit.py::_point_fit_native_move`（新增） | 框外入口的 move 直接重算 hover 候选 | 先算框外候选；未按下且指针进入明确框内区时，把 `entry` 切到 `lock`、保存目标与原几何、锁住该区对角 | 复用 `point_fit_lock_decision`，四区与十字缓冲规则不变 |
| `widgets/point_fit.py::_point_fit_lock_move` | 带 `Alt` 分支切 `_point_fit_combo` 走同侧角 | 删除 `Alt` 分支与 `_point_fit_combo` | `Alt` 不再影响固定端 |
| `widgets/point_fit.py::_update_point_fit` | `inward` 参数 + `proposed_inward_point_fit_box` | 只保留默认对角提案 | 几何函数 `proposed_inward_point_fit_box` 保留（锁角仍用） |
| `widgets/point_fit.py::_point_fit_release_lock` | 任何释放都 `_point_fit_end_round()` | 无效/未变化释放走 `_point_fit_end_round(keep_lock=True)`，保留锁角，轮次继续 | 有效提交仍结束轮次并取消选中 |
| `widgets/point_fit.py::_clear_point_fit` / `_point_fit_end_round` | 无条件清锁角 | 新增 `keep_lock` 参数，按需保留角/目标/原几何 | 取消、切图、失焦仍全清 |
| `widgets/point_fit.py::_build_lock_point_fit_preview` | 实心点取 `_point_fit_anchor`（临时预览状态） | 改为 `corner_point(locked_box, locked_corner)` 直接算，click 结束清掉临时预览后实心点仍在 | 释放时若 `Shift` 已松或原框失效走取消收尾 |
| `widgets/point_fit.py::_point_fit_press_classic` | 无候选分支 `_clear_point_fit()` | 只 `_point_fit_clear_classic_preview()`，左键完整交回普通画布，保留本轮真实 `Shift` 建立的进框锁角资格 | 松开左键后移入明确区仍可锁角 |
| `widgets/point_fit.py::_point_fit_release` | 成功写回后按入口决定 `finished` | `_point_fit_end_round(finish=changed)`，框外与锁角两条路径成功写回后都进 `ENTRY_FINISHED` | 继续按着 `Shift` 可正常选矩形，重新按 `Shift` 才开始新一轮 |
| `widgets/point_fit.py::_point_fit_release_lock` | 任何未提交释放都 `keep_lock=True` | 未提交且仍按 `Shift` → 保留锁角重试；`Shift` 已松或原框失效 → `_point_fit_cancel_round()` | 取消轮次时仍消费被接管的左键释放 |
| `widgets/point_fit.py::_point_fit_lock_visible` | 仅 `entry == lock` 时画锁角预览 | `lock` 与 `finished` 都算，前提是角/目标/原几何齐全 | 供保留锁角后的重试预览 |
| `widgets/point_fit.py::_build_point_fit_preview` | 框外候选也画橙色实心点 | `fixed_point=None`，只有锁角流程画实心点 | 对应规格「只有真正锁定的原角显示实心点」 |
| `widgets/point_fit.py::_point_fit_shift_round` / `_point_fit_ensure_entry` | 合成入口与真实 `Shift` 等价 | 新增 `_point_fit_round_locks`，只有真实 `Shift` 按下开启的轮次才允许进框锁角 | 保住「画布没收到 Shift 按键」的降级路径，避免键盘微调后误锁角 |
| `widgets/canvas.py` | `Alt` 按下/松开都刷新拟合预览 | 删除这两处 `Alt` 处理；新增 `_point_fit_round_locks` / `_point_fit_round_spent` 初始化 | 画布其他 `Alt` 手势（顶点橡皮擦、绘制）不受影响 |
| `widgets/canvas.py::set_loading` | 只取消框选 | 同时 `_point_fit_cancel_round()` | 加载中的左键释放仍被消费，但不提交 |
| `widgets/canvas.py::mouseDoubleClickEvent` | Shift 左键双击走标签编辑 | 先试 `_point_fit_press`，命中则由拟合接管 | 快速重试不再打开标签编辑器 |
| `widgets/canvas.py::paintEvent` 十字线 | `setOpacity` 后不恢复 | 画完两根线恢复 `previous_opacity` | 拟合标记与虚线不再继承十字线透明度 |
| `widgets/point_fit.py::_point_fit_handle_release_event` | 加载中仍提交 | 加载中改为取消并消费 | 切图期间不会写回旧标注 |
| `widgets/point_fit.py::_point_fit_cancel_round` / `_point_fit_ensure_entry` | 取消后可凭仍按住的 `Shift` 重开 | 新增 `_point_fit_round_spent`，取消后封锁，只有新的真实 `Shift` 按下（或 `Shift` 松开）清除 | 失焦、切图后同一 `Shift` 不再重开 |
| `widgets/point_fit.py::_point_fit_cancel_during_release`（新增） | 释放事件里发现取消仍置待释放 | 直接消费当前事件、清归属 | 不再等一次永不到来的释放 |
| `widgets/point_fit.py::_point_fit_widget_pos` / `_point_fit_pointer_from_widget` / `_point_fit_refresh_landing_point`（新增） | 平移缩放后预览仍用旧落点 | 记住鼠标屏幕位置，映射变化时重算落点，固定角仍用原图坐标 | 预览与松手结果一致 |
| `widgets/point_fit.py::_point_fit_press_classic` | 无候选就接管左键（含「候选等于原框」） | 未锁角时统一用「几何有效且确实变化」判断；不满足则交还普通画布并保留本轮锁角资格 | 无虚线时不再抢左键 |
| `widgets/point_fit.py::_point_fit_release`（classic） | 未提交即结束轮次 | 未提交时 `keep_lock=True`，保留进框锁角资格；`valid` 为假走 `_point_fit_cancel_during_release()` | 框外一次无效释放不再让本轮失去锁角能力 |
| `widgets/point_fit.py::_point_fit_press_classic`（固定端） | 按下时按新坐标重算角 | 已有有效且未失效的已显示预览时复用其固定端 | 合成事件（无中间 move）不再换固定端 |

`proposed_inward_point_fit_box` 保留在 `rect_edge_click.py`：锁角拟合就是「固定某原角 + 鼠标点」张成的矩形，与同侧角语义无关。

## 兼容与数据影响

- 标注坐标、四点矩形顺序、撤销次数（一次提交一次撤销）与图片边界裁剪规则不变。
- **键位变化**：`Shift + Alt` 同侧角单击拟合移除。习惯该组合键的用户改用「从要调整的一侧进框按 `Shift` 锁对角，再移到落点单击」。
- 小框命中区、十字缓冲宽度、`HOVER_SWITCH_SCREEN_PX` 悬浮迟滞全部沿用，未调整阈值。
- 锁角后无效落点不再结束轮次，因此「单击无效」与「单击有效」在轮次结束时机上不同：前者等待重试或 `Shift` 松开。
- 与 CUSTOM-101/103 共边显示、CUSTOM-003 拖动刷新无交互改动。

## 验证

环境：解释器 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，`QT_QPA_PLATFORM=offscreen`，均加 `-p no:cacheprovider`。

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| 单点拟合专项（几何 + 交互 + 锁角） | `pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_corner_lock_fit.py -q` | **135 passed** |
| 预览共边与键盘微调 | `pytest tests/test_canvas/test_rectangle_preview_overlap.py -k "not host_dirty" -q` | **43 passed**、14 deselected（`dirty_host` 夹具与已提交代码不一致，见下） |
| 画布目录整体回归 | `pytest tests/test_canvas -q --ignore=test_toolbar_layout.py --ignore=test_navigation.py --ignore=test_rectangle_edge_migration.py -k "not host_dirty"` | **551 passed**、2 failed（既有）、14 deselected、83 subtests passed |
| 独立规格套件（外部提供） | `pytest .tmp/test_independent_shift_point_fit.py -q` | **82 passed**（修复前 67 passed / 15 failed） |
| 两者合跑 | 同上合并且排除项一致 | **633 passed**、2 failed（既有） |

新增/改写的用例覆盖：框外起手首次进框锁角（四区、十字缓冲等待、出框返回、跨区仍固定）、框外未进框直接单击提交、锁角无效落点保留锁角并可二次单击提交、固定点与落点重合的无效释放、`Alt` 不改变框内/框外与已锁角轮次、合成入口（`_ensure_entry`）不锁角、实心点只在锁角帧出现。

### 复核后补修的三处（每条都有 Qt 事件回归）

| 问题 | 修复位置 | 回归用例 |
| --- | --- | --- |
| 框外提交后同一 `Shift` 还能开启预览 | `_point_fit_release` 成功写回后统一 `finish=True` → `ENTRY_FINISHED` | `test_outside_commit_finishes_the_round_for_a_held_shift` |
| 无效点击后实心点暂时消失 | `_build_lock_point_fit_preview` 改用 `corner_point(locked_box, locked_corner)`；`_point_fit_release_lock` 在 `Shift` 已松或目标失效时改走 `_point_fit_cancel_round()` | `test_invalid_locked_click_keeps_the_solid_point_while_the_pointer_rests`（鼠标静止时断言像素 + `preview.fixed_point`） |
| 无预览点一下后进框锁不了角 | `_point_fit_press_classic` 无候选分支改 `_point_fit_clear_classic_preview()`，保留 `_point_fit_round_locks` | `test_click_without_a_candidate_keeps_the_inside_lock_eligibility` |

三条用例已做红/绿验证：把三处修复 revert 成旧行为后，对应用例全部转红；恢复后转绿。

### 第二轮复核后补修的八处（独立规格套件 15 红 → 0 红）

外部独立套件（82 离屏 Qt 场景）复现出 8 类缺陷，逐条修复并各自补仓库内回归（`tests/test_canvas/test_shift_corner_lock_fit.py` 末尾 9 条）：

| 缺陷 | 修复 | 回归用例 |
| --- | --- | --- |
| 加载中松手仍写回矩形 | `set_loading(True)` 取消拟合并保留待释放；释放入口再查 `is_loading` | `test_loading_before_the_release_never_commits` |
| 失焦/切图后同一 `Shift` 重开拟合 | 新增 `_point_fit_round_spent`，取消时封锁；真实 `Shift` 按下或松开才清除 | `test_cancelled_round_blocks_the_still_held_shift` |
| 快速重试被 Qt 送成双击 → 打开标签编辑 | `mouseDoubleClickEvent` 先试 `_point_fit_press` | `test_double_click_on_a_locked_preview_still_confirms` |
| 平移后预览与松手结果不一致 | 记录屏幕坐标，映射变化时 `_point_fit_refresh_landing_point` 重算落点 | `test_locked_preview_follows_a_pan_of_the_image` |
| 十字线透明度为 0 时实心点消失 | 十字线画完恢复 `p.setOpacity(previous_opacity)` | `test_locked_marker_ignores_the_crosshair_opacity` |
| 框外无效释放让本轮失去锁角能力 | classic 释放未提交时 `keep_lock=True` | `test_invalid_outside_release_keeps_the_inside_lock_eligibility` |
| 候选等于原框（无虚线）仍抢左键 | 未锁角时统一用「几何有效且确实变化」判定 | `test_unchanged_candidate_never_steals_the_press` |
| 释放事件里才发现取消，却重新置待释放 | 新增 `_point_fit_cancel_during_release()`，直接消费当前事件 | `test_release_discovering_a_cancel_leaves_no_release_debt` |
| 合成事件（无中间 move）临时换固定端 | 按下时复用仍有效的已显示预览固定端 | `test_press_without_a_move_keeps_the_shown_anchor` |

9 条均做红/绿验证：逐一 revert 对应修复后转红，恢复后转绿。

### 与本变更无关的既有问题

- **`tests/test_canvas/test_navigation.py`、`test_rectangle_edge_migration.py` 在 offscreen 下永久挂起**：构造 `MainWindow` 时，并行的「设置持久化」改动在 `persist_user_preferences` 抛 `ConfigError`，经 `error_message()` 弹出 `QMessageBox.critical()` 模态框；offscreen 无人确认，进程即挂死。**已用 `git stash` 把本次改动退回 HEAD 逐一复现，同样挂起**，确认与单点拟合无关。定位手段：`pytest -o faulthandler_timeout=12` 得到的栈为 `label_widget.py:10054 error_message ← :8676 persist_user_preferences ← :8717 update_user_preference ← :8620 set_canvas_params`。
- `test_groups.py::...test_shape_label_keeps_fixed_screen_size_while_zooming`：`179 != 139`，标签屏幕尺寸缩放，前次验证已记录。
- `test_rectangle_size.py::test_action_switch_updates_canvas_and_config`：`AttributeError: 'types.SimpleNamespace' object has no attribute 'update_user_preference'`，同上并行改动与旧测试替身不一致。
- `test_rectangle_preview_overlap.py` 的 `dirty_host` 系列：夹具用无 `canvas` 属性的 `SimpleNamespace`，而 `_on_geometry_committed` 读 `self.canvas.shapes`，PyQt6 在槽内抛异常时直接终止进程（退出码 0xC0000409），故按名 deselect。
- `black --check` 与 `flake8` 在 `widgets/canvas.py` 上的报错（`mouseReleaseEvent` C901=22、需要重排格式）在 HEAD 上同样存在，非本次引入。

### 人工验收

2026-11-13，用户确认点拟合功能人工测试通过。

## 迁移与回退

- 移植顺序：先合入 `add-shift-corner-lock-point-fit` 与 `improve-point-fit-algorithm` 的同名规格，再应用本次的修改与移除条目（主规格 `openspec/specs/` 目前尚无 `rectangle-point-fit`）。
- 回退：恢复 `_point_fit_lock_move` 的 `Alt` 分支与 `_point_fit_combo`、`_update_point_fit` 的 `inward` 参数、`_point_fit_release_lock` 的无条件收尾，以及 `canvas.py` 的两处 `Alt` 刷新；标注文件无需改动。
- 上游变化时需保留：`point_fit_decision` 的悬浮迟滞、`point_fit_inside_box` 严格框内判定、裁剪与最小 1 像素校验、`shape_moved` 单次发射与单次撤销。

## 后续修订

| 日期 | 原因 | 实际改动 / 提交 | 验证结果 |
| --- | --- | --- | --- |
| 2026-11-12 | 实施 OpenSpec `unify-shift-rectangle-point-fit` | 见上表；新增 `_point_fit_native_move`、`_point_fit_round_locks`、`_point_fit_end_round(keep_lock=, finish=)` | 专项 135 passed；画布 539 passed / 2 既有失败；人工验收待做 |
| 2026-11-12 | 复核补修：轮次收尾、实心点存活、无候选点击保留锁角资格 | `_point_fit_release(finish=)`、`_build_lock_point_fit_preview` 改用锁定原框算固定点、`_point_fit_press_classic` 只清临时预览；新增 3 条 Qt 回归 | 专项 138 passed；画布 542 passed / 2 既有失败；3 条新用例完成红/绿验证 |
| 2026-11-13 | 外部独立规格套件（82 场景）复现 8 类缺陷 | 加载中禁提交、`_point_fit_round_spent` 封锁取消后的旧 `Shift`、双击走拟合、按屏幕坐标重算落点、恢复十字线透明度、classic 未提交保留锁角、无虚线不抢左键、`_point_fit_cancel_during_release`、复用已显示固定端；新增 9 条 Qt 回归 | 独立套件 67→**82 passed**；画布 551 passed / 2 既有失败；合跑 **633 passed**；9 条新用例完成红/绿验证 |
| 2026-11-13 | 独立复核复现 5 个组合场景 | 以全局坐标重算平移或滚动后的落点，按未裁剪坐标判断预览能否复用。普通按下和双击共用释放归属初始化。框外捕获失效后消费释放并等待新一轮 Shift。 | 独立套件 82 passed / 5 failed → **87 passed**。画布和独立套件合跑 **643 passed** / 2 既有失败。详见[验证记录](../../openspec/changes/unify-shift-rectangle-point-fit/verification.md)。 |

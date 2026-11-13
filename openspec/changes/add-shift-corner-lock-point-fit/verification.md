# 框内 Shift 锁角拖动：实施与验证

2026-11-11，任务 4 组共 11 项完成，未归档。自动化验证通过；真实屏幕人工验收待用户确认。

## 改动文件

- `anylabeling/views/labeling/rect_edge_click.py`：新增 `point_fit_inside_box`（严格框内，含边线排除）、`point_fit_lock_decision`（复用首次判角缓冲）、`point_fit_drag_reached`（屏幕像素曼哈顿拖动阈值）。
- `anylabeling/views/labeling/rectangle_preview.py`：`PointFitPreview` 增加 `fixed_point`、`pointer`、`guides` 与 `owns_guides`。
- `anylabeling/views/labeling/widgets/point_fit.py`：Shift 轮次入口、锁角状态（角 + 目标身份 + 原几何）、左键归属、拖动阈值与候选、单次写回提交、取消与清理、锁角预览与辅助线绘制。
- `anylabeling/views/labeling/widgets/canvas.py`：首次非自动重复 Shift 按键入口、锁角拖动状态初始化、Shift 松开结束轮次、`interaction_in_progress` 计入锁角、失焦/切图/编辑模式/重置清空锁角。
- `anylabeling/views/labeling/widgets/rectangle_crosshair.py`：拟合辅助线出现时抑制常驻十字线。
- 测试：新增 `tests/test_canvas/test_shift_corner_lock_fit.py`；扩充 `tests/test_canvas/test_shift_point_fit_geometry.py`；更新 `tests/test_canvas/test_shift_point_fit_interaction.py` 中受行为变化影响的按键用例。
- 文档：`docs/zh_cn/rectangle_point_fit.md`、`docs/custom_changes/2026-11-11-point-fit-shift-corner-alignment.md`、`docs/custom_changes/CATALOG-20261030.md`、`docs/custom_changes/2026-11-06-project-change-audit.md`。

## 测试命令与结果

解释器 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，环境 `QT_QPA_PLATFORM=offscreen`，均加 `-p no:cacheprovider`。

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| 单点拟合专项（几何 + 交互 + 新增锁角） | `pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_corner_lock_fit.py -q` | **126 passed**（第四轮修复后） |
| 画布目录整体回归 | `pytest tests/test_canvas -q`，排除 1 个既有挂起用例、10 个既有夹具崩溃参数与 2 个沙箱临时目录文件 | **610 passed**、2 failed（既有）、11 deselected、78 subtests passed |

新增/更新用例覆盖：严格框内判定与边线排除、缩放后小框四区、跨过固定点、屏幕像素拖动阈值；框外/边线起步保持原流程、框内立即锁角只显示实心点、跨中线与出框不换角、缓冲区待锁、未锁角左键交还原流程、锁角后出框再按左键拖动、轻点/抖动与无效落点不改框不记撤销、出图裁剪与预览一致、先松 Shift 取消且消费释放、放手后本轮不再锁角、重新按 Shift 恢复入口、Shift+Alt 两种按键顺序、拖动中加按 Alt 保持模式；第二轮补充失焦/切图后的释放归属、轻点后 Shift+Alt 恢复、静止按 Shift 清除边线提示、Shift+Alt 提交后轮次收尾、实心点无红色描边；成功提交断言恰一次 `shape_moved` 与一次撤销；离屏渲染断言实心点、辅助线与常驻十字线抑制。

自查与独立复核发现并修复的问题共 5 项，见文末「第二轮」。注意：第一轮曾用"spent 标记"表达"本轮锁角资格已用尽"，该机制在第二轮被移除——锁角本只能由真实的 Shift 按下事件开启，保留 spent 反而会切断 Shift+Alt 与"画布没收到 Shift 按键"的原流程降级路径。

## 与本变更无关的既有问题（均已在其他变更或本环境记录）

- `test_canvas/test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`：前次变更验证记录已记载的基线失败（`AssertionError: 179 != 139`，标签屏幕尺寸缩放），本变更未改标签缩放逻辑。
- `test_canvas/test_rectangle_size.py::test_action_switch_updates_canvas_and_config`：`AttributeError: 'types.SimpleNamespace' object has no attribute 'update_user_preference'`（`label_widget.py:8601`），来自工作区并行的设置持久化改动与旧测试替身不一致，前次验证已记录；本变更未改 `label_widget.py` 与设置模块。
- `test_canvas/test_navigation.py` 2 项、`test_canvas/test_shape_identity.py::TestLabelFileIdentity` 3 项、`tests/test_labeling/test_canvas_controls_integration.py` 36 项：`PermissionError: [WinError 5]` 指向 `AppData\Local\Temp\...\pytest-of-*`。当前会话的沙箱不允许 shell 子进程写文件，依赖 `tmp_path` 的用例无法运行，与源码无关。
- `test_canvas/test_rectangle_edge_migration.py::test_main_window_exposes_translated_edge_toggle`：打开真实窗口时弹出模态错误对话框导致挂起，前次验证已记录，本次按名 deselect。
- `test_canvas/test_rectangle_preview_overlap.py::test_nudge_preview_preserves_host_dirty[*]`、`test_fit_commit_marks_host_dirty_once[*]`：该文件的 `dirty_host` 夹具使用没有 `canvas` 属性的 `SimpleNamespace`，而 `HEAD` 的 `LabelWidget._on_geometry_committed` 已改为读取 `self.canvas.shapes`，PyQt6 在槽内抛异常时直接终止进程（退出码 0xC0000409）。属夹具与已提交代码不一致的既有问题，本变更未改该夹具与 `label_widget.py`，按名 deselect。

## 画布验收状态

- 离屏渲染验收：完成。实心固定点、空心落点、横竖辅助线、裁剪后橙色虚线、常驻十字线在锁角/拖动/取消三态下的显示均有像素断言。
- 真实屏幕人工验收：**未完成，待用户确认**。需要用户在深色、浅色两种图片背景下观察锁角、拖动、轻点取消、先松 Shift 取消、出图裁剪与提交后单次撤销。

## OpenSpec 校验

`openspec validate add-shift-corner-lock-point-fit --strict` 通过。

## 第二轮：独立复核三个问题的修复（2026-11-11）

独立复核用真实 Qt 键鼠事件确认了三个偏差，本轮按 TDD 先补最小回归用例、在当前实现上确认失败，再改生产代码。

### 复现（修复前，红）

| 新增用例 | 修复前失败断言 |
| --- | --- |
| `test_focus_loss_mid_drag_keeps_the_release_consumed` | `assert canvas._point_fit_pressed` → False（失焦后释放归属丢失） |
| `test_image_change_mid_drag_keeps_the_release_consumed` | `assert canvas._point_fit_pressed` → False（切图后同上） |
| `test_alt_after_a_cancelled_tap_restores_the_same_side_click` | `assert canvas._point_fit_pending_box == (180, 100, 200, 120)` → None（轻点后 Shift+Alt 无预览） |
| `test_stationary_shift_press_clears_the_edge_hint` | `assert canvas._rectangle_edge_hover is None` → `(<Shape>, 'left')`（边线高亮未清除） |
| `test_combo_commit_inside_a_locked_round_resolves_the_round` | `assert canvas._point_fit_entry is None` → `'lock'`（轮次未收尾） |
| `test_locked_preview_paints_a_solid_point_and_guides`（扩充断言） | `assert not any(is_invalid_red(...))` → True（固定点周边有红色描边像素） |

红阶段命令：`pytest tests/test_canvas/test_shift_corner_lock_fit.py -k "focus_loss_mid_drag or image_change_mid_drag or alt_after_a_cancelled_tap or stationary_shift_press"` → **4 failed**；追加两项后 `-k "combo_commit_inside_a_locked_round or locked_preview_paints"` → **1 failed**（像素断言）与 **1 failed**（entry 悬挂），修复后各自转绿。

### 修复

1. **取消后的左键归属**：`widgets/point_fit.py` 新增 `_point_fit_cancel_round()`，在锁角拖动被取消时复用 `_point_fit_end_round(keep_press=...)` 保留已接管的左键，后续释放经 `_point_fit_release` 的既有分支消费；`widgets/canvas.py` 的失焦、切图、编辑模式切换、重置四处取消点改用它。未锁角的原有单击捕获保持既有行为（`test_load_pixmap_cancels_in_progress_fit` 不变）。
2. **轻点取消后的 Shift+Alt**：删除 `_point_fit_spent` 对入口解析的封锁，`_point_fit_ensure_entry()` 在轮次结束后把本轮降级为原有流程；锁角仍只由 `_point_fit_shift_round`（真实的 Shift 按下事件）开启，因此"普通锁角必须松开再按 Shift"不变。`canvas.py` 同步移除该方法初始化。
3. **按 Shift 后残留边线提示**：`_point_fit_shift_round` 在产生预览后补上与 `_point_fit_refresh_from_cursor` 相同的边线清理（`_rectangle_edge_cancel()`），复用现有光标恢复与重绘逻辑。
4. **Shift+Alt 提交后轮次未收尾**（独立复核追加）：`_point_fit_release` 的经典分支改调 `_point_fit_end_round()`，不再留下 `entry="lock"` 且 `locked_target` 为空悬挂状态；下一帧起原流程可直接预览。
5. **锁角实心点的红色描边**（独立复核追加）：`_paint_point_fit` 给固定点单独使用橙色实心画笔，避免锁角静止帧因无候选框而套用无效候选红色；新增像素断言确认固定点周边无红色像素。

### 修复后验证（绿）

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| 单点拟合专项 | `pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_corner_lock_fit.py -q` | **119 passed** |
| 矩形预览共边 | `pytest tests/test_canvas/test_rectangle_preview_overlap.py`（10 个既有夹具崩溃参数 deselect） | 47 passed |
| 矩形创建十字线 | `pytest tests/test_canvas/test_rectangle_creation_crosshair.py` | 9 passed |
| 边线编辑回归 | `pytest tests/test_canvas/test_rectangle_edge_migration.py`（1 个既有挂起 deselect） | 94 passed |
| 画布目录整体 | `pytest tests/test_canvas`（同上 deselect + 排除 2 个沙箱临时目录文件） | **603 passed、78 subtests passed、2 failed（既有）、11 deselected** |
| OpenSpec 严格校验 | `openspec validate add-shift-corner-lock-point-fit --strict` | valid |
| 空白检查 | `git diff --check` | 退出码 0（仅并行改动带来的 CRLF 警告） |

新增用例修复后逐项 PASSED：`test_focus_loss_mid_drag_keeps_the_release_consumed`、`test_image_change_mid_drag_keeps_the_release_consumed`、`test_alt_after_a_cancelled_tap_restores_the_same_side_click`、`test_stationary_shift_press_clears_the_edge_hint`、`test_combo_commit_inside_a_locked_round_resolves_the_round`，以及扩充后的 `test_locked_preview_paints_a_solid_point_and_guides`。`flake8 -j 1` 对 `widgets/point_fit.py` 与新增测试文件干净；`widgets/canvas.py` 仅报 `C901 Canvas.mouseReleaseEvent is too complex (22)`，该告警在 `HEAD` 版本同样存在（本次未改该方法），属既有复杂度过高。

### 剩余已知小问题（未在本轮修复）

- 光标在画布外按 `Shift` 时按键被消费但无任何效果（`point_fit.py` `_point_fit_shift_round` 的 `pos is None` 分支返回 True）。纯事件消费细节，无用户可见副作用。

### 真实屏幕人工验收

仍未执行。本轮全部证据来自离屏渲染与真实 Qt 键鼠事件；深色/浅色背景的人工观察仍需用户确认。

## 第三轮：左键归属的连续取消与迟到释放（2026-11-11）

最新复核指出：取消只保留一次、迟到或丢失的释放会阻塞后续交互、加载期间到达的释放被 `is_loading` 短路吞掉。本轮把**活动拖动**（`_point_fit_lock_drag`）与**取消后等待释放**（新增 `_point_fit_release_pending`）分开，按 TDD 先补用例再改实现。

### 复现（修复前，红）

新增 5 个用例，修复前全部失败：

| 新增用例 | 修复前失败断言 |
| --- | --- |
| `test_repeated_cancels_still_consume_the_release`（重置画布 → 加载新图 → 松开左键） | 第二次取消后 `assert canvas._point_fit_pressed` → False（归属被第二次取消丢弃） |
| `test_focus_loss_then_image_change_still_consumes_the_release`（失焦 → 切图 → 松开左键） | 同上 |
| `test_undelivered_release_does_not_block_the_next_drag`（失焦后在画布外松开，先移动鼠标再普通拖框） | `assert not canvas._point_fit_pressed` → True（旧归属吞掉新手势），普通拖框几何不变 |
| `test_undelivered_release_then_direct_press_starts_normally`（同上，直接按下左键） | 同上 |
| `test_release_while_loading_is_consumed_and_clears_ownership`（切图后加载期间松开左键） | `assert not canvas._point_fit_pressed` → True（`is_loading` 短路吞掉释放） |

用旧行为（取消只保留活动拖动、新按下不清理待处理释放、无按键移动一律消费）做 monkeypatch 复核，修正后的用例仍全部失败：第二次取消后 `pressed=False`；新按下后 `pressed=True`；普通拖框结果保持 `(100,100,200,200)` 而非 `(120,80,220,180)`。

### 修复

1. **取消可重复**：`_clear_point_fit(keep_press=True)` 同时置 `_point_fit_release_pending = _point_fit_pressed`；`_point_fit_cancel_round()` 在"活动拖动 **或** 已在等待释放"时都保留左键，所以重置、切图、失焦、模式切换可连续调用而不会丢掉同一次释放。
2. **旧归属不阻塞也不吞新手势**：新增 `_point_fit_abandon_pending_release()`，`canvas.mousePressEvent` 收到新的左键按下时先放弃未送达的旧释放，再走原有点击/拖动链路；等待释放期间的无按键移动不再被拟合消费（`_point_fit_move` 直接返回 False），迟到的释放仍归拟合，满足"不凭一次移动把旧释放交给普通流程"。
3. **加载期间的释放当场消费**：`canvas.mouseReleaseEvent` 把 `_point_fit_handle_release_event(ev)` 移到 `is_loading` 短路之前；取消后 `lock_drag` 已清、目标为空，因此该释放不会提交几何，只消费并清除归属，加载结束即可立即开始新操作。

### 修复后验证（绿）

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| 单点拟合专项 | `pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_corner_lock_fit.py -q` | **124 passed** |
| 矩形预览共边 | `pytest tests/test_canvas/test_rectangle_preview_overlap.py`（10 个既有夹具崩溃参数 deselect） | 47 passed |
| 矩形创建十字线 | `pytest tests/test_canvas/test_rectangle_creation_crosshair.py` | 9 passed |
| 边线编辑回归 | `pytest tests/test_canvas/test_rectangle_edge_migration.py`（1 个既有挂起 deselect） | 94 passed |
| 画布目录整体 | `pytest tests/test_canvas`（同上 deselect + 排除 2 个沙箱临时目录文件） | **608 passed、78 subtests passed、2 failed（既有）、11 deselected** |
| OpenSpec 严格校验 | `openspec validate add-shift-corner-lock-point-fit --strict` | valid |
| 空白检查 | `git diff --check` | 退出码 0 |
| 静态检查 | `flake8 -j 1 widgets/point_fit.py tests/test_canvas/test_shift_corner_lock_fit.py` | 退出码 0 |

测试预期修正说明：首轮红运行后修正了三处测试自身问题——`reset_state()` 会清空 `shapes_backups`（去掉该断言，改用 `shape_moved` 与几何断言）、普通拖框位移应为 `(120, 80, 220, 180)`、边线光标断言前先清空全局 override cursor 栈以隔离其他用例。修正后用旧行为 monkeypatch 复核确认仍然失败（见上）。

### 排除用例及原因（三轮共用）

- `test_rectangle_edge_migration.py::test_main_window_exposes_translated_edge_toggle`：开真实窗口时弹模态错误对话框挂起（既有）。
- `test_rectangle_preview_overlap.py::test_nudge_preview_preserves_host_dirty[*]`、`::test_fit_commit_marks_host_dirty_once[*]`（10 参数）：旧夹具 `SimpleNamespace` 缺 `canvas`，HEAD 的 `_on_geometry_committed` 读取 `self.canvas.shapes`，PyQt6 槽内异常直接终止进程（0xC0000409），既有。
- `test_navigation.py`、`test_shape_identity.py`：依赖 `tmp_path`，本会话沙箱禁止 shell 子进程写系统临时目录（`PermissionError WinError 5`）。
- 2 项失败：`test_groups` 标签缩放基线（`179 != 139`）、`test_rectangle_size::test_action_switch_updates_canvas_and_config`（并行设置改动的旧测试替身缺 `update_user_preference`）。

### 真实屏幕人工验收

仍未执行。三轮证据均来自离屏渲染与真实 Qt 键鼠事件；深色/浅色背景的人工观察需要用户确认后才能标记通过。

## 第四轮：取消后按住左键误移原框 / 漏释放仍报编辑进行中（2026-11-11）

最新复核指出两处遗留：取消手势后仍按着左键移动会落到原生拖框，把原框移走；漏掉释放后 `interaction_in_progress()` 仍为 True。本轮在 Canvas 层分流等待释放的鼠标移动，并把活动拟合与等待释放分开。

### 复现（修复前，红）

| 新增用例 | 修复前失败断言 |
| --- | --- |
| `test_moving_with_the_button_after_a_cancel_does_not_move_the_box`（普通点击建起点 → Shift 锁角拖动 → 先松 Shift、按住左键移动 → 松开左键） | `assert coordinates(shape) == BOX` → `(10, 190, 110, 290)`，原框被原生拖框移走 |
| `test_lost_release_clears_the_interaction_after_a_bare_move`（失焦后画布外松开，回到画布只发一次无按键移动） | `assert not canvas.interaction_in_progress()` → True |

复现要点：先做一次普通点击（建立 `prev_point` 拖框起点），否则原生拖框分支不满足条件；取消后两次移动事件必须是**无 Shift 修饰**的移动，否则会被拟合层旧分支消费而看不出问题。

### 修复

1. **Canvas 层分流等待释放的移动**（`mouseMoveEvent` 在 `is_loading` 之后、原生拖框之前）：`_point_fit_release_pending` 为真时，若 `ev.buttons()` 仍含左键则 `ev.accept()` 直接返回（这次移动属于已取消的旧手势，不进 `bounded_move_shapes`/顶点拖动）；若左键已松开则 `_pointer_down = False` 并继续正常悬停，且**保留** `_point_fit_release_pending`，迟到的释放仍归拟合消费。
2. **拟合层让出等待期间的移动**（`_point_fit_move` 开头）：`_point_fit_release_pending` 为真直接返回 `False`，无按键悬停不再被 Shift 修饰键重新接管；原先放在无 Shift 分支里的同类判断已合并到开头。
3. **编辑中判定区分状态**：`interaction_in_progress()` 的 `or self._point_fit_pressed` 改为 `or (self._point_fit_pressed and not self._point_fit_release_pending)`，等待释放不再算编辑进行中；其他编辑状态判断不变。
4. 既有行为保留：新左键按下时清理旧归属（`_point_fit_abandon_pending_release`）、加载期间优先消费旧释放（`_point_fit_handle_release_event` 置于 `is_loading` 之前）均未改动；`mouseReleaseEvent` 中该判断合并回单个 `if`，使复杂度保持与 `HEAD` 一致的既有告警水平。

### 修复后验证（绿）

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| 单点拟合专项 | `pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_corner_lock_fit.py -q` | **126 passed** |
| 矩形预览共边 | `pytest tests/test_canvas/test_rectangle_preview_overlap.py`（10 个既有夹具崩溃参数 deselect） | 47 passed |
| 矩形创建十字线 | `pytest tests/test_canvas/test_rectangle_creation_crosshair.py` | 9 passed |
| 边线编辑回归 | `pytest tests/test_canvas/test_rectangle_edge_migration.py`（1 个既有挂起 deselect） | 94 passed |
| 画布目录整体 | `pytest tests/test_canvas`（同上 deselect + 排除 2 个沙箱临时目录文件） | **610 passed、78 subtests passed、2 failed（既有）、11 deselected** |
| OpenSpec 严格校验 | `openspec validate add-shift-corner-lock-point-fit --strict` | valid |
| 空白检查 | `git diff --check` | 退出码 0 |
| 静态检查 | `flake8 -j 1 widgets/point_fit.py tests/test_canvas/test_shift_corner_lock_fit.py` | 退出码 0 |

同时重跑了前几轮的连续取消、加载期间释放、下一次普通拖框用例，均继续通过。`widgets/canvas.py` 仍只有 `C901 Canvas.mouseReleaseEvent` 既有告警，复杂度与 `HEAD` 相同（22，阈值 18），本轮未新增复杂度。

### 排除用例及原因（四轮共用）

- `test_rectangle_edge_migration.py::test_main_window_exposes_translated_edge_toggle`：开真实窗口时弹模态错误对话框挂起（既有）。
- `test_rectangle_preview_overlap.py::test_nudge_preview_preserves_host_dirty[*]`、`::test_fit_commit_marks_host_dirty_once[*]`（10 参数）：旧夹具 `SimpleNamespace` 缺 `canvas`，HEAD 的 `_on_geometry_committed` 读取 `self.canvas.shapes`，PyQt6 槽内异常直接终止进程（0xC0000409），既有。
- `test_navigation.py`、`test_shape_identity.py`：依赖 `tmp_path`，本会话沙箱禁止 shell 子进程写系统临时目录（`PermissionError WinError 5`）。
- 2 项失败：`test_groups` 标签缩放基线（`179 != 139`）、`test_rectangle_size::test_action_switch_updates_canvas_and_config`（并行设置改动的旧测试替身缺 `update_user_preference`）。

### 真实屏幕人工验收

仍未执行。四轮证据均来自离屏渲染与真实 Qt 键鼠事件；深色/浅色背景的人工观察需要用户确认后才能标记通过。


## 第五轮：取消后的旧释放阻塞新一轮 Shift 锁定（2026-11-11）

复核指出：失焦取消锁角拖动、且旧左键释放没有送达时，下一次真实的 `Shift`
按下被"等待释放"状态提前分流，右上角不再锁定；随后轻点左键退回旧的单击拟合，
把原框改成 `(100, 120, 180, 200)`。本轮把**活动按下**与**待消费释放**彻底拆开，
按 TDD 先补用例、在当前实现上确认失败，再改生产代码。

### 复现（修复前，红）

| 新增用例 | 修复前失败断言 |
| --- | --- |
| `test_a_lost_release_does_not_block_the_next_lock[False]`（直接按 Shift） | `assert canvas._point_fit_entry == "lock"` → `None` |
| `test_a_lost_release_does_not_block_the_next_lock[True]`（先无按键悬停再按 Shift） | 同上 |
| `test_a_late_release_keeps_the_newly_locked_corner` | 同上（新 Shift 未能锁角） |
| `test_a_held_button_keeps_the_next_shift_from_locking` | `AttributeError: ... has no attribute '_point_fit_mouse_buttons'`（缺少显式控制按键状态的入口） |

红阶段命令：`pytest tests/test_canvas/test_shift_corner_lock_fit.py -k "lost_release_does_not_block or late_release_keeps or held_button_keeps"` → **4 failed**。

复现路径与用户报告一致：选中 `(100,100,200,200)` → 光标在右上区 `(180,120)` 按 `Shift` →
按住左键拖过阈值 → 画布失焦（不发送旧左键释放）→ 松开 `Shift` → 回到右上区再按 `Shift`。
旧实现里 `_point_fit_pressed` 同时表示"本手势接管左键"和"还欠一次释放"，`_point_fit_shift_round()`
看到它即转入 `_point_fit_refresh_from_cursor()`，而 `_point_fit_move()` 又在开头因待释放短路，
于是这次 `Shift` 既没锁角也没预览；等左键按下时 `_point_fit_abandon_pending_release()`
清掉旧归属后，`_point_fit_ensure_entry()` 只能把本轮降级成原有流程，轻点即走旧单击拟合。

### 修复：两种归属分开记录

1. **`_point_fit_pressed` 只表示"当前左键由拟合手势接管"。** `_clear_point_fit(keep_press=True)`
   在放弃活动按下时改设 `_point_fit_release_pending`；它不再用 `pressed` 覆写该标记，
   因此普通预览清理、Shift 轮次结束、重复取消都保留同一条待释放记录。经典单击拟合的取消行为不变
   （按下交还、预览清除、原框不动、释放被消费）。
2. **新增 `_point_fit_left_press_owned()`**（活动按下 **或** 待释放），替换 `point_fit.py` 与
   `canvas.py` 中所有 `keep_press=self._point_fit_pressed` 调用点：目标失效、原几何变化、
   `Shift` 松开、锁角预览失效都保留待消费的释放。
3. **`_point_fit_shift_round()` 只在真实活动按下时走刷新分支。** 等待旧释放不再挡住新的 `Shift`：
   - `Qt` 仍报告有按键按下 → 继续阻止新锁角，旧左键移动仍由 `Canvas.mouseMoveEvent()` 拦截；
   - 无按键、但 `_pointer_down` 只是取消手势的残留 → 清除该残留值，再按当前光标执行原有的
     框内 / 边线 / 框外判断；
   - 加载、平移、边线拖动保护不变。
4. **`_point_fit_move()` 的等待短路加上 `_point_fit_entry is None` 条件。** 本轮尚未建立入口时，
   任何 Shift 修饰移动都不得把取消的手势接回来；真实 `Shift` 按下已建立锁角或缓冲区等待后，
   预览可以正常显示与更新。
5. **`_point_fit_handle_release_event()` 先消费待释放的旧释放。** "左键释放 + `_point_fit_release_pending`"
   只清除标记、接受事件并返回；不提交几何、不结束当前轮次，因为此时可能已经锁好了新角。
   加载期间优先消费的顺序保持不变；新的左键按下仍先清除旧标记（`_point_fit_abandon_pending_release()`）。
6. **新增 `_point_fit_mouse_buttons()`** 收口两处 `QGuiApplication.mouseButtons()` 读取，
   用例可显式指定"Qt 报告左键仍按住"，不依赖运行测试时的真实鼠标位置或按键。

### 测试预期同步（仅断言层，行为断言保留）

旧用例通过 `_point_fit_pressed` 表达"还欠一次释放"，本轮按新语义改用 `_point_fit_release_pending`：

- `test_shift_corner_lock_fit.py`：`test_releasing_shift_during_the_locked_drag_cancels`、
  `test_focus_loss_mid_drag_keeps_the_release_consumed`、
  `test_image_change_mid_drag_keeps_the_release_consumed`、
  `test_repeated_cancels_still_consume_the_release`、
  `test_focus_loss_then_image_change_still_consumes_the_release`、
  `test_undelivered_release_does_not_block_the_next_drag`、
  `test_moving_with_the_button_after_a_cancel_does_not_move_the_box`。
  事件消费、几何结果、无 `shape_moved`、无撤销、无取消选中等断言全部保留。
- `test_rectangle_preview_overlap.py::test_captured_fit_cancels_when_keyboard_moves_source`：
  几何变化取消后改为断言 `_point_fit_release_pending`，并补一条释放后归零的断言。

### 修复后验证（绿）

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| 单点拟合专项 | `pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_corner_lock_fit.py -q` | **132 passed** |
| 新增锁角用例单文件 | `pytest tests/test_canvas/test_shift_corner_lock_fit.py -q` | **38 passed** |
| 矩形预览共边 | `pytest tests/test_canvas/test_rectangle_preview_overlap.py`（10 个既有夹具崩溃参数 deselect） | 47 passed |
| 矩形创建十字线 | `pytest tests/test_canvas/test_rectangle_creation_crosshair.py` | 9 passed |
| 边线编辑回归 | `pytest tests/test_canvas/test_rectangle_edge_migration.py`（1 个既有挂起 deselect） | 94 passed |
| 画布目录整体 | `pytest tests/test_canvas`（13 项 deselect，见下） | **715 passed、83 subtests passed、2 failed（既有）** |
| OpenSpec 严格校验 | `openspec validate add-shift-corner-lock-point-fit --strict` | valid |
| 空白检查 | `git diff --check` | 退出码 0（仅并行改动的 CRLF 警告） |
| 静态检查 | `flake8 -j 1 widgets/point_fit.py tests/test_canvas/test_shift_corner_lock_fit.py` | 退出码 0 |

本轮新增行为断言：新一轮 `Shift` 立即锁角且只显示实心点（`entry="lock"`、`pending_box is None`）；
轻点只结束本轮（坐标、选中、撤销记录、`shape_moved` 全部不变）；旧释放迟到时新锁角保留、
随后一次有效拖动只发一次 `shape_moved` 且一次撤销可回原框；Qt 仍报告旧左键按住时不开启新锁角，
继续移动也不改原框；小框十字缓冲区在残留待释放期间仍能首次进入明确选角区并锁角。

`widgets/canvas.py` 仍只有 `C901 Canvas.mouseReleaseEvent is too complex (22)` 既有告警
（本轮未改该方法）；`point_fit.py`、`canvas.py` 的 black 偏差均为既有行
（`HEAD` 版本同样 `would reformat`），本轮未重排无关代码。

### 第五轮补充：画布外按 `Alt` 丢弃待处理的旧释放

复核指出 `_point_fit_refresh_from_cursor()` 的"光标在画布外"分支仍用无参
`_clear_point_fit()`，会把已经取消的手势还欠着的旧释放一起清掉，迟到的旧释放随后落入原生
释放路径。按 TDD 先补用例确认失败，再把该分支改为保留归属。

| 新增用例 | 修复前失败断言 |
| --- | --- |
| `test_alt_outside_the_canvas_keeps_the_owed_release` | 取消锁角拖动 → 无按键移动 → 画布外按 `Alt` 后 `assert canvas._point_fit_release_pending` → `False` |

红阶段命令：`pytest tests/test_canvas/test_shift_corner_lock_fit.py -k alt_outside` → **1 failed**。

修复："光标在画布外"分支改为 `_clear_point_fit(keep_press=self._point_fit_left_press_owned())`，
离开画布只清预览，不丢弃待消费的释放；用例同时断言随后的旧释放被拟合消费（坐标、选中、
撤销记录、`shape_moved` 均不变）。修复后专项 **132 passed**、画布目录整体 **715 passed**。
其余取消路径已核对：新左键按下（`canvas.py` 的 Ctrl 框选分支、`_point_fit_press*`）与
`_point_fit_release*` 末尾的清理仍按"旧按下确已结束"直接清除，属正确行为。

### 排除用例及原因（本轮实际执行的 13 项）

- `test_rectangle_edge_migration.py::test_main_window_exposes_translated_edge_toggle`：打开真实窗口时弹模态错误对话框挂起（既有）。
- `test_rectangle_preview_overlap.py::test_nudge_preview_preserves_host_dirty[*]`、`::test_fit_commit_marks_host_dirty_once[*]`（10 参数）：旧夹具 `SimpleNamespace` 缺 `canvas`，HEAD 的 `_on_geometry_committed` 读取 `self.canvas.shapes`，PyQt6 槽内异常直接终止进程（0xC0000409），既有。
- `test_navigation.py::test_image_switch_restores_fractional_zoom_and_pan_and_fit_resets`、`::test_shared_view_tracks_revisits_and_reset`：构建 `MainWindow` 时挂起。`faulthandler` 栈证实在 `label_widget.py:10042 error_message` ← `persist_user_preferences` ← `set_canvas_params` ← `LabelWidget.__init__`，即工作区并行的设置持久化改动在无配置会话时弹模态错误框；本变更未触碰 `label_widget.py` 与设置模块。前几轮同两项因沙箱不允许写系统临时目录而以 `PermissionError WinError 5` 报错，属同一环境/既有问题。
- 2 项失败：`test_groups::test_shape_label_keeps_fixed_screen_size_while_zooming`（标签缩放基线 `179 != 139`）、`test_rectangle_size::test_action_switch_updates_canvas_and_config`（并行设置改动的旧测试替身缺 `update_user_preference`）。

### 真实屏幕人工验收

仍未执行。五轮证据均来自离屏渲染与真实 Qt 键鼠事件；深色/浅色背景下观察锁角、拖动、轻点取消、
先松 `Shift` 取消、出图裁剪与提交后单次撤销，仍需用户确认后才能标记通过。

## 2026-11-12 锁角即时预览与单击确认

本节验证当前交互。以上各轮记录对应之前的锁角拖动版。

| 范围 | 结果 |
| --- | --- |
| 单点拟合几何、交互、锁角与纠错计量单次提交 | 129 passed |
| 画布目录 | 711 passed、83 subtests passed、2 failed、13 deselected |
| OpenSpec 严格校验 | valid |

画布目录排除项和两项失败与第五轮相同，详见上文「排除用例及原因」。两项既有失败分别为标签缩放断言和设置替身缺少持久化方法。本轮未运行 CI 排除的 Windows 工具栏布局和点云测试。

回归复现了用户的右下角操作。按下 Shift 立即生成候选，左键松开提交一次，继续按住 Shift 并重新选择时预览仍关闭。其他覆盖包括中央缓冲区、未锁角时的普通左键、跨区和越过固定角、出图裁剪、无效落点、松 Shift 取消、失焦、切图、迟到的左键释放和 Shift + Alt。像素断言覆盖鼠标悬停时的橙色预览、实心点和辅助线。

2026-11-12 用户实测确认新交互可用。用户观察到，小框的初始选角区较窄，容易误选。从右上区锁角再调整左下方的落点时，鼠标移动距离较长。这两点作为已知交互取舍记录。

## 2026-11-12 框内起手固定对角

Qt 键鼠用例覆盖四区按下 Shift 的对角映射、中央缓冲区、从左下出框再返回及越过固定点。预览与提交复用既有锁角状态，框外及组合键回归一并运行。

- 单点拟合专项及纠错计量提交用例共 132 项通过。
- 画布目录 714 项和 83 个子测试通过，2 项既有失败与 13 项既有排除同第五轮。
- 工具栏布局和点云测试本轮未运行。固定对角修订的用户实测待确认。

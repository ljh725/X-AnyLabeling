# Shift 单点拟合统一手势：实施与验证

2026-11-13，4 组共 8 项任务完成，用户确认点拟合功能人工验收通过。

## 2026-11-13 独立复核修复

| 场景 | 修复与验证 |
| --- | --- |
| 框外确认期间平移 | 使用上次指针的全局坐标和当前画布映射重算预览落点，保留按下时捕获的原角。松手结果与预览一致，只新增一次撤销。 |
| 锁角后滚动视口 | 画布移动时安排一次重绘。绘制使用当前画布原点重算落点，原图上的锁角坐标保持固定。 |
| 旧释放未到时收到双击 | 普通左键按下和双击共用释放归属初始化，新按下清掉旧的待释放标记。新的松手事件提交一次。 |
| 图片外静止指针 | 比较未裁剪的原图坐标，显示时使用裁剪坐标。绘制中重算候选时不请求额外重绘。 |
| 框外确认期间原框几何变化 | 移动、绘制和释放按同一份按下时的点坐标检查目标。失效即取消轮次，消费对应释放，重新按下 Shift 才能再拟合。 |

在 `x-anylabeling-cu12` 使用 PyQt6 `offscreen` 复验：

| 范围 | 结果 |
| --- | --- |
| `.tmp/test_independent_shift_followup.py` | 修复前 82 passed / 5 failed，修复后 **87 passed** |
| 单点拟合、预览共边、键盘微调和独立规格合跑 | **282 passed**、14 deselected |
| 画布目录与独立规格合跑 | **643 passed**、2 failed（下文记录的既有失败）、14 deselected、83 subtests passed |
| OpenSpec 严格校验 | `openspec validate unify-shift-rectangle-point-fit --strict` 通过 |

画布合跑排除下文记录的 `test_navigation.py`、`test_rectangle_edge_migration.py` 和 `host_dirty` 用例。CI 单独排除的 `test_toolbar_layout.py` 和 `tests/test_pointcloud/` 本轮未运行。

## 改动文件

- `anylabeling/views/labeling/widgets/point_fit.py`
  - 新增 `_point_fit_native_move`：框外或边线入口先算原有预览，未按下且指针落入明确框内区时切到 `lock` 入口并锁该区对角。
  - `_point_fit_lock_move` 移除 `Alt` 分支；`_update_point_fit` 移除 `inward` 参数与同侧角提案。
  - `_point_fit_release_lock` 对无效/未变化释放改为 `_point_fit_end_round(keep_lock=True)`，保留锁角与轮次。
  - `_clear_point_fit` / `_point_fit_end_round` 增加 `keep_lock`；`_point_fit_lock_visible` 接受 `lock` 与 `finished` 两态。
  - `_build_point_fit_preview` 的框外候选不再给 `fixed_point`，实心点只在锁角帧出现。
  - 新增 `_point_fit_round_locks`：`_point_fit_shift_round` 置真、`_point_fit_ensure_entry` 置假，保证只有真实 `Shift` 按下开启的轮次才进框锁角。
- `anylabeling/views/labeling/widgets/canvas.py`：删除 `Alt` 按下/松开对拟合预览的刷新，新增 `_point_fit_round_locks` 初始化。
- 测试：`tests/test_canvas/test_shift_corner_lock_fit.py`、`test_shift_point_fit_interaction.py`、`test_rectangle_preview_overlap.py` 按新契约改写。
- 文档：`docs/zh_cn/rectangle_point_fit.md`、`docs/custom_changes/2026-11-12-point-fit-unify-shift.md`、`docs/custom_changes/README.md`。

## 测试命令与结果

解释器 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，`QT_QPA_PLATFORM=offscreen`，均加 `-p no:cacheprovider`。

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| 单点拟合专项 | `pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_corner_lock_fit.py -q` | **147 passed** |
| 预览共边与键盘微调 | `pytest tests/test_canvas/test_rectangle_preview_overlap.py -k "not host_dirty" -q` | **43 passed**、14 deselected |
| 画布目录整体回归 | 排除 `test_toolbar_layout.py`、`test_navigation.py`、`test_rectangle_edge_migration.py`，`-k "not host_dirty"` | **551 passed**、2 failed（既有）、14 deselected、83 subtests passed |
| 外部独立规格套件（82 离屏 Qt 场景） | `pytest .tmp/test_independent_shift_point_fit.py -q` | 修复前 67 passed / 15 failed → **82 passed** |
| 两者合跑 | 同上合并 | **633 passed**、2 failed（既有） |

## 复核后补修的三处

| 问题 | 修复 | 回归用例 |
| --- | --- | --- |
| 框外提交后同一 `Shift` 还能开启预览 | `_point_fit_release` 成功写回统一 `finish=True` → `ENTRY_FINISHED`；同一 `Shift` 内只能选矩形 | `test_outside_commit_finishes_the_round_for_a_held_shift` |
| 无效点击后实心点暂时消失 | `_build_lock_point_fit_preview` 用 `corner_point(locked_box, locked_corner)` 算固定点；`_point_fit_release_lock` 在 `Shift` 已松/目标失效时走 `_point_fit_cancel_round()` | `test_invalid_locked_click_keeps_the_solid_point_while_the_pointer_rests`（鼠标静止断言像素） |
| 无预览点一下后进框锁不了角 | `_point_fit_press_classic` 无候选分支改 `_point_fit_clear_classic_preview()`，保留 `_point_fit_round_locks` | `test_click_without_a_candidate_keeps_the_inside_lock_eligibility` |

三条用例做过红/绿验证：逐一 revert 三处修复后，对应用例全部转红；恢复后转绿。

## 第二轮：外部独立套件复现的八类缺陷

外部独立规格套件（82 离屏 Qt 场景，未复用本仓库测试代码）复现 8 类缺陷，全部修复并各补一条仓库内回归：

| 缺陷 | 修复要点 | 回归用例 |
| --- | --- | --- |
| 加载中松手仍写回矩形 | `set_loading(True)` 取消拟合并保留待释放；释放入口再查 `is_loading` | `test_loading_before_the_release_never_commits` |
| 失焦/切图后同一 `Shift` 重开拟合 | `_point_fit_round_spent` 封锁；真实 `Shift` 按下/松开才清除 | `test_cancelled_round_blocks_the_still_held_shift` |
| 快速重试被送成双击 → 打开标签编辑 | `mouseDoubleClickEvent` 先试 `_point_fit_press` | `test_double_click_on_a_locked_preview_still_confirms` |
| 平移后预览与松手结果不一致 | 记录屏幕坐标，映射变化时重算落点；固定角仍用原图坐标 | `test_locked_preview_follows_a_pan_of_the_image` |
| 十字线透明度为 0 时实心点消失 | 十字线画完恢复 `p.setOpacity(previous_opacity)` | `test_locked_marker_ignores_the_crosshair_opacity` |
| 框外无效释放让本轮失去锁角能力 | classic 释放未提交时 `keep_lock=True` | `test_invalid_outside_release_keeps_the_inside_lock_eligibility` |
| 候选等于原框（无虚线）仍抢左键 | 未锁角时统一用「几何有效且确实变化」判定 | `test_unchanged_candidate_never_steals_the_press` |
| 释放事件里才发现取消，却重新置待释放 | `_point_fit_cancel_during_release()` 直接消费当前事件 | `test_release_discovering_a_cancel_leaves_no_release_debt` |
| 合成事件（无中间 move）临时换固定端 | 按下时复用仍有效的已显示预览固定端 | `test_press_without_a_move_keeps_the_shown_anchor` |

9 条均做红/绿验证。测试覆盖规格与上述边界，但离屏 Qt 无法证明所有平台的真实事件顺序。

## 画布回归的两个挂起文件（既有，非本变更）

`test_navigation.py` 与 `test_rectangle_edge_migration.py` 在 offscreen 下**永久挂起**，会让整目录 pytest 停住。用 `git stash` 把本次改动退回 HEAD 后逐一复现，同样挂起。栈（`-o faulthandler_timeout=12`）：

```
label_widget.py:10054 error_message
label_widget.py:8676  persist_user_preferences
label_widget.py:8717  update_user_preference
label_widget.py:8620  set_canvas_params
label_wrapper.py:24 / mainwindow.py:43 / test 用例构造 MainWindow
```

即并行进行的「设置持久化」改动在 `save_patch` 抛 `ConfigError` 后走 `QMessageBox.critical()` 模态阻塞。未在本变更范围内修复，回归按名排除。

**给后续跑回归的人**：不要直接 `pytest tests/test_canvas`，会卡住；按上表排除这两个文件（以及 `-k "not host_dirty"`），或者用 `-o faulthandler_timeout=<秒>` 快速定位挂点。

## 既有失败（与本次无关）

| 用例 | 现象 | 说明 |
| --- | --- | --- |
| `test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming` | `179 != 139` | 标签屏幕尺寸缩放，前次验证已记录 |
| `test_rectangle_size.py::test_action_switch_updates_canvas_and_config` | `AttributeError: ... no attribute 'update_user_preference'` | 并行的设置持久化改动与旧测试替身不一致 |
| `test_rectangle_preview_overlap.py` 的 `dirty_host` 系列 | 进程退出码 `0xC0000409` | 夹具 `SimpleNamespace` 缺 `canvas` 属性，PyQt6 槽内异常直接终止进程 |
| `canvas.py` 的 `flake8 C901`（`mouseReleaseEvent` 22）与 `black --check` | 报错 | HEAD 上同样存在 |

## OpenSpec 校验

`openspec validate unify-shift-rectangle-point-fit --strict` 通过。

## 人工验收

2026-11-13，用户确认点拟合功能人工测试通过。

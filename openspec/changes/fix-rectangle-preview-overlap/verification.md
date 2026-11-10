# 矩形预览共边显示实施与验证

## 2026-11-09 6.1 真实屏幕人工验收完成

用户于 2026-11-09 在真实可见窗口、深色与浅色两种图片背景上完成 6.1 验收，范围与任务原文一致：

- **两点矩形创建（四个方向）**：与青蓝色引导共线的两条草稿边只显示引导虚线，另两条边保持实线；第二点确认后正式框四边完整；取消后无残留。
- **Shift 框外扩张 / Shift+Alt 框内收缩**：橙色虚线候选与原框共线的区间不露出原框实线，非共线部分保持原样式，固定角标记可辨认。
- **取消**（松开修饰键、移开指针、Esc）：原框立即恢复完整轮廓，无缺边、无旧候选残影。
- **提交**：成为完整普通标注框，单次撤销恢复原几何，预览未产生额外撤销步骤。

用户确认以上四项全部无问题并同意勾选 6.1。**证据性质**：人工可见窗口观察，未用离屏渲染或像素采样替代；本次为对话确认，**未附真实屏幕截图文件**，逐条观察记录见 [evidence/real-screen-acceptance-20261109.md](evidence/real-screen-acceptance-20261109.md)。至此任务清单 24/24 完成；变更未归档，归档需另行确认。

## 2026-11-06 单点拟合修复与用户验收

本次 CUSTOM-101 修复已由用户实际测试并明确确认功能验收通过。范围为 Shift/Alt 按键即时刷新、小框中心附近预览防跳，以及相关拟合交互；原计划 6.1 还包含矩形创建、深浅背景截图等，不扩大解释为该整项验收已经完成。

- 修改：`rect_edge_click.py` 增加已有角的切换缓冲；`widgets/point_fit.py` 保存悬停角、按当前光标刷新并在点击时捕获预览角；`widgets/canvas.py` 初始化状态并接入 Shift/Alt 键事件。
- 复现：修复前新增 9 项事件回归均失败；原有几何与交互 57 项通过。
- 修复后：以下隔离 Qt 回归 **132 passed in 3.38s**，覆盖几何、静止按键、缩放、小框轻微抖动、主动换角、提交/撤销、共边像素及 dirty 信号。
- 修正旧测试夹具 `dirty_host` 缺失的 `_notify_inspection_edit` 生产方法绑定，消除 Qt 信号回调异常导致的提前退出；运行时 dirty 逻辑未修改。

```powershell
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_rectangle_preview_overlap.py -q --color=no -p no:cacheprovider --tb=short
```

用户已授权沙箱外运行；采用项目隔离配置、QSettings 和离屏画布，没有操作当前真实标注。语法校验与 `git diff --check` 通过。修复代码在验收后归集提交，提交号及同步信息见 [实施与交付记录](../../../docs/custom_changes/2026-11-02-rectangle-preview-overlap-plan.md)。

操作说明：[矩形单点拟合](../../../docs/zh_cn/rectangle_point_fit.md)。本次未重跑全项目测试，未构建安装包，也未自动归档整个共边显示变更。

## 2026-11-05 补齐 dirty 断言与实际反例证据

**（截至 2026-11-05）5.3、5.6 验证缺口已关闭，6.4 证据已补齐；当时 23/24 项完成，仅 6.1 真实屏幕验收未完成（该项已于 2026-11-09 完成，见顶部章节）。** 本轮只新增测试和证据脚本/日志，未修改运行源码或回退共享工作区。

### 新增测试与验收边界

`tests/test_canvas/test_rectangle_preview_overlap.py` 新增 14 项参数化用例，预览测试共 57 项：

- `test_preview_cancel_preserves_host_dirty`（4 项）：Shift/Shift+Alt、初始干净/已脏；悬停、重复绘制和松开 Shift 取消后 dirty 保持原值，`set_dirty` 与提交信号均为零，序列化及撤销不变。
- `test_nudge_preview_preserves_host_dirty`（8 项）：向左/向右、悬停/已捕获、mask 开/关；键盘微调正常发出一次 `shape_moved` 并变脏；模拟清除 dirty 检查点后，来源重算、取消及释放不再次标脏、不增加提交信号、序列化或撤销。
- `test_fit_commit_marks_host_dirty_once`（2 项）：Shift/Shift+Alt 有效拟合前预览保持干净，提交只标脏一次、发出一次提交信号、增加一次撤销，单次撤销恢复原几何，后续绘制不发信号。

夹具 `dirty_host` 使用 `LabelingWidget._on_geometry_committed` 和 `LabelingWidget.set_dirty` 的真实实现，连接 Canvas 的移动、旋转和新建信号，并通过 `QSignalSpy`、`set_dirty` 调用次数及 dirty 值独立断言。仅 UI actions 使用替身，自动保存关闭；这是 dirty 处理链路的离屏测试，未宣称完整主窗口、自动保存或真实屏幕验收通过。

### 实际执行的负向对照

可复现脚本：[verify_preview_controls.py](evidence/verify_preview_controls.py)。从仓库根目录分别运行；脚本检查 pytest 退出码为 1（预期断言失败）后自身退出 0。每种对照在独立进程内临时替换 Canvas 方法，结束后恢复绑定；没有覆盖运行源码，也没有复原其他工作区差异。

```powershell
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe openspec/changes/fix-rectangle-preview-overlap/evidence/verify_preview_controls.py dirty-signal
# 14 failed, 43 deselected, 1 warning；pytest exit 1，脚本 exit 0

& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe openspec/changes/fix-rectangle-preview-overlap/evidence/verify_preview_controls.py pre-p2
# 2 failed, 55 deselected, 1 warning；pytest exit 1，脚本 exit 0
```

- [dirty-signal.txt](evidence/dirty-signal.txt)：在存在预览时人为增加 `shape_moved`，14 项新测试均被 dirty 或提交次数断言检出，补上原 43 项测试无法检出的缺口。
- [pre-p2.txt](evidence/pre-p2.txt)：从 Git `9673d3b9` 读取原始 `_build_point_fit_preview` 方法，仅临时替换该方法，在当前工作区及当前测试上运行同一无效候选反例。普通和 mask 两项均实际失败于“旧候选仍不为 None”。这是历史方法的定向对照，不是完整历史检出的全量测试；当前方法下同一反例通过。
- 两次 warning 均为进程预先导入模块后 pytest 的 assertion rewrite 提示，不是夹具错误；预期失败不计入正常通过数。

### 当前实现回归结果

Windows、conda `x-anylabeling-cu12` Python、PyQt6 offscreen、仓库配置隔离 fixture；Qt DLL 在默认沙箱中被拒绝加载，因此测试沿用已批准的更宽权限环境。

```powershell
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_rectangle_preview_overlap.py tests/test_canvas/test_rectangle_creation_crosshair.py tests/test_canvas/test_shift_point_fit_interaction.py tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_stroke_width.py tests/test_canvas/test_rectangle_extreme_creation.py tests/test_canvas/test_drawing_mode_switch.py tests/test_canvas/test_fill_opacity.py -q --tb=short --color=no -p no:cacheprovider
# 149 passed, 72 subtests passed in 3.42s

& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m flake8 -j 1 tests/test_canvas/test_rectangle_preview_overlap.py openspec/changes/fix-rectangle-preview-overlap/evidence/verify_preview_controls.py --select=E9,F63,F7,F82,F401,F811,F841
# 退出码 0，无输出
```

完整正常回归日志见 [regression-20261105.txt](evidence/regression-20261105.txt)。没有重跑全仓库或画布全量、性能测试或真实屏幕验收；历史全量失败归因未在本轮重新证明。

## 历史：2026-11-05 完成情况复核（补证前）

本轮重新运行定向回归：135 passed、72 subtests passed；flake8 与 OpenSpec 严格校验通过。已核对候选来源重算、捕获取消、普通/mask 共边轮廓与创建绘制顺序，未发现新的实现缺陷。

完成度修正：原 23/24 项勾选中的 5.3、5.6 尚缺 dirty 状态断言，现恢复未勾选，清单为 21/24 项完成。现有 `snapshot()` 只比较序列化和撤销栈；进程内临时让预览额外发出 `shape_moved`（主窗口会据此调用 `set_dirty()`）后，43 项预览测试仍全部通过。因此，下文历史记录中的“零副作用”不能视为已经验证 dirty 不变。该检查没有修改运行源码或测试文件。6.1 真实屏幕验收仍未完成，变更未归档；详细证据与后续验收要求见 [review-20261105.md](review-20261105.md)。

## 历史实施记录

2026-11-02，实施分支 `codex/refactor-data-inspector-workflow`，基线 `9a37c547`。当时的源码接入与自动化验证已完成。2026-11-04 复核发现的 P2（原框几何变化后旧拟合候选未失效）已于 2026-11-04 修复并新增回归；任务 4.6、5.6、6.4 已完成。任务 6.1（真实屏幕验收）仍未完成，本变更未归档。

## 2026-11-04 复核补充：原几何变化后旧候选未失效

**状态：已修复并新增回归（2026-11-04 第二轮实施）。** 下方「问题与复现」保留修复前的复现证据；修复落点、修复后结果与新增回归见后文。

### 问题与复现（修复前）

- 优先级：P2。位置：`widgets/point_fit.py::_build_point_fit_preview()`，当前目标几何与 `_point_fit_pending_box` 之间缺少来源一致性检查。
- 使用内存白底图片与一个选中矩形，原框为 `(100,100,200,200)`；按住 Shift，将指针放在 `(151.5,120)`，得到候选 `(100,120,151.5,200)`。
- 不移动指针，发送 Shift+右方向键的真实 Canvas 键盘事件，原框右移 1 像素为 `(101,100,201,200)`。
- 实际：帧快照仍保留旧候选 `(100,120,151.5,200)`，旧候选右边的采样区间 `x=151, y=130..189` 中检测到 55 个橙色像素；显式按当前原框和相同指针重算后，候选为 `None`。
- 预期：悬停候选重算后显示无效反馈，当前原框完整，不再绘制旧橙色候选或按其避让；已捕获手势的原几何改变时取消并消费释放。具体约束见 `design.md` 决策 3 和对应 spec 场景。

### 修复落点

- `widgets/point_fit.py::_update_point_fit`：候选计算时记录来源快照 `_point_fit_source_target`（目标身份）、`_point_fit_source_box`（本次使用的原几何）和 `_point_fit_pointer`（未裁剪的图片坐标指针），并把当前 Shift/Shift+Alt 生效模式写入 `_point_fit_inward`，供后续无鼠标事件的重算复用。
- `widgets/point_fit.py::_build_point_fit_preview`：生成每帧快照前比较来源。悬停期间同一目标几何变化时，以当前几何和已记录指针重算候选，普通轮廓、mask 轮廓、候选叠层和常驻十字线资格统一消费重算结果；已捕获手势的原几何与按下时快照不同则取消拟合并保留按下状态，使随后的鼠标释放被消费，不重新选择固定角、不提交旧候选，也不覆盖键盘等入口产生的新几何。
- `widgets/point_fit.py::_point_fit_move`：捕获期间若鼠标移动发现原几何已变化，同样取消并消费该手势，避免在下一帧绘制前用旧按下快照重新生成候选。
- `widgets/canvas.py::Canvas.__init__`：仅在 Canvas 内新增三个临时字段，不写入 Shape、标注 JSON 或配置；`_clear_point_fit()` 统一清理。
- 预览刷新不调用 `store_shapes()`、不写保存/配置、不改变坐标；重算只在来源变化时发生（第二帧不再调用 `_update_point_fit`）。

### 修复后结果

同一反例通过真实 Canvas 鼠标/键盘事件与离屏像素确认：Shift 悬停 `(151.5,120)` 后按 Shift+右方向键，原框变为 `(101,100,201,200)`，下一帧候选为 `None`，`x=151, y=130..189` 无橙色像素，当前原框四边完整，常驻十字线按配置恢复并以既有红色定位点提示无效候选。重算仍有效的左移反例得到 `(99,120,151.5,200)` 并只按新共边避让；Shift+Alt 重算保持向内语义。捕获后几何改变时取消拟合、消费释放且不提交；重新开始有效拟合仍可提交并撤销。

### 新增回归（`tests/test_canvas/test_rectangle_preview_overlap.py`，共 43 项）

- `test_hover_preview_does_not_recompute_without_source_change`：来源未变时逐帧复用候选，不重复推断。
- `test_keyboard_nudge_recomputes_still_valid_hover_candidate[False/True]`：重算仍有效的反例、遮罩开关、零副作用与单次重算。
- `test_keyboard_nudge_invalidates_hover_candidate[False/True]`：P2 无效反例、像素、常驻十字线恢复、红色无效反馈、键盘自身一次撤销与预览零副作用。
- `test_keyboard_nudge_keeps_alt_hover_mode`：Shift+Alt 向内候选按新几何重算。
- `test_captured_fit_cancels_when_keyboard_moves_source`：捕获手势取消、释放被消费、指针移动不能复活旧候选、不新增撤销。
- `test_refit_after_cancelled_capture_commits_and_undoes`：取消后重新拟合可提交，两次撤销逐级恢复。

### 复核期间已运行的相关回归

环境：Windows，`x-anylabeling-cu12` conda Python，PyQt6 离屏平台；测试使用仓库现有隔离配置 fixture。沙箱内首次加载 QtCore DLL 被拒绝，以下命令在批准的更宽权限环境中成功执行。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_rectangle_preview_overlap.py tests/test_canvas/test_rectangle_creation_crosshair.py tests/test_canvas/test_shift_point_fit_interaction.py -q --tb=short --color=no -p no:cacheprovider
# 74 passed

C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_stroke_width.py tests/test_canvas/test_rectangle_extreme_creation.py tests/test_canvas/test_drawing_mode_switch.py tests/test_canvas/test_fill_opacity.py -q --tb=short --color=no -p no:cacheprovider
# 53 passed, 72 subtests passed
```

合计 **127 项通过，另有 72 项子测试通过**，但这些既有用例未覆盖上述键盘微调反例，属修复前复核结果。修复方案对应待办 4.6，新增回归对应 5.6，修复后证据收尾对应 6.4；任务 6.1 的真实屏幕验收继续独立保留。

## 实际文件

- 新增 `anylabeling/views/labeling/rectangle_preview.py`：矩形四边规范化、同线区间差集、屏幕线宽端点余量与开放路径构建；另有 `PointFitPreview` 单帧快照数据。
- `anylabeling/views/labeling/shape.py::Shape.paint`：新增仅本次调用有效的关键字参数 `outline_path`。`None` 保持原轮廓，空路径描边为空；填充、顶点和选中手柄继续使用完整几何。
- `anylabeling/views/labeling/widgets/point_fit.py`：新增 `_build_point_fit_preview()`；候选改为 RGBA `(220,130,0,255)`、cosmetic 2.0 的完整虚线路径；相同几何不叠画候选轮廓，无效候选保留红色指针反馈。2026-11-04 P2 修复后，`_update_point_fit()` 记录候选来源目标身份、原几何、未裁剪指针与生效模式；`_build_point_fit_preview()` 在来源变化时重算悬停候选或取消已捕获手势，`_point_fit_move()` 对捕获期间变化的几何做同样的取消并消费释放。
- `anylabeling/views/labeling/widgets/rectangle_crosshair.py`：提供当前草稿剩余轮廓；有效且不同的拟合预览期间常驻十字线让位，预览结束按原配置恢复。
- `anylabeling/views/labeling/widgets/canvas.py`：每帧只生成一次预览快照，普通 Shape 与 `show_masks` 额外轮廓共用该轮廓；创建十字线移到草稿预览之后、文字信息之前。2026-11-04 P2 修复新增 `_point_fit_source_target`、`_point_fit_source_box`、`_point_fit_pointer` 三个仅存在于 Canvas 的临时字段，由 `_clear_point_fit()` 统一清理。
- 新增 `tests/test_canvas/test_rectangle_preview_overlap.py`：共边几何、缩放余量、四象限、遮罩、真实画布像素、取消恢复、提交后完整轮廓、数据独立与导出检查；2026-11-04 追加 8 项 P2 键盘微调与捕获取消回归，共 43 项。

## 实际命令与结果

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_rectangle_preview_overlap.py -q --tb=short --color=no -p no:cacheprovider
```

结果：**35 passed**（2026-11-02 首轮，P2 修复前；2026-11-04 追加回归后为 43 passed）。覆盖 0.25/0.5/1/2/4 倍缩放的几何余量，四象限共边，相近但非共线、仅点相交、相同矩形、小框、遮罩开关、常驻线让位、创建引导开关，以及预览/取消/导出前后的像素和数据快照。

另用同一离屏平台生成了深色背景下的拟合与创建渲染图做目视核对：拟合时原框共边只剩橙色候选虚线，非共边白线完整；创建时草稿仅保留非共边两条实线，另两条由青色引导虚线表示。该核对仅用于辅助，不计入 6.1 的真实屏幕验收。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas -q --tb=line --color=no -p no:cacheprovider
```

结果：**578 passed / 1 failed**，失败项为既有 `test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`（`179 != 139`）。该失败在实施前的既有报告和本次改动前运行中均存在，与共边预览无关。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_labeling -q --tb=short --color=no -p no:cacheprovider
```

结果：**192 passed / 8 failed**，失败项均为既有环境/基线问题（Windows 临时文件权限、路径分隔符、既有 mock 契约），数量与 `reports/inspector_workflow_20261102/REPORT.md` 记录的基线一致，未出现与本次画布绘制接入相关的新增失败。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m flake8 anylabeling/views/labeling/rectangle_preview.py anylabeling/views/labeling/shape.py anylabeling/views/labeling/widgets/point_fit.py anylabeling/views/labeling/widgets/rectangle_crosshair.py anylabeling/views/labeling/widgets/canvas.py --max-line-length=79 --select=E9,F63,F7,F82,F401,F811,F841
```

结果：无输出（通过）。`black --check` 已用于新增模块和基线本已干净的 `point_fit.py`、`rectangle_crosshair.py`；`canvas.py` 在基线中即非 black-clean，未整体重排以避免混入无关格式差异。测试文件按项目惯例不纳入 black。

## 2026-11-04 P2 修复后的命令与结果

环境：Windows，`x-anylabeling-cu12` conda Python 3.12.12，PyQt6 6.10.2，`QT_QPA_PLATFORM=offscreen`，仓库隔离配置 fixture。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_rectangle_preview_overlap.py tests/test_canvas/test_rectangle_creation_crosshair.py tests/test_canvas/test_shift_point_fit_interaction.py -q --tb=short --color=no -p no:cacheprovider
# 82 passed（含新增 8 项 P2 回归）

C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_shift_point_fit_geometry.py tests/test_canvas/test_stroke_width.py tests/test_canvas/test_rectangle_extreme_creation.py tests/test_canvas/test_drawing_mode_switch.py tests/test_canvas/test_fill_opacity.py -q --tb=short --color=no -p no:cacheprovider
# 53 passed, 72 subtests passed
```

新增回归在修复前反例上会失败：键盘微调后 `_point_fit_pending_box` 仍为旧候选且 `x=151, y=130..189` 有橙色像素；修复后同一断言为 `None`、0 个橙色像素。以下场景均已由上述用例覆盖并通过：悬停后几何变化仍有效/变为无效、普通与遮罩绘制、常驻十字线恢复、Shift+Alt 向内语义、捕获期间几何改变后取消并消费释放、指针移动不能复活旧候选、重新拟合后提交与逐级撤销、预览刷新对序列化与撤销栈零副作用。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas -q --tb=line --color=no -p no:cacheprovider --deselect tests/test_canvas/test_rectangle_edge_migration.py::test_main_window_exposes_translated_edge_toggle
# 599 passed, 5 failed, 2 errors, 1 deselected, 83 subtests passed
```

上述失败与错误均归属并行工作区或既有基线，与本次 P2 修复无关：`test_groups.py::test_shape_label_keeps_fixed_screen_size_while_zooming` 为既有 `179 != 139`；`test_shape_identity.py` 三项失败和两个 `test_navigation.py` 错误均为 Windows 沙箱临时目录 ACL 拒绝（`PermissionError: [WinError 5]`）；`test_rectangle_size.py::test_action_switch_updates_canvas_and_config` 因工作区并行的设置持久化改动在 `label_widget.py:8231` 调用 `update_user_preference` 而失败。被取消选择的 `test_main_window_exposes_translated_edge_toggle` 在当前并行改动下会在 `label_widget.py` 的 `error_message`/`persist_user_preferences` 弹出模态错误对话框而挂起；这些文件不在本项差异内。

```powershell
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m flake8 -j 1 anylabeling/views/labeling/rectangle_preview.py anylabeling/views/labeling/shape.py anylabeling/views/labeling/widgets/point_fit.py anylabeling/views/labeling/widgets/rectangle_crosshair.py anylabeling/views/labeling/widgets/canvas.py --max-line-length=79 --select=E9,F63,F7,F82,F401,F811,F841
# 无输出（通过）

C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m black --diff anylabeling/views/labeling/widgets/point_fit.py
# All done! 1 file would be left unchanged.
# rectangle_preview.py、rectangle_crosshair.py 同样无变更；canvas.py 基线即非 black-clean，未整体重排。
# 注：本机沙箱下多文件 black 会因 multiprocessing 管道被拒绝而报错，故按单文件运行。
```

```powershell
openspec validate fix-rectangle-preview-overlap --strict
# Change 'fix-rectangle-preview-overlap' is valid
```

## 未验证

- （2026-11-05 时）6.1 真实屏幕深浅背景验收未执行：本次仍为离屏渲染与像素采样，不能替代人工可见窗口验收。该验收已于 2026-11-09 由用户完成，见顶部章节。
- 未重跑 `pytest tests` 全量，未做性能重测；新增计算只比较当前矩形几何与已记录指针，不读取标注文件、不遍历目录或全部标注对象。
- 未提交 Git；回退仅撤销 `point_fit.py` 的来源校验/重算/取消逻辑、`canvas.py` 的三个临时字段和 8 项新增测试，不回退整个共享 `canvas.py`，不涉及用户标注数据。

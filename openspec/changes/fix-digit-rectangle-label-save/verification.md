# 数字快捷键矩形类别保存修复：实施与验证

2026-11-11 补充复核覆盖放弃绘制时的类别绑定清理，见 [CUSTOM-011 实施与复核记录](../../../docs/custom_changes/2026-11-11-digit-rectangle-label-save.md)。

## 独立完成复核（2026-11-10）

本轮重新审阅 `create_digit_mode()`、`new_shape()`、规格及回归断言，未发现本次修复的阻断问题。任务清单维持 **10/10 完成**；未归档。

重新运行数字矩形保存、数字键选中对象改类、文件保存及数字映射设置四份测试：**53 passed in 84.79s**，无失败、跳过、XFAIL 或 XPASS。原始结果见 [evidence/review-regression-20261110.xml](evidence/review-regression-20261110.xml)。覆盖 16 种保存组合、0–9 数字键、JSON 顶点与图片尺寸、保存重载、绑定消费、下一次普通绘制、上次类别复用及自动标注特殊标记。

复核命令（仓库根目录）：

```powershell
New-Item -ItemType Directory -Force .tmp/digit-review-20261110 | Out-Null
$env:PYTEST_DEBUG_TEMPROOT = 'D:/X-AnyLabeling-4.2.1/.tmp/digit-review-20261110'
$env:PYTHONPATH = '.tmp/harness'
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_labeling/test_digit_rectangle_save.py tests/test_labeling/test_digit_label_actions.py tests/test_labeling/test_label_file_save.py tests/test_settings/test_digit_shortcut_flow.py -q --tb=short --color=no -p no:cacheprovider -p pytest_tmp777 --junitxml=openspec/changes/fix-digit-rectangle-label-save/evidence/review-regression-20261110.xml
```

首次启动被沙箱的 PyQt6 DLL 读取权限阻止；改在沙箱外运行后，因未预建 `PYTEST_DEBUG_TEMPROOT` 出现 28 项夹具错误、25 项通过。创建上述目录后完整重跑得到 53 项通过，未修改业务或测试代码。`openspec validate fix-digit-rectangle-label-save --strict` 与相关文件 `git diff --check` 均通过。

发现并修正任务汇总过期：`openspec/PENDING_TASKS.md` 仍记本变更 0/10，现已移至“已完成但未归档”，未完成总数由 4 个变更 / 69 项更新为 3 个变更 / 59 项。本轮未重跑全项目测试或人工可见屏幕验收；原离屏界面验收记录继续保留。

## 结论（2026-11-10）

`fix-digit-rectangle-label-save` 任务清单 10 项全部完成。普通矩形完成时的类别解析改为：**自动标注特殊标记 > 本次数字键绑定 > 类别预选 / 复用上次类别 / 标签弹窗**。关闭标签弹窗且类别列表预选其他类别时，JSON 与画布均写入数字键绑定类别；绑定在成功创建时消费。原 4 项严格 xfail 已移除并成为必过断言；定向回归、相邻回归与真实主窗口离屏验收均通过。

- 修复前（同一套测试、移除 xfail 后）：**6 failed, 25 passed**（4 个原 xfail 组合 + 绑定消费用例 + 单元优先级用例）。
- 修复后：**31 passed**（16 种保存组合 + 0–9 数字键 + 2 项新增端到端回归 + 3 项单元级相邻验证）。
- 真实主窗口离屏验收：4/4 场景通过，见 [evidence/ui-acceptance-20261110.txt](evidence/ui-acceptance-20261110.txt)。

本次未做人工可见屏幕验收，未运行全项目测试，未归档变更；取消绘制/切图等绑定生命周期问题按设计文档保持原状，仅核对与本次改动相邻的回归。

## 环境前置（本工作区当前状态，非本次代码改动）

### 1. Windows 沙箱使 pytest 临时目录不可访问

本会话沙箱中，以 POSIX `0700` 权限创建的目录（`os.mkdir(path, 0o700)`）对当前令牌不可访问（`PermissionError: [WinError 5]`）。pytest 的 `basetemp` 与每个用例的 `tmp_path` 都用 `mode=0o700` 创建，因此默认 pytest 运行会在会话收尾或首次 `tmp_path` 时失败/挂起。

处理方式（仅测试运行用，不进入仓库交付物）：在 `.tmp/harness/pytest_tmp777.py` 放一个 pytest 插件，把 `os.mkdir` / `pathlib.Path.mkdir` 的 mode 统一改为 `0o777`，并用独立目录作为 pytest 临时根：

```powershell
$env:PYTEST_DEBUG_TEMPROOT = 'D:/X-AnyLabeling-4.2.1/.tmp/pytestroot9'
$env:PYTHONPATH = '.tmp/harness'
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest <目标> -q --tb=line --color=no -p no:cacheprovider -p pytest_tmp777
```

该插件只影响测试进程内临时目录的创建权限，不改变任何业务代码或用户配置。

### 2. 目标测试夹具已过期（会导致模态框挂起）

`tests/test_labeling/test_digit_rectangle_save.py` 原夹具先写入空 `config.yaml` 再 `user_config.begin_session(ensure_created=True)`。当前工作区已有“配置字段冲突检测 + 持久化”逻辑（见 `persist_user_preferences`/`ConfigConflict`），空文件使 `show_groups` 的启动期保存被判定为冲突，`error_message()` 弹出 `QMessageBox` 模态框；离屏测试无人应答而永久挂起（faulthandler 栈：`error_message` ← `persist_user_preferences` ← `update_user_preference` ← `set_canvas_params` ← 构造期 `show_groups` 动作）。

按同一仓库较新夹具（`test_canvas_display_retention.py`、`test_review_status_panel.py`、`test_toolbar_display_actions.py`）的做法修正：不再预写空文件，让 `begin_session()` 用模板创建目标。该修正只改测试夹具，不改变被测业务行为；修正后同样的用例可正常执行。

### 3. 与本变更无关的既有测试挂起/失败

`tests/test_labeling` 目录整体运行无法完成：若目录内仍有测试使用“预写空 config + 不建会话”的旧夹具，构造 `MainWindow` 时即触发上述同一类模态框挂起（例如 `tests/test_ui_density_extremes_repair.py` 在 faulthandler 20 秒超时处停在同一条 `error_message` 栈；`tests/test_candidate_review_regressions.py` 同样超时）。该现象在本次实现改动之前（2026-11-10 10:08 的构造期诊断日志已记录 `Failed to save user preferences: ... show_groups`）就存在，与 `new_shape()` 无关；本次未扩大范围去修改这些无关夹具。

`tests/test_auto_labeling`：52 passed、3 failed，失败为环境能力而非本变更——`test_cache_symlinks_are_not_followed` 需要符号链接特权（`WinError 1314`），`test_remote_server` 两项因 `tempfile` 以 `0600` 创建临时文件在本沙箱不可读（`PermissionError: ... tmppnv9e53n.jpg`）。

## 根本原因与代码改动

`new_shape()`（`anylabeling/views/labeling/label_widget.py:7842`）先取类别列表预选值，数字绑定只在“弹窗开启 / 无预选 / 自动标注 OBJECT”分支内消费：

```python
        elif (
            self._config["display_label_popup"]
            or not text
            or self.canvas.shapes[-1].label == AutoLabelingMode.OBJECT
        ):
            ...
            if self.digit_to_label is not None:      # 关闭弹窗且有预选时永远走不到
                text = self.digit_to_label
                self.digit_to_label = None
```

修复把数字绑定提升为独立分支，置于自动标注特殊标记之后、弹窗/复用上次类别之前；命中时读取并清除绑定，再进入原有公共的合法性校验、属性、登记与保存流程：

```python
        elif self.digit_to_label is not None:
            # A digit shortcut owns the shape being finished: the binding wins
            # over the preselected class, the reused last label and the label
            # dialog, so a disabled popup cannot silently replace it.
            text = self.digit_to_label
            self.digit_to_label = None
            if self._config["auto_use_last_gid"]:
                last_gid = self.find_last_gid()
                if last_gid is not None:
                    group_id = last_gid
```

改动范围：`label_widget.py` 的 `new_shape()` 一个分支（约 +12/−8 行）、`tests/test_labeling/test_digit_rectangle_save.py` 夹具与用例、本 change 下的 evidence/文档。该文件里其余未提交差异属本工作区既有 inspector/handoff 改动，本次未触碰。

## 1.2 调用顺序复核（实施前记录）

1. `create_digit_mode(digit)`（`label_widget.py:5734`）：校验数字映射与 `create_mode`；`canvas.current` 或 `rectangle_creation.draft` 存在时忽略；有可编辑选中对象时走 `_relabel_selection`；否则 `digit_to_label = label` 并 `toggle_draw_mode(edit=False, create_mode=...)`。
2. `toggle_draw_mode(edit=False)`（`:5792`）：先经 `rectangle_creation.before_tool_change`；关闭 brush/magic wand；`disable_auto_labeling=True` 时清理自动标注标记并置 `AutoLabelingMode.NONE`；`canvas.set_editing(False)`、设置 `canvas.create_mode`。
3. 画布两次点击完成几何后 `Canvas.finalise()`（`widgets/canvas.py:5561` 起）把 `current` 追加进 `shapes` 并 `new_shape.emit()`。
4. `LabelingWidget.new_shape()`：确定类别 → `validate_label` → 属性处理 → `canvas.set_last_label` / `label_list` 登记 → `add_label` → `set_dirty()`；`set_dirty()`（`:3621`）在 `auto_save` 时立即 `save_labels()` 并清 dirty，否则置 dirty 等待 Ctrl+S。
5. `finalise()` 返回后，鼠标释放继续执行 `mode_changed.emit()`（`canvas.py:3446–3451`，仅在非自动标注且无 `current` 时），经“自动切回编辑模式”应用器调用 `set_edit_mode()` → `toggle_draw_mode(edit=True)`。**该步骤晚于 `new_shape()`**，所以绑定必须在 `new_shape()` 内消费，不能依赖模式切换顺带清理。
6. 分支边界：自动标注 `AUTO_LABEL_ADD/REMOVE` 标记最先判定（保留原语义，且不消费绑定）；`AutoLabelingMode.OBJECT` 只影响是否进入弹窗分支；无 `digit_to_label` 时完整保留预选值/复用上次类别/弹窗原规则。`rectangle_creation.continue_drawing()` 会主动写 `owner.digit_to_label = _last_label`，属“本次绘制的绑定”，同样按新优先级生效。

## 测试改动

- 移除 4 项严格 xfail（`selected_label and not popup`），保留原断言与 16 组合参数化。
- 新增端到端回归（真实主窗口、真实按键/鼠标、真实 JSON 与重载）：
  - `test_digit_binding_is_consumed_by_the_completed_rectangle`：预选其他类别 + 弹窗关闭完成数字矩形后，`digit_to_label is None`、画布/JSON 为绑定类别，随后普通绘制使用预选类别。
  - `test_last_label_reuse_cannot_override_digit_binding`：`auto_use_last_label` 开启且上次类别不同，数字键完成后仍为绑定类别。
- 新增单元级相邻验证（以最小宿主绑定真实 `LabelingWidget.new_shape`）：
  - `test_binding_precedes_preselected_class_without_popup`（核心缺陷的单元镜像）；
  - `test_ordinary_creation_without_binding_uses_preselected_class`（无绑定普通绘制不变）；
  - `test_auto_labeling_special_mark_outranks_the_digit_binding`（自动标注 ADD 标记优先且不消费绑定）。

## 红/绿证据

红（原实现 + 新测试，`6 failed, 25 passed`）：

```
FAILED ...test_digit_rectangle_save_roundtrip[True-False-False-True]
FAILED ...test_digit_rectangle_save_roundtrip[True-False-False-False]
FAILED ...test_digit_rectangle_save_roundtrip[True-False-True-True]
FAILED ...test_digit_rectangle_save_roundtrip[True-False-True-False]
FAILED ...test_digit_binding_is_consumed_by_the_completed_rectangle
FAILED ...test_binding_precedes_preselected_class_without_popup
```

失败断言分别是 `assert '其他类别' == '车辆'`（矩形类别被预选覆盖）与 `assert '车辆' is None`（绑定未被消费）。

绿（修复后）：`31 passed in 86.66s`；复核阶段强化 0–9 用例断言后重跑为 `31 passed in 86.47s`。最终确认运行（实现与测试定稿后一次运行本文件 + `test_digit_label_actions.py` + `test_label_file_save.py` + `tests/test_settings/test_digit_shortcut_flow.py`）：**53 passed in 84.67s**。16 种组合（自动/手动保存 × 同目录/输出目录 × 弹窗开/关 × 有/无预选）全部正常通过，无 XFAIL/XPASS；0–9 每个数字键用例均核对真实 JSON 的 `label=车辆`、`shape_type=rectangle`、四点顶点、`imageWidth=200`/`imageHeight=160`，并 `load_file()` 重载核对类别与坐标。

## 相邻回归

| 目标 | 结果 |
| --- | --- |
| `tests/test_labeling/test_digit_rectangle_save.py` | 31 passed |
| `tests/test_labeling/test_digit_label_actions.py` + `test_label_file_save.py` + `tests/test_settings/test_digit_shortcut_flow.py` | 22 passed |
| `tests/test_labeling/test_canvas_display_retention.py` | 26 passed |
| `tests/test_labeling/test_classification_flags.py` | 3 passed, 4 subtests |
| `tests/test_labeling/test_image_tags.py` | 16 passed, 2 subtests |
| `tests/test_labeling/test_label_widget_brush_mode.py` | 8 passed |
| `tests/test_canvas/test_rectangle_extreme_creation.py` | 13 passed |
| `tests/test_canvas/test_magic_wand.py` | 9 passed |
| `tests/test_auto_labeling` | 52 passed, 3 失败（均为环境：符号链接特权、临时文件 0600 权限，见上） |

## 3.5 真实主窗口离屏验收

脚本：[evidence/verify_digit_rectangle_ui.py](evidence/verify_digit_rectangle_ui.py)，原始输出：[evidence/ui-acceptance-20261110.txt](evidence/ui-acceptance-20261110.txt)。四个场景（自动保存/Ctrl+S × 图片同目录/独立输出目录）均为：预选其他类别 + 关闭弹窗 + 数字键 3 + 两次真实鼠标点击 → 真实 JSON 与重载断言 → `PASS`，合计 `4 passed, 0 failed`。这是离屏真实控件链路，不是人工可见屏幕观察。

## 交付前对抗式复核（2026-11-10）

按“假设交付不满足规格”逐维核对，记录两条真实发现与若干确认项：

1. **发现并已修复**：`test_every_digit_can_save_a_rectangle` 原本只断言类别与矩形类型，未覆盖规格中“0–9 数字键的顶点、图片尺寸与重载一致”。已把四个顶点、`imageWidth/Height`、`load_file()` 重载类别与坐标、无错误弹窗补入该用例，重跑仍 `31 passed`。这是测试增强，不涉及实现改动。
2. **确认项（有意保留）**：绑定在 `new_shape()` 读取时即清除，因此若 `validate_label` 拒绝绑定类别，本次绑定不会保留到下一次绘制。这与修复前语义一致（原实现同样在读取时清除），且失败的绘制本身不会写入错误类别；规格中的“成功创建后消费”以“本次绘制使用该绑定”为准，未额外引入延迟清除逻辑。
3. **确认项（行为范围）**：该分支位于所有绘制模式的公共完成路径，数字键启动的多边形、点、旋转框等创建同样按新优先级取类别；这与设计文档“普通绘制存在待应用绑定时优先采用并消费该绑定”一致，未扩大到状态机重构。
4. **确认项（非目标）**：未改 JSON 格式、保存机制、数字映射持久化；未批量重写历史 JSON；未新增绑定生命周期功能。

## 剩余问题与边界

- 未做人工可见屏幕验收；如需真实屏幕确认，需用户在有显示环境操作一次。
- 未运行全项目测试；`tests/test_labeling` 目录整体运行仍被上文第 3 条约 20 个旧夹具的模态框挂起阻塞（与本变更无关，未扩大范围修复）。
- 不根据既有 JSON 猜测并批量修正历史错存类别；JSON 格式、保存机制、数字映射持久化均未改动。
- 取消绘制、切图、切换图片时残留绑定的生命周期问题未在本轮定义或修复；新解析下任何一次完成的形状都会消费绑定，不再跨绘制遗留。

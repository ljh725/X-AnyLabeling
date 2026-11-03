# Inspector 检查与复核工作流实施报告

日期：2026-11-02（Asia/Shanghai）
分支：`codex/refactor-data-inspector-workflow`
实施前基线：`9a37c5474c390e93243e33a88e8232a19c833280`
状态：实施中；自动化测试通过，人工试用与部分交付项未完成。实现尚未提交 Git。

## 备份

- 分支/标签：`backup/refactor-data-inspector-workflow-20261102`
- 基线提交：`9a37c547`；父提交 `1038d555` 保存实施前未提交的 `resources.py` 与四语种 `.qm`
- 远端核验：`git ls-remote origin` 返回分支和标签剥离提交均为 `9a37c547`
- 恢复：`git clone --branch backup/refactor-data-inspector-workflow-20261102 https://github.com/ljh725/X-AnyLabeling.git <目录>`

## 环境

- 解释器：`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`
- Python 3.12.12；PyQt6 6.10.2；Qt 6.10.0
- 测试平台：`QT_QPA_PLATFORM=offscreen`（Windows）
- 静态检查：flake8 `--max-line-length=79 --max-complexity=18`；新模块通过 Black（line length 79）

## 已实现

### 纯 Python 服务 `anylabeling/services/inspection/`

- `models.py`：版本化 profile、manifest、file/shape 快照、issue/evidence/location、coverage、run report、feedback/session、candidate 数据契约；人工判断、动作、机器验证三轴独立。
- `duplicate.py`：从 beta4 迁移几何指标、阈值、空间索引、全扫与增量核心；取消返回显式 `cancelled`，不再以空 pairs 表示成功；保留 L2-13 同组边缘规则。
- `rules.py`：标签必填、形状类型绑定、坐标点数量、分组必填、矩形几何、疑似重复框、L2-13、四角点完整性、课堂动作关系、成组完整性、数量约束；场景例外和不可评估状态显式记录。
- `profiles.py`：规则目录与实现版本、通用/屏幕/课堂三套模板、schema/阶段/未知规则/关系冲突校验、复制、导入导出、冻结配置快照。
- `manifest.py`：完整数据集清单、输出目录隔离、缺失/损坏 JSON、内容摘要、持久身份核验与只读临时身份、内存快照、已变更文件比较。
- `runner.py`：四种范围、逐文件逐规则 coverage、后台可取消、completed/partial/cancelled/failed 终态、问题族证据合并、问题上限截断。
- `storage.py`：原子 JSON 写入、report + manifest sidecar、feedback/session revision 与排他锁、冲突副本、项目方案绑定。
- `importers.py`：旧 TSV/CSV/JSON 导入、路径歧义报告、完整 JSON 导出与简化 TSV、本格式往返。
- `candidates.py`：外部候选类别/坐标/尺寸校验、来源隔离、接受意图与重复接受保护。
- `handoff.py`：普通画布回退、五维完成状态、密集复核不可用的诚实说明。
- `verification.py`：恢复报告时核验当前标注/图片摘要、文件清单、对象身份、方案冻结配置和规则实现版本；变化时标记过期，不把旧人工结论计为当前已处理。

### Inspector UI `anylabeling/views/labeling/inspector/`

- 非模态入口：方案、阶段、范围、运行历史、开始/取消、进度与状态。
- 问题队列：风险/规则/文件/对象或区域/机器状态/人工判断；筛选、上一个/下一个、定位。
- 人工动作：误报、可接受、需讨论、确认错误、标记已修改、删除选中框、重标、复查当前图。
- 画布编辑、撤销、删除信号会将相关文件的问题标记为待复查。
- 方案复制、导入、导出；报告 JSON/TSV 导出；旧问题导入；候选导入、接受、拒绝、暂存。
- 继续上次处理与运行历史加载；反馈/会话/绑定持久化。

### 主窗口接入

- `label_widget.py`：Workflow 菜单新增 Inspector；当前图内存快照、数据集/选中文件路径、稳定身份导航、删除/重标、候选接受均走现有画布和编辑链路。
- 入口默认不由配置自动打开；关闭 Inspector 不改变原有画布流程。

## 评审问题修复（2026-11-02）

1. **删除只作用于画布当前选中对象**：删除和重标按钮在无选中对象时禁用；操作只提交当前画布中选中且属于该问题、未锁定的对象，确认框列出精确 ID 集合，不再默认删除整对对象。新增 `test_delete_only_removes_canvas_selected_issue_object`。
2. **恢复报告核验当前上下文**：新增 `verify_report_context()`；恢复时比对当前标注/图片摘要、文件清单、对象身份、数据集/输出根、方案冻结配置和规则实现版本。变化时问题机器状态改为 `stale`，不计入当前已处理，并显示原因；过期问题拒绝直接记录新人工结论，需先复查或重新运行；缺少历史清单时全部不可核验。新增 `test_resume_marks_changed_annotation_as_stale` 和 4 项 `test_verification.py` 用例。
3. **运行尊重当前方案选择**：绑定只在首次进入项目或项目切换时恢复；用户显式选择过方案后，启动不再被旧 binding 覆盖。新增 `test_run_respects_profile_selected_after_binding`。
4. **manifest 读取失败纳入范围与终态**：`load_file_snapshot()` 对非数值 `imageWidth/imageHeight` 返回显式 error 快照；运行器把 `manifest.errors` 计入请求文件、失败文件、coverage 和 `partial` 终态。新增 `test_manifest_error_counts_as_requested_and_failed` 与 `test_invalid_dimensions_are_kept_as_failed_file`。
5. **恢复报告纳入未保存画布内容**：`FileSnapshot` 增加规范化 shape 摘要；`verify_report_context(..., memory_files=...)` 同时比较当前内存快照与磁盘。未保存修改标为 `pending_recheck`，磁盘/配置变化标为 `stale`；磁盘版本报告在当前画布移动框但未保存时重新恢复，不会再回到 `CURRENT`。新增 `test_resume_keeps_unsaved_canvas_edit_pending` 及 4 项内存/磁盘对照用例。

## 自动化证据

| 测试/检查 | 命令 | 结果 |
| --- | --- | --- |
| 新增服务与 GUI | `python -m pytest tests/test_inspection -q ...` | **80 passed** |
| 定向 labeling | `tests/test_labeling/test_check_status.py`、`test_editing_command_scope.py`、`test_batch_edit_fields.py` | **25 passed, 11 subtests passed** |
| labeling 全量 | `python -m pytest tests/test_labeling -q ...` | **192 passed, 8 failed**, 45 subtests passed |
| canvas | `python -m pytest tests/test_canvas -q ...` | **543 passed, 1 failed**, 83 subtests passed |
| widgets | `python -m pytest tests/test_widgets -q ...` | **29 passed, 3 failed**, 2 subtests passed |
| settings | `test_schema.py`、`test_controller.py` | **20 passed** |
| 分阶段加载 | `test_staged_annotation_metadata.py`、`test_staged_output_window.py` | **32 passed** |
| utils/config | `python -m pytest tests/test_utils tests/test_config -q ...` | **85 passed, 8 skipped**, 28 subtests passed |
| OpenSpec | `openspec validate refactor-data-inspector-workflow --strict` | 通过 |
| 静态检查 | flake8 / Black / `git diff --check` | 通过 |

JUnit 原始文件：`inspection.xml`、`labeling-targeted.xml`、`labeling.xml`、`canvas.xml`、`widgets.xml`、`settings.xml`、`staged.xml`、`utils-config.xml`。

评审问题修复后，已重新运行 `tests/test_inspection`（80 passed）和定向 labeling（25 passed, 11 subtests passed）；其余回归数据来自实施阶段，修复仅触及新增 inspection 模块与 Inspector 对话框，未改既有画布/加载代码。

### 既有失败（不是本次新增）

以下失败在实施前基线 worktree（`9a37c547`）复跑结果相同：

- `tests/test_canvas/test_groups.py::TestCanvasGroups::test_shape_label_keeps_fixed_screen_size_while_zooming`（179 != 139）
- `tests/test_widgets/test_canvas_adjustment.py::TestCanvasAdjustmentWidget::test_brightness_contrast_updates_are_throttled`（0 != 1）
- `tests/test_widgets/test_toolbar_layout.py::TestToolBarLayout::test_first_tool_button_stays_inside_vertical_toolbar`（26 < 28）
- `tests/test_widgets/test_toolbar_layout.py::TestToolBarLayout::test_scaled_buttons_fit_after_actions_are_rebuilt`（39 != 42）
- labeling 全量的 8 项失败（SimpleNamespace 缺方法、Windows 路径断言、临时文件权限）也在基线 worktree 相同复现。

### 重复框核心对照

`duplicate_core_comparison.json`：beta4 来源提交 `b45af4adcbbfb13d4ae1fcffa04afe5678b463e0`；160 个有效矩形、3 组预设、38,160 对指标比较：

- 指标最大绝对差：`0.0`
- 分级不一致：`0`
- 全扫候选对集合不一致：`0`

## 未完成 / 未验证

- 方案改名、编辑和停用；批量删除、按类别批量重标预览；i18n `.ts/.qm` 生成与快捷键配置（任务 3.3、6.6、6.7）。
- 编辑提交后的逐次增量结果更新目前以“标记待复查 + 用户触发复查”实现；增量核心已有测试，但未接到每次 mouse/edit 热路径（任务 4.5）。
- 报告分批写入、写入失败另选目录的完整 UI 测试；性能/取消时延实测（任务 5.6、5.7）。
- 候选独立覆盖层、批量接受、接受后撤销关联恢复（任务 8.3–8.5）。
- 有密集复核环境下的交接、返回位置和双方失效联动（任务 9.3）。
- 两位使用者 30–50 张样本试用、独立质量复核和用户操作说明（任务 10.3–10.5）。
- 本报告不把“问题清零”或自动测试通过表述为整库无漏标或人工验收通过。

## 回退

实现尚未提交。回退时：

1. 删除新增目录 `anylabeling/services/inspection/`、`anylabeling/views/labeling/inspector/`、`tests/test_inspection/`。
2. 还原 `label_widget.py` 的菜单/方法改动，以及本报告、台账和清单改动。
3. 删除数据目录下的 `.xanylabeling/inspection/`（报告/反馈/会话 sidecar）；不要改写原标注 JSON。
4. 若后续拆分提交，按逆序 revert 本功能提交；保留独立报告和配置作为历史证据。

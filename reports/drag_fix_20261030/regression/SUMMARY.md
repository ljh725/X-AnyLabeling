# CUSTOM-003 全量回归证据

日期：2026-10-30。对应 OpenSpec tasks 1.3 / 4.1。配套实施说明见 [REPORT.md](../REPORT.md)。

本目录保存可核验的原始日志、JUnit XML、失败 node ID 与差集，供复核"改后 11 失败 / 基线 12 失败"这一说法，而不是只给分类摘要。

## 环境与命令

- Python 3.12.12（`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`），Qt 6.10.0，PyQt 6.10.2，pytest 9.0.3。
- 修复后树：`D:/X-AnyLabeling-4.2.1`，分支 `codex/smooth-canvas-dragging`。
- 基线树：`git worktree` 独立检出 `backup/pre-drag-fix-20261030`（提交 `d4c7256e`），基线不含本功能新增的 3 个测试文件。
- 命令（两树完全相同，仅工作目录与输出名不同）：

```bash
QT_QPA_PLATFORM=offscreen <python> -m pytest \
  tests/test_canvas tests/test_labeling tests/test_widgets \
  tests/test_staged_annotation_metadata.py tests/test_staged_output_window.py \
  -p no:cacheprovider -q --tb=no -rfE --color=no \
  --junitxml=reports/drag_fix_20261030/regression/core_<label>.xml \
  > reports/drag_fix_20261030/regression/core_<label>.log 2>&1
```

原始命令另见 `command_fixed.txt`；扩展范围见下文"扩展范围"。

## 核心范围结果

| 树 | pytest 汇总 | 用例级失败 | 子测试失败 |
|---|---|---:|---:|
| 修复后 | 11 failed, 682 passed, 130 subtests | 9 | 2 |
| 基线 | 12 failed, 660 passed, 130 subtests | 10 | 2 |

`N failed` 与用例数不一致，是因为 `test_upload_preserves_auto_switch_signal_state` 的两个 unittest 子测试各计一条失败（两树都出现，`SUBFAILED` 记录在日志中）。差额 21 项通过来自本功能新增的 21 个测试。

**差集（`failure_diff.txt`）**

- 仅修复后失败：**无**。
- 仅基线失败：`tests/test_widgets/test_canvas_adjustment.py::TestCanvasAdjustmentWidget::test_brightness_contrast_updates_are_throttled`。
- 两树共有（既有失败）9 项，全部为标签/属性面板、视频流、工具栏布局、缩放标签尺寸等与本功能无关的用例；清单见 `failures_fixed.txt`、`failures_baseline.txt`。

**稳定/间歇判定（`flaky_matrix.md`）**

把两树失败并集（10 项）各重复运行两轮：

| 结果 | 数量 | 说明 |
|---|---:|---|
| 四轮均失败 | 9 | 稳定既有失败 |
| 部分轮次通过 | 1 | `test_brightness_contrast_updates_are_throttled`，隔离运行时在基线第二轮通过，属负载敏感用例 |

原始四份日志：`rerun_fixed_1.log`、`rerun_fixed_2.log`、`rerun_baseline_1.log`、`rerun_baseline_2.log`。

## 扩展范围

其余可稳定运行的目录，两树命令相同：

```bash
QT_QPA_PLATFORM=offscreen <python> -m pytest \
  tests/test_auto_labeling tests/test_auto_training tests/test_config \
  tests/test_models tests/test_ppocr tests/test_utils tests/test_updates \
  tests/test_ui_density_extremes_repair.py \
  -p no:cacheprovider -q --tb=no -rfE --color=no \
  --junitxml=.../extra_<label>.xml > .../extra_<label>.log 2>&1
```

| 树 | 结果 |
|---|---|
| 修复后 | 5 failed, 466 passed, 29 skipped, 34 subtests |
| 基线 | 5 failed, 466 passed, 29 skipped, 34 subtests |

失败 node ID 逐条一致（`extra_failures_fixed.txt` 与 `extra_failures_baseline.txt` 的 `diff` 为空），5 项分别属于远程推理类别过滤、训练数据集/环境/进程停止，与本功能无关。

## 未纳入对比的目录

| 目录 | 现象 | 证据 |
|---|---|---|
| `tests/test_pointcloud` | 进程崩溃（Windows access violation / 退出码 127、139），无法产出完整结果 | `crash_probe/fixed_file_test_cuboids.log`（`test_cuboid_drag_stops_at_subview_boundary`，test_cuboids.py:1552）；同文件同用例在基线树同样崩溃。`test_perspective.py`、`test_ui_details.py` 同样崩溃，`test_export_dialog.py` 300 s 超时 |
| `tests/test_settings` | 设置对话框用例令解释器崩溃，逐条 deselect 后仍在下一个对话框用例崩溃 | `crash_probe/settings_fixed.log`；`test_canvas_label_font_size_editor_uses_supported_range` 在两个树上都复现同一退出 |

这两个目录是离屏环境下的 3D 视图/模态对话框问题，与本次只改状态栏文本和画布刷新请求无关；本次不修改它们，也不把它们的崩溃计入本功能回归结论。需要时可另立变更处理离屏环境兼容性。

## 结论

在可稳定运行的核心与扩展范围内，修复后相对基线**没有新增失败**：9 项稳定既有失败 + 1 项负载敏感用例 + 5 项扩展范围既有失败，全部在两树上同样出现。新增的 21 个测试全部通过。环境性崩溃的两个目录未纳入，并已单列证据，不作为"通过"计入。

## 文件说明

| 文件 | 内容 |
|---|---|
| `core_fixed.log` / `core_fixed.xml` | 修复后核心范围原始输出与 JUnit |
| `core_baseline.log` / `core_baseline.xml` | 基线核心范围原始输出与 JUnit |
| `failures_fixed.txt` / `failures_baseline.txt` | 用例级失败 node ID |
| `failure_diff.txt` | 差集与计数口径 |
| `flaky_matrix.md` | 四轮重复运行矩阵 |
| `extra_*.log/xml`、`extra_failures_*.txt` | 扩展范围结果 |
| `crash_probe/` | 崩溃证据：`fixed_file_test_cuboids/perspective/ui_details/export_dialog.log`（access violation 或超时）、`settings_fixed.log`、逐文件退出码 `fixed_exitcodes.txt`、批次运行日志 `cloud_fixed.log` |
| `run_regression.sh`、`run_dir_files.sh`、`diff_logs.py`、`compare_failures.py` | 复跑与解析脚本 |

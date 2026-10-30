# CUSTOM-003 实施结果：大数据集拖动响应

日期：2026-10-30。对应 OpenSpec：[smooth-canvas-dragging](../../openspec/changes/smooth-canvas-dragging/design.md)。问题定位见 [REAL_DATA_REPORT_20261030](../drag_diagnosis_20261029/REAL_DATA_REPORT_20261030.md)。

本文件记录**已实施**的代码、测试与实测数据。所有数字为本机同环境对照，不是任意硬件的帧率保证。

> 2026-10-30复核与补证：复核提出三项证据缺口（全量回归失败集合、固定生效配置、人工体验），本轮已补齐——回归补了逐项 node ID、原始日志与差集（仅修复后失败 0 项，见 [regression/SUMMARY.md](regression/SUMMARY.md)）；性能用固定生效配置快照复跑（§3.1，门槛 7 项全通过）；可见窗口拖动由用户人工确认无异常。复核意见见 REVIEW-20261030.md，最终结论见 CUSTOM-003 台账。

## 1. 改了什么

| 文件 | 位置 | 改动 |
|---|---|---|
| `anylabeling/views/labeling/label_widget.py` | `show_shape` | 删除每次鼠标移动的两遍 `image_list` 构建（`len()` + `in`）。合并两组文本完全相同的分支，只保留整数坐标/宽高和无图不更新行为 |
| `anylabeling/views/labeling/widgets/canvas.py` | `mouseMoveEvent` | 移动前的 `repaint()` 改为 `update()`；普通矩形整体拖动、顶点拖动、立方体面拖动的 5 处移动后 `repaint()` 改为 `update()`，由事件循环合并为一次绘制 |

未直接修改普通鼠标释放的 `mouseReleaseEvent() → store_moving_shape()` 提交链路，以及右键复制/移动的 `end_move()`。边拖动、旋转、绘制预览、右键复制和平移的独立分支调用保持原样，但共用的前置刷新已改变，仍需相邻交互回归。

## 2. 绘制请求计数（同一脚本，两棵源码树）

`probe_paints.py`：仅给 `Canvas.paintEvent` 套计数包装，原绘制照常执行。5 次移动为一组：

| 场景 | 修复前 | 修复后 | 几何结果 |
|---|---:|---:|---|
| 矩形整体拖动（不插入事件循环） | 10 | 1 | 一致 (105,105,205,205) |
| 矩形整体拖动（每次 processEvents） | 10 | 5 | 一致 |
| 顶点拖动（不插入事件循环） | 10 | 1 | 一致 (95,95,200,200) |
| 创建矩形预览 | 10 | 5 | 预览终点一致 (65,65) |
| 悬停空白处 | 5 | 1 | — |
| 悬停图形 | 6 | 1 | — |
| 边拖动 | 5 | 5 | 一致（未改该分支） |

普通拖框路径由每次移动 2 次同步完整重绘降为 1 次，几何与预览终点不变。

## 3. 真实 PRW 基准（11792 张 / 54 对象）

`benchmark_drag_fix.py`：使用**已修改的生产方法**，未替换状态栏槽、未 monkeypatch `repaint`。仅对 `paintEvent` 与 `image_list` 属性做计数包装（仍调用原实现）。一次样本 = `sendEvent` + 一次 `processEvents`，包含移动帧的事件队列处理。

环境：Python 3.12.12、Qt 6.10.0、PyQt 6.10.2、离屏窗口 2560×1377、用户显示配置、自动保存关闭、数据集目录由审计钩子禁写。两轮随机顺序，每条件每轮 100 次移动。

| 后台状态 | 修复后中位数 | 修复后 P95 | 修复前中位数 | 修复前 P95 | 中位数改善 |
|---|---:|---:|---:|---:|---:|
| 全部结束 | 10.38 / 10.86 | 11.61 / 15.29 | 42.34 / 42.14 | 44.00 / 44.44 | 75.5% / 74.2% |
| 仅 EXIF | 10.83 / 11.03 | 13.68 / 14.76 | 43.16 / 44.26 | 46.84 / 50.69 | 74.9% / 75.1% |
| 仅审核首次回填 | 11.09 / 12.20 | 17.12 / 20.91 | 43.31 / 42.84 | 49.87 / 48.59 | 74.4% / 71.5% |
| 审核 + EXIF | 11.86 / 14.37 | 19.36 / 24.59 | 43.94 / 43.71 | 54.38 / 52.38 | 73.0% / 67.1% |

（单元格为两轮各自的中位数 / P95，单位 ms。）

- 每 100 次移动：修复前 200 次 `paintEvent`、200 次 `image_list` 读取；修复后 100 次、0 次。
- 列表规模对照（同图同 54 对象）：1 / 1000 / 11792 条目修复后 10.66 / 10.92 / 10.74 ms，极差 0.27 ms（门槛 ≤3 ms）；修复前 20.92 / 22.58 / 47.21 ms。
- 处理函数本身：修复后 0.17–0.43 ms 中位数，绘制与后台竞争体现在周期时间上。

验收门槛（design.md §3）：无后台中位数 ≤15 ms、P95 ≤25 ms、改善 ≥60%；审核/同时中位数 ≤25 ms、P95 ≤40 ms；规模差 ≤3 ms 且零全列表读取。**本轮全部达到**。

### 3.1 第二轮：冻结生效配置快照（tasks 4.5）

第一轮只记录了用户配置**路径**，不能证明两树当时读到同一份生效配置。补跑把合并后的生效配置（模板 + 用户配置 + 基准覆盖项 `auto_save=False`、`keep_prev=False`）序列化为快照，两树加载同一文件，且不改写第一轮样本：

- 快照 `config_snapshot_20261030.json`：61 个生效键，SHA256 `facd7cfe7dce50bc7eb457caaf3d6977f30ca0dc24eaccb578c965577c7e8ccf`，两树逐字节一致。
- 解释器 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`（Python 3.12.12）；脚本 SHA256、`argv`、解释器路径写入 `results_fixed_r2.json` / `results_baseline_r2.json` 的 `script_sha256`、`argv`、`interpreter` 字段。
- 第一轮产物保留为 `results_fixed.json` / `results_baseline.json`；补跑写 `*_r2.json` 与 `summary_r2.md`。

| 后台状态 | 修复后中位数 | 修复后 P95 | 修复前中位数 | 修复前 P95 | 中位数改善 |
|---|---:|---:|---:|---:|---:|
| 全部结束 | 11.27 / 11.27 | 13.83 / 14.31 | 44.53 / 44.56 | 55.39 / 56.23 | 74.7% / 74.7% |
| 仅 EXIF | 11.32 / 13.16 | 17.04 / 17.46 | 43.87 / 48.46 | 58.49 / 60.76 | 74.2% / 72.8% |
| 仅审核首次回填 | 12.07 / 11.82 | 19.76 / 21.16 | 48.07 / 45.60 | 60.55 / 61.24 | 74.9% / 74.1% |
| 审核 + EXIF | 14.14 / 14.20 | 21.05 / 21.50 | 48.15 / 49.35 | 58.64 / 59.70 | 70.6% / 71.2% |

- 列表规模 1 / 1000 / 11792：修复后 11.87 / 9.92 / 10.04 ms（极差 1.95 ms ≤3）；修复前 21.57 / 23.15 / 51.22 ms。
- 每 100 次移动：绘制 100 次、`image_list` 读取 0 次（修复前 200 / 200）。
- 门槛全部满足：无后台中位数 11.27 ≤15、P95 14.31 ≤25、改善 74.7% ≥60%；审核/同时中位数 ≤14.20 ≤25、P95 ≤21.50 ≤40。
- 两轮同条件中位数差 0.9–2.3 ms（本机噪声），第二轮整体偏慢 1–2 ms，仍有余量；结论方向一致。

## 4. 测试

新增 21 个测试，均在离屏 Qt 下运行：

| 文件 | 数量 | 覆盖 |
|---|---:|---|
| `tests/test_labeling/test_show_shape_status.py` | 7 | 用`访问即失败`的 `image_list` 属性质替身，覆盖空列表、当前图不在列表、11792 条目、有效/无效尺寸、无图保持原文本 |
| `tests/test_canvas/test_drag_refresh.py` | 11 | 真实 press/move/release：合并绘制、逐次绘制、释放后末帧、顶点拖动、边界裁剪、越界不动、锁定、多选、撤销、悬停刷新、创建预览 |
| `tests/test_labeling/test_drag_commit.py` | 3 | 自动保存只在释放触发一次、撤销可用且恢复拖动前几何、保存后重开坐标一致 |

反向验证：把三个测试文件原样放到修复前源码树运行，`test_show_shape_status.py` 7 项全失败（读取全列表），`test_drag_refresh.py` 4 项合并绘制断言失败（`10 != 1`、`10 != 5`），`test_drag_commit.py` 3 项通过（提交时机本应不变）。说明测试确实约束本次改动，而不是无条件通过。

回归证据：[regression/SUMMARY.md](regression/SUMMARY.md)（原始日志、JUnit XML、失败 node ID、差集、四轮稳定性矩阵）。

| 树 | 结果 | 用例级失败 | 子测试失败 |
|---|---|---:|---:|
| 修复后 | 11 failed, 682 passed, 130 subtests | 9 | 2 |
| 基线 | 12 failed, 660 passed, 130 subtests | 10 | 2 |

- 差集：仅修复后失败 **0 项**；仅基线失败 1 项（`test_brightness_contrast_updates_are_throttled`，负载敏感）；两树共有 9 项用例级 + 2 条子测试失败。
- 失败并集重复两轮：9 项稳定失败、1 项间歇，未出现新增失败。
- 扩展范围（auto_labeling、auto_training、config、models、ppocr、utils、updates、ui_density）：两树均 5 failed / 466 passed，失败 node ID 逐条一致。
- `tests/test_pointcloud`、`tests/test_settings` 在本机离屏环境崩溃（access violation），未纳入对比；证据与两树复现见 `regression/crash_probe/`。

`openspec validate smooth-canvas-dragging --strict` → `Change 'smooth-canvas-dragging' is valid`。

## 5. 未完成 / 限制

- 4.4 可见窗口人工拖动体验：用户于 2026-10-30 在可见窗口实际拖动并反馈无异常；这是人工确认，不是本次离屏计时，未记录帧率。
- 审核条件测量的是首次回填进行中的 100 次移动，未覆盖回填完成后的长时间稳定态。
- 后台回填本身仍带来约 1–3 ms 增量（11.09→11.86、12.20→14.37），属设计已知的剩余负担，本轮不处理调度。
- 性能数字为本机（同机同 Qt）对照；换硬件、换显示缩放需重测。两轮同条件差 0.9–2.3 ms，属本机噪声。
- `tests/test_pointcloud`、`tests/test_settings` 在本机离屏环境进程崩溃，未纳入回归对比，不计为通过。

## 6. 复测方法

```bash
# 第二轮（冻结同一生效配置；先跑修复后生成快照，再在基线检出复用同一文件）
python reports/drag_fix_20261030/benchmark_drag_fix.py --label fixed_r2 \
  --out results_fixed_r2.json --moves 100 --rounds 2 \
  --config-snapshot config_snapshot_20261030.json
python reports/drag_fix_20261030/benchmark_drag_fix.py --label baseline_r2 \
  --out results_baseline_r2.json --moves 100 --rounds 2 \
  --config-snapshot config_snapshot_20261030.json
python reports/drag_fix_20261030/summarize.py results_fixed_r2.json results_baseline_r2.json summary_r2
```

第一轮未冻结快照时的命令为去掉 `--config-snapshot` 的同名脚本调用，产物即 `results_fixed.json` / `results_baseline.json`。

产物：`results_fixed.json` / `results_baseline.json`（第一轮）、`results_fixed_r2.json` / `results_baseline_r2.json`（冻结配置补跑）、`config_snapshot_20261030.json`、`summary.md`、`summary_r2.md`、`probe_paints.py`、`regression/`。

## 7. 回退

只撤销本功能时，按相反顺序 revert 状态栏与绘制两个实现提交（提交说明含 CUSTOM-003）。不要 revert 实施前基线，也不要用 `reset --hard` 清除其他工作。详细恢复方式见 [BACKUP-20261030.md](../../docs/custom_changes/BACKUP-20261030.md)。

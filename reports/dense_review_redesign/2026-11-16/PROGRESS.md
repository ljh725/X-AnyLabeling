# 密集复核重设计：实施进度与验证记录

本文件记录 `redesign-dense-review-workspace` 的实施批次、验证命令、退出码与未覆盖项。
规格依据见 `openspec/changes/redesign-dense-review-workspace/`，验收矩阵见其 `acceptance.md`。

- 工作分支：`codex/4.2.1/dense-review-redesign-plan`
- 集成目标：`codex/4.2.1-baseline-organization`
- 实施起点（备份标签）：`pre-dense-review-redesign` = `37c4679b`（指向提交 `052239f2`）
- 环境：conda `x-anylabeling-cu12`，Python 3.12.12，PyQt6 6.10.2 / Qt 6.10.0，Windows
- 测试入口：`tests/conftest.py` 强制 `QT_QPA_PLATFORM=offscreen`，配置与 `QSettings` 重定向到 `.tmp/`

## 验证口径

`tests/test_dense_review` 全目录在本机约需 140–170 秒，因此按 AGENTS.md
「Qt 集成测试防挂起」约定，使用外层硬超时包装器并在 pytest 侧开启
`faulthandler_timeout`，便于在挂起时保留用例名与堆栈：

```bash
python .tmp/hard_timeout.py <秒> -q -o faulthandler_timeout=60 <目标> \
    -p no:randomly --basetemp=.tmp/pt-<名称>
```

单项关闭随机顺序（`-p no:randomly`）以便横向比对同一批次的通过数。

## 基线既有失败（不属于本变更）

开工前实测，`pre-dense-review-redesign` 起点即存在以下失败，之后各批次保持不变：

| 用例 | 现象 |
| --- | --- |
| `tests/test_dense_review/test_workspace_evidence.py::test_closed_workspace_keeps_shift_fit_target_and_undo[False]` | 单点拟合后 `bounding_rect()` 未变化 |
| 同上 `[True]` | 同上 |

分类：既有缺陷，未在本次修复，也未因本次改动新增失败。

## 批次 1 · `bf75b13f` 列表启用与滚动（任务组 1–2）

改动：空状态禁用的批次/卡片/区域列表在会话恢复时按实际内容重新启用；
区域动作随区域计划就位。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_workspace_lists.py` | 4 passed，新增 |
| `tests/test_dense_review` 全目录 | 144 passed，2 项基线失败 |
| 覆盖场景 | WL-05 空状态到有效会话、WL-06 会话切换、OC-16 滚轮/滚动条与后台刷新不回滚 |
| 未覆盖 | 真实鼠标滚轮物理事件（使用合成 `QWheelEvent`，仍属离屏） |

修复前对照：同一批测试在旧实现上 3 failed，确认断言有效。

## 批次 2 · `3b09eefd` 显示解析纯数据层（任务组 3 前半）

改动：新增 `services/dense_review/display.py`，按当前/本批/其他角色输出
填充、描边、点、手柄、文字、属性、连线、遮罩强度，默认填充为零；
同一结果同时给出可绘制与可命中；排除原因可读。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_display_policy.py` | 14 passed，新增 |
| 覆盖场景 | DP-01 三角色分级、DP-02 零强度退出命中、DP-11/DP-12 优先级、DP-15 附属叠加、DP-17/DP-18 普通模式 |
| 未覆盖 | 真实屏幕亮度调参（规格列为试用默认值） |

## 批次 3 · `96e93981` 画布集成与审核范围分离（任务组 3–4）

改动：`Canvas` 安装复核显示表，绘制门与命中门同源；`Shape.paint` 接受
`display_style` 按组件强度绘制；mask、组连线、标签底板/文字、属性与度数
文字统一服从角色；`ObjectReviewState` 记录 `group_id`，`session.associated_ids()`
只关联「同图 + 同组 + 唯一主矩形」的点，group 0 有效，多框歧义不猜测。

关键语义修正：`unsupported` 不再抑制绘制与命中。关键点与其他形状保持
可观察、可命中、可按既有命令编辑，仅以 `reviewable=False` 表达其不在正式
确认范围（`SUPPORTED_SHAPE_TYPES` 仍为 `("rectangle",)`）。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_canvas_display_overlay.py` | 9 passed，新增 |
| `tests/test_dense_review/test_workspace_mixed_shapes.py` | 6 passed，新增，真实 `MainWindow` |
| `tests/test_dense_review/test_session.py` | 32 passed（含 group_id 往返） |
| `tests/test_dense_review` 全目录 | 173 passed，2 项基线失败 |
| 覆盖场景 | OC-01/OC-02/OC-03 group 关联与歧义、OC-10/OC-12/OC-15 点可观察与待支持、PC-03/PC-04 矩形确认不波及点、DP-01/DP-02/DP-03/DP-07/DP-08/DP-15 绘制与命中 |

## 批次 4 · `4af3c92f` 显示结果贯穿绘制/命中/退出（任务组 5 及 DP-17）

改动（含两处实施中发现的真实缺陷）：

1. 手动隐藏与类别/group 过滤/反选变更后立即重建显示表。此前会话中表格
   不失效，隐藏对象仍被绘制并响应命中。
2. 退出复核时按当前用户设置重算画布可见性，不再用进入时快照覆盖复核期间
   新增的隐藏/过滤（DP-17、WL-12 明确禁止）。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_display_consistency.py` | 9 passed，新增，真实 `MainWindow` |
| `tests/test_dense_review` 全目录 | 182 passed，2 项基线失败 |
| 覆盖场景 | DP-11 隐藏原因与命中、PC-06 临时显示不改确认资格、DP-11/DP-14 切目标与切图结束例外、DP-12/DP-13 原图对照退出命中、DP-17/WL-12 关闭恢复最新设置、DP-07 当前矩形边优先、DP-10 拖动目标固定、DP-08 绘制顺序不改保存顺序 |

## 批次 5 · `26fed309` 复核标签策略与原图对照（任务组 6）

改动：复核期间标签文字由角色强度决定，临时覆盖普通 `show_labels=False`
与 `show_labels_only_selected=True`，类别名始终可读且不写回普通设置；
标签循环在复核模式下即使普通开关全关也进入。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_display_text_and_original.py` | 7 passed，新增，真实 `MainWindow` |
| `tests/test_dense_review` 全目录 | 189 passed，2 项基线失败 |
| 覆盖场景 | DP-05 普通开关两态下的标签可读与设置不被改写、DP-13 对照暂停标注命中、DP-14 切图/关闭结束对照、DP-17 退出恢复、DP-18 普通模式 |

## 批次 6 · `c569a29f` 可调卡片图像高度与大图块（任务组 8.1–8.5 部分）

改动：移除固定 176 单元高与 108 图像高；图像区默认 320（160–640 可调），
文字带单独预留；面板增宽只改列数并保持高度；图块目标像素按显示尺寸与
DPR 计算并进入缓存键；新增高度滑块与四语言文案并重跑资源编译。

| 项目 | 结果 |
| --- | --- |
| `tests/test_dense_review/test_card_geometry.py` | 9 passed，新增 |
| `tests/test_dense_review/test_translations.py` | 8 passed，614 subtests |
| `tests/test_dense_review` 全目录 | 198 passed，2 项基线失败 |
| 覆盖场景 | OC-07 默认值与可调范围、OC-08 上下文独立、OC-09 列数与 DPR、OC-17/OC-18 尺寸进入缓存键 |

过程中修正的自身问题：新增文案未入翻译导致 `test_translations` 12 项失败；
`.ts` 插入时留下重复 `<message>` 与缺失开标签，`lrelease` 直接报错。
均已修复并重新编译，最终 `test_translations` 全通过。

## 任务 1 附带修复 · `db2b10d2` 导航用例配置会话挂起

现象：`tests/test_canvas/test_navigation.py` 顺序执行必挂，单跑通过。

根因（faulthandler 实测）：两条用例裸建 `MainWindow` 时未建立配置会话，
窗口初始化保存偏好失败触发模态 `QMessageBox.critical`，offscreen 下永久阻塞。

修复：改用 `get_config()` 加载 `.tmp` 下测试专用配置，建立可写会话，保留
真实保存路径与写保护。

| 项目 | 结果 |
| --- | --- |
| 两条用例单跑 | 各 1 passed（5.99s / 5.52s） |
| `tests/test_canvas/test_navigation.py` 整文件 | 83 passed，9.93s，退出码 0 |

### 同类挂起仍存在于其他两个文件（未修，超出本次授权范围）

`tests/test_canvas/test_rectangle_edge_migration.py` 与
`tests/test_canvas/test_rectangle_preview_overlap.py` 整文件执行仍复现同一
模态弹窗阻塞（堆栈同样落在 `label_widget.error_message`）。两者的目标是
`MainWindow` / `LabelingWidget` 直建用例，需要同样的配置会话改造。
本批次只按要求修复 `test_navigation.py`，上述两文件按未覆盖登记。

## 最终验收（本次交付范围）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 密集复核目录 | `pytest tests/test_dense_review` | 198 passed，2 failed（基线既有），614 subtests |
| 导航文件 | `pytest tests/test_canvas/test_navigation.py` | 83 passed，9.94s，退出码 0 |
| 受影响的画布文件 | `test_fill_opacity` / `test_shape_selection` / `test_groups` / `test_label_visibility_mode` | 12 / 11 / 16 / 6 passed |
| OpenSpec | `openspec validate redesign-dense-review-workspace --strict` | valid |
| 翻译 | `scripts/compile_languages.py` | 四语言 2459 条，无错误 |

单列说明：

- `tests/test_widgets/test_toolbar_layout.py`：**未运行**（CI 排除项，本次未涉及工具栏布局）。
- `tests/test_pointcloud/`：**未运行**（Windows 不具备 xcb + xvfb），本功能不涉及点云。
- `tests/test_canvas/test_rectangle_edge_migration.py` 与
  `tests/test_canvas/test_rectangle_preview_overlap.py`：整文件执行仍复现基线
  既有模态弹窗挂起，**未作为本次回归依据**；其目标用例单跑可过。
- 人工验收 M1–M8、性能门槛 P1–P4：**未执行**，均为真实屏幕项。
- 本次勾选 26 项任务，均对应具体提交与测试；其余 65 项未勾选，保持未完成。

## 未覆盖与后续

- `tests/test_widgets/test_toolbar_layout.py`：未运行（CI 排除项）。
- `tests/test_pointcloud/`：Windows 上不适用（需 xcb + xvfb），未运行。
- 任务组 6 已完成（`26fed309`）；任务组 8 的尺寸/DPR/缓存键部分已完成
  （`c569a29f`），其余部分（裁切并集、框外点入口、失败重试、比较窗口）
  尚未实施。
- 尚未实施：矩形卡聚合 UI（组 7）、停靠工作区（组 9）、原图小地图与
  空间查漏（组 10）、设置与交接（组 11–12）。
- 人工验收 M1–M8 与性能门槛 P1–P4 未执行，均为真实屏幕项，不能由离屏
  截图替代。
